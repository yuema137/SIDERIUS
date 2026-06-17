# Design: Enable Loss Inventory (`enable_loss_inventory`)

**Status**: Draft  
**Author**: Yue Ma  
**Created**: 2026-06-13  
**Branch**: (new branch, to be created)

---

## Scope

This design doc covers **loss inventory only**. The CLI (`siderius capabilities list`) is intentionally **out of scope** for this iteration — but the `CapabilityRegistry` and `_capability_index.json` are designed to be CLI-ready: the registry reads directly from a flat JSON file with no Python import required, so a future CLI command can be bolted on without touching any of the infrastructure built here.

All other agent-generated capability types (data analysis tools, feature extractors, etc.) are also out of scope. The `CapabilityRegistry` architecture is designed to accommodate them, but their plugin interfaces and loaders are not defined here.

---

## Development principles

This doc and the implementation follow four working rules. Respect them at every step.

1. **Check, don't guess.** When uncertain about how existing code behaves, grep / read the source. If the answer isn't in the code, **ask the user**. Never extrapolate from memory or a summary.
2. **Keep the design doc and code in lock-step.** Update this file as work lands — tick each `[ ] → [x]` as soon as a sub-bullet is verified, record test results inline next to the relevant checklist item, and add an "Implementation notes" line under the commit when a non-obvious decision is made. Don't wait for the full commit to be done before updating.
3. **Stop before each commit.** Surface the progress and the main implementation details, then wait for explicit approval before running `git commit`. Tests run freely without permission **except** the real-LLM + real-training combo — that needs a time estimate and approval first. Real-LLM + pseudo-training, pseudo-LLM + real-training, and pure unit tests run freely.
4. **Split logical commits at clean seams.** Every "Commit L\*" entry below is the *logical* unit. When the actual git commit would be too large, split it into multiple smaller commits at natural boundaries (e.g. `-schemas`, `-impl`, `-tests`, `-docs`). The L\* heading stays as the logical anchor; the split appears in git history.

---

## Motivation

Checkpoint S (2026-06-13) found that 93% of lit-review findings recommend
loss function changes (SNR-weighted MSE, STFT magnitude loss, per-segment
influence weighting, etc.), but the current `LossConfig` is hardcoded to
four literal loss types (`focal`, `focal_cw`, `ce`, `smooth_l1`) with no
extension mechanism. The implementor writes only `__init__` + `forward` for
model plugins and has no surface for emitting custom loss functions.

This design doc describes how to extend SIDERIUS so that:

1. The proposer can recommend novel loss functions grounded in lit-review findings
2. The implementor can generate loss function code and register it
3. All subsequent iterations can discover and reuse registered losses
4. The validator automatically stress-tests the loss via the existing training loop
5. A unified `CapabilityRegistry` provides the foundation for future
   agent-generated capabilities (data analysis tools, feature extractors, etc.)

This unblocks Checkpoint D.

---

## Architecture overview

```
agent_generated/
  models/          ← existing (model plugins)
  losses/          ← NEW (loss plugins)
  _registry.py     ← NEW (unified capability discovery)
ml_models/
  loss_models_sandbox.py   ← get_criterion() extended to support "custom"
  models_format_sandbox.py ← LossConfig extended with loss_name field
agent/schemas/
  proposal.py      ← ProposalOutput gets optional custom_loss_spec field
  implementor.py   ← ImplementorOutput gets optional loss_provenance field
                     ImplementorInput gets custom_loss_spec + loss_dir fields
nodes/ml_model_implementor/
  ml_model_implementor.py  ← generates loss code when custom_loss_spec present
# CLI (future) — siderius capabilities list [--type model|loss|all]
#   Out of scope for this doc. CapabilityRegistry._capability_index.json
#   is the data source; no Python import required for a future CLI reader.
```

---

## Loss plugin interface

Every loss plugin file in `agent_generated/losses/` must define exactly
three module-level symbols (mirroring the model plugin interface):

```python
PLUGIN_LOSS_TYPE: str          # unique key, e.g. "snr_weighted_mse"
PLUGIN_LOSS_CONFIG_CLASS: type # Pydantic BaseModel subclass
PLUGIN_LOSS_CLASS: type        # nn.Module subclass

# Forward contract:
#   inputs:  torch.Tensor [B, 256, T] float32  (model logits)
#   targets: torch.Tensor [B, T]     int64     (ground truth class indices)
#   returns: torch.Tensor scalar               (must have requires_grad=True)
```

Example stub:

