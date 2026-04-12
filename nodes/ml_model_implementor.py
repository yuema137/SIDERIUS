# -*- coding: utf-8 -*-
# nodes/ml_model_implementor.py
"""
ml_model_implementor — Node 4 in the SIDERIUS graph.

Reads a ProposalOutput (via ImplementorInput) and writes two files:
  - {plugin_dir}/{model_name}.py       — plugin file
  - {test_dir}/test_{model_name}.py    — test file

Uses a two-call chain-of-thought:
  1. Reasoning call (generate_text): think through implementation details —
     what PyTorch modules are needed, how to handle shapes, config fields, etc.
  2. Code call (generate): commit to specific code sections as strict JSON

The node assembles the final files from a fixed template + LLM-generated sections.
The LLM writes only the marked sections; all plugin boilerplate is fixed.

Node contract:
  run(input: ImplementorInput) -> ImplementorOutput
  CLI: --workspace, --run_name, --provider, --model_id
"""

import ast
import re
import os
import sys
import json
import types
import textwrap
import argparse
import tempfile

from agent.llm_bridge import LLMBridge
from agent.schemas.implementor import ImplementorInput, ImplementorOutput
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from agent.schemas.hyperparam_tuning import serialize_expert_advice


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _class_name(model_name: str) -> str:
    """Convert snake_case model name to CamelCase class name."""
    return "".join(word.capitalize() for word in model_name.split("_"))


# Fields provided by the fixed template — LLM must not redefine them,
# but may reference them in init_body / forward_body.
_TEMPLATE_CONFIG_FIELDS = {"segmentation_size", "batch_size"}


def _check_config_field_consistency(code: dict) -> list[str]:
    """
    Parse init_body for all ``config.<field>`` references and verify that
    each field is declared in config_fields_code (or is a template-provided
    field like segmentation_size / batch_size).

    Returns a list of missing field names (empty list = all good).
    """
    init_body = code.get("init_body", "")
    config_fields_code = code.get("config_fields_code", "")

    # All config.X references in init_body
    referenced = set(re.findall(r"config\.(\w+)", init_body))

    # Fields declared in config_fields_code (e.g. "    channels: int = Field(...)")
    declared = set(re.findall(r"^\s*(\w+)\s*:", config_fields_code, re.MULTILINE))

    # Also accept fields from the config_fields dict (belt-and-suspenders)
    config_fields_dict = code.get("config_fields", {})
    declared.update(config_fields_dict.keys())

    # Template fields are always available
    declared.update(_TEMPLATE_CONFIG_FIELDS)

    return sorted(referenced - declared)


def _smoke_test_plugin(plugin_src: str, model_name: str) -> str | None:
    """
    Dynamically load *plugin_src*, instantiate the model with default config,
    and run a dummy forward pass ``[1, 64] int64 → expected [1, 256, 64] float32``.

    Returns ``None`` on success, or a human-readable error string on failure.
    The function never raises — all errors are caught and described.
    """
    import torch  # deferred so module-level import stays lightweight

    # Write to a temp file so importlib can load it
    tmp_dir = tempfile.mkdtemp(prefix="siderius_smoke_")
    tmp_path = os.path.join(tmp_dir, f"{model_name}.py")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(plugin_src)

        # Load the module
        import importlib.util
        spec = importlib.util.spec_from_file_location(model_name, tmp_path)
        if spec is None or spec.loader is None:
            return f"Could not create import spec for {tmp_path}"
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Check required attributes
        for attr in ("PLUGIN_MODEL_TYPE", "PLUGIN_CONFIG_CLASS", "PLUGIN_MODEL_CLASS"):
            if not hasattr(mod, attr):
                return f"Plugin missing required attribute: {attr}"

        # Instantiate
        config = mod.PLUGIN_CONFIG_CLASS()
        model = mod.PLUGIN_MODEL_CLASS(config)
        model.eval()

        # Forward pass
        T = 64
        x = torch.randint(0, 256, (1, T))
        with torch.no_grad():
            out = model(x)

        # Shape check
        expected = (1, 256, T)
        if out.shape != expected:
            return (
                f"Forward pass shape mismatch: expected {expected}, "
                f"got {tuple(out.shape)}"
            )

        # NaN check
        if torch.isnan(out).any():
            return "Forward pass produced NaN values"

        return None  # success

    except Exception as e:
        return f"{type(e).__name__}: {e}"
    finally:
        # Clean up temp file
        try:
            os.remove(tmp_path)
            os.rmdir(tmp_dir)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

