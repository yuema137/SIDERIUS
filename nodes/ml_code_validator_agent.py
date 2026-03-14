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

    # --- Human advice (injected by workflow) ---
    if inp.human_advice:
        parts.append(f"\n\n## Human Guidance (high priority)\n\n{inp.human_advice}\n")

    return "".join(parts)


# ---------------------------------------------------------------------------
# Deterministic check helpers
# ---------------------------------------------------------------------------

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
) -> tuple[bool, bool, str | None]:
    """
    Load plugin, instantiate config + model, run a dummy forward + backward pass.

    Returns (instantiation_ok, gradient_ok, error_message_or_None).
      - instantiation_ok: config instantiated, model instantiated, forward pass
                          produced the correct output shape [1, 256, 64].
      - gradient_ok:      backward pass succeeded and all trainable parameters
                          received non-None gradients.
    """
    spec = importlib.util.spec_from_file_location("_validator_plugin_inst", model_file_path)
    if spec is None:
        return False, False, f"Could not create module spec for {model_file_path}"
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        return False, False, f"Import error: {e}"

    # Instantiate config and model
    try:
        config = module.PLUGIN_CONFIG_CLASS()
        model = module.PLUGIN_MODEL_CLASS(config)
        model.train()
    except Exception as e:
        return False, False, f"Model instantiation failed: {e}"

    # Forward pass with small dummy input
    try:
        x = torch.randint(0, 256, (1, 64))
        out = model(x)
        if tuple(out.shape) != (1, 256, 64):
            return False, False, (
                f"Forward output shape {tuple(out.shape)} does not match expected (1, 256, 64)"
            )
    except Exception as e:
        return False, False, f"Forward pass failed: {e}"

    # Gradient flow check
    try:
        loss = out.sum()
        loss.backward()
    except Exception as e:
        return True, False, f"Backward pass failed: {e}"

    no_grad = [
        name for name, p in model.named_parameters()
        if p.requires_grad and p.grad is None
    ]
    if no_grad:
        return True, False, f"Parameters with no gradient: {no_grad[:5]}"

    return True, True, None


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

class MLCodeValidatorAgent:
    """
    Validator node for agent-generated ML model plugins.
    Combines deterministic checks with LLM code review.
    """

    def __init__(self, provider: str = "gemini", model_id: str = "gemini-3.1-flash-lite-preview"):
        self.bridge = LLMBridge(provider=provider, model_id=model_id)

    def run(self, inp: ValidatorInput) -> ValidatorOutput:
        # 1. Plugin load
        plugin_ok, plugin_err = _check_plugin(inp.model_file_path)

        # 2. Pytest
        tests_ok, test_output = _run_tests(inp.test_file_path)

        # 3. Description
        desc_ok, desc_err = _check_description(inp.description_file_path)

        # 4. Config fields
        cfg_ok, cfg_err = _check_config_fields(inp.config_fields)

        # 5 + 6. In-process instantiation + gradient (only if plugin loaded)
        if plugin_ok:
            inst_ok, grad_ok, inst_err = _check_instantiation_and_gradient(inp.model_file_path)
        else:
            inst_ok, grad_ok, inst_err = False, False, "Skipped — plugin did not load"

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

        passed = all([plugin_ok, tests_ok, desc_ok, cfg_ok, inst_ok, grad_ok, llm_ok])

        errors = [e for e in [plugin_err, desc_err, cfg_err, inst_err] if e is not None]
        if not tests_ok:
            errors.append("pytest tests failed — see test_output for details")
        if not llm_ok:
            errors.append(f"LLM review did not pass: {review.notes}")
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
            llm_review_passed=llm_ok,
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