```python
# agent_generated/losses/snr_weighted_mse.py

import torch
import torch.nn as nn
from pydantic import BaseModel, Field

PLUGIN_LOSS_TYPE = "snr_weighted_mse"

class SNRWeightedMSEConfig(BaseModel):
    # Plugin-specific hyperparameters only.
    # Do NOT add loss_type here — that belongs to LossConfig (the router).
    snr_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    high_snr_weight: float = Field(default=2.0, ge=1.0, le=10.0)

PLUGIN_LOSS_CONFIG_CLASS = SNRWeightedMSEConfig

class SNRWeightedMSE(nn.Module):
    def __init__(self, config: SNRWeightedMSEConfig):
        super().__init__()
        self.snr_threshold = config.snr_threshold
        self.high_snr_weight = config.high_snr_weight

    def forward(self, inputs: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        # inputs: [B, 256, T], targets: [B, T]
        ...

PLUGIN_LOSS_CLASS = SNRWeightedMSE
```

Files starting with `_` are skipped by the loader (same convention as models).

---

## `CapabilityRegistry` — unified discovery layer

`agent_generated/_registry.py` provides a single discovery interface for
all agent-generated capability types. The calling layer (loss, model, future
tools) remains type-specific; the registry unifies metadata, versioning, and
CLI surface.

```python
# agent_generated/_registry.py

class CapabilityMetadata(BaseModel):
    name: str                    # e.g. "snr_weighted_mse"
    capability_type: str         # "loss" | "model" | "tool" (future)
    file_path: str               # absolute path to the .py file
    created_at: str              # ISO datetime
    source_iteration: str | None # e.g. "iter_014" — which iteration generated it
    description: str             # one-line summary

class CapabilityRegistry:
    """Unified discovery for agent_generated/ capability types."""

    def list(self, capability_type: str | None = None) -> list[CapabilityMetadata]:
        """Return all registered capabilities, optionally filtered by type."""
        ...

    def exists(self, name: str, capability_type: str) -> bool:
        """Check if a capability with this name already exists."""
        ...

    def register(self, metadata: CapabilityMetadata) -> None:
        """Write metadata to agent_generated/_capability_index.json."""
        ...
```

Metadata is persisted to `agent_generated/_capability_index.json` — a flat
JSON array of `CapabilityMetadata` objects. This file is the source of truth
for CLI queries and for the proposer's "what losses already exist?" check.

---

## `LossConfig` extension

```python
# ml_models/models_format_sandbox.py

class LossConfig(BaseModel):
    loss_type: Literal[
        "focal", "focal_cw", "ce", "smooth_l1",
        "custom"          # NEW — routes to plugin loss
    ] = "focal"

    # Existing fields unchanged
    alpha: float | None = ...
    gamma: float | None = ...
    beta: float | None = ...
    reduction: Literal["mean", "sum"] = "mean"
    use_class_weights: bool = False

    # NEW — required when loss_type == "custom"
    loss_name: str | None = Field(
        default=None,
        description="PLUGIN_LOSS_TYPE key of the agent-generated loss to use. "
                    "Required when loss_type='custom'. The loss plugin must exist "
                    "in agent_generated/losses/ before training begins."
    )

    @model_validator(mode="after")
    def enforce_custom_loss_name(self) -> "LossConfig":
        if self.loss_type == "custom" and not self.loss_name:
            raise ValueError("loss_name is required when loss_type='custom'")
        if self.loss_type != "custom" and self.loss_name:
            raise ValueError("loss_name must be None when loss_type != 'custom'")
        return self
```

---

## `get_criterion()` extension

```python
# ml_models/loss_models_sandbox.py

def get_criterion(config: LossConfig, class_weights=None):
    if config.loss_type == "custom":
        return _load_custom_loss(config.loss_name)
    # ... existing 4 cases unchanged ...

def _load_custom_loss(loss_name: str) -> nn.Module:
    """Load a plugin loss from agent_generated/losses/{loss_name}.py.

    LossConfig is the routing layer only — it carries `loss_type="custom"`
    and `loss_name`. The plugin's own PLUGIN_LOSS_CONFIG_CLASS is a
    completely separate Pydantic model with the plugin's own hyperparameters
    (e.g. snr_threshold, stft_window_size). The two configs are independent;
    LossConfig.alpha/gamma/beta are irrelevant for custom losses and are
    nullified by `enforce_parameter_consistency`.
    """
    from agent_generated._loss_loader import load_loss_plugin
    plugin = load_loss_plugin(loss_name)
    if plugin is None:
        raise ValueError(
            f"Custom loss '{loss_name}' not found in agent_generated/losses/. "
            f"Run the implementor first to generate the loss plugin, or check "
            f"that SIDERIUS_LOSS_DIRS points to the correct directory."
        )
    # Construct the plugin's own config with its own defaults.
    # Do NOT pass loss_type="custom" or loss_name here — those belong to
    # LossConfig (the router), not to the plugin's config class.
    loss_cfg = plugin["config_class"]()
    return plugin["loss_class"](loss_cfg)
```