PLUGIN_TEMPLATE = """\
import torch
import torch.nn as nn
import torch.nn.functional as F
from pydantic import BaseModel, Field, model_validator
from typing import Self
{extra_imports}

PLUGIN_MODEL_TYPE = "{model_name}"


class {ModelClass}Config(BaseModel):
    model_type: str = Field(default="{model_name}", description="Plugin model type key.")
    segmentation_size: int = Field(default={segmentation_size}, ge=1)
    batch_size: int = Field(default={batch_size}, ge=1)
{config_fields_code}
{config_validators_code}

PLUGIN_CONFIG_CLASS = {ModelClass}Config


class {ModelClass}(nn.Module):
    def __init__(self, config: "{ModelClass}Config"):
        super().__init__()
{init_body}

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # forward contract: input [B, T] int64 → output [B, 256, T] float32
{forward_body}


PLUGIN_MODEL_CLASS = {ModelClass}
PLUGIN_OUTPUT_TYPE = "classifier"  # [B, 256, T] → 256-class classification
"""

TEST_TEMPLATE = """\
import torch
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "models"))
from {model_name} import PLUGIN_MODEL_CLASS, PLUGIN_CONFIG_CLASS


def test_forward_shape():
    config = PLUGIN_CONFIG_CLASS()
    model = PLUGIN_MODEL_CLASS(config)
    model.eval()
    x = torch.randint(0, 256, (2, config.segmentation_size))
    with torch.no_grad():
        out = model(x)
    assert out.shape == (2, 256, config.segmentation_size), (
        f"Expected (2, 256, {{config.segmentation_size}}), got {{out.shape}}"
    )


def test_forward_no_nan():
    config = PLUGIN_CONFIG_CLASS()
    model = PLUGIN_MODEL_CLASS(config)
    model.eval()
    x = torch.randint(0, 256, (1, config.segmentation_size))
    with torch.no_grad():
        out = model(x)
    assert not torch.isnan(out).any(), "Forward pass produced NaN values"


def test_config_instantiation():
    config = PLUGIN_CONFIG_CLASS()
    assert config.segmentation_size > 0
    assert config.batch_size >= 1
"""


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

IMPLEMENTOR_REASONING_PROMPT = """\
You are a senior PyTorch engineer specialising in 1-D signal processing models.

Your task: given a mathematical description of a new neural architecture and its
baseline configuration, plan the PyTorch implementation in detail before writing code.

Background on the task:
- Input data: TIDMAD SQUID magnetometry time-series, integer ADC values 0–255.
- The model must satisfy this forward contract (non-negotiable):
    input:  [B, T]       int64   — raw signal, integer class indices (0–255)
    output: [B, 256, T]  float32 — per-timestep logits over 256 denoising classes
- ADC values must be embedded: the model receives integer indices, not floats.
  Use nn.Embedding(256, embed_dim) to convert [B, T] int64 → [B, T, embed_dim],
  then transpose to [B, embed_dim, T] for Conv1d layers (or keep as [B, T, embed_dim]
  for transformer-style layers).
- The output must be exactly [B, 256, T] — use a final Conv1d(channels, 256, 1)
  or Linear + transpose to achieve this.
- GPU budget: <10 GB VRAM, <100M parameters for initial exploration.

In your reasoning, cover all of the following:
1. What nn.Module submodules are needed? Name each one and its role.
2. How will you handle the embedding step and get the right tensor shapes?
3. Trace the full forward pass, showing the tensor shape at each stage.
4. What Pydantic config fields are needed? For each: name, type, default, valid range.
   Keep them minimal — only fields that the hyperparameter tuner will actually search.
   For every channel dimension, answer these questions:
   a. Is it passed to `.chunk(2, dim=1)` (gated activation)? If yes, it MUST be even.
      Use `Field(..., multiple_of=2)` to enforce this.
   b. Is it used as `d_model` in a TransformerEncoderLayer or MultiheadAttention?
      If yes, it MUST be divisible by `nhead`. Choose defaults that satisfy this
      (e.g. skip_channels=32, nhead=4). State the divisibility explicitly.
   c. Is it used in a sinusoidal positional encoding that computes sin/cos pairs?
      If yes, it MUST be even. Use `Field(..., multiple_of=2)`.
5. Are there any shape alignment issues (e.g. after pooling/upsampling)?
   How will you handle them?
6. What additional imports beyond torch, nn, F, BaseModel, Field are needed?

Think step by step. Be concrete about tensor shapes at each stage.
Do not write final Python code yet — that is the next step."""


