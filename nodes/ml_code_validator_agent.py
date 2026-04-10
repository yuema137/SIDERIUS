# nodes/ml_code_validator_agent.py
"""
ml_code_validator_agent — Node 5 in the SIDERIUS graph.

Receives file paths, config metadata, and model spec from ml_model_implementor
(via ValidatorInput) and performs seven checks:

Deterministic:
  1. Plugin load: file imports without error; PLUGIN_MODEL_TYPE, PLUGIN_CONFIG_CLASS,
     PLUGIN_MODEL_CLASS are all present.
  2. Tests pass: pytest exits 0 on the generated test file.
  3. Description valid: description.md exists and has >50 characters.
  4. Config fields scalar: all config_fields values are int, float, or bool.

In-process (no subprocess):
  5. Instantiation: PLUGIN_CONFIG_CLASS() and PLUGIN_MODEL_CLASS(config) succeed;
     forward pass on a small dummy input [1, 64] produces shape [1, 256, 64].
  6. Gradient flow: loss.backward() succeeds; all trainable parameters have
     non-None gradients.

LLM review:
  7. Code review: LLM reads plugin source + mathematical definition + model description
     and assesses spec alignment, trainability concerns, and implementation issues.

Output written to: {workspace}/validation_{run_name}.json

Node contract:
  run(input: ValidatorInput) -> ValidatorOutput
  CLI: --model_type, --model_file_path, --test_file_path, --description_file_path,
       --config_fields (JSON), --model_description, --mathematical_definition,
       --llm_provider, --llm_model_id, --workspace, --run_name
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys

from agent.schemas.hyperparam_tuning import serialize_expert_advice
import argparse

import torch

from agent.llm_bridge import LLMBridge
from agent.schemas.validator import ValidatorInput, ValidatorOutput, LLMCodeReview
from agent.schemas.storage import StorageConfig, LocalStorageConfig


# ---------------------------------------------------------------------------
# LLM prompts
# ---------------------------------------------------------------------------

VALIDATOR_REVIEW_SYSTEM_PROMPT = """\
You are a senior ML engineer reviewing an auto-generated PyTorch model plugin.

Your task is to verify that the implementation is CORRECT — meaning it will run,
train, and produce the expected output shape without errors. You are NOT reviewing
for production readiness, style, or optimality.

Check for these CONCRETE BUGS (set passed=false if any are present):
1. Implementation contradicts the mathematical spec in a way that changes the
   model's computational semantics (e.g. spec says additive residual but code
   uses multiplicative, spec says causal but code uses bidirectional).
2. Correctness bugs that cause wrong results: wrong tensor shapes, missing
   operations, incorrect dimension ordering, broken residual connections.
3. Trainability-breaking bugs: detached tensors in the gradient path,
   non-differentiable operations where gradients are needed, operations that
   always produce zero gradients.

Do NOT fail the review for:
- Theoretical edge-case concerns (e.g. "padding breaks if kernel_size is even"
  when the default kernel_size is odd and within valid Field constraints).
- Suggestions for improvement, alternative designs, or missing bells and whistles.
- Concerns about input data format — the forward contract ([B,T] int64 input with
  nn.Embedding) is specified by the system and is always correct.
- Hyperparameter range concerns — Field constraints are handled by the config schema.
Put these observations in trainability_concerns or notes instead.

When runtime errors are provided (pytest output, forward/backward errors), use them as
primary evidence to diagnose the precise root cause and report it in implementation_issues.
Do not speculate about unrelated issues when a concrete runtime error is present.

Output a JSON object with exactly these fields:
{
  "spec_alignment": true or false,
  "trainability_concerns": ["concern 1", "concern 2"],
  "implementation_issues": ["issue 1"],
  "passed": true or false,
  "notes": "brief overall assessment"
}

- trainability_concerns and implementation_issues must be lists (empty list [] if none).
- passed should be true if the implementation correctly implements the spec and will
  train without errors. Minor concerns belong in trainability_concerns, not in passed.