### Two-config design

There are two completely separate config objects:

| Config | Owner | Purpose | Example fields |
|---|---|---|---|
| `LossConfig` | SIDERIUS | Routing + built-in hyperparams | `loss_type`, `loss_name`, `alpha`, `gamma` |
| `PLUGIN_LOSS_CONFIG_CLASS` | Plugin | Plugin-specific hyperparams | `snr_threshold`, `high_snr_weight` |

`LossConfig.alpha/gamma/beta` are nullified for `loss_type="custom"` in `enforce_parameter_consistency` — this is safe and correct because the plugin's config class is a separate object that never receives those fields.

The plugin stub in `_stub_loss_template.py` must NOT define `loss_type` as a field — that belongs to `LossConfig` only. The stub's config class defines only the plugin's own hyperparameters.

A new `agent_generated/_loss_loader.py` mirrors `ml_models/plugin_loader.py`
for losses — same `importlib` pattern, same `_` prefix skip convention.

---

## Schema changes

### `ProposalOutput` — add `custom_loss_spec`

```python
class CustomLossSpec(BaseModel):
    loss_name: str = Field(
        description="Snake_case unique key for this loss. "
                    "Must not clash with existing losses in agent_generated/losses/."
    )
    description: str = Field(
        description="Plain-English description of what this loss computes and why."
    )
    mathematical_definition: str = Field(
        description="Precise mathematical definition of the loss function. "
                    "Must be concrete enough for the implementor to generate code directly."
    )
    config_fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Hyperparameter fields for the loss config class. "
                    "Keys are field names, values are (type, default, description) tuples."
    )

class ProposalOutput(BaseModel):
    # ... all existing fields unchanged ...

    custom_loss_spec: CustomLossSpec | None = Field(
        default=None,
        description="Specification for a novel loss function to be generated by "
                    "the implementor. When set, baseline_config['loss_config'] "
                    "must have loss_type='custom' and loss_name matching this spec. "
                    "When None, the proposer uses one of the 4 built-in loss types."
    )
```

### `ImplementorOutput` — add `loss_provenance`

```python
class LossProvenance(BaseModel):
    """Full audit trail for a single loss plugin use.

    Present whenever `baseline_config.loss_config.loss_type == "custom"`.
    None when using a built-in loss type (focal, focal_cw, ce, smooth_l1).
    """
    loss_name: str = Field(
        description="PLUGIN_LOSS_TYPE key, e.g. 'snr_weighted_mse'."
    )
    action: Literal["reused", "generated"] = Field(
        description="'generated' = implementor wrote the plugin file this iteration. "
                    "'reused' = plugin already existed in the registry; no LLM call made."
    )
    source_iteration: str | None = Field(
        description="Which iteration originally generated this loss plugin. "
                    "For action='generated': current iteration's run_name. "
                    "For action='reused': the run_name from the registry entry "
                    "(i.e. the iteration that created it, not the current one)."
    )
    loss_file_path: str = Field(
        description="Absolute path to the loss plugin .py file."
    )
    dummy_tensor_validated: bool = Field(
        description="True if the implementor's dummy-tensor forward pass succeeded. "
                    "Always True for action='reused' (the plugin was already validated "
                    "when it was first generated). Always True for action='generated' "
                    "(the implementor only writes to disk after validation passes)."
    )

class ImplementorOutput(BaseModel):
    # ... all existing fields unchanged ...

    loss_provenance: LossProvenance | None = Field(
        default=None,
        description="Audit trail for custom loss usage. None when the proposer "
                    "used a built-in loss type. Present for loss_type='custom' — "
                    "records whether the loss was reused from a prior iteration or "
                    "newly generated this iteration, and from which iteration it originates."
    )
```

The `loss_file_path` field previously proposed as a standalone field on `ImplementorOutput` is now consolidated into `LossProvenance`.

---

## Implementor changes

When `inp.custom_loss_spec` is not None, the implementor:

1. **Checks registry first** — if `loss_name` already exists in
   `agent_generated/losses/`, skip generation and reuse the existing file.
   Log: `[LossLoader] Reusing existing loss plugin: '{loss_name}'`

2. **Generates loss code** via a dedicated LLM call (separate from the model
   code generation call, using the same `bridge`):
   - System prompt: loss plugin interface contract + forward contract
   - User prompt: `custom_loss_spec.mathematical_definition` + config fields

3. **Validates immediately** — runs a dummy tensor test before writing to disk:
```python
   loss_fn = PluginLossClass(config)
   pred = torch.randn(2, 256, 100, requires_grad=True)
   target = torch.randint(0, 256, (2, 100))
   out = loss_fn(pred, target)
   assert out.shape == torch.Size([])    # scalar
   assert out.requires_grad              # gradient flows
```
   If this fails, retry the LLM call (up to `max_retries=2`).