IMPLEMENTOR_CODE_PROMPT = """\
You are a senior PyTorch engineer. You have just reasoned through a PyTorch implementation.
Now commit to the actual code sections.

Output a JSON object with exactly these fields:

{
  "extra_imports": "any additional import lines beyond torch/nn/F/BaseModel/Field/model_validator, one per line, or empty string",
  "config_fields_code": "additional Pydantic field definitions — each line indented with 4 spaces, e.g.:\\n    channels: int = Field(default=64, ge=8, le=256)\\n    depth: int = Field(default=4, ge=1, le=8)",
  "config_validators_code": "a @model_validator(mode='after') method enforcing divisibility constraints, indented with 4 spaces — or empty string if no constraints needed. Example:\\n    @model_validator(mode='after')\\n    def check_constraints(self) -> Self:\\n        if self.gate_channels % 2 != 0:\\n            raise ValueError(f'gate_channels must be even, got {self.gate_channels}')\\n        if self.skip_channels % self.nhead != 0:\\n            raise ValueError(f'skip_channels ({self.skip_channels}) must be divisible by nhead ({self.nhead})')\\n        return self",
  "config_fields": {"field_name": default_value, ...},
  "init_body": "the __init__ body after super().__init__(). Each line indented with 8 spaces.",
  "forward_body": "the forward body. Each line indented with 8 spaces. Must return [B, 256, T] float32."
}

Hard constraints — violating any of these makes the code invalid:
- The forward method signature is: def forward(self, x: torch.Tensor) -> torch.Tensor:
  The input argument is named x. Use x everywhere in forward_body — NEVER use 'input' (that is a Python builtin).
- forward_body MUST end with a statement that returns a tensor of shape [B, 256, T] float32.
- init_body must define ALL modules referenced in forward_body.
- If forward_body needs any config value (e.g. a size, a count), store it as a plain attribute
  in init_body (e.g. `self.window_size = config.window_size`). Do NOT access `config` inside
  forward_body — it is only in scope during __init__.
- Do NOT define or reference any helper classes (e.g. ResidualBlock, GatedBlock) — there is no
  slot in the template for class definitions outside __init__ and forward. All logic must be
  written inline using nn.ModuleList, nn.Sequential, or standard PyTorch primitives only.
- When building a list of modules dynamically, always use a list comprehension — NEVER pass a
  generator expression to nn.ModuleList or nn.Sequential. Correct: `nn.ModuleList([... for ...])`.
  Wrong: `nn.ModuleList(... for ...)`. Generator expressions are not accepted by PyTorch containers.
- Every `config.<field>` reference in init_body MUST have a matching field defined in
  config_fields_code. Accessing a config attribute that is not declared will cause an
  AttributeError at runtime. Before finalising, scan your init_body for every `config.X`
  and confirm that X appears in config_fields_code.
- config_fields dict must contain exactly the same field names as config_fields_code, with their default values.
- All config fields must be scalar types (int, float, bool) — do NOT use List, Dict, or other
  container types, as the hyperparameter tuner searches scalar dimensions only.
- Do NOT include segmentation_size or batch_size in config_fields_code — those are already in the template.
- Do NOT wrap the code in a class or function — write only the method body lines.
- Do NOT include markdown fences or commentary in the code values.
- Use only Pydantic V2 Field kwargs: ge, le, gt, lt, multiple_of, min_length, max_length.
  Do NOT use min_items or max_items (those are Pydantic V1 and are deprecated).
- Any channel dimension passed to `.chunk(2, dim=1)` (e.g. gate_channels for gated
  activation) MUST be even. Declare it with `Field(..., multiple_of=2)`.
- Any channel dimension used as `d_model` in TransformerEncoderLayer MUST satisfy
  `d_model % nhead == 0`. Verify your default values satisfy this before committing
  (e.g. skip_channels=32 with nhead=4 is valid; skip_channels=32 with nhead=6 is NOT).

Output only the JSON object — no preamble, no markdown fences, no commentary."""


