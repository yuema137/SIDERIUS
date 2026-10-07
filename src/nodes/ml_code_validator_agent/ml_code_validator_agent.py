# nodes/ml_code_validator_agent/ml_code_validator_agent.py
"""
ml_code_validator_agent — Node 5 in the SIDERIUS graph.

Receives file paths, config metadata, and model spec from ml_model_implementor
(via ValidatorInput) and performs eight checks:

Deterministic:
  1. Plugin load: file imports without error; PLUGIN_MODEL_TYPE, PLUGIN_CONFIG_CLASS,
     PLUGIN_MODEL_CLASS are all present.
  2. Tests pass: pytest exits 0 on the generated test file.
  3. Description valid: description.md exists and has >50 characters.
  4. Config fields scalar: all config_fields values are int, float, or bool.
  5. Forbidden patterns: forward() contains no Python loops over the time
     dimension (T). Such loops cause RAM OOMs and CPU hangs at long T.

Model probe (isolated for long temporal inputs):
  6. Instantiation: PLUGIN_CONFIG_CLASS(...) and PLUGIN_MODEL_CLASS(config) succeed;
     a dummy forward pass produces the shape the candidate's declared contract
     requires. Since Step 04a that shape is DERIVED from the task's normalized
     Model-I/O contract when one is supplied — it is not a fixed [1, 256, 64].
     Without a contract the legacy geometry is used unchanged. The config
     kwargs come from the same recipe module, via `probe_config_kwargs` —
     empty for every candidate that declares its own defaults, and a value
     only for a framework-template field the candidate declares REQUIRED
     (C12-P / F-12e-G1). A required field is a legal declaration, not a
     defect.
  7. Gradient flow: loss.backward() succeeds; all trainable parameters have
     non-None gradients.

LLM review:
  8. Code review: LLM reads plugin source + mathematical definition + model description
     and assesses spec alignment, trainability concerns, and implementation issues.

Output written to: {workspace}/validation_{run_name}.json

Node contract:
  run(input: ValidatorInput) -> ValidatorOutput
  CLI: --model_type, --model_file_path, --test_file_path, --description_file_path,
       --config_fields (JSON), --model_description, --mathematical_definition,
       --llm_provider, --llm_model_id, --workspace, --run_name
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys

import torch

from agent.llm_bridge import LLMBridge
from agent.prompt_templates.native_training import render_native_training_appendix
from agent.schemas.hyperparam_tuning import serialize_expert_advice
from agent.schemas.model_io_contract import ModelIOContract
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.validator import LLMCodeReview, ValidatorInput, ValidatorOutput
from agent.skills.forbidden_pattern_skill import check_file as _check_forbidden_patterns
from agent.skills.forbidden_pattern_skill import check_source as _check_forbidden_source
from agent.skills.model_io_probe_skill import (
    ProbeConstructionError,
    build_model_input,
    candidate_probe_extent,
    declared_output_tensor,
    expected_output_shape,
    probe_config_kwargs,
)
from core.local_code.child import prepare_child
from core.local_code.failure import raise_if_code_package_failure
from core.subprocess_env import subprocess_env
from ml_models.plugin_loader import PLUGIN_LEGAL_OUTPUT_TYPES
from nodes.ml_code_validator_agent.source import (
    REQUIRED_PLUGIN_ATTRIBUTES,
    captured_plugin,
    captured_source,
    read_source,
)

__all__ = [
    "MLCodeValidatorAgent",
    "main",
]
# Acquisition helpers are new private implementation details, not moved APIs.
_COMPATIBILITY_REEXPORTS: tuple[str, ...] = ()

# ---------------------------------------------------------------------------
# LLM prompts
# ---------------------------------------------------------------------------

VALIDATOR_REVIEW_SYSTEM_PROMPT = """\
You are a senior ML engineer reviewing an auto-generated PyTorch model plugin.

Your task is to verify that the implementation will RUN AND TRAIN correctly.
You are NOT reviewing for production readiness, style, optimality, or exact
mathematical fidelity to the spec.

## The two fields you set are INDEPENDENT — understand this distinction:

`passed` — TRAINABILITY GATE (the only hard gate):
  Set passed=true if the model will run and train without errors.
  Set passed=false ONLY for bugs that will cause a crash or completely broken training:
    - Shape mismatches that cause a runtime error
    - Broken gradient path (detached tensors, non-differentiable ops where needed)
    - Missing operations that prevent the model from running at all
    - Wrong output shape for the contract the plugin DECLARES in
      PLUGIN_OUTPUT_TYPE: "classifier" must emit {CLASSIFIER_SHAPE},
      "regressor" must emit {REGRESSOR_SHAPE}. Judge against the declared contract,
      not against classification by default.
  Implementation details that differ from the spec but still produce a valid,
  trainable model do NOT set passed=false. A model that is "structurally close
  and should run" MUST have passed=true.