4. **Writes to disk** — `agent_generated/losses/{loss_name}.py`

5. **Registers metadata** — calls `CapabilityRegistry.register()` with
   `source_iteration` from `inp.run_name`.

6. **Sets `loss_provenance`** on `ImplementorOutput` (with `action="generated"` for new losses or `action="reused"` for registry hits — see the `LossProvenance` schema above).

---

## Validator — no changes needed

The existing `ml_code_validator_agent` runs a training loop that calls
`get_criterion(loss_cfg)`. After the implementor writes the loss plugin,
`get_criterion` with `loss_type="custom"` will load it automatically.
The validator gets a **free integration test** — not just a dummy tensor
check, but the loss running in a real training loop on real data.

---

## Proposer prompt changes

The proposer's prompt template needs two additions:

1. **"Available losses" section** — rendered at proposer-call time from
   `CapabilityRegistry.list(capability_type="loss")`. Shows the proposer
   what losses already exist so it can choose to reuse rather than regenerate.

2. **`custom_loss_spec` output field** — added to the JSON output contract
   with clear instructions:
   - If reusing an existing loss: set `loss_config.loss_type="custom"`,
     `loss_config.loss_name=<existing name>`, leave `custom_loss_spec=None`
   - If proposing a new loss: set `loss_config.loss_type="custom"`,
     `loss_config.loss_name=<new name>`, populate `custom_loss_spec`
   - If using a built-in loss: set `loss_config.loss_type` to one of the
     4 built-ins, leave `custom_loss_spec=None`

---

## Commit plan

### Commit L1 — `CapabilityRegistry` + `_loss_loader.py` + loss plugin interface

**Goal**: stand up the discovery + registry plumbing so L2's `get_criterion()` extension has something to call into. No schema or node changes yet.

**Code**:
- [ ] `agent_generated/_registry.py`
  - [ ] `CapabilityMetadata` Pydantic model (6 fields per architecture overview)
  - [ ] `CapabilityRegistry.list(capability_type=None)` reads `_capability_index.json`
  - [ ] `CapabilityRegistry.exists(name, capability_type)` membership lookup
  - [ ] `CapabilityRegistry.register(metadata)` — atomic append (tmp-file rename, not in-place rewrite)
  - [ ] Path resolution uses a NEW `SIDERIUS_LOSS_DIRS` env var (NOT `SIDERIUS_PLUGIN_DIRS`).
    Rationale: sharing `SIDERIUS_PLUGIN_DIRS` is unsafe — when that env var is set to a
    run-scoped model directory, the loss loader would (a) silently skip all globally-registered
    losses (the env-var override is exclusive, no fallback to `AGENT_GENERATED_DIR`), and
    (b) produce log spam by attempting to load every model `.py` file as a loss plugin and
    failing the required-attr check. Clean separation requires a dedicated env var.
    - [ ] `SIDERIUS_LOSS_DIRS` follows identical priority semantics to `SIDERIUS_PLUGIN_DIRS`:
      when set, scans only those directories; when unset, falls back to
      `agent_generated/losses/` (the global default).
    - [ ] `core/sandbox_executor.py` — add `_loss_subprocess_env(loss_dir)` helper mirroring
      `_subprocess_env(plugin_dir)`, injecting `SIDERIUS_LOSS_DIRS` into the subprocess env.
    - [ ] `workflows/model_exploration.py` — add `get_loss_dir(workspace, run_name)` helper
      mirroring `get_plugin_dir`; wire `SIDERIUS_LOSS_DIRS` at the same point where
      `SIDERIUS_PLUGIN_DIRS` is wired (near line 1535).
- [ ] `agent_generated/_capability_index.json` — seed file with literal `[]`
- [ ] `agent_generated/_loss_loader.py` — mirrors `ml_models/plugin_loader.py::_load_plugin`
  - [ ] `_load_loss_plugin(path)` returns dict or None
  - [ ] `importlib.util.spec_from_file_location` + `exec_module`
  - [ ] `sys.modules` rebind under prefix `siderius_loss_plugin_` (parallel to existing `siderius_plugin_` for models)
  - [ ] Required-attr check: `PLUGIN_LOSS_TYPE`, `PLUGIN_LOSS_CONFIG_CLASS`, `PLUGIN_LOSS_CLASS`
  - [ ] Files starting with `_` are skipped (same convention as models)
  - [ ] `load_loss_plugin(loss_name)` convenience wrapper used by `_load_custom_loss` (L2)
- [ ] `agent_generated/losses/` directory + `.gitkeep`
- [ ] `agent_generated/_stub_loss_template.py` — minimal valid loss plugin for tests. Leading `_` keeps the loader from picking it up in production.