IMPLEMENTOR_REPAIR_PROMPT = """\
Your previous code attempt failed validation. Fix the issue and return a corrected
JSON object with the same 5 fields: extra_imports, config_fields_code, config_fields,
init_body, forward_body.

All the hard constraints from the previous prompt still apply.
Focus specifically on the error described below — do not rewrite unrelated code.

Output only the JSON object — no preamble, no markdown fences, no commentary."""


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_reasoning_prompt(inp: ImplementorInput) -> str:
    model_cfg = inp.baseline_config.get("model_config", {})
    train_cfg = inp.baseline_config.get("train_config", {})

    lines = [
        f"## Model to implement: `{inp.model_name}`",
        "",
        "## Description",
        inp.model_description,
        "",
        "## Mathematical definition",
        inp.mathematical_definition,
        "",
        "## Baseline configuration",
        "model_config:",
        json.dumps(model_cfg, indent=2),
        "",
        "train_config (for context only — do not implement training logic):",
        f"  segmentation_size: {train_cfg.get('segmentation_size', 40000)} (if present)",
        f"  batch_size: {train_cfg.get('batch_size', 1)}",
        "",
        "## Forward contract (non-negotiable)",
        "  input:  [B, T]       int64   — raw ADC signal",
        "  output: [B, 256, T]  float32 — per-timestep logits",
    ]

    # --- Expert advice (from upstream agents) ---
    expert_advice_str = serialize_expert_advice(inp.expert_advice) if inp.expert_advice else ""
    if expert_advice_str:
        lines += [
            "",
            "## Expert Guidance (from upstream agents)",
            expert_advice_str,
        ]

    # --- Human advice (injected by workflow) ---
    if inp.human_advice:
        lines += [
            "",
            "## Human Guidance (high priority)",
            inp.human_advice,
        ]

    # --- Reference code from ancestor models ---
    if inp.reference_code:
        lines += [
            "",
            "## Reference Code (from ancestor models — USE AS TEMPLATE)",
            "",
            "The following source code is from models your design inherits from.",
            "Use this as a reference implementation — copy and modify rather than",
            "writing from scratch. Preserve the reference code's architectural",
            "patterns faithfully, even if some appear redundant. The reference",
            "code is a WORKING implementation; your job is to extend it, not",
            "to rewrite it from scratch.",
            "",
        ]
        for model_type, source in inp.reference_code.items():
            lines += [
                f"### {model_type} (reference implementation)",
                "```python",
                source,
                "```",
                "",
            ]

    return "\n".join(lines)


def _build_code_prompt(reasoning: str, inp: ImplementorInput) -> str:
    model_cfg = inp.baseline_config.get("model_config", {})
    return (
        f"## Your Reasoning\n\n{reasoning}\n\n"
        f"---\n\n"
        f"## Model name: `{inp.model_name}`\n"
        f"## Class name: `{_class_name(inp.model_name)}`\n"
        f"## Baseline model_config (use these as Field defaults): {json.dumps(model_cfg)}\n\n"
        "Now output the JSON code sections."
    )


