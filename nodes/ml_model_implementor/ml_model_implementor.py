# nodes/ml_model_implementor/ml_model_implementor.py
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

import argparse
import ast
import json
import os
import re
import tempfile
import textwrap
from datetime import UTC, datetime

from agent.llm_bridge import LLMBridge
from agent.schemas.hyperparam_tuning import serialize_expert_advice
from agent.schemas.implementor import ImplementorInput, ImplementorOutput, LossProvenance
from agent.schemas.proposal import CustomLossSpec
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.task_config import ForwardContract
from agent_generated._registry import CapabilityMetadata, CapabilityRegistry
from workflows.task_config import render_forward_contract

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
            return f"Forward pass shape mismatch: expected {expected}, got {tuple(out.shape)}"

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


def _check_baseline_schema_compatibility(
    plugin_src: str,
    model_name: str,
    baseline_config: dict,
) -> str | None:
    """
    Verify the implementor's pydantic config schema accepts the proposer's
    ``baseline_config['model_config']`` values — not just its own defaults.

    This is Phase B.2's post-write gate. The smoke test already instantiates
    ``PLUGIN_CONFIG_CLASS()`` with defaults (which always pass by construction);
    this helper instantiates ``PLUGIN_CONFIG_CLASS(**model_config)`` with the
    values the proposer actually asked for. A mismatch means the implementor
    invented a constraint (e.g. ``multiple_of=2``) that rejects the proposer's
    baseline (e.g. ``refiner_kernel_size=5``) — the exact failure mode seen in
    the 2026-04-16 `explore_novel_v1` run.

    The returned error string is consumed by the existing `_validate_code` →
    `_build_repair_prompt` retry loop, so no new wiring is needed.

    Returns ``None`` on success (or when there is no baseline to check), or a
    human-readable error string describing the rejection and pointing the LLM
    toward the adjust-or-relax options. Never raises — unexpected errors are
    returned as None so the smoke test / syntax check can surface them instead.

    Args:
        plugin_src: The assembled plugin source code.
        model_name: The snake_case model type (used as import name).
        baseline_config: ``inp.baseline_config`` — the full proposer baseline.
            The ``model_config`` subdict is what gets fed to the schema.

    Returns:
        ``None`` when the schema accepts the baseline (or when there is nothing
        to check), or an error string when the schema rejects it.
    """
    model_cfg = (baseline_config or {}).get("model_config") or {}
    if not model_cfg:
        return None  # No baseline values to check — skip gracefully

    tmp_dir = tempfile.mkdtemp(prefix="siderius_basecheck_")
    tmp_path = os.path.join(tmp_dir, f"{model_name}.py")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(plugin_src)

        import importlib.util

        spec = importlib.util.spec_from_file_location(model_name, tmp_path)
        if spec is None or spec.loader is None:
            return None  # Smoke/syntax check already covers import failure
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception:
            return None  # Import error — smoke/syntax check will surface it

        if not hasattr(mod, "PLUGIN_CONFIG_CLASS"):
            return None  # Smoke test will surface the missing attribute

        try:
            mod.PLUGIN_CONFIG_CLASS(**model_cfg)
        except Exception as exc:
            return (
                f"Baseline self-check failed: the plugin's PLUGIN_CONFIG_CLASS "
                f"rejects the proposer's baseline_config.model_config. "
                f"Schema error: {type(exc).__name__}: {exc}\n"
                f"Proposer's model_config was: {model_cfg}\n"
                f"To fix: RELAX the offending schema constraint on the field "
                f"named in the error above so the baseline value is accepted. "
                f"Do NOT change `segmentation_size` — that field is owned by "
                f"the proposer."
            )
        return None

    finally:
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
You are a senior PyTorch engineer specialising in deep learning for signal denoising.

Your task: given a mathematical description of a new neural architecture and its
baseline configuration, plan the PyTorch implementation in detail before writing code.

{TASK_BACKGROUND}- GPU budget: <10 GB VRAM, <100M parameters for initial exploration.

## Allowed imports — STRICT ALLOW-LIST

The plugin runtime is a RESTRICTED sandbox. The ONLY modules you may import are:
  - torch
  - torch.nn (as nn)
  - torch.nn.functional (as F)
  - pydantic (BaseModel, Field, model_validator)
  - typing (Self, Optional, List, Tuple, etc.)
  - math
  - dataclasses

ANY other import will fail at plugin load time. In particular:
  - Do NOT import from `your_module`, `some_module`, `ml_models`, `agent`,
    `core`, `utils`, or any project-internal path.
  - Do NOT import third-party libraries (numpy, scipy, einops, etc.) — they
    are not guaranteed available in the sandbox.
  - Do NOT use placeholder names like `from your_module import X` even as a
    template; the plugin loader will reject them.
  - If you need a primitive that is not in the allow-list, INLINE its logic
    using the allowed modules — do not invent an import.

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

## Construction-time memory anti-pattern — STRICT

NEVER pre-allocate buffers in ``__init__`` that scale with the sequence length T.
Hidden states for SSM/RNN must be shape ``[B, d_state]`` (NOT ``[B, T, d_state]``
or ``[T, T]``). FFT plans must not materialize T-length arrays at construction
time. A single layer with a ``[T, T]`` buffer at ``T=16000`` costs 1 GB of RAM;
4 layers × optimizer moments = >10 GB — the process will be OOM-killed BEFORE
training starts, and the pre-flight VRAM probe will not catch it because the
allocation happens in CPU host RAM at module-construct time, not in CUDA.