**Tests** (all pure-Python, no LLM, no GPU — run freely):
- [ ] `tests/unit/agent_generated/test_capability_registry.py`
  - [ ] empty index → `list()` returns `[]`
  - [ ] `register()` → `list()` round-trip
  - [ ] `list(capability_type="loss")` filters correctly
  - [ ] `exists(name, type)` true/false branches
  - [ ] atomic-rename: concurrent `register()` from two processes doesn't corrupt JSON
- [ ] `tests/unit/agent_generated/test_loss_loader.py`
  - [ ] stub template loads cleanly when copied (without `_` prefix) to `losses/`
  - [ ] missing each of the 3 required attrs → loader rejects with explicit message
  - [ ] `_`-prefixed files are skipped (the template itself stays dormant)
  - [ ] `sys.modules` rebind allows `inspect.getsource(PLUGIN_LOSS_CLASS)` to resolve the file
  - [ ] `SIDERIUS_LOSS_DIRS` env var: when set to a dir with a valid
    loss plugin, loader finds it; when set to a dir with only model `.py` files, loader
    skips cleanly with zero log spam (missing-attr lines are suppressed or clearly labeled,
    not mistaken for failures).

**Out of scope for this commit**: no `get_criterion` changes, no schema changes, no implementor changes.

**Implementation notes** (filled in as work lands):
- _none yet_

### Commit L2 — `LossConfig` + `get_criterion()` extension

**Goal**: route `loss_type="custom"` through `_loss_loader.py`. After this commit, training and the two evaluate-* skills automatically pick up any plugin loss without further changes.

**Code**:
- [ ] `ml_models/models_format_sandbox.py` — modify `LossConfig`
  - [ ] Add `"custom"` to the `loss_type` `Literal[...]`
  - [ ] Add `loss_name: str | None` field (default `None`, description per design doc above)
  - [ ] Add `enforce_custom_loss_name` `@model_validator(mode="after")`
  - [ ] Update existing `enforce_parameter_consistency` validator: add `loss_type == "custom"` branch
    that nullifies alpha, gamma, and beta unconditionally. This is safe: LossConfig and the
    plugin's PLUGIN_LOSS_CONFIG_CLASS are completely separate objects. The plugin config is
    constructed independently in `_load_custom_loss()` with no reference to LossConfig's
    alpha/gamma/beta. Nullifying them in LossConfig has zero effect on plugin behaviour.
    Remove the "unless the plugin's config schema reuses them" hedge — it is a non-concern.
  - [ ] Update `check_compatibility(model_type)` — for `"custom"`, defer compatibility to the plugin (no built-in vs model_type check)
- [ ] `ml_models/loss_models_sandbox.py` — extend `get_criterion`
  - [ ] Add `"custom"` branch at the top of the if/elif chain
  - [ ] Write `_load_custom_loss(loss_name, config)` helper
  - [ ] On lookup miss, raise `ValueError` with the exact remediation message ("Run the implementor first…")
- [ ] Update the module docstring at the top of `loss_models_sandbox.py` to mention the plugin path

**Tests** (pure-Python, no LLM, no GPU — run freely):
- [ ] `tests/unit/ml_models/test_loss_config.py` (extend existing file)
  - [ ] `loss_type="custom"` with `loss_name=None` → `ValidationError`
  - [ ] `loss_type="focal"` with `loss_name="x"` → `ValidationError`
  - [ ] `loss_type="custom"` with `loss_name="snr_weighted_mse"` → valid round-trip
  - [ ] `check_compatibility("any_model_type")` is a no-op when `loss_type="custom"`
- [ ] `tests/unit/ml_models/test_get_criterion.py` (extend existing file)
  - [ ] `"custom"` branch: temp-dir loss plugin, `get_criterion` returns the plugin's `PLUGIN_LOSS_CLASS` instance
  - [ ] `"custom"` branch: missing plugin raises `ValueError` with implementor-pointer text
  - [ ] All 4 existing branches still pass unchanged (regression guard)
- [ ] Existing `evaluate_vram_skill` + `evaluate_time_skill` unit tests still pass (they call `get_criterion` indirectly)

**Out of scope**: no schema changes (those live in L3); no implementor or proposer changes.

**Dependency**: L1 must land first (this commit imports `agent_generated._loss_loader`).

**Implementation notes**:
- _none yet_

### Commit L3 — Schema changes (`ProposalOutput` + `ImplementorOutput`)

**Goal**: open the proposer → implementor → validator channel for loss specs without yet wiring any node logic. Safe to land before L4/L5 because `custom_loss_spec` defaults to `None` (back-compat).