- Output only the JSON object — no preamble, no markdown fences."""


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
        parts.append("No runtime errors observed. Review the implementation against the specification above.")

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
    for entry in (vocab_seed or []):
        name = entry.get("name") if isinstance(entry, dict) else getattr(entry, "name", None)
        pattern = entry.get("pattern") if isinstance(entry, dict) else getattr(entry, "pattern", None)
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
            if re.search(pattern, plugin_source, re.IGNORECASE):
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
    spec = importlib.util.spec_from_file_location("_validator_plugin_load", model_file_path)
    if spec is None:
        return False, f"Could not create module spec for {model_file_path}"
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        return False, f"Import error: {e}"

    for attr in ("PLUGIN_MODEL_TYPE", "PLUGIN_CONFIG_CLASS", "PLUGIN_MODEL_CLASS"):
        if not hasattr(module, attr):
            return False, f"Plugin is missing required attribute '{attr}'"

    return True, None


def _run_tests(test_file_path: str) -> tuple[bool, str]:
    """
    Run pytest on test_file_path.
    Returns (passed, full_stdout_stderr).
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_file_path, "-v", "--tb=short"],
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    return result.returncode == 0, output


def _check_description(description_file_path: str) -> tuple[bool, str | None]:
    """
    Verify description.md exists and has >50 characters of content.
    Returns (valid, error_message_or_None).
    """
    if not os.path.isfile(description_file_path):
        return False, f"description.md not found at {description_file_path}"
    content = open(description_file_path).read()
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

def _check_instantiation_and_gradient(
    model_file_path: str,
) -> tuple[bool, bool, bool, str | None]:
    """
    Load plugin, instantiate config + model, run a dummy forward + backward pass,
    and verify output type consistency.

    Returns (instantiation_ok, gradient_ok, output_type_ok, error_message_or_None).
      - instantiation_ok: config instantiated, model instantiated, forward pass
                          produced the correct output shape [1, 256, 64].
      - gradient_ok:      backward pass succeeded and all trainable parameters
                          received non-None gradients.
      - output_type_ok:   PLUGIN_OUTPUT_TYPE matches the actual forward output dims.
    """
    spec = importlib.util.spec_from_file_location("_validator_plugin_inst", model_file_path)
    if spec is None:
        return False, False, False, f"Could not create module spec for {model_file_path}"
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        return False, False, False, f"Import error: {e}"

    # Instantiate config and model
    try:
        config = module.PLUGIN_CONFIG_CLASS()
        model = module.PLUGIN_MODEL_CLASS(config)
        model.train()
    except Exception as e:
        return False, False, False, f"Model instantiation failed: {e}"

    # Forward pass with small dummy input
    try:
        x = torch.randint(0, 256, (1, 64))
        out = model(x)
        if tuple(out.shape) != (1, 256, 64):
            return False, False, False, (
                f"Forward output shape {tuple(out.shape)} does not match expected (1, 256, 64)"
            )
    except Exception as e:
        return False, False, False, f"Forward pass failed: {e}"

    # Output type consistency check
    declared_type = getattr(module, "PLUGIN_OUTPUT_TYPE", "classifier")
    actual_dims = len(out.shape)
    if declared_type == "classifier" and actual_dims != 3:
        return True, False, False, (
            f"PLUGIN_OUTPUT_TYPE='classifier' but output has {actual_dims} dims "
            f"(expected 3: [B, 256, T])"
        )
    if declared_type == "regressor" and actual_dims != 2:
        return True, False, False, (
            f"PLUGIN_OUTPUT_TYPE='regressor' but output has {actual_dims} dims "
            f"(expected 2: [B, T])"
        )
    output_type_ok = True

    # Gradient flow check
    try:
        loss = out.sum()
        loss.backward()
    except Exception as e:
        return True, False, output_type_ok, f"Backward pass failed: {e}"

    no_grad = [
        name for name, p in model.named_parameters()
        if p.requires_grad and p.grad is None
    ]
    if no_grad:
        return True, False, output_type_ok, f"Parameters with no gradient: {no_grad[:5]}"

    return True, True, output_type_ok, None


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