def _build_repair_prompt(
    code: dict,
    error: str,
    inp: ImplementorInput,
    error_history: list[tuple[int, str]] | None = None,
) -> str:
    """
    Build repair prompt with full error history so the LLM doesn't fix one
    mistake only to reintroduce a previous one.

    Args:
        code: The last generated code dict.
        error: The current (latest) error.
        inp: Implementor input.
        error_history: List of (attempt_number, error_message) for all prior
            failed attempts, in chronological order. Excludes the current error.
    """
    model_cfg = inp.baseline_config.get("model_config", {})

    history_section = ""
    if error_history:
        history_lines = ["## Error History (do NOT reintroduce these mistakes)\n"]
        for attempt_num, past_error in error_history:
            history_lines.append(f"Attempt {attempt_num}: {past_error}")
        history_section = "\n".join(history_lines) + "\n\n"

    return (
        f"## Previous code (failed)\n\n"
        f"```json\n{json.dumps(code, indent=2)}\n```\n\n"
        f"## Current Error (fix this)\n\n{error}\n\n"
        f"{history_section}"
        f"---\n\n"
        f"## Model name: `{inp.model_name}`\n"
        f"## Class name: `{_class_name(inp.model_name)}`\n"
        f"## Baseline model_config: {json.dumps(model_cfg)}\n\n"
        "Fix the current error without reintroducing any error from the history. "
        "Output the corrected JSON code sections."
    )


# ---------------------------------------------------------------------------
# File assembly
# ---------------------------------------------------------------------------

def _assemble_plugin(inp: ImplementorInput, code: dict) -> str:
    model_cfg  = inp.baseline_config.get("model_config", {})
    train_cfg  = inp.baseline_config.get("train_config", {})
    seg_size   = model_cfg.get("segmentation_size", train_cfg.get("segmentation_size", 40000))
    batch_size = model_cfg.get("batch_size", train_cfg.get("batch_size", 1))
    model_cls  = _class_name(inp.model_name)

    extra_imports      = code.get("extra_imports", "").strip()
    config_fields_code = code.get("config_fields_code", "").rstrip()
    config_validators_code = code.get("config_validators_code", "").rstrip()
    init_body          = code.get("init_body", "        pass").rstrip()
    forward_body       = code.get("forward_body", "        pass").rstrip()

    # Ensure correct indentation: init_body and forward_body must be indented 8 spaces
    init_body    = textwrap.indent(textwrap.dedent(init_body), "        ")
    forward_body = textwrap.indent(textwrap.dedent(forward_body), "        ")

    # Remove imports already present in the fixed template header to avoid duplicates.
    # Also drop any line that is not a valid import statement (must start with 'import'
    # or 'from') — LLMs occasionally emit partial fragments like "torch.nn.functional as F"
    # which would cause a SyntaxError.
    _already_imported = {"import torch", "import torch.nn as nn",
                         "import torch.nn.functional as F",
                         "from pydantic import BaseModel, Field"}
    extra_lines = [
        line for line in extra_imports.splitlines()
        if line.strip()
        and line.strip() not in _already_imported
        and (line.strip().startswith("import ") or line.strip().startswith("from "))
    ]
    extra_imports = "\n".join(extra_lines)

    # extra_imports: ensure leading newline if non-empty
    if extra_imports:
        extra_imports = "\n" + extra_imports

    # Indent validators with 4 spaces (class body level); dedent first to normalise
    if config_validators_code.strip():
        config_validators_code = textwrap.indent(
            textwrap.dedent(config_validators_code), "    "
        )

    return PLUGIN_TEMPLATE.format(
        model_name=inp.model_name,
        ModelClass=model_cls,
        segmentation_size=seg_size,
        batch_size=batch_size,
        extra_imports=extra_imports,
        config_fields_code=config_fields_code,
        config_validators_code=config_validators_code,
        init_body=init_body,
        forward_body=forward_body,
    )


def _assemble_test(model_name: str) -> str:
    return TEST_TEMPLATE.format(model_name=model_name)


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