`spec_alignment` — FIDELITY SIGNAL (warning only, never gates passed):
  Set spec_alignment=true only if the implementation exactly matches the
  mathematical definition — same operations, same data flow, same semantics.
  Set spec_alignment=false if there are ANY deviations, even minor ones
  (different padding strategy, simplified gating, alternative upsampling, etc.).
  This field is informational. It does NOT affect passed. A model can and should
  have spec_alignment=false and passed=true when it is a valid trainable
  implementation that differs in implementation details from the spec.

## Do NOT set passed=false for:
- Causal length alignment approaches (min_len truncation, F.pad strategies) that
  differ from the spec but still produce the correct output shape.
- Engineering simplifications (shared projections instead of separate ones,
  F.interpolate instead of transposed conv, etc.) that change implementation
  details but not the fundamental computation.
- Standard enhancements (residual connections, layer norm, dropout) not in the spec.
- Theoretical edge-case concerns when default config values avoid the edge case.
- Hyperparameter range choices — those are for the tuner, not the validator.

When runtime errors are provided (pytest output, forward/backward errors), use them
as primary evidence. Do not speculate about unrelated issues.

Output a JSON object with exactly these fields:
{
  "spec_alignment": true or false,
  "trainability_concerns": ["concern 1", "concern 2"],
  "implementation_issues": ["issue 1"],
  "passed": true or false,
  "notes": "brief overall assessment"
}