class MLCodeValidatorAgent:
    """
    Validator node for agent-generated ML model plugins.
    Combines deterministic checks with LLM code review.
    """

    def __init__(self, provider: str = "gemini", model_id: str = "gemini-3.1-flash-lite-preview",
                 max_retries: int | None = None):
        self.bridge = LLMBridge(provider=provider, model_id=model_id, max_retries=max_retries)

    def run(self, inp: ValidatorInput) -> ValidatorOutput:
        # 1. Plugin load
        plugin_ok, plugin_err = _check_plugin(inp.model_file_path)

        # 2. Pytest
        tests_ok, test_output = _run_tests(inp.test_file_path)

        # 3. Description
        desc_ok, desc_err = _check_description(inp.description_file_path)

        # 4. Config fields
        cfg_ok, cfg_err = _check_config_fields(inp.config_fields)

        # 5 + 6 + 8. In-process instantiation + gradient + output type (only if plugin loaded)
        if plugin_ok:
            inst_ok, grad_ok, otype_ok, inst_err = _check_instantiation_and_gradient(inp.model_file_path)
        else:
            inst_ok, grad_ok, otype_ok, inst_err = False, False, False, "Skipped — plugin did not load"

        # 7. LLM code review (only if plugin file is readable)
        if os.path.isfile(inp.model_file_path):
            plugin_src = open(inp.model_file_path).read()
            review = self._llm_review(
                inp,
                plugin_src,
                test_output=test_output if not tests_ok else None,
                inst_err=inst_err if plugin_ok and inst_err is not None else None,
            )
            llm_ok = review.passed
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
        if inp.inherited_components and os.path.isfile(inp.model_file_path):
            inherit_src = plugin_src if 'plugin_src' in dir() else open(inp.model_file_path).read()
            # Load vocab seed for pattern lookup
            vocab_for_check = None
            try:
                import json as _json
                seed_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "agent", "schemas", "vocab_seed.json",
                )
                if os.path.exists(seed_path):
                    with open(seed_path) as f:
                        vocab_for_check = _json.load(f)
            except Exception:
                pass
            inherit_ok, inherit_notes_list = _check_inherited_components(
                inherit_src,
                [ic.model_dump() if hasattr(ic, "model_dump") else ic
                 for ic in inp.inherited_components],
                vocab_for_check,
            )
            inherit_notes = inherit_notes_list if inherit_notes_list else None
            if not inherit_ok:
                print(f"  Inheritance check FAILED: {inherit_notes}")

        passed = all([plugin_ok, tests_ok, desc_ok, cfg_ok, inst_ok, grad_ok, otype_ok, llm_ok, inherit_ok])

        errors = [e for e in [plugin_err, desc_err, cfg_err, inst_err] if e is not None]
        if not tests_ok:
            errors.append("pytest tests failed — see test_output for details")
        if not llm_ok:
            errors.append(f"LLM review did not pass: {review.notes}")
        if not inherit_ok:
            failed_claims = [n for n in (inherit_notes or []) if "NOT FOUND" in n]
            errors.append(f"Inheritance check failed: {'; '.join(failed_claims)}")
        error_message = "; ".join(errors) if errors else None

        out = ValidatorOutput(
            passed=passed,
            model_type=inp.model_type,
            plugin_registered=plugin_ok,
            tests_passed=tests_ok,
            description_valid=desc_ok,
            config_fields_valid=cfg_ok,
            instantiation_passed=inst_ok,
            gradient_check_passed=grad_ok,
            output_type_valid=otype_ok,
            llm_review_passed=llm_ok,
            inheritance_check_passed=inherit_ok,
            inheritance_check_notes=inherit_notes,
            test_output=test_output if test_output.strip() else None,
            llm_review_spec_alignment=review.spec_alignment,
            llm_review_trainability_concerns=review.trainability_concerns,
            llm_review_implementation_issues=review.implementation_issues,
            llm_review_notes=review.notes,
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
        user_prompt = _build_review_prompt(inp, plugin_src, test_output=test_output, inst_err=inst_err)
        raw = self.bridge.generate(VALIDATOR_REVIEW_SYSTEM_PROMPT, user_prompt)
        return LLMCodeReview.model_validate(raw)

    def _save(self, inp: ValidatorInput, out: ValidatorOutput) -> None:
        workspace = inp.storage.local.workspace
        run_name = inp.storage.local.run_name
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
    p.add_argument("--config_fields", required=True, help="JSON dict of field names → default values")
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