What this rule covers:
  - SSM ``A``/``B``/``C``/``D`` matrices: only the recurrent state matrix
    ``A`` of shape ``[d_state]`` or ``[d_state, d_state]`` belongs in
    ``__init__``. The unrolled state sequence ``h[1..T]`` must live in
    ``forward()`` and be released between steps (or computed via an
    associative scan that does not materialize the full T-length tensor).
  - Attention: precomputed ``[T, T]`` masks / positional biases at full
    ``segmentation_size`` are forbidden. Generate masks on the fly inside
    ``forward()`` or use a chunk size strictly less than ``segmentation_size``.
  - FFT: ``torch.fft.rfft`` plans are JIT-compiled — fine. Pre-baking
    ``[T // 2 + 1]`` filter coefficients is fine (small). Pre-baking a
    ``[T, T]`` mixing matrix is NOT fine.
  - Positional encodings: a sinusoidal PE table of shape ``[max_len, d]``
    is fine when ``max_len`` is a config field (typically ≤ 1024). A
    ``[T, T]`` relative-position matrix at full ``segmentation_size`` is
    not.

A useful check before declaring any ``self.<name> = ...`` in ``__init__``:
ask "does this tensor's first dimension equal ``segmentation_size``?" If
yes, move it to ``forward()`` or rework the architecture.

Think step by step. Be concrete about tensor shapes at each stage.
Do not write final Python code yet — that is the next step."""


IMPLEMENTOR_CODE_PROMPT = """\
You are a senior PyTorch engineer. You have just reasoned through a PyTorch implementation.
Now commit to the actual code sections.

Output a JSON object with exactly these fields:

{
  "extra_imports": "any additional import lines beyond torch/nn/F/BaseModel/Field/model_validator, one per line, or empty string. STRICT ALLOW-LIST: only `import math`, `import dataclasses`, and additional `from typing import ...` lines are accepted. NEVER emit `from your_module import ...`, `from some_module import ...`, `from ml_models...`, or any project-internal/third-party path — the plugin loader will fail.",
  "config_fields_code": "additional Pydantic field definitions — each line indented with 4 spaces, e.g.:\\n    channels: int = Field(default=64, ge=8, le=256)\\n    depth: int = Field(default=4, ge=1, le=8)",
  "config_validators_code": "a @model_validator(mode='after') method enforcing divisibility constraints, indented with 4 spaces — or empty string if no constraints needed. Example:\\n    @model_validator(mode='after')\\n    def check_constraints(self) -> Self:\\n        if self.gate_channels % 2 != 0:\\n            raise ValueError(f'gate_channels must be even, got {self.gate_channels}')\\n        if self.skip_channels % self.nhead != 0:\\n            raise ValueError(f'skip_channels ({self.skip_channels}) must be divisible by nhead ({self.nhead})')\\n        return self",
  "config_fields": {"field_name": default_value, ...},
  "init_body": "the __init__ body after super().__init__(). Each line indented with 8 spaces.",
  "forward_body": "the forward body. Each line indented with 8 spaces. Must return {OUTPUT_SHAPE}."
}

Hard constraints — violating any of these makes the code invalid:
- The forward method signature is: def forward(self, x: torch.Tensor) -> torch.Tensor:
  The input argument is named x. Use x everywhere in forward_body — NEVER use 'input' (that is a Python builtin).
- forward_body MUST end with a statement that returns a tensor of shape {OUTPUT_SHAPE}.
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
# L4 — Loss-plugin template + prompts + assembly + dummy-tensor validator
# ---------------------------------------------------------------------------
#
# The implementor's existing flow generates a MODEL plugin into
# ``inp.plugin_dir``. L4 adds a parallel flow that generates a LOSS plugin
# into ``inp.loss_dir`` when ``inp.custom_loss_spec`` is set. The model and
# loss flows share the same ``self.bridge``; only the prompts, the
# assembly template, and the dummy-tensor validation differ.
#
# See ``docs/design/enable_loss_inventory.md`` § Commit L4.


# Fixed boilerplate for the loss plugin. The LLM fills only the variable
# slots (extra_imports, config_fields_code, config_validators_code,
# init_body, forward_body); the 3 required PLUGIN_LOSS_* constants and the
# class/config skeleton are produced by the template so the LLM cannot
# accidentally omit them.
LOSS_PLUGIN_TEMPLATE = """\
import torch
import torch.nn as nn
import torch.nn.functional as F
from pydantic import BaseModel, Field, model_validator
from typing import Self
{extra_imports}

PLUGIN_LOSS_TYPE = "{loss_name}"

# I13 — target dtype the loss expects. "long" (int64) is the classifier
# contract; "float" matches a regressor (smooth_l1-style) contract. All
# losses generated under the current proposer forward contract use "long".
PLUGIN_LOSS_TARGET_DTYPE = "long"


class {LossClass}Config(BaseModel):
    \"\"\"Hyperparameters for the {loss_name} loss.

    Lives in the plugin's own config namespace per the two-config design.
    Independent of ``LossConfig`` (the router in ``ml_models``); the agent
    cannot reach LossConfig.alpha / gamma / beta from here.
    \"\"\"
{config_fields_code}
{config_validators_code}

PLUGIN_LOSS_CONFIG_CLASS = {LossClass}Config


class {LossClass}(nn.Module):
    \"\"\"{description}\"\"\"

    def __init__(self, config: "{LossClass}Config"):
        super().__init__()
{init_body}

    def forward(self, inputs: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        # Forward contract:
        #   inputs:  [B, num_classes, T] float32  (model logits)
        #   targets: [B, T]              int64    (class indices)
        #   returns: scalar tensor                (requires_grad=True)
{forward_body}


PLUGIN_LOSS_CLASS = {LossClass}
"""


IMPLEMENTOR_LOSS_REASONING_PROMPT = """\
You are a senior PyTorch engineer specialising in loss functions for signal denoising.

Your task: given a mathematical definition for a new loss function, plan its PyTorch
implementation in detail before writing code. The loss receives classifier-shaped
logits and integer class targets; it must return a SCALAR tensor with gradient.

## Forward contract — non-negotiable

  - ``inputs``  : ``torch.Tensor`` of shape ``[B, num_classes, T]`` (float32, logits)
  - ``targets`` : ``torch.Tensor`` of shape ``[B, T]``              (int64, class indices in [0, num_classes))
  - returns     : ``torch.Tensor`` SCALAR  (i.e. ``.dim() == 0``)
                  with ``requires_grad=True`` so training can backprop.

## Module-level constant — REQUIRED (I13)

Every loss plugin you generate MUST declare ``PLUGIN_LOSS_TARGET_DTYPE``
at module level. For the classifier contract above (int64 targets), the
value is the literal string ``"long"``. The template already includes
this declaration — do NOT remove or rename it. Consumers
(``evaluate_time_skill``, ``train_engine_sandbox``) read this to decide
whether to cast targets to ``.long()`` or ``.float()`` before invoking
your loss. Missing this declaration will silently default to ``"long"``
but is treated as a defect.

## Allowed imports — STRICT ALLOW-LIST

The loss plugin runtime is the same RESTRICTED sandbox as model plugins. ONLY:
  - torch
  - torch.nn (as nn)
  - torch.nn.functional (as F)
  - pydantic (BaseModel, Field, model_validator)
  - typing (Self, Optional, List, Tuple, etc.)
  - math
  - dataclasses

ANY other import will fail at plugin load time. In particular:
  - Do NOT import from project-internal paths (`ml_models`, `agent`, `core`, ...).
  - Do NOT import third-party libraries (numpy, scipy, einops, ...).
  - If you need something not in the allow-list, INLINE its logic with torch ops.

## Anti-patterns to avoid

  - Do NOT return a non-scalar tensor (any reduction over the leading and time
    dims is fine: ``.mean()``, ``.sum()`` / batch_size, etc.).
  - Do NOT compute the loss on ``targets.float()`` without checking shape — if the
    loss uses ``F.cross_entropy`` or similar, pass the int64 targets directly.

## Gradient-flow requirement

The final scalar loss MUST have gradient flowing back to ``inputs``. The
implementor's validator runs ``loss.backward()`` on dummy tensors and rejects
the plugin if ``inputs.grad is None``.

You MAY use ``.detach()`` or ``torch.no_grad()`` on **weighting or masking
terms** (treating them as constants is legitimate and sometimes necessary for
non-differentiable operations like ``argmax``-based weights). However, NEVER
call ``.detach()`` on ``inputs`` directly, and never sever the main
computational path from ``inputs`` → loss.

Safe pattern — weight is detached; gradient still flows via ``F.cross_entropy``:

    with torch.no_grad():
        weight = compute_weight(inputs, targets)   # treated as constant
    per_elem = F.cross_entropy(inputs, targets, reduction='none')  # flows grad
    loss = (per_elem * weight).mean()

Unsafe pattern — severs gradient entirely (validator will reject):

    loss = F.cross_entropy(inputs.detach(), targets)  # inputs.grad will be None

In your reasoning, cover all of the following:
1. How will you reduce the per-element loss to a scalar (mean? sum? weighted mean?).
2. Does the loss require any per-class weighting, auxiliary tensor, or spectral
   transform? If so, name each one and how it is computed from ``inputs`` / ``targets``.
3. What Pydantic config fields are needed? For each: name, type, default, valid range.
   Keep them minimal — the agent will tune these later.
4. What additional imports beyond torch, nn, F, BaseModel, Field, model_validator are needed?
5. Trace the forward pass shape-by-shape from ``[B, num_classes, T]`` to scalar.

Think step by step. Be concrete about tensor shapes at each stage.
Do not write final Python code yet — that is the next step."""


IMPLEMENTOR_LOSS_CODE_PROMPT = """\
You are a senior PyTorch engineer. You have just reasoned through a loss implementation.
Now commit to the actual code sections.

Output a JSON object with exactly these fields:

{
  "extra_imports": "any additional import lines beyond torch/nn/F/BaseModel/Field/model_validator/Self, one per line, or empty string. STRICT ALLOW-LIST: only `import math`, `import dataclasses`, and additional `from typing import ...` lines are accepted.",
  "config_fields_code": "Pydantic field definitions for the loss's own hyperparameters — each line indented with 4 spaces, e.g.:\\n    snr_threshold: float = Field(default=0.5, ge=0.0, le=1.0)\\n    high_snr_weight: float = Field(default=2.0, ge=0.1, le=10.0)\\nEmpty string if the loss has no tunable hyperparameters.",
  "config_validators_code": "optional @model_validator(mode='after') method enforcing cross-field constraints, indented with 4 spaces — or empty string if no constraints needed.",
  "config_fields": {"field_name": default_value, ...},
  "init_body": "the __init__ body after super().__init__(). Each line indented with 8 spaces. Use this to copy config values onto self (e.g. `self.snr_threshold = config.snr_threshold`). The `config` object is only in scope HERE — forward_body cannot reference it.",
  "forward_body": "the forward body. Each line indented with 8 spaces. Must end with a return statement of a SCALAR tensor with requires_grad=True."
}

Hard constraints — violating any of these makes the code invalid:
- The forward signature is FIXED: ``def forward(self, inputs: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:``.
  Use ``inputs`` and ``targets`` everywhere in forward_body — NEVER rename them.
- forward_body MUST end with a return of a SCALAR tensor (``.dim() == 0``) that
  carries gradient through ``inputs``.
- init_body MUST define every attribute referenced in forward_body. Do NOT access
  ``config`` inside forward_body.
- Do NOT include the 3 PLUGIN_LOSS_* constants — those are emitted by the template.
- Do NOT define helper classes — write the entire forward body inline.
- All config fields must be scalar (int, float, bool) — no List/Dict/Tuple.
- Use Pydantic V2 Field kwargs only: ge, le, gt, lt, multiple_of.
- Do NOT wrap any forward path in ``torch.no_grad()``; do NOT call ``.detach()`` on
  ``inputs`` or anything derived from it.

Output only the JSON object — no preamble, no markdown fences, no commentary."""


IMPLEMENTOR_LOSS_REPAIR_PROMPT = """\
Your previous loss-plugin code failed validation. Fix the issue and return a
corrected JSON object with the same 6 fields: extra_imports, config_fields_code,
config_validators_code, config_fields, init_body, forward_body.

All hard constraints from the previous prompt still apply. In particular:
  - The forward signature stays ``forward(self, inputs, targets) -> torch.Tensor``.
  - The return MUST be a scalar tensor with ``requires_grad=True``.
  - No torch.no_grad(), no .detach() on inputs.

Focus specifically on the error below — do not rewrite unrelated code.

Output only the JSON object — no preamble, no markdown fences, no commentary."""


def _loss_class_name(loss_name: str) -> str:
    """Snake_case loss name → CamelCase class name. Mirrors ``_class_name``
    for model plugins. ``"snr_weighted_mse"`` → ``"SnrWeightedMse"``."""
    return "".join(word.capitalize() for word in loss_name.split("_"))


def _assemble_loss_plugin(loss_name: str, description: str, code: dict) -> str:
    """Assemble the final loss plugin source from the LLM-generated JSON sections.

    Mirrors ``_assemble_plugin`` for model plugins: the template owns the 3
    required PLUGIN_LOSS_* constants and the class/config skeleton; the LLM
    only fills the variable slots. Indentation is normalised so the LLM can
    return any of: 0-space, 4-space, 8-space, or mixed indentation in
    ``init_body`` / ``forward_body`` and the assembled file always parses.

    Args:
        loss_name: ``PLUGIN_LOSS_TYPE`` key (snake_case).
        description: Short docstring for the loss class (shown by
            ``help(LossClass)`` and rendered into the registry entry's
            ``description`` field). Stripped of newlines so it stays on one
            line in the assembled source.
        code: JSON dict returned by the LLM's loss-code call. Expected keys:
            ``extra_imports``, ``config_fields_code``, ``config_validators_code``,
            ``init_body``, ``forward_body``. Missing keys substitute safe
            placeholders (``"pass"``) so the assembled file still parses
            for downstream validation messages.

    Returns:
        The complete assembled ``.py`` source as a string.
    """
    loss_cls = _loss_class_name(loss_name)

    extra_imports = code.get("extra_imports", "").strip()
    config_fields_code = code.get("config_fields_code", "").rstrip()
    config_validators_code = code.get("config_validators_code", "").rstrip()
    init_body = code.get("init_body", "        pass").rstrip()
    forward_body = code.get("forward_body", "        pass").rstrip()

    # Mirror _assemble_plugin: normalise indentation (dedent then re-indent)
    # so the LLM can emit any indentation level without breaking the assembly.
    init_body = textwrap.indent(textwrap.dedent(init_body), "        ")
    forward_body = textwrap.indent(textwrap.dedent(forward_body), "        ")

    # If config_fields_code is empty, insert a no-op pass so the config class
    # body is not empty (an empty class body would be a SyntaxError after the
    # docstring; pydantic BaseModel with no fields is otherwise legal).
    if not config_fields_code.strip():
        config_fields_code = "    pass"

    # Drop imports already present in the template header. Same allow-list
    # logic as _assemble_plugin — accept only well-formed import lines.
    _already_imported = {
        "import torch",
        "import torch.nn as nn",
        "import torch.nn.functional as F",
        "from pydantic import BaseModel, Field, model_validator",
        "from typing import Self",
    }
    extra_lines = [
        line
        for line in extra_imports.splitlines()
        if line.strip()
        and line.strip() not in _already_imported
        and (line.strip().startswith("import ") or line.strip().startswith("from "))
    ]
    extra_imports = "\n".join(extra_lines)
    if extra_imports:
        extra_imports = "\n" + extra_imports

    if config_validators_code.strip():
        config_validators_code = textwrap.indent(textwrap.dedent(config_validators_code), "    ")

    # One-line docstring: collapse newlines + strip so the assembled class
    # docstring fits on a single rendered line.
    description_oneline = " ".join(description.split()).replace('"', "'")

    return LOSS_PLUGIN_TEMPLATE.format(
        loss_name=loss_name,
        LossClass=loss_cls,
        description=description_oneline,
        extra_imports=extra_imports,
        config_fields_code=config_fields_code,
        config_validators_code=config_validators_code,
        init_body=init_body,
        forward_body=forward_body,
    )


def _dummy_tensor_validate_loss(plugin_src: str, loss_name: str) -> str | None:
    """Run the L2-equivalent dummy-tensor check on an assembled loss-plugin source.

    Procedure:
      1. Write the source to a tmp file (so ``importlib`` can load it).
      2. Import the module and look up the 3 required PLUGIN_LOSS_* attrs.
      3. Construct ``PLUGIN_LOSS_CONFIG_CLASS()`` with its declared defaults.
      4. Instantiate ``PLUGIN_LOSS_CLASS(cfg)`` and run forward with:
         - ``inputs``  = ``torch.randn(2, 256, 100, requires_grad=True)``
         - ``targets`` = ``torch.randint(0, 256, (2, 100), dtype=torch.int64)``
      5. Assert ``loss.dim() == 0`` and ``math.isfinite(loss.item())``.
      6. **Run ``loss.backward()``** and assert ``inputs.grad is not None``
         and ``torch.isfinite(inputs.grad).all()``. ``requires_grad=True`` on
         the loss output does NOT guarantee gradient actually flows back to
         ``inputs`` — a ``.detach()`` on inputs or mid-computation can leave
         ``requires_grad=True`` on the final tensor while severing the graph.
         The backward() check is the only reliable detector for this class
         of bug, and it also surfaces NaN/Inf gradient instabilities the
         scalar finite check cannot.

    Args:
        plugin_src: The assembled loss-plugin source code.
        loss_name: The ``PLUGIN_LOSS_TYPE`` key, used only for error messages.

    Returns:
        ``None`` if all checks pass; otherwise a human-readable error string
        describing the first failure. The string is suitable for feeding back
        into ``IMPLEMENTOR_LOSS_REPAIR_PROMPT`` as the ``error`` field.
    """
    # Lazy import keeps torch off the import-time path for callers that
    # only use the model-code helpers above. Mirrors `_smoke_test_plugin`.
    import contextlib
    import importlib.util
    import math

    import torch

    # Stage in a tmp dir + file (matches `_smoke_test_plugin` convention so
    # both helpers share the same cleanup pattern).
    tmp_dir = tempfile.mkdtemp(prefix=f"siderius_loss_dummy_{loss_name}_")
    tmp_path = os.path.join(tmp_dir, f"{loss_name}.py")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(plugin_src)

        spec = importlib.util.spec_from_file_location(f"siderius_loss_dummy_{loss_name}", tmp_path)
        if spec is None or spec.loader is None:
            return f"Could not resolve module spec for assembled loss plugin '{loss_name}'."
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            return f"Plugin source failed to import: {type(e).__name__}: {e}"

        for attr in ("PLUGIN_LOSS_TYPE", "PLUGIN_LOSS_CONFIG_CLASS", "PLUGIN_LOSS_CLASS"):
            if not hasattr(module, attr):
                return f"Assembled plugin is missing required attribute '{attr}'."

        config_cls = module.PLUGIN_LOSS_CONFIG_CLASS
        loss_cls = module.PLUGIN_LOSS_CLASS
        try:
            cfg = config_cls()
        except Exception as e:
            return (
                f"PLUGIN_LOSS_CONFIG_CLASS() failed to instantiate with defaults: "
                f"{type(e).__name__}: {e}. Every config field must have a default."
            )
        try:
            loss_fn = loss_cls(cfg)
        except Exception as e:
            return f"PLUGIN_LOSS_CLASS(config) failed to construct: {type(e).__name__}: {e}."

        # Dummy tensors mirror L2's test_custom_plugin_forward_pass_runs.
        torch.manual_seed(0)
        inputs = torch.randn(2, 256, 100, requires_grad=True)
        targets = torch.randint(0, 256, (2, 100), dtype=torch.int64)
        try:
            loss = loss_fn(inputs, targets)
        except Exception as e:
            return (
                f"forward(inputs, targets) raised on dummy tensors: "
                f"{type(e).__name__}: {e}. The forward must accept "
                f"inputs=[2, 256, 100] float32 and targets=[2, 100] int64."
            )

        if not isinstance(loss, torch.Tensor):
            return (
                f"forward returned {type(loss).__name__}, not a torch.Tensor. "
                f"It must return a scalar tensor."
            )
        if loss.dim() != 0:
            return (
                f"forward returned a tensor of shape {tuple(loss.shape)}; "
                f"expected a SCALAR (dim()==0). Reduce per-element loss to a "
                f"scalar before returning (e.g. .mean() or .sum())."
            )
        try:
            value = loss.item()
        except Exception as e:
            return f"loss.item() raised: {type(e).__name__}: {e}."
        if not math.isfinite(value):
            return f"forward returned a non-finite scalar (got {value!r})."

        # Run backward pass to confirm gradient actually flows back to inputs.
        # requires_grad=True on the loss output does not guarantee this —
        # a .detach() on inputs or mid-computation can leave requires_grad=True
        # on the final tensor while severing the gradient graph. See
        # IMPLEMENTOR_LOSS_REASONING_PROMPT § Gradient-flow requirement for
        # the safe-vs-unsafe pattern distinction the LLM is shown.
        try:
            loss.backward()
        except Exception as e:
            return (
                f"loss.backward() raised: {type(e).__name__}: {e}. "
                "The loss graph is malformed — check for in-place ops on "
                "leaf tensors or operations that produce non-differentiable "
                "outputs on the main path from inputs."
            )
        if inputs.grad is None:
            return (
                f"Loss '{loss_name}': backward() ran but inputs.grad is None — "
                "gradient does not flow back to inputs. Check for .detach() on "
                "inputs (or on any tensor derived from inputs on the main path "
                "to loss), or for a torch.no_grad() block wrapping the main "
                "computational path. .detach() on weighting/masking terms is "
                "OK; .detach() on inputs is not."
            )
        if not torch.isfinite(inputs.grad).all():
            return (
                f"Loss '{loss_name}': inputs.grad contains NaN or Inf after "
                "backward(). Loss may be numerically unstable — check for "
                "log(0), division by small quantities, or unbounded "
                "exponentials in the forward pass."
            )

        return None
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)
            os.rmdir(tmp_dir)


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def _render_task_background(task_description: str, fc: ForwardContract) -> str:
    """Render the ``{TASK_BACKGROUND}`` placeholder block for the reasoning
    system prompt.

    Returns the multi-line block ``Background on the task:`` header + a
    bullet for the task description + the rendered forward contract, with
    a trailing newline so the template's next line (``- GPU budget: ...``)
    follows naturally. Returns ``""`` when both ``task_description`` and
    ``fc`` are empty — only reachable from test fixtures that don't go
    through ``load_task_config`` (production callers always populate both).
    """
    if not task_description and fc.is_empty():
        return ""
    parts = ["Background on the task:"]
    if task_description:
        parts.append(f"- {task_description}")
    fc_block = render_forward_contract(fc)
    if fc_block:
        parts.append(fc_block)
    # Trailing empty string → final "\n" so the next template line (the
    # GPU-budget bullet) starts on a fresh line.
    parts.append("")
    return "\n".join(parts)