class MLModelImplementor:

    def __init__(self, provider: str = "gemini", model_id: str = "gemini-3.1-pro-preview",
                 max_retries: int | None = None):
        self.bridge = LLMBridge(provider=provider, model_id=model_id, max_retries=max_retries)

    # ------------------------------------------------------------------
    # Validation helpers (used in the generate-validate-repair loop)
    # ------------------------------------------------------------------

    @staticmethod
    def _patch_common_mistakes(code: dict) -> dict:
        """Fix known LLM quirks in generated code sections (in-place + return)."""
        for field in ("init_body", "forward_body"):
            if field not in code:
                continue
            src = code[field]
            src = src.replace("self.embedding(input)", "self.embedding(x)")
            src = "\n".join(line.rstrip("$") for line in src.splitlines())
            code[field] = src
        return code

    @staticmethod
    def _validate_code(code: dict, inp: ImplementorInput) -> str | None:
        """
        Run all three pre-write checks on *code*.

        Returns ``None`` if all checks pass, or a human-readable error string
        describing the first failure.
        """
        # Check 1: config field consistency
        missing = _check_config_field_consistency(code)
        if missing:
            return (
                f"Config field consistency: init_body references config fields "
                f"not declared in config_fields_code: {missing}. "
                f"Each config.<field> used in __init__ must have a corresponding "
                f"Pydantic Field definition."
            )

        # Check 2: config fields must be scalar (int, float, bool)
        config_fields = code.get("config_fields", {})
        non_scalar = {
            k: type(v).__name__ for k, v in config_fields.items()
            if not isinstance(v, (int, float, bool))
        }
        if non_scalar:
            return (
                f"Non-scalar config fields: {non_scalar}. "
                f"All config fields must be int, float, or bool — "
                f"the hyperparameter tuner only searches scalar dimensions. "
                f"Remove or replace string/list/dict fields with scalar alternatives."
            )

        # Check 3: syntax
        plugin_src = _assemble_plugin(inp, code)
        try:
            ast.parse(plugin_src)
        except SyntaxError as e:
            return (
                f"Syntax error in assembled plugin: {e}. "
                f"Check for undefined helper classes or malformed expressions."
            )

        # Check 3: smoke test (instantiate + forward pass)
        smoke_error = _smoke_test_plugin(plugin_src, inp.model_name)
        if smoke_error:
            return f"Smoke test failed: {smoke_error}"

        return None  # all good

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, inp: ImplementorInput) -> ImplementorOutput:
        print(f"🔧 Implementing model '{inp.model_name}' ...")

        # --- Call 1: reasoning (free text, runs once) ---
        reasoning_prompt = _build_reasoning_prompt(inp)
        reasoning = self.bridge.generate_text(IMPLEMENTOR_REASONING_PROMPT, reasoning_prompt)
        print(f"   Reasoning complete ({len(reasoning)} chars).")

        # --- Call 2: code commit (strict JSON) ---
        code_prompt = _build_code_prompt(reasoning, inp)
        code = self.bridge.generate(IMPLEMENTOR_CODE_PROMPT, code_prompt)
        code = self._patch_common_mistakes(code)

        # --- Validate → repair loop ---
        max_retries = inp.max_retries
        error = self._validate_code(code, inp)
        attempt = 0
        error_history: list[tuple[int, str]] = []
        while error is not None and attempt < max_retries:
            attempt += 1
            print(f"   ⚠ Attempt {attempt + 1}/{max_retries + 1}: {error}")
            repair_prompt = _build_repair_prompt(code, error, inp, error_history)
            error_history.append((attempt, error))
            code = self.bridge.generate(IMPLEMENTOR_REPAIR_PROMPT, repair_prompt)
            code = self._patch_common_mistakes(code)
            error = self._validate_code(code, inp)

        # If still failing after retries, raise with the last error
        if error is not None:
            plugin_src = _assemble_plugin(inp, code)
            raise ValueError(
                f"Code generation failed after {max_retries + 1} attempts "
                f"for '{inp.model_name}': {error}\n\n"
                f"The assembled plugin source:\n{plugin_src}"
            )

        if attempt > 0:
            print(f"   ✅ Self-correction succeeded on attempt {attempt + 1}.")

        plugin_src = _assemble_plugin(inp, code)
        test_src   = _assemble_test(inp.model_name)

        # --- Write plugin file ---
        os.makedirs(inp.plugin_dir, exist_ok=True)
        model_file_path = os.path.abspath(
            os.path.join(inp.plugin_dir, f"{inp.model_name}.py")
        )
        with open(model_file_path, "w", encoding="utf-8") as f:
            f.write(plugin_src)
        print(f"✅ Plugin written → {model_file_path}")

        # --- Write description.md so result_interpretation_agent can load it ---
        # Mirrors the structure expected by ml_models/model_descriptions.py:
        #   agent_generated/models/{model_name}/description.md
        desc_dir  = os.path.join(inp.plugin_dir, inp.model_name)
        desc_path = os.path.join(desc_dir, "description.md")
        os.makedirs(desc_dir, exist_ok=True)
        description_md = (
            f"# {_class_name(inp.model_name)}\n\n"
            f"## Overview\n\n{inp.model_description}\n\n"
            f"**Forward contract:** `[B, T] int64 → [B, 256, T] float32`\n\n"
            f"## Architecture\n\n{inp.mathematical_definition}\n\n"
            f"## Baseline Configuration\n\n"
            f"```json\n{json.dumps(inp.baseline_config, indent=2)}\n```\n"
        )
        with open(desc_path, "w", encoding="utf-8") as f:
            f.write(description_md)
        print(f"✅ Description   → {desc_path}")

        # --- Write test file ---
        os.makedirs(inp.test_dir, exist_ok=True)
        test_file_path = os.path.abspath(
            os.path.join(inp.test_dir, f"test_{inp.model_name}.py")
        )
        with open(test_file_path, "w", encoding="utf-8") as f:
            f.write(test_src)
        print(f"✅ Test written  → {test_file_path}")

        # --- Build output ---
        config_fields = code.get("config_fields", {})
        output = ImplementorOutput(
            model_type=inp.model_name,
            description_file_path=os.path.abspath(desc_path),
            model_file_path=model_file_path,
            test_file_path=test_file_path,
            config_fields=config_fields,
            model_description=inp.model_description,
            mathematical_definition=inp.mathematical_definition,
        )

        # --- Persist output record ---
        if inp.storage.backend == "local" and inp.storage.local:
            workspace = inp.storage.local.workspace
            run_name  = inp.storage.local.run_name
            os.makedirs(workspace, exist_ok=True)
            out_path = os.path.join(workspace, f"implementor_{run_name}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(output.model_dump_json(indent=4))
            print(f"✅ Output record → {out_path}")

        return output


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="SIDERIUS ml_model_implementor")
    parser.add_argument("--workspace", type=str, default="./siderius_workspace")
    parser.add_argument("--run_name",  type=str, default="v1")
    parser.add_argument("--provider",  type=str, default="gemini", choices=["gemini", "openai"])
    parser.add_argument("--model_id",  type=str, default="gemini-3.1-pro-preview")
    args = parser.parse_args()

    proposal_path = os.path.join(args.workspace, f"proposal_{args.run_name}.json")
    if not os.path.exists(proposal_path):
        raise FileNotFoundError(
            f"Proposal file not found: {proposal_path}\n"
            f"Run ml_model_proposal_agent first."
        )
    with open(proposal_path, "r", encoding="utf-8") as f:
        proposal = json.load(f)

    agent_input = ImplementorInput(
        model_name=proposal["model_name"],
        model_description=proposal["model_description"],
        mathematical_definition=proposal["mathematical_definition"],
        baseline_config=proposal["baseline_config"],
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=args.workspace, run_name=args.run_name),
        ),
    )

    agent = MLModelImplementor(provider=args.provider, model_id=args.model_id)
    output = agent.run(agent_input)

    print(f"\n{'='*60}")
    print(f"  Implementor — {output.model_type}")
    print(f"{'='*60}")
    print(f"  Plugin  : {output.model_file_path}")
    print(f"  Tests   : {output.test_file_path}")
    print(f"  Config  : {output.config_fields}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