- trainability_concerns: list concerns about gradient flow or stability (empty [] if none).
- implementation_issues: list only bugs that cause crashes or wrong output shape.
- passed: true if the model will run and train. false only for crash/broken-gradient bugs.
- Output only the JSON object — no preamble, no markdown fences."""


#: The shapes the shipped prompt named, used when no normalized contract is
#: supplied (design §15.1 row 1). A prose-only caller therefore sends the
#: byte-identical prompt it always has — which is what keeps ``pb6_*`` exact.
_LEGACY_PROMPT_SHAPES: dict[str, str] = {
    "classifier": "[B, 256, T]",
    "regressor": "[B, T]",
}


def _build_review_system_prompt(model_io_contract: ModelIOContract | None) -> str:
    """Render the reviewer's system prompt from the task's declaration.

    Step 04a: the two shape tokens the reviewer judges against are RENDERED
    from the normalized contract rather than restated. A prompt that names
    ``[B, 256, T]`` for a task declaring sixteen classes does not merely read
    oddly — it instructs the reviewer to reject every correct candidate, and
    no shape check anywhere else in the pipeline would catch it, because the
    defect lives in prose (design §9 failure class 6).

    Both forms come from the same ``declared_output_tensor`` rule the probe
    uses, so the prompt cannot describe a contract the probe would refuse.
    A contract that cannot express the classifier form degrades to naming
    only what it can: there is nothing to say about a class alphabet a task
    never declared.
    """
    shapes = dict(_LEGACY_PROMPT_SHAPES)
    if model_io_contract is not None:
        for form in ("classifier", "regressor"):
            try:
                shapes[form] = declared_output_tensor(model_io_contract, form).render_shape()
            except ProbeConstructionError:
                # A continuous task has no classifier form to describe. Say so
                # rather than inventing an alphabet — the probe fails closed on
                # exactly this case, and the prompt must not promise otherwise.
                shapes[form] = "(not declared by this task)"
    return (
        VALIDATOR_REVIEW_SYSTEM_PROMPT.replace("{CLASSIFIER_SHAPE}", shapes["classifier"]).replace(
            "{REGRESSOR_SHAPE}", shapes["regressor"]
        )
        + render_native_training_appendix()
    )


def _build_review_prompt(
    inp: ValidatorInput,
    plugin_src: str,
    test_output: str | None = None,
    inst_err: str | None = None,
) -> str:
    parts = [
        f"## Model Description\n\n{inp.model_description}\n\n",
        f"## Mathematical Definition\n\n{inp.mathematical_definition}\n\n",
        f"## Plugin Implementation\n\n```python\n{plugin_src}\n```\n\n",
    ]

    if inst_err:
        parts.append(f"## Runtime Error (in-process forward/backward)\n\n```\n{inst_err}\n```\n\n")

    if test_output:
        parts.append(f"## Pytest Output (tests failed)\n\n```\n{test_output}\n```\n\n")

    if inst_err or test_output:
        parts.append(
            "Runtime errors were observed above. "
            "Diagnose the precise root cause(s) in `implementation_issues`. "
            "Also assess spec alignment and trainability."
        )
    else:
        parts.append(
            "No runtime errors observed. Review the implementation against the specification above."
        )

    # --- Expert advice (from upstream agents) ---
    expert_advice_str = serialize_expert_advice(inp.expert_advice) if inp.expert_advice else ""
    if expert_advice_str:
        parts.append(f"\n\n## Expert Guidance (from upstream agents)\n\n{expert_advice_str}\n")

    # --- Human advice (injected by workflow) ---
    if inp.human_advice:
        parts.append(f"\n\n## Human Guidance (high priority)\n\n{inp.human_advice}\n")

    return "".join(parts)


# ---------------------------------------------------------------------------
# Deterministic check helpers
# ---------------------------------------------------------------------------


def _check_inherited_components(
    plugin_source: str,
    inherited_components: list,
    vocab_seed: list | None = None,
) -> tuple[bool, list[str]]:
    """
    Check #8: verify that claimed inherited components appear in the code.

    For each claimed component, look up its ``pattern`` in the vocab seed.
    If a pattern exists, regex-match against the plugin source. Components
    without patterns are soft-skipped (noted but not failed).

    Args:
        plugin_source: Full source code of the plugin file.
        inherited_components: List of InheritedComponent dicts or objects.
        vocab_seed: List of VocabEntry dicts or objects for pattern lookup.

    Returns:
        (all_passed, notes): all_passed is True if every component with a
        pattern was found. notes is a per-component list of results.
    """
    import re

    if not inherited_components:
        return True, []

    # Build pattern lookup from vocab seed
    patterns: dict[str, str | None] = {}
    for entry in vocab_seed or []:
        name = entry.get("name") if isinstance(entry, dict) else getattr(entry, "name", None)
        pattern = (
            entry.get("pattern") if isinstance(entry, dict) else getattr(entry, "pattern", None)
        )
        if name:
            patterns[name] = pattern

    notes = []
    all_passed = True

    for ic in inherited_components:
        component = ic.get("component") if isinstance(ic, dict) else getattr(ic, "component", None)
        if not component:
            continue

        pattern = patterns.get(component)
        if pattern is None:
            notes.append(f"{component}: SKIPPED (no pattern in vocab seed)")
            continue

        try:
            if re.search(pattern, plugin_source, re.IGNORECASE | re.DOTALL):
                notes.append(f"{component}: FOUND (pattern '{pattern}' matched)")
            else:
                notes.append(f"{component}: NOT FOUND (pattern '{pattern}' not in source)")
                all_passed = False
        except re.error as e:
            notes.append(f"{component}: REGEX ERROR ({e})")
            all_passed = False

    return all_passed, notes


def _check_plugin(model_file_path: str) -> tuple[bool, str | None]:
    """
    Load the plugin file and verify the three required module-level attributes.
    Returns (success, error_message_or_None).
    """
    try:
        module = captured_plugin(model_file_path)
    except Exception as e:
        raise_if_code_package_failure(e)
        return False, f"Import error: {e}"
    if module is None:
        spec = importlib.util.spec_from_file_location("_validator_plugin_load", model_file_path)
        if spec is None or spec.loader is None:
            return False, f"Could not create module spec/loader for {model_file_path}"
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            raise_if_code_package_failure(e)
            return False, f"Import error: {e}"

    for attr in REQUIRED_PLUGIN_ATTRIBUTES:
        if not hasattr(module, attr):
            return False, f"Plugin is missing required attribute '{attr}'"

    return True, None


def _run_tests(test_file_path: str) -> tuple[bool, str]:
    """
    Run pytest on ``test_file_path``.

    Branch B model reuse produces no new test file — the implementor's
    Branch B short-circuit (``ml_model_implementor.run`` early return) emits
    ``ImplementorOutput.test_file_path=""`` because the reused plugin was
    already validated at initial registration. When that empty sentinel
    (or any non-file path) reaches this function, pytest's positional
    argument becomes ``""``, which pytest treats as "no path given → discover
    from rootdir" and collects the entire project test suite. In v16 this
    caused 22 loss-chain iterations to false-fail on real-API integration
    tests that legitimately fail in the validator subprocess.

    Guard: on empty or non-file ``test_file_path``, skip pytest and return
    success. Re-validating a previously-registered plugin here is both
    wasted work and, as v16 showed, actively harmful.

    Returns (passed, full_stdout_stderr).
    """
    if not test_file_path or not os.path.isfile(test_file_path):
        return True, (
            "Skipped: no test file provided (Branch B model reuse — "
            "plugin already validated at registration time)."
        )
    invocation = prepare_child(
        [sys.executable, "-m", "pytest", test_file_path, "-v", "--tb=short"],
        subprocess_env(),
    )
    try:
        result = subprocess.run(invocation.argv, capture_output=True, text=True, env=invocation.env)
    except Exception as exc:
        invocation.check(getattr(exc, "returncode", None))
        raise
    invocation.check(result.returncode)
    output = result.stdout + result.stderr
    return result.returncode == 0, output


def _check_description(description_file_path: str) -> tuple[bool, str | None]:
    """
    Verify description.md exists and has >50 characters of content.
    Returns (valid, error_message_or_None).
    """
    if not os.path.isfile(description_file_path):
        return False, f"description.md not found at {description_file_path}"
    with open(description_file_path) as f:
        content = f.read()
    if len(content.strip()) <= 50:
        return False, (
            f"description.md at {description_file_path} is too short "
            f"({len(content.strip())} chars, need >50)"
        )
    return True, None


def _check_config_fields(config_fields: dict) -> tuple[bool, str | None]:
    """
    Verify all config field default values are scalar types (int, float, bool).
    Returns (valid, error_message_or_None).
    """
    bad = []
    for name, value in config_fields.items():
        if not isinstance(value, (int, float, bool)):
            bad.append(f"'{name}': {type(value).__name__}")
    if bad:
        return False, "Non-scalar config fields: " + ", ".join(bad)
    return True, None


# ---------------------------------------------------------------------------
# In-process instantiation + gradient check
# ---------------------------------------------------------------------------


#: Output contracts a plugin may declare. An unrecognised value fails closed
#: rather than defaulting — see ``_check_instantiation_and_gradient``.
#:
#: Step 12 / PR-12a C4 (issue #234): IMPORTED, no longer a second literal. The
#: validator had independently enforced this exact pair since V21 PR A while
#: the loader accepted three, so a plugin declaring ``hybrid`` loaded and was
#: then refused at validation. One authority, one set — a divergence is now a
#: structural impossibility rather than something a census has to notice.
_LEGAL_OUTPUT_TYPES: tuple[str, ...] = PLUGIN_LEGAL_OUTPUT_TYPES

#: Legacy-read default for plugins predating the declaration (V21 PR A).
#: A NEWLY generated plugin must always declare its contract explicitly;
#: relying on this default is a producer defect, not a convenience.
_DEFAULT_OUTPUT_TYPE: str = "classifier"

#: Legacy probe geometry, used ONLY when no normalized contract is supplied.
#: This is design §15.1 row 1 — a caller that predates the Model-I/O contract
#: keeps today's behaviour exactly, and absence alone is never an error.
#:
#: FU-A-1 is DISCHARGED (Step 04a): the class count is no longer restated
#: here. When a contract IS supplied it is the authority, and these values
#: are not consulted at all.
_LEGACY_CLASSIFIER_PROBE_CLASSES: int = 256
_LEGACY_PROBE_TIME_STEPS: int = 64


def _check_instantiation_and_gradient(
    model_file_path: str,
    model_io_contract: ModelIOContract | None = None,
    *,
    _isolated_worker: bool = False,
) -> tuple[bool, bool, bool, str | None, int | None, int | None]:
    """
    Load plugin, instantiate config + model, run a dummy forward + backward pass,
    and verify the model matches its own declared output contract.

    Returns (instantiation_ok, gradient_ok, output_type_ok,
    error_message_or_None, realized_total_parameter_count,
    realized_trainable_parameter_count).

    V21 PR E (O-E-6 FINAL): the two counts are measured from the SAME model
    instance this check already instantiates — no extra instantiation, and
    OBSERVATION ONLY: neither count influences any verdict boolean.
    ``None`` means the model never instantiated (measurement unavailable);
    ``0`` is a real measurement of a parameterless model. They are computed
    the moment instantiation succeeds, so a candidate that fails its forward
    pass or output contract still records how large the implementation was —
    those are exactly the candidates the funnel must not lose.
      - instantiation_ok: config instantiated, model instantiated, forward pass
                          produced the shape required by its DECLARED contract.
      - gradient_ok:      backward pass succeeded and all trainable parameters
                          received non-None gradients.
      - output_type_ok:   the declaration is legal and the actual output matches
                          it.

    This function answers two of the three compatibility questions: is the
    declaration legal, and does the model honour its own declaration. The
    third — is the (output contract, loss) PAIR legal — belongs to the shared
    rule in ``ml_models.models_format_sandbox`` and is deliberately not
    duplicated here.

    Step 04a — where the probe's shape comes from:

    * ``model_io_contract`` supplied: the probe input and the expected output
      shape are DERIVED from it through ``agent.skills.model_io_probe_skill``.
      Class cardinality, rank, axis order and input dtype are contract-owned;
      the batch extent and the realization of a symbolic axis are Step-04
      recipes. A contract that cannot supply a semantic the candidate's own
      declared form requires fails CLOSED here rather than being guessed
      (§15.1 row 3).
    * ``model_io_contract is None``: the legacy prose-only path (§15.1 row 1).
      The probe reproduces its pre-Step-04a geometry exactly —
      ``[1, 256, 64]`` for ``classifier``, ``[1, 64]`` for ``regressor`` —
      and absence alone is never an error.

    Args:
        model_file_path: absolute path to the plugin to probe.
        model_io_contract: the normalized Step-03 declaration this candidate
            was generated against, mapped in by the impl->valid protocol, or
            ``None`` on the legacy path.
    """
    try:
        module = captured_plugin(model_file_path)
    except Exception as e:
        raise_if_code_package_failure(e)
        return False, False, False, f"Import error: {e}", None, None
    if module is None:
        spec = importlib.util.spec_from_file_location("_validator_plugin_inst", model_file_path)
        if spec is None or spec.loader is None:
            return (
                False,
                False,
                False,
                f"Could not create module spec/loader for {model_file_path}",
                None,
                None,
            )
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            raise_if_code_package_failure(e)
            return False, False, False, f"Import error: {e}", None, None

    # Instantiate config and model.
    #
    # C12-P / F-12e-G1: a generated config class may LEGITIMATELY declare
    # required fields. Since the implementor stopped inventing a
    # `segmentation_size` default into the plugins it writes, a candidate
    # whose baseline declared no size carries that field as REQUIRED — and
    # "PLUGIN_CONFIG_CLASS() must succeed with zero arguments" is not a valid
    # generic validator invariant. It rejected such a candidate here with an
    # opaque Pydantic string, before the tuner ever saw it, so the task's own
    # named refusal was never what the operator read.
    #
    # The probe kwargs come from the Step-04 recipe module — the SAME
    # authority the implementor's self-check and the generated test file use.
    # This node deliberately learns nothing about WHICH fields those are or
    # what they mean; it asks, and splats. Re-spelling the rule here would
    # recreate the implementor/validator divergence that recipe module exists
    # to prevent.
    try:
        config = module.PLUGIN_CONFIG_CLASS(
            **probe_config_kwargs(module.PLUGIN_CONFIG_CLASS, model_io_contract)
        )
        probe_extent = candidate_probe_extent(config, model_io_contract)
    except Exception as e:
        raise_if_code_package_failure(e)
        return False, False, False, f"Model instantiation failed: {e}", None, None

    # A task-declared long temporal probe can retain many full-size activation
    # tensors during backward. Run generated code in a bounded child before
    # constructing the model; an OOM must reject this candidate, not the chain.
    if (
        not _isolated_worker
        and probe_extent is not None
        and probe_extent >= 8192
        and captured_plugin(model_file_path) is None
        and os.path.isfile(model_file_path)
    ):
        from agent.skills.validator_probe_worker import run_bounded_probe

        return run_bounded_probe(model_file_path, model_io_contract)

    try:
        model = module.PLUGIN_MODEL_CLASS(config)
        model.train()
    except Exception as e:
        raise_if_code_package_failure(e)
        return False, False, False, f"Model instantiation failed: {e}", None, None

    # V21 PR E (O-E-6 FINAL): both parameter-count views of the instantiated
    # implementation, measured once, from this exact instance. numel() reads
    # tensor metadata — no allocation, no forward pass. TOTAL is the
    # architecture's size; TRAINABLE is what an optimizer would update; a
    # frozen parameter makes them differ, and they are reported as two
    # separate facts, never reconciled into one number.
    realized_total = sum(p.numel() for p in model.parameters())
    realized_trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)

    # ---- Output contract is read BEFORE the shape probe (V21 PR A2) -------
    #
    # Previously the probe hard-required (1, 256, 64) and only afterwards
    # looked at PLUGIN_OUTPUT_TYPE. That ordering made a regressor
    # unvalidatable: a [B, T] output was rejected by the shape gate before
    # its declaration was ever read, so the `regressor` branch below was
    # unreachable. (The `classifier` branch was dead too: a shape equal to
    # (1, 256, 64) is 3-dim by construction, so `actual_dims != 3` could
    # never be true there either.)
    #
    # The expected shape is now DERIVED from the plugin's own declaration,
    # which is what makes both contracts reachable.
    declared_type = getattr(module, "PLUGIN_OUTPUT_TYPE", _DEFAULT_OUTPUT_TYPE)
    if declared_type not in _LEGAL_OUTPUT_TYPES:
        # Fail closed. Never coerce an unrecognised declaration to classifier:
        # that is exactly how a metadata defect becomes wrong semantics.
        return (
            False,
            False,
            False,
            (
                f"PLUGIN_OUTPUT_TYPE={declared_type!r} is not a legal output contract "
                f"(expected one of: {', '.join(_LEGAL_OUTPUT_TYPES)})"
            ),
            realized_total,
            realized_trainable,
        )

    # Step 04a: the probe geometry. With a contract the facts are derived;
    # without one the legacy geometry is reproduced verbatim (§15.1 row 1).
    # A contract that cannot express what the candidate's declared form needs
    # is a verdict, not a crash — it is reported through the same error
    # channel as every other rejection, so an operator sees WHY the candidate
    # could not be probed.
    if model_io_contract is None:
        extent = probe_extent if probe_extent is not None else _LEGACY_PROBE_TIME_STEPS
        expected_shape: tuple[int, ...] = (
            (1, _LEGACY_CLASSIFIER_PROBE_CLASSES, extent)
            if declared_type == "classifier"
            else (1, extent)
        )
        probe_input = torch.randint(0, _LEGACY_CLASSIFIER_PROBE_CLASSES, (1, extent))
    else:
        try:
            expected_shape = expected_output_shape(
                model_io_contract, declared_type, symbolic=probe_extent
            )
            probe_input = build_model_input(model_io_contract, symbolic=probe_extent)
        except ProbeConstructionError as e:
            return (
                False,
                False,
                False,
                f"Probe construction failed: {e}",
                realized_total,
                realized_trainable,
            )

    # Forward pass with small dummy input
    try:
        out = model(probe_input)
    except Exception as e:
        raise_if_code_package_failure(e)
        return False, False, False, f"Forward pass failed: {e}", realized_total, realized_trainable

    if not isinstance(out, torch.Tensor):
        return (
            False,
            False,
            False,
            f"Forward returned {type(out).__name__}, expected a torch.Tensor",
            realized_total,
            realized_trainable,
        )

    if tuple(out.shape) != expected_shape:
        return (
            False,
            False,
            False,
            (f"Forward output shape {tuple(out.shape)} does not match expected {expected_shape}"),
            realized_total,
            realized_trainable,
        )

    output_type_ok = True

    # Gradient flow check
    try:
        loss = out.sum()
        loss.backward()
    except Exception as e:
        raise_if_code_package_failure(e)
        return (
            True,
            False,
            output_type_ok,
            f"Backward pass failed: {e}",
            realized_total,
            realized_trainable,
        )

    no_grad = [name for name, p in model.named_parameters() if p.requires_grad and p.grad is None]
    if no_grad:
        # Dead parameters are a WARNING, not a failure. Some architectures
        # have parameters that participate in the forward pass but are
        # disconnected from the loss (e.g. the last block in a residual
        # chain where only skip connections feed the output). These don't
        # affect training or output quality.
        print(
            f"  WARNING (gradient check): {len(no_grad)} parameters with no gradient: "
            f"{no_grad[:5]}. This is typically harmless."
        )

    return True, True, output_type_ok, None, realized_total, realized_trainable


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------


class MLCodeValidatorAgent:
    """
    Validator node for agent-generated ML model plugins.
    Combines deterministic checks with LLM code review.
    """

    def __init__(
        self,
        provider: str = "gemini",
        model_id: str = "gemini-3.1-flash-lite-preview",
        max_retries: int | None = None,
        reasoning_effort: str | None = None,
        bridge_factory=None,
        **kwargs,
    ):
        self._bridge_factory = bridge_factory or LLMBridge
        bridge_kwargs = {"provider": provider, "model_id": model_id, "max_retries": max_retries}
        if reasoning_effort is not None:
            bridge_kwargs["reasoning_effort"] = reasoning_effort
        self.bridge = self._bridge_factory(**bridge_kwargs)

    def run(self, inp: ValidatorInput) -> ValidatorOutput:
        # 1. Plugin load
        plugin_ok, plugin_err = _check_plugin(inp.model_file_path)

        # 2. Pytest
        tests_ok, test_output = _run_tests(inp.test_file_path)

        # 3. Description
        desc_ok, desc_err = _check_description(inp.description_file_path)

        # 4. Config fields
        cfg_ok, cfg_err = _check_config_fields(inp.config_fields)

        # 5. Forbidden patterns: AST scan rejects Python loops over the time
        #    dim in `forward(...)`. Cheap, deterministic, runs even if the
        #    plugin failed to import.
        captured_entry = captured_source(inp.model_file_path)
        if captured_entry is not None:
            forbid_ok, forbid_err = _check_forbidden_source(captured_entry)
        elif os.path.isfile(inp.model_file_path):
            forbid_ok, forbid_err = _check_forbidden_patterns(inp.model_file_path)
        else:
            forbid_ok, forbid_err = False, "Skipped — plugin file not found"

        # 6 + 7 + (output-type). Long temporal probes use a bounded child;
        # small probes preserve the existing in-process path.
        if plugin_ok:
            (
                inst_ok,
                grad_ok,
                otype_ok,
                inst_err,
                realized_total_parameter_count,
                realized_trainable_parameter_count,
            ) = _check_instantiation_and_gradient(
                inp.model_file_path,
                # Step 04a: the declaration the implementor generated this
                # candidate against, carried here by the impl->valid protocol.
                # `None` = legacy prose-only caller, which keeps the shipped
                # probe geometry.
                model_io_contract=inp.model_io_contract,
            )
        else:
            inst_ok, grad_ok, otype_ok, inst_err = (
                False,
                False,
                False,
                "Skipped — plugin did not load",
            )
            # V21 PR E: never instantiated -> measurement unavailable, not 0.
            realized_total_parameter_count = None
            realized_trainable_parameter_count = None

        # 7. LLM code review (only if plugin file is readable)
        if captured_entry is not None or os.path.isfile(inp.model_file_path):
            plugin_src = read_source(inp.model_file_path, captured_entry)
            review = self._llm_review(
                inp,
                plugin_src,
                test_output=test_output if not tests_ok else None,
                inst_err=inst_err if plugin_ok and inst_err is not None else None,
            )
            llm_ok = review.passed
            if llm_ok and not review.spec_alignment:
                print(
                    f"  WARNING (spec alignment): implementation deviates from proposal spec. "
                    f"Model will train but may not exactly test the proposed hypothesis. "
                    f"Notes: {review.notes}"
                )
        else:
            review = LLMCodeReview(
                spec_alignment=False,
                trainability_concerns=[],
                implementation_issues=["Plugin file not found"],
                passed=False,
                notes="Skipped — plugin file not found",
            )
            llm_ok = False

        # 8. Inheritance check (only if plugin source is readable and claims exist)
        inherit_ok = True
        inherit_notes = None
        if inp.inherited_components and (
            captured_entry is not None or os.path.isfile(inp.model_file_path)
        ):
            if "plugin_src" in dir():
                inherit_src = plugin_src
            else:
                inherit_src = read_source(inp.model_file_path, captured_entry)
            # Load vocab seed for pattern lookup
            vocab_for_check = None
            try:
                import json as _json

                from core.layout import package_root

                seed_path = os.path.join(
                    package_root(),
                    "agent",
                    "schemas",
                    "vocab_seed.json",
                )
                if os.path.exists(seed_path):
                    with open(seed_path) as f:
                        vocab_for_check = _json.load(f)
            except Exception:
                pass
            inherit_ok, inherit_notes_list = _check_inherited_components(
                inherit_src,
                [
                    ic.model_dump() if hasattr(ic, "model_dump") else ic
                    for ic in inp.inherited_components
                ],
                vocab_for_check,
            )
            inherit_notes = inherit_notes_list if inherit_notes_list else None
            if not inherit_ok:
                print(f"  Inheritance check FAILED: {inherit_notes}")

        # Trainability gate — inheritance_check_passed is NOT in this list (regex checks
        # are too brittle to block a model that otherwise runs and trains). It is surfaced
        # as a deviation note so the tuner/interpretation agents can treat unverified
        # component claims with appropriate skepticism.
        passed = all(
            [plugin_ok, tests_ok, desc_ok, cfg_ok, forbid_ok, inst_ok, grad_ok, otype_ok, llm_ok]
        )

        errors = [e for e in [plugin_err, desc_err, cfg_err, forbid_err, inst_err] if e is not None]
        if not tests_ok:
            errors.append("pytest tests failed — see test_output for details")
        if not llm_ok:
            errors.append(f"LLM review did not pass: {review.notes}")
        error_message = "; ".join(errors) if errors else None

        # Populate spec_deviation_notes when the model passes but doesn't match the spec —
        # propagated to the tuner so its planner knows what it's actually tuning.
        spec_deviation_notes = None
        if passed and not review.spec_alignment:
            issues = review.implementation_issues or []
            concerns = review.trainability_concerns or []
            deviation_lines = issues + concerns
            spec_deviation_notes = (
                "NOTE: This implementation passes trainability checks but deviates from "
                "the proposed mathematical spec. The tuner is optimizing an approximation "
                "of the intended architecture. Deviations: "
                + (" | ".join(deviation_lines) if deviation_lines else review.notes)
            )

        # Parallel treatment for inheritance: when a claimed inherited_component's regex
        # pattern did not match, record it structurally (for downstream consumers like the
        # interpretation agent) and in prose (for the tuner's LLM planner).
        unverified_components: list[str] = []
        inheritance_deviation_notes = None
        if not inherit_ok and inherit_notes:
            for note in inherit_notes:
                if "NOT FOUND" in note:
                    unverified_components.append(note.split(":", 1)[0].strip())
            if passed and unverified_components:
                inheritance_deviation_notes = (
                    f"NOTE: The implementation passes trainability checks, but the following "
                    f"claimed inherited_components could not be verified in the plugin source "
                    f"by pattern match: {', '.join(unverified_components)}. The regex check is "
                    f"brittle (e.g. a primitive implemented via F.interpolate may not match a "
                    f"pattern that expects 'upsample'). Treat confirmation credit for these "
                    f"components with caution."
                )

        out = ValidatorOutput(
            passed=passed,
            # V21 PR E: explicit echo beside the existing hand-echoed
            # model_type; persisted in validation_{run_name}.json, which is
            # what makes a died-at-validation candidate joinable.
            candidate_id=inp.candidate_id,
            # V21 PR E (O-E-6 FINAL): the two stage-native measurements,
            # observation only — no verdict boolean reads either.
            realized_total_parameter_count=realized_total_parameter_count,
            realized_trainable_parameter_count=realized_trainable_parameter_count,
            model_type=inp.model_type,
            plugin_registered=plugin_ok,
            tests_passed=tests_ok,
            description_valid=desc_ok,
            config_fields_valid=cfg_ok,
            forbidden_patterns_check_passed=forbid_ok,
            instantiation_passed=inst_ok,
            gradient_check_passed=grad_ok,
            output_type_valid=otype_ok,
            llm_review_passed=llm_ok,
            inheritance_check_passed=inherit_ok,
            inheritance_check_notes=inherit_notes,
            unverified_inherited_components=unverified_components,
            test_output=test_output if test_output.strip() else None,
            llm_review_spec_alignment=review.spec_alignment,
            llm_review_trainability_concerns=review.trainability_concerns,
            llm_review_implementation_issues=review.implementation_issues,
            llm_review_notes=review.notes,
            spec_deviation_notes=spec_deviation_notes,
            inheritance_deviation_notes=inheritance_deviation_notes,
            error_message=error_message,
        )

        self._save(inp, out)
        return out

    def _llm_review(
        self,
        inp: ValidatorInput,
        plugin_src: str,
        test_output: str | None = None,
        inst_err: str | None = None,
    ) -> LLMCodeReview:
        user_prompt = _build_review_prompt(
            inp, plugin_src, test_output=test_output, inst_err=inst_err
        )
        raw = self.bridge.generate(
            _build_review_system_prompt(inp.model_io_contract),
            user_prompt,
            label="validator.code_review",
        )
        return LLMCodeReview.model_validate(raw)

    def _save(self, inp: ValidatorInput, out: ValidatorOutput) -> None:
        # StorageConfig.local is Optional (only set when backend='local').
        # The validator only writes locally — surface the precondition
        # explicitly rather than letting it crash on attribute access.
        storage_local = inp.storage.local
        if storage_local is None:
            raise ValueError(
                f"ValidatorInput requires storage.local to be populated "
                f"(got backend={inp.storage.backend!r}, local=None)"
            )
        workspace = storage_local.workspace
        run_name = storage_local.run_name
        os.makedirs(workspace, exist_ok=True)
        path = os.path.join(workspace, f"validation_{run_name}.json")
        with open(path, "w") as f:
            json.dump(out.model_dump(), f, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ml_code_validator_agent")
    p.add_argument("--model_type", required=True)
    p.add_argument("--model_file_path", required=True)
    p.add_argument("--test_file_path", required=True)
    p.add_argument("--description_file_path", required=True)
    p.add_argument(
        "--config_fields", required=True, help="JSON dict of field names → default values"
    )
    p.add_argument("--model_description", required=True)
    p.add_argument("--mathematical_definition", required=True)
    p.add_argument("--llm_provider", default="gemini", choices=["gemini", "openai"])
    p.add_argument("--llm_model_id", default="gemini-3.1-flash-lite-preview")
    p.add_argument("--workspace", default="./siderius_workspace")
    p.add_argument("--run_name", default="v1")
    return p


def main() -> None:
    args = _build_parser().parse_args()
    inp = ValidatorInput(
        model_type=args.model_type,
        model_file_path=args.model_file_path,
        test_file_path=args.test_file_path,
        description_file_path=args.description_file_path,
        config_fields=json.loads(args.config_fields),
        model_description=args.model_description,
        mathematical_definition=args.mathematical_definition,
        llm_provider=args.llm_provider,
        llm_model_id=args.llm_model_id,
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=args.workspace, run_name=args.run_name),
        ),
    )
    agent = MLCodeValidatorAgent(provider=args.llm_provider, model_id=args.llm_model_id)
    out = agent.run(inp)
    print(json.dumps(out.model_dump(), indent=2))


if __name__ == "__main__":
    main()