def _build_reasoning_system_prompt(inp: ImplementorInput) -> str:
    """Substitute the ``{TASK_BACKGROUND}`` placeholder in
    ``IMPLEMENTOR_REASONING_PROMPT`` from ``inp``.

    Production callers always have ``inp.task_description`` non-empty and
    ``inp.forward_contract`` fully populated (workflow injects from
    ``load_task_config()``); test fixtures may leave both at defaults, in
    which case the placeholder collapses to ``""``.
    """
    return IMPLEMENTOR_REASONING_PROMPT.replace(
        "{TASK_BACKGROUND}",
        _render_task_background(inp.task_description, inp.forward_contract),
    )


def _build_code_system_prompt(inp: ImplementorInput) -> str:
    """Substitute the ``{OUTPUT_SHAPE}`` placeholder in
    ``IMPLEMENTOR_CODE_PROMPT`` from ``inp.forward_contract.output_shape``.

    Falls back to a generic ``[B, C, T] float32`` only when the contract is
    empty (test fixtures); production callers always provide a concrete
    output shape via ``load_task_config()``.
    """
    output_shape = inp.forward_contract.output_shape or "[B, C, T] float32"
    return IMPLEMENTOR_CODE_PROMPT.replace("{OUTPUT_SHAPE}", output_shape)


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
    ]

    # --- Forward contract (rendered from inp.forward_contract; suppressed
    # when the contract is empty — only happens in test fixtures that don't
    # populate it). ---
    fc_block = render_forward_contract(inp.forward_contract)
    if fc_block:
        lines += ["", "## Forward contract (non-negotiable)", fc_block]

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
            "## Reference Code (from ancestor models — for ARCHITECTURAL INSPIRATION ONLY)",
            "",
            "⚠ WARNING — read before using the snippets below:",
            "",
            "1. Private helper classes (e.g. `CausalConv1d`, `WaveNetBlock`,",
            "   `DoubleConv`, `PositionalEncoding`, `Down`, `Up`, etc.) shown below",
            "   are NOT available in your plugin's runtime — they live in",
            "   `ml_models/models_sandbox.py` which the plugin loader does not import.",
            "   You MUST inline their logic using only the allowed primitives",
            "   (torch, torch.nn, torch.nn.functional). Do NOT reference these helper",
            "   class names in your `init_body` or `forward_body` — that produces",
            "   `NameError` at smoke-test time.",
            "",
            "2. The `self.config = config` + `self.config.X` access pattern that some",
            "   reference samples use is FORBIDDEN in your plugin. The `config` object",
            "   is only in scope during `__init__`. Store every value you need as a",
            "   plain attribute on `self` (e.g. `self.channels = config.channels`)",
            "   inside `init_body`, then reference `self.channels` in `forward_body`.",
            "",
            "3. Use the references for architectural ideas (block structure, dilation",
            "   schedules, skip-connection topology) — not as code to copy verbatim.",
            "",
        ]
        for model_type, source in inp.reference_code.items():
            lines += [
                f"### {model_type} (reference implementation — inspiration only)",
                "```python",
                source,
                "```",
                "",
            ]

    # --- Previous validation failure (retry context) ---
    if inp.previous_validation_failure:
        lines += [
            "",
            "## ⚠ Previous Implementation Failed Validation — Fix This",
            "",
            "Your previous implementation of this same proposal was rejected by the",
            "validator with the following error. Address it explicitly in your reasoning",
            "before committing to code:",
            "",
            inp.previous_validation_failure,
            "",
            "Do NOT reproduce the same mistake. Your reasoning must explain how you will",
            "fix each issue raised above.",
        ]

    return "\n".join(lines)