**Code**:
- [ ] `agent/schemas/proposal.py`
  - [ ] Add `CustomLossSpec` BaseModel with 4 fields (loss_name, description, mathematical_definition, config_fields)
  - [ ] Add `ProposalOutput.custom_loss_spec: CustomLossSpec | None = None`
  - [ ] Add `@model_validator(mode="after")` on `ProposalOutput`: if `custom_loss_spec` is set, `baseline_config["loss_config"]["loss_type"]` MUST be `"custom"` AND `baseline_config["loss_config"]["loss_name"]` MUST match `custom_loss_spec.loss_name` — emit clear ValidationError on mismatch
- [ ] `agent/schemas/implementor.py`
  - [ ] Add `ImplementorOutput.loss_provenance: LossProvenance | None = None` (full audit trail; supersedes the earlier standalone `loss_file_path` proposal)
  - [ ] Add `ImplementorInput.custom_loss_spec: CustomLossSpec | None = None`
    (the implementor needs this field to know what to generate; default None preserves back-compat)
  - [ ] Add `ImplementorInput.loss_dir: str = "agent_generated/losses"`
    mirroring the existing `plugin_dir: str = "agent_generated/models"` field (line 133-137).
    Workflow will override this at call time, same pattern as `plugin_dir`.
  - [ ] No `loss_test_dir` field needed — loss plugins do NOT get a stub test file.
    Rationale: two validation layers already exist (dummy-tensor check in implementor +
    real training loop in validator). A third stub test would be redundant overhead.
- [ ] `agent/schemas/protocols/ml_model_propose_to_ml_model_impl.py` — in `local_full_spec()`,
  add `custom_loss_spec=output.custom_loss_spec` to the `ImplementorInput(...)` constructor call.
  (Protocol currently forwards only 4 fields; this adds the 5th.)
- [ ] Update `ProposalOutput` and `ImplementorOutput` docstrings + the description.md generation in the implementor's existing path to note the new optional fields

**Tests** (pure-Python — run freely):
- [ ] `tests/unit/agent/schemas/test_proposal_schemas.py` (extend)
  - [ ] `custom_loss_spec=None` → no validation error (back-compat)
  - [ ] `custom_loss_spec` set but `baseline_config.loss_config.loss_type != "custom"` → ValidationError
  - [ ] `custom_loss_spec.loss_name != baseline_config.loss_config.loss_name` → ValidationError
  - [ ] Happy path round-trip
- [ ] `tests/unit/agent/schemas/test_implementor_schemas.py` (extend)
  - [ ] `loss_provenance=None` round-trip (back-compat)
  - [ ] `loss_provenance=LossProvenance(action="generated", ...)` round-trip
  - [ ] `loss_provenance=LossProvenance(action="reused", ...)` round-trip
  - [ ] `ImplementorInput.custom_loss_spec=None` round-trip (back-compat)
  - [ ] `ImplementorInput.loss_dir` default value matches schema (`"agent_generated/losses"`)
- [ ] `tests/unit/agent/protocols/test_ml_model_propose_to_ml_model_impl.py` (extend)
  - [ ] `local_full_spec` forwards `custom_loss_spec` end-to-end

**Out of scope**: no implementor logic, no proposer prompt changes, no CLI.

**Dependency**: independent of L1 / L2 — can land in parallel.

**Implementation notes**:
- _none yet_

### Commit L4 — Implementor loss code generation

**Goal**: implementor reads `custom_loss_spec` and writes a valid loss plugin to disk + registers it. Depends on L1, L2, L3.

**Code**:
- [ ] `nodes/ml_model_implementor/ml_model_implementor.py`
  - [ ] New private method `_generate_loss(inp)` triggered when `inp.custom_loss_spec` is set
    - [ ] **Registry hit short-circuit** — call `CapabilityRegistry.exists(loss_name, "loss")`; on hit, log `[LossLoader] Reusing existing loss plugin: '{loss_name}'`, populate `loss_provenance` with `action="reused"` + `source_iteration` from the registry entry + `loss_file_path` from the registry entry + `dummy_tensor_validated=True`, return early
    - [ ] **LLM call** — separate from model-code call; use the same `self.bridge` with a new label `implementor.loss`
    - [ ] **Source assembly** — `_assemble_loss_plugin(spec, code)` helper mirroring `_assemble_plugin`
    - [ ] **Dummy-tensor validation** — instantiate, run forward with `pred=randn(2,256,100, requires_grad=True)` + `target=randint(0,256,(2,100))`, assert scalar shape + `requires_grad`
    - [ ] **Retry loop** — up to `max_retries=2` on validation failure, feeding the assertion error back into a repair prompt
    - [ ] **Write** — to `inp.loss_dir` (default `"agent_generated/losses"`; workflow overrides for run-scoped isolation — see workflow sub-bullet below). The implementor uses `inp.loss_dir` as the destination, same caller-sets-path / node-uses-path pattern as `inp.plugin_dir` for model plugins.
    - [ ] **Register** — `CapabilityRegistry.register(CapabilityMetadata(...))` with `source_iteration=inp.storage.local.run_name`
    - [ ] Populate `loss_provenance` on the output with `action="generated"`, `source_iteration=inp.storage.local.run_name`, the absolute `loss_file_path`, and `dummy_tensor_validated=True`
  - [ ] Order in `run()`: generate loss BEFORE model (so if model code references the custom loss class, it can — but only if shape compatibility check passes; this is a soft optimisation)