def _build_code_prompt(reasoning: str, inp: ImplementorInput) -> str:
    model_cfg = inp.baseline_config.get("model_config", {})
    advice_block = ""
    if inp.human_advice:
        advice_block = f"\n## Implement Advice (high priority)\n{inp.human_advice}\n"
    return (
        f"## Your Reasoning\n\n{reasoning}\n\n"
        f"---\n\n"
        f"## Model name: `{inp.model_name}`\n"
        f"## Class name: `{_class_name(inp.model_name)}`\n"
        f"## Baseline model_config (use these as Field defaults): {json.dumps(model_cfg)}\n"
        f"{advice_block}\n"
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
# L4b — Loss user-prompt builders
# ---------------------------------------------------------------------------


def _build_loss_reasoning_prompt(spec: CustomLossSpec) -> str:
    """Render the user-prompt for the loss-reasoning LLM call.

    Provides the LLM with the spec's loss_name, description, mathematical
    definition, and any pre-specified config_fields hints. Mirrors
    ``_build_reasoning_prompt`` in shape (sectioned markdown), but the
    content is loss-specific (no model_config / train_config sections).
    """
    lines = [
        f"## Loss to implement: `{spec.loss_name}`",
        "",
        "## Description",
        spec.description,
        "",
        "## Mathematical definition",
        spec.mathematical_definition,
    ]
    if spec.config_fields:
        lines += [
            "",
            "## Pre-specified config fields (from proposer)",
            json.dumps(spec.config_fields, indent=2),
            "",
            "These are hints — keep, drop, or adjust ranges as needed. The plugin's "
            "config class is independent of LossConfig and carries only this loss's "
            "own hyperparameters.",
        ]
    return "\n".join(lines)


def _build_loss_code_prompt(reasoning: str, spec: CustomLossSpec) -> str:
    """Render the user-prompt for the loss-code LLM call. Includes the
    reasoning output verbatim, then restates the loss name and class name
    so the strict-JSON response is anchored."""
    return (
        f"## Your Reasoning\n\n{reasoning}\n\n"
        f"---\n\n"
        f"## Loss name: `{spec.loss_name}`\n"
        f"## Class name: `{_loss_class_name(spec.loss_name)}`\n\n"
        "Now output the JSON code sections."
    )


def _build_loss_repair_prompt(
    code: dict,
    error: str,
    spec: CustomLossSpec,
    error_history: list[tuple[int, str]] | None = None,
) -> str:
    """Render the user-prompt for the loss-code repair call. Mirrors
    ``_build_repair_prompt`` shape (history block + previous JSON + current
    error + name anchor)."""
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
        f"## Loss name: `{spec.loss_name}`\n"
        f"## Class name: `{_loss_class_name(spec.loss_name)}`\n\n"
        "Fix the current error without reintroducing any error from the history. "
        "Output the corrected JSON code sections."
    )


# ---------------------------------------------------------------------------
# File assembly
# ---------------------------------------------------------------------------


def _assemble_plugin(inp: ImplementorInput, code: dict) -> str:
    model_cfg = inp.baseline_config.get("model_config", {})
    train_cfg = inp.baseline_config.get("train_config", {})
    seg_size = model_cfg.get("segmentation_size", train_cfg.get("segmentation_size", 40000))
    batch_size = model_cfg.get("batch_size", train_cfg.get("batch_size", 1))
    model_cls = _class_name(inp.model_name)

    extra_imports = code.get("extra_imports", "").strip()
    config_fields_code = code.get("config_fields_code", "").rstrip()
    config_validators_code = code.get("config_validators_code", "").rstrip()
    init_body = code.get("init_body", "        pass").rstrip()
    forward_body = code.get("forward_body", "        pass").rstrip()

    # Ensure correct indentation: init_body and forward_body must be indented 8 spaces
    init_body = textwrap.indent(textwrap.dedent(init_body), "        ")
    forward_body = textwrap.indent(textwrap.dedent(forward_body), "        ")

    # Remove imports already present in the fixed template header to avoid duplicates.
    # Also drop any line that is not a valid import statement (must start with 'import'
    # or 'from') — LLMs occasionally emit partial fragments like "torch.nn.functional as F"
    # which would cause a SyntaxError.
    _already_imported = {
        "import torch",
        "import torch.nn as nn",
        "import torch.nn.functional as F",
        "from pydantic import BaseModel, Field",
    }
    extra_lines = [
        line
        for line in extra_imports.splitlines()
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
        config_validators_code = textwrap.indent(textwrap.dedent(config_validators_code), "    ")

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
    def __init__(
        self,
        provider: str = "gemini",
        model_id: str = "gemini-3.1-pro-preview",
        max_retries: int | None = None,
        bridge_factory=None,
        capability_index_path: str | None = None,
        **kwargs,
    ):
        self._bridge_factory = bridge_factory or LLMBridge
        self.bridge = self._bridge_factory(
            provider=provider, model_id=model_id, max_retries=max_retries
        )
        # L4b — registry handle for custom-loss provenance writes. Tests pass
        # ``capability_index_path=str(tmp_path / "_capability_index.json")``
        # to avoid contaminating the canonical index; production callers
        # leave it None to use ``agent_generated/_capability_index.json``.
        self._registry = CapabilityRegistry(index_path=capability_index_path)

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
            k: type(v).__name__
            for k, v in config_fields.items()
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

        # Check 3: smoke test (instantiate + forward pass with defaults)
        smoke_error = _smoke_test_plugin(plugin_src, inp.model_name)
        if smoke_error:
            return f"Smoke test failed: {smoke_error}"

        # Check 4 (Phase B.2a): baseline self-check. The smoke test uses
        # schema defaults only; here we instantiate PLUGIN_CONFIG_CLASS with
        # the proposer's actual baseline_config.model_config to catch
        # implementor-invented constraints (e.g. multiple_of=2) that reject
        # the proposer's values. On failure, the existing retry loop picks
        # up the error and feeds it to the LLM via _build_repair_prompt.
        # See docs/improving_validation_awareness.md Phase B.2.
        baseline_error = _check_baseline_schema_compatibility(
            plugin_src,
            inp.model_name,
            inp.baseline_config,
        )
        if baseline_error:
            return baseline_error

        return None  # all good

    # ------------------------------------------------------------------
    # L4b — Custom-loss generation (registry-hit short-circuit + LLM path)
    # ------------------------------------------------------------------

    def _generate_loss(self, inp: ImplementorInput) -> LossProvenance:
        """Generate (or reuse) a custom loss plugin and return the provenance.

        Preconditions:
          - ``inp.custom_loss_spec`` is not None — the caller (``run``) is
            responsible for this guard.

        Flow:
          1. **Registry hit short-circuit** — if ``CapabilityRegistry``
             already has an entry for ``(spec.loss_name, "loss")``, log a
             reuse message, return a ``LossProvenance(action="reused", …)``
             pointing at the registered file. No LLM call is made.
          2. **Reasoning + code LLM calls** — two ``bridge`` calls
             (``implementor.loss.reasoning`` then ``implementor.loss.code``)
             producing the strict-JSON sections consumed by
             ``_assemble_loss_plugin``.
          3. **Dummy-tensor validate → repair loop** — up to
             ``inp.max_retries`` repair attempts, each feeding the validator
             error back into ``IMPLEMENTOR_LOSS_REPAIR_PROMPT``.
          4. **Write** the assembled source to
             ``{inp.loss_dir}/{spec.loss_name}.py``.
          5. **Register** in the capability index with
             ``capability_type="loss"`` and ``source_iteration`` from
             ``inp.storage.local.run_name``.
          6. Return ``LossProvenance(action="generated", …)``.

        Raises:
            ValueError: When all retries fail. The error message includes
                the final assembled source and the full error history so
                the caller (workflow + operator) can diagnose.
        """
        spec = inp.custom_loss_spec
        # Caller guarantees this is not None; assert is a pyright hint.
        assert spec is not None
        loss_name = spec.loss_name

        # Source iteration label for registry + provenance. ``storage.local``
        # may be absent for non-local backends; degrade gracefully.
        source_iteration: str | None = None
        if inp.storage.backend == "local" and inp.storage.local:
            source_iteration = inp.storage.local.run_name

        # ---- 1. Registry-hit short-circuit ------------------------------
        existing = next(
            (m for m in self._registry.list(capability_type="loss") if m.name == loss_name),
            None,
        )
        if existing is not None:
            print(
                f"🔁 Reusing existing loss plugin: '{loss_name}' (from {existing.source_iteration})"
            )
            print(f"   Loss file → {existing.file_path}")
            return LossProvenance(
                loss_name=loss_name,
                action="reused",
                source_iteration=existing.source_iteration,
                loss_file_path=existing.file_path,
                # Registry entries are only written after dummy-tensor passed
                # at original generation time. Reuse therefore inherits that
                # validation result.
                dummy_tensor_validated=True,
            )

        # ---- 2. LLM calls (reasoning + code) ----------------------------
        print(f"🧪 Generating custom loss '{loss_name}' ...")
        reasoning = self.bridge.generate_text(
            IMPLEMENTOR_LOSS_REASONING_PROMPT,
            _build_loss_reasoning_prompt(spec),
            label="implementor.loss.reasoning",
        )
        print(f"   Loss reasoning complete ({len(reasoning)} chars).")

        code = self.bridge.generate(
            IMPLEMENTOR_LOSS_CODE_PROMPT,
            _build_loss_code_prompt(reasoning, spec),
            label="implementor.loss.code",
        )

        # ---- 3. Validate → repair loop ----------------------------------
        max_retries = inp.max_retries
        plugin_src = _assemble_loss_plugin(loss_name, spec.description, code)
        error = _dummy_tensor_validate_loss(plugin_src, loss_name)
        attempt = 0
        error_history: list[tuple[int, str]] = []
        while error is not None and attempt < max_retries:
            attempt += 1
            print(f"   ⚠ Loss attempt {attempt + 1}/{max_retries + 1}: {error}")
            repair_prompt = _build_loss_repair_prompt(code, error, spec, error_history)
            error_history.append((attempt, error))
            code = self.bridge.generate(
                IMPLEMENTOR_LOSS_REPAIR_PROMPT,
                repair_prompt,
                label="implementor.loss.repair",
            )
            plugin_src = _assemble_loss_plugin(loss_name, spec.description, code)
            error = _dummy_tensor_validate_loss(plugin_src, loss_name)

        if error is not None:
            raise ValueError(
                f"Loss generation failed after {max_retries + 1} attempts for "
                f"'{loss_name}': {error}\n\n"
                f"The assembled loss source:\n{plugin_src}"
            )
        if attempt > 0:
            print(f"   ✅ Loss self-correction succeeded on attempt {attempt + 1}.")

        # ---- 4. Write the loss plugin -----------------------------------
        os.makedirs(inp.loss_dir, exist_ok=True)
        loss_file_path = os.path.abspath(os.path.join(inp.loss_dir, f"{loss_name}.py"))
        with open(loss_file_path, "w", encoding="utf-8") as f:
            f.write(plugin_src)
        print(f"✅ Loss written  → {loss_file_path}")

        # ---- 5. Register in the capability index ------------------------
        registry_description = " ".join(spec.description.split())
        self._registry.register(
            CapabilityMetadata(
                name=loss_name,
                capability_type="loss",
                file_path=loss_file_path,
                created_at=datetime.now(UTC).isoformat(),
                source_iteration=source_iteration,
                description=registry_description,
                # L6c — persist the formula so the proposer's
                # {available_losses_block} can render it for
                # semantic-similarity judgment (Branch B vs Branch C).
                mathematical_definition=spec.mathematical_definition,
            )
        )
        print(f"✅ Registered    → loss '{loss_name}' (source={source_iteration})")

        # ---- 6. Return provenance ---------------------------------------
        return LossProvenance(
            loss_name=loss_name,
            action="generated",
            source_iteration=source_iteration,
            loss_file_path=loss_file_path,
            dummy_tensor_validated=True,
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, inp: ImplementorInput) -> ImplementorOutput:
        # L4b — generate the custom loss BEFORE the model. Sequential order
        # so a loss-generation failure short-circuits before any model LLM
        # spend. ``loss_provenance`` is None when the proposer used a
        # built-in loss type (``inp.custom_loss_spec is None``).
        loss_provenance: LossProvenance | None = None
        if inp.custom_loss_spec is not None:
            # Branch C: proposer emitted a CustomLossSpec → generate the loss.
            loss_provenance = self._generate_loss(inp)
        else:
            # Either Branch A (built-in loss) or Branch B (reuse from registry).
            # Discriminate by inspecting baseline_config.loss_config.loss_type.
            # Bug found by Gate 3 (2026-06-22): proposer can emit
            # loss_type="custom" with a loss_name that doesn't exist in the
            # registry — Branch B with a phantom loss. Without this guard the
            # implementor silently proceeded, the tuner planner LLM then
            # rewrote loss_type to "ce" downstream, and training ran under
            # the wrong loss. Raise loudly here so the workflow's existing
            # max_proposal_attempts retry loop re-prompts the proposer.
            loss_cfg = inp.baseline_config.get("loss_config") or {}
            if loss_cfg.get("loss_type") == "custom":
                loss_name = loss_cfg.get("loss_name") or ""
                existing_names = {m.name for m in self._registry.list(capability_type="loss")}
                if not loss_name:
                    raise ValueError(
                        "Implementor received an invalid Branch B proposal: "
                        "loss_type='custom' with no loss_name. The proposer must "
                        "either pick Branch A (built-in loss_type ∈ {focal, "
                        "focal_cw, ce, smooth_l1}) or Branch C (populate "
                        "custom_loss_spec with the full spec) or Branch B (reuse "
                        "an existing registered loss by name)."
                    )
                if loss_name not in existing_names:
                    raise ValueError(
                        f"Implementor received Branch B proposal "
                        f"(loss_type='custom', loss_name={loss_name!r}) but "
                        f"{loss_name!r} is not in the capability registry. "
                        f"Registry currently contains: "
                        f"{sorted(existing_names) if existing_names else 'no losses'}. "
                        f"The proposer must either use Branch A (built-in loss), "
                        f"Branch C (generate new loss via custom_loss_spec), or "
                        f"Branch B with a loss_name that actually exists in the "
                        f"registry. Advice-file loss-name suggestions are not "
                        f"registry entries — they only become registered after a "
                        f"prior iteration successfully generated them via Branch C."
                    )
                # Branch B happy path: record the reuse provenance.
                existing_meta = next(
                    (m for m in self._registry.list(capability_type="loss") if m.name == loss_name),
                    None,
                )
                loss_provenance = LossProvenance(
                    loss_name=loss_name,
                    action="reused",
                    source_iteration=(existing_meta.source_iteration if existing_meta else None),
                    loss_file_path=(existing_meta.file_path if existing_meta else ""),
                    dummy_tensor_validated=True,
                )

        print(f"🔧 Implementing model '{inp.model_name}' ...")

        # --- Call 1: reasoning (free text, runs once) ---
        # System prompt has its {TASK_BACKGROUND} placeholder substituted at
        # call time from inp.task_description + inp.forward_contract; see
        # docs/design/enable_global_task_config.md § Commit T2.
        reasoning_system_prompt = _build_reasoning_system_prompt(inp)
        reasoning_prompt = _build_reasoning_prompt(inp)
        reasoning = self.bridge.generate_text(
            reasoning_system_prompt,
            reasoning_prompt,
            label="implementor.reasoning",
        )
        print(f"   Reasoning complete ({len(reasoning)} chars).")

        # --- Call 2: code commit (strict JSON) ---
        # System prompt has its {OUTPUT_SHAPE} placeholder substituted from
        # inp.forward_contract.output_shape (T2).
        code_system_prompt = _build_code_system_prompt(inp)
        code_prompt = _build_code_prompt(reasoning, inp)
        code = self.bridge.generate(
            code_system_prompt,
            code_prompt,
            label="implementor.code",
        )
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
            code = self.bridge.generate(
                IMPLEMENTOR_REPAIR_PROMPT,
                repair_prompt,
                label="implementor.repair",
            )
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
        test_src = _assemble_test(inp.model_name)

        # --- Write plugin file ---
        os.makedirs(inp.plugin_dir, exist_ok=True)
        model_file_path = os.path.abspath(os.path.join(inp.plugin_dir, f"{inp.model_name}.py"))
        with open(model_file_path, "w", encoding="utf-8") as f:
            f.write(plugin_src)
        print(f"✅ Plugin written → {model_file_path}")

        # --- Write description.md so result_interpretation_agent can load it ---
        # Mirrors the structure expected by ml_models/model_descriptions.py:
        #   agent_generated/models/{model_name}/description.md
        desc_dir = os.path.join(inp.plugin_dir, inp.model_name)
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
        test_file_path = os.path.abspath(os.path.join(inp.test_dir, f"test_{inp.model_name}.py"))
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
            loss_provenance=loss_provenance,
        )

        # --- Persist output record ---
        if inp.storage.backend == "local" and inp.storage.local:
            workspace = inp.storage.local.workspace
            run_name = inp.storage.local.run_name
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
    parser.add_argument("--run_name", type=str, default="v1")
    parser.add_argument("--provider", type=str, default="gemini", choices=["gemini", "openai"])
    parser.add_argument("--model_id", type=str, default="gemini-3.1-pro-preview")
    args = parser.parse_args()

    proposal_path = os.path.join(args.workspace, f"proposal_{args.run_name}.json")
    if not os.path.exists(proposal_path):
        raise FileNotFoundError(
            f"Proposal file not found: {proposal_path}\nRun ml_model_proposal_agent first."
        )
    with open(proposal_path, encoding="utf-8") as f:
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

    print(f"\n{'=' * 60}")
    print(f"  Implementor — {output.model_type}")
    print(f"{'=' * 60}")
    print(f"  Plugin  : {output.model_file_path}")
    print(f"  Tests   : {output.test_file_path}")
    print(f"  Config  : {output.config_fields}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