- [ ] `workflows/model_exploration.py` — override `impl_input.loss_dir` at the same
  point where `impl_input.plugin_dir` is overridden (near line 1436):
  `impl_input.loss_dir = os.path.join(attempt_dir, "losses")`
  This mirrors the caller-sets-path, node-uses-path pattern used for model plugins.
- [ ] `agent/prompt_templates/implementor/loss_generation_system.md` (new)
  - [ ] Forward contract block (inputs `[B, 256, T] float32`, targets `[B, T] int64`, scalar output, `requires_grad=True`)
  - [ ] Plugin interface contract (the 3 PLUGIN_LOSS_* symbols)
  - [ ] Anti-patterns (don't use `torch.no_grad()` in `forward`, don't return non-scalar, don't import outside torch/pydantic/stdlib)
- [ ] `agent/prompt_templates/implementor/__init__.py` (or wherever existing prompts are exported) — register the new template

**Tests** (mostly pure-Python; real LLM optional):
- [ ] `tests/unit/agent/ml_model_implementor/test_loss_generation.py` (mocked bridge — runs freely)
  - [ ] Registry hit → no LLM call; `loss_provenance` populated with `action="reused"`; no file written
  - [ ] Registry miss → mocked LLM returns valid loss code; dummy-tensor passes; file written; `CapabilityRegistry.register` called once; `loss_provenance.action == "generated"`
  - [ ] First mocked LLM response fails the scalar-shape assertion → retry triggered; second response succeeds → file written
  - [ ] All retries fail → `ValueError` raised with last assertion error
  - [ ] `custom_loss_spec=None` → existing behaviour unchanged (regression guard)
- [ ] **Optional Tier-1 integration** — `tests/integration/nodes/test_ml_model_implementor_custom_loss.py` with `@real_run` marker; one real LLM call generating SNR-weighted MSE from a hand-crafted `CustomLossSpec`. Skipped in CI; **needs user approval to run** (real LLM only, no training).

**Out of scope**: proposer awareness (L5). CLI is out of scope for this whole design doc (see Scope section).

**Implementation notes**:
- _none yet_

### Commit L5 — Proposer prompt + registry query

**Goal**: proposer becomes aware of the loss registry and emits a `custom_loss_spec` when proposing a novel loss (or chooses to reuse an existing one). Depends on L1, L3 — does NOT depend on L4 (the implementor will be ready when this lands).

**Code**:
- [ ] Inject `{AVAILABLE_LOSSES}` into BOTH the causal-reasoning stage AND the proposing stage:
  - `causal_reasoning_stage.md`, `causal_reasoning_stage_exploit.md`,
    `causal_reasoning_stage_explore.md` — inject early in the reasoning context so the
    LLM knows which losses exist BEFORE deciding what to propose. This is where the
    proposer reasons about what to build; awareness of available losses at this stage
    produces better proposals than injecting only at the output-formatting stage.
  - `proposing_stage.md`, `proposing_stage_exploit.md`, `proposing_stage_explore.md` —
    inject in the JSON output contract section with the 3-branch decision rule:
      * Reuse existing: `loss_config.loss_type="custom"`, `loss_config.loss_name=<existing>`,
        `custom_loss_spec=None`
      * Generate new: `loss_config.loss_type="custom"`, `loss_config.loss_name=<new>`,
        `custom_loss_spec` populated
      * Use built-in: `loss_config.loss_type` ∈ {focal, focal_cw, ce, smooth_l1},
        `custom_loss_spec=None`
- [ ] `agent/prompt_templates/proposal/__init__.py` — add `render_available_losses(registry)`
  helper. When registry is empty, renders: "No custom losses registered yet — propose a
  new one grounded in lit-review findings, or use a built-in loss."
  When non-empty, renders a markdown table: `loss_name | source_iteration | description`,
  sorted by `created_at` descending (most recent first).
  Rationale: most recently generated loss was produced under the closest prior
  experiment state and is most likely relevant to the current bottleneck.
- [ ] `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py` — query
  `CapabilityRegistry.list(capability_type="loss")` before each proposing-stage call
  and pass the rendered list into the prompt context for ALL 6 prompt variants
  (causal_reasoning × 3 + proposing × 3).

**Tests** (mocked LLM — run freely):
- [ ] `tests/unit/agent/ml_model_proposal_agent/test_loss_awareness.py`
  - [ ] Empty registry → prompt renders the "no custom losses" fallback message
  - [ ] Registry with 3 losses → prompt renders all 3 sorted by `created_at` descending
    (most recently generated loss first). Rationale: the most recently generated loss was
    created under the closest prior experiment state and is most likely relevant to the
    current bottleneck. Test must verify the order is stable across calls (same input →
    same output).
  - [ ] Proposer mocked to emit `custom_loss_spec` → output validates against schema
  - [ ] Proposer mocked to emit `loss_config.loss_type="custom"` + matching `loss_name` but `custom_loss_spec=None` (reuse path) → output validates
  - [ ] Proposer mocked to emit mismatched `custom_loss_spec.loss_name` vs `loss_config.loss_name` → ValidationError surfaced
- [ ] `tests/unit/agent/prompt_templates/test_proposal_prompts.py` (extend)
  - [ ] `render_available_losses` golden output

**Out of scope**: implementor LLM call (L4). CLI is out of scope for this whole design doc (see Scope section).

**Implementation notes**:
- _none yet_

### Checkpoint L — Behavioral validation

**Goal**: end-to-end real-LLM evidence that the feature works in the closed loop. **Real-LLM + real-training combo — requires user approval before running** (per development principle 3).

**Pre-flight** (run freely):
- [ ] Full unit suite green: `uv run pytest tests/unit/ -q`
- [ ] Tier-0 dual-mode integration suite green: `uv run pytest tests/integration/ -q`
- [ ] L4 optional Tier-1 (real LLM, no training) ran successfully at least once

**Validation runs** (need user approval — estimated cost / wall-time to be filled in below):
- [ ] **Run A — new loss generation**: 1 chain iteration, `--ml_lit_review_enabled`, target a finding that recommends a novel loss
  - [ ] Proposer output contains non-null `custom_loss_spec`
  - [ ] `baseline_config.loss_config.loss_type == "custom"` and `loss_name` matches
  - [ ] Implementor writes `agent_generated/losses/{loss_name}.py` (or run-scoped equivalent)
  - [ ] `_capability_index.json` has a new entry with `capability_type="loss"`, correct `source_iteration`
  - [ ] Validator passes — the loss runs in the real training loop
  - [ ] Tuner runs ≥ 1 round successfully using the custom loss
- [ ] **Run B — reuse path**: 1 more iteration after Run A; force the proposer to reuse Run A's loss
  - [ ] Proposer emits `loss_name=<Run A's loss>`, `custom_loss_spec=None`
  - [ ] Implementor short-circuits (no second LLM call for loss code; log line `[LossLoader] Reusing existing loss plugin: ...`)
  - [ ] `_capability_index.json` unchanged (no duplicate entry)
  - [ ] Validator passes again

**Sign-off artifact**:
- [ ] `docs/checkpoint_l_sign_off.md` written with:
  - [ ] Wall-time + token cost for both runs
  - [ ] Excerpt of generated loss source
  - [ ] Validator log showing training-loop usage
  - [ ] Decision: ready to merge / blocked on X

**Estimated cost / time** (filled in once L1–L5 are done):
- _TBD_

**Implementation notes**:
- _none yet_

---

## Open questions

1. **Loss hyperparameter tuning**: the tuner currently sweeps `loss_config`
   fields (alpha, gamma, etc.). For custom losses, the tuner needs to know
   which fields are tunable. Should `CustomLossSpec.config_fields` include
   tuning ranges, or should the tuner treat custom loss config as fixed?

2. **Loss versioning**: if iter_017 generates a better `snr_weighted_mse`
   that supersedes iter_014's version, how do we handle the collision?
   Options: (a) append version suffix (`snr_weighted_mse_v2`), (b) overwrite
   with a registry audit trail, (c) namespace by iteration
   (`iter_014/snr_weighted_mse`).

3. **AE model special case**: `AE.__init__` takes `loss_type: str` directly
   for forward-pass shape adaptation (`smooth_l1` uses regressor output,
   others use classifier). Custom losses will always use classifier output
   shape. This should be documented as a constraint in the loss plugin
   interface.

4. **evaluate_time_skill + evaluate_vram_skill**: both call `get_criterion()`.
   They will automatically benefit from custom losses once L2 lands. No
   changes needed, but worth noting in testing.

---

## Non-goals (explicit out-of-scope)

- Multi-stage training loops (pretraining + finetuning) — separate feature
- Perceptual loss requiring a separate encoder model — separate feature  
- Loss ensembling (combining multiple loss functions) — separate feature
- Automatic loss architecture search — separate feature
