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

   See `docs/gates/gate_testing_standard.md` for canonical gate definitions, parameters, and pass criteria.

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

**Split decision (2026-06-19)**: L1 is split into two git commits at a clean
seam (per development principle 4):

- **L1a** (this checklist, items below marked `[x]`) — self-contained registry
  + loader + stub template + tests. Importable + unit-tested without any
  workflow wiring.
- **L1b** (deferred) — workflow + subprocess wiring (`_loss_subprocess_env`,
  `get_loss_dir`). Not needed until L4 actually invokes the loader from a
  per-run scoped directory. Marked with **(L1b)** tags below.

**Code**:
- [x] `agent_generated/_registry.py`
  - [x] `CapabilityMetadata` Pydantic model (6 fields per architecture overview)
  - [x] `CapabilityRegistry.list(capability_type=None)` reads `_capability_index.json`
  - [x] `CapabilityRegistry.exists(name, capability_type)` membership lookup
  - [x] `CapabilityRegistry.register(metadata)` — atomic append (tmp-file rename, not in-place rewrite)
  - [x] Path resolution uses a NEW `SIDERIUS_LOSS_DIRS` env var (NOT `SIDERIUS_PLUGIN_DIRS`).
    Rationale: sharing `SIDERIUS_PLUGIN_DIRS` is unsafe — when that env var is set to a
    run-scoped model directory, the loss loader would (a) silently skip all globally-registered
    losses (the env-var override is exclusive, no fallback to `AGENT_GENERATED_DIR`), and
    (b) produce log spam by attempting to load every model `.py` file as a loss plugin and
    failing the required-attr check. Clean separation requires a dedicated env var.
    - [x] `SIDERIUS_LOSS_DIRS` follows identical priority semantics to `SIDERIUS_PLUGIN_DIRS`:
      when set, scans only those directories; when unset, falls back to
      `agent_generated/losses/` (the global default).
    - [x] **(L1b)** `core/sandbox_executor.py` — extended existing `_subprocess_env(plugin_dir=None)`
      to `_subprocess_env(plugin_dir=None, loss_dir=None)` rather than adding a separate
      `_loss_subprocess_env` helper. Rationale: subprocesses always need both env vars,
      so a single function avoids duplicate `PYTHONPATH` construction + env-merge logic
      at every call site. Backward-compatible — existing callers passing only `plugin_dir`
      get identical behavior. **Verified by `TestSubprocessEnvLossDir` (6 tests):
      independence of the two env vars, both-populated, PYTHONPATH preservation.**
    - [x] **(L1b)** `core/sandbox_executor.py` — `get_loss_dir(workspace, run_name)` helper added
      next to `get_plugin_dir` (NOT in `workflows/model_exploration.py` as the doc originally
      said — that was a doc imprecision; the existing `get_plugin_dir` lives in
      `core/sandbox_executor.py:214` and the workflow imports it, so symmetry dictates
      `get_loss_dir` lives next to it). Returns `<workspace>/losses/<run_name>/`
      absolutised. **Verified by `TestGetLossDir` (3 tests).**
    - [x] **(L1b)** `TidmadSandbox.__init__` — added `self.loss_dir = get_loss_dir(...)` + eager
      `_ensure_dir(self.loss_dir)` directly after the existing `plugin_dir` setup at line 423-424.
      All 3 `_subprocess_env(plugin_dir=self.plugin_dir)` call sites in the file (lines 577, 745, 864)
      updated to also pass `loss_dir=self.loss_dir`. **Verified by `TestSandboxLossDir` (4 tests):
      dir is created under workspace, two sandboxes get distinct dirs, plugin_dir and loss_dir
      are distinct siblings, training subprocess receives both env vars.**
    - [x] **(L1b)** No `workflows/model_exploration.py` changes needed. The sandbox-level wiring
      is sufficient at L1b — there's no loss to stage into the per-run dir until L4 generates one.
      Workflow-side staging (a `_register_loss` analog of `_register_plugin`) will land with L4
      when there's actually content to stage.
- [x] `agent_generated/_capability_index.json` — seed file with literal `[]`
- [x] `agent_generated/_loss_loader.py` — mirrors `ml_models/plugin_loader.py::_load_plugin`
  - [x] `_load_loss_plugin(path)` returns dict or None
  - [x] `importlib.util.spec_from_file_location` + `exec_module`
  - [x] `sys.modules` rebind under prefix `siderius_loss_plugin_` (parallel to existing `siderius_plugin_` for models)
  - [x] Required-attr check: `PLUGIN_LOSS_TYPE`, `PLUGIN_LOSS_CONFIG_CLASS`, `PLUGIN_LOSS_CLASS`
  - [x] Files starting with `_` are skipped (same convention as models)
  - [x] `load_loss_plugin(loss_name)` convenience wrapper used by `_load_custom_loss` (L2)
- [x] `agent_generated/losses/` directory + `.gitkeep`
- [x] `agent_generated/_stub_loss_template.py` — minimal valid loss plugin for tests. Leading `_` keeps the loader from picking it up in production.

**Tests** (all pure-Python, no LLM, no GPU — run freely) — **39 new tests, all pass in 0.77 s; full `agent_generated/` regression: 44/44 pass in 0.71 s**:
- [x] `tests/unit/agent_generated/test_capability_registry.py` — 22 tests
  - [x] empty index → `list()` returns `[]` (5 tests: missing file, type filter, exists branch, explicit `[]`, `null` content)
  - [x] `register()` → `list()` round-trip (3 tests: single, multiple insertion order, valid-JSON-array on-disk)
  - [x] `list(capability_type="loss")` filters correctly (3 tests: type filter, no-match, no-filter)
  - [x] `exists(name, type)` true/false branches (3 tests: match, wrong name, wrong type)
  - [x] atomic-rename: concurrent `register()` from two processes doesn't corrupt JSON
  - [x] Bonus: duplicate-registration rejection + schema-validation edge cases
- [x] `tests/unit/agent_generated/test_loss_loader.py` — 17 tests
  - [x] stub template loads cleanly when copied (without `_` prefix) to `losses/`
  - [x] missing each of the 3 required attrs → loader rejects with explicit message (parametrized over all 3 attrs)
  - [x] `_`-prefixed files are skipped (the template itself stays dormant)
  - [x] `sys.modules` rebind allows `inspect.getsource(PLUGIN_LOSS_CLASS)` to resolve the file
  - [x] `SIDERIUS_LOSS_DIRS` env var: when set to a dir with a valid
    loss plugin, loader finds it; when set to a dir with only model `.py` files, loader
    skips cleanly with one `Skipping ... missing 'PLUGIN_LOSS_TYPE'` line per misnamed
    file — clearly labeled, not mistaken for catastrophic failure
    *(`test_loader_isolates_model_dir_misuse`)*
  - [x] Bonus: `load_loss_plugin(name)` name-lookup hit/miss + path-resolution edge cases

**Out of scope for this commit**: no `get_criterion` changes, no schema changes, no implementor changes.

**Implementation notes**:
- **Stub loss = cross-entropy with label-smoothing**. The L1 spec doesn't
  prescribe the stub's exact loss formula — only that it must satisfy the
  `[B, C, T] float32` × `[B, T] int64` → scalar contract with
  `requires_grad=True`. Cross-entropy was chosen because (a) it's the same
  family used by every classifier model in `MODEL_REGISTRY`, so the stub
  exercises the same gradient path the production losses do, and (b)
  `F.cross_entropy` accepts `[B, C, *]` logits + `[B, *]` indices natively,
  so the stub stays small (one `torch.nn.functional` call) without any
  shape-juggling boilerplate.
- **Registry vs Loader separation of concerns**: the registry (`_registry.py`)
  is a pure JSON read/write layer that has no Python-import dependency on
  the actual plugin modules. This is deliberate — a future CLI reader (out
  of scope per the Scope section) can iterate the registry without ever
  importing torch/pydantic. The loader (`_loss_loader.py`) handles the
  Python-import path and is the only module that needs torch at all.
- **Atomic write via tmp-file-then-rename**: matches the T1b
  `_snapshot_task_config` pattern. The test `test_concurrent_register_does_not_corrupt_json`
  spawns two `multiprocessing.Process` workers that interleave writes —
  the file is always valid JSON afterwards (no half-written-file
  corruption), even though some individual `register()` calls may lose
  their write due to read-modify-write contention. This is the correct
  guarantee for L1: the index file remains parseable; concurrent writers
  are not in scope (production has one `register()` per chain run).
- **Schema validation surfaces corruption early**: `list()` calls
  `CapabilityMetadata.model_validate(row)` on every row, so a hand-edited
  index with a malformed entry raises at list time, not at row-access
  time downstream. The `test_list_raises_on_corrupted_row` test pins this.
- **Lint**: ruff (check + format) clean. Pyright clean (0 errors, 0 warnings).
- **Test results**: 39 new tests pass in 0.77 s. Full `tests/unit/agent_generated/`
  suite (44 tests including the pre-existing `test_stub_plugin_template_loads`)
  pass in 0.71 s. No prior tests broke.
- **L1b — `_subprocess_env` extended, not duplicated**: the original L1 design said to
  add a separate `_loss_subprocess_env(loss_dir)` helper. Implementation chose instead
  to extend the existing `_subprocess_env(plugin_dir=None)` with a `loss_dir=None`
  kwarg. Rationale: subprocesses always need both env vars, so a single function
  avoids duplicate `PYTHONPATH` construction + env-merge logic at every call site.
  Backward-compatible — existing callers passing only `plugin_dir` get identical
  behavior (verified by all 36 pre-existing `core/sandbox_executor` tests staying green).
- **L1b — `get_loss_dir` lives in `core/sandbox_executor.py`, not `workflows/model_exploration.py`**:
  the design doc said the latter, but pre-read showed `get_plugin_dir` lives in
  `core/sandbox_executor.py:214` (the workflow only *imports* it). Symmetry dictates
  `get_loss_dir` lives next to it. The doc bullet has been corrected to reflect this.
- **L1b — no workflow-side staging at this commit**: a `_register_loss` analog of
  `_register_plugin` is not needed until L4 actually generates a loss to stage.
  At L1b, the empty per-run `<workspace>/losses/<run_name>/` is sufficient — the
  loss loader scans it, finds nothing, and the existing `loss_type="ce"` /
  `loss_type="focal"` paths continue unaffected.
- **L1b test results**: 13 new tests in `tests/unit/core/test_sandbox_executor.py`
  (`TestSubprocessEnvLossDir` × 6, `TestSandboxLossDir` × 4, `TestGetLossDir` × 3).
  Full `tests/unit/core/` + `tests/unit/agent_generated/` regression sweep: **267/267
  pass in 1.29 s**. Ruff + pyright clean.

### Commit L2 — `LossConfig` + `get_criterion()` extension

**Goal**: route `loss_type="custom"` through `_loss_loader.py`. After this commit, training and the two evaluate-* skills automatically pick up any plugin loss without further changes.

**Code**:
- [x] `ml_models/models_format_sandbox.py` — modify `LossConfig`
  - [x] Add `"custom"` to the `loss_type` `Literal[...]`
  - [x] Add `loss_name: str | None` field (default `None`, description per design doc above)
  - [x] Add `enforce_custom_loss_name` `@model_validator(mode="after")`
  - [x] Update existing `enforce_parameter_consistency` validator: add `loss_type == "custom"` branch
    that nullifies alpha, gamma, and beta unconditionally. This is safe: LossConfig and the
    plugin's PLUGIN_LOSS_CONFIG_CLASS are completely separate objects. The plugin config is
    constructed independently in `_load_custom_loss()` with no reference to LossConfig's
    alpha/gamma/beta. Nullifying them in LossConfig has zero effect on plugin behaviour.
    Remove the "unless the plugin's config schema reuses them" hedge — it is a non-concern.
  - [x] Update `check_compatibility(model_type)` — for `"custom"`, defer compatibility to the plugin (no built-in vs model_type check)
- [x] `ml_models/loss_models_sandbox.py` — extend `get_criterion`
  - [x] Add `"custom"` branch at the top of the if/elif chain
  - [x] Write `_load_custom_loss(loss_name)` helper (signature corrected from the
    earlier `_load_custom_loss(loss_name, config)` plan — `config` param dropped,
    plugin constructs its own `PLUGIN_LOSS_CONFIG_CLASS()` per the two-config design)
  - [x] On lookup miss, raise `ValueError` with the exact remediation message ("Run the implementor first…")
- [x] Update the module docstring at the top of `loss_models_sandbox.py` to mention the plugin path

**Tests** (pure-Python, no LLM, no GPU — run freely):
- [x] `tests/unit/ml_models/test_loss_functions.py` (extend existing file — the
  consolidated home for all loss-related unit tests; `test_loss_config.py` and
  `test_get_criterion.py` from the original plan never existed as separate files
  in the repo, so the test additions were appended to the actual file)
  - [x] `loss_type="custom"` with `loss_name=None` → `ValidationError`
  - [x] `loss_type="focal"` with `loss_name="x"` → `ValidationError`
  - [x] `loss_type="custom"` with `loss_name="snr_weighted_mse"` → valid round-trip
  - [x] `check_compatibility("any_model_type")` is a no-op when `loss_type="custom"`
  - [x] `"custom"` branch: temp-dir loss plugin, `get_criterion` returns the plugin's `PLUGIN_LOSS_CLASS` instance
  - [x] `"custom"` branch: missing plugin raises `ValueError` with implementor-pointer text
  - [x] All 4 existing branches still pass unchanged (regression guard)
- [x] Existing `evaluate_vram_skill` + `evaluate_time_skill` unit tests still pass (they call `get_criterion` indirectly)

**Out of scope**: no schema changes (those live in L3); no implementor or proposer changes.

**Dependency**: L1 must land first (this commit imports `agent_generated._loss_loader`).

**Implementation notes**:
- **Helper signature deviation** — the original plan said `_load_custom_loss(loss_name, config)`.
  Implementation dropped the `config` parameter: the plugin's
  `PLUGIN_LOSS_CONFIG_CLASS` is a separate Pydantic model with its own
  hyperparameters (e.g. `snr_threshold`, `stft_window_size`) constructed
  independently inside `_load_custom_loss()`. `LossConfig` is only the *router*
  (carries `loss_type="custom"` + `loss_name`); passing it to the plugin would
  break the two-config separation of concerns documented in § "Two-config
  design". The hyperparameters from the proposer's `CustomLossSpec` will arrive
  via a separate channel at L4 (TBD), not through `LossConfig`.
- **Test-file consolidation deviation** — the plan listed
  `tests/unit/ml_models/test_loss_config.py` and `test_get_criterion.py` as
  separate "extend existing file" targets. Neither exists in the repo; the
  consolidated home is `tests/unit/ml_models/test_loss_functions.py` (14 prior
  tests covered both schema and routing). The 25 new L2 tests were appended
  to that single file in 5 classes (`TestLossConfigCustomValidation` × 7,
  `TestEnforceParameterConsistencyCustom` × 1, `TestCheckCompatibilityCustom`
  × 4 parametrized, `TestGetCriterionCustom` × 4, `TestBuiltinsStillWorkAfterCustomBranch`
  × 4 parametrized).
- **`check_compatibility` is implicit no-op, not an explicit branch** — the
  pre-existing function only raised when `loss_type == "smooth_l1"` and
  `model_type != "fcnet"`. Since `"custom"` never enters that branch, the
  no-op behaviour is automatic; the implementation added a clarifying comment
  rather than an explicit `if self.loss_type == "custom": return` line. Four
  parametrized tests in `TestCheckCompatibilityCustom` pin the behaviour
  regardless.
- **`enforce_custom_loss_name` ordering matters** — runs *before*
  `enforce_parameter_consistency` so an invalid `(loss_type, loss_name)` pair
  is caught at the first validator, not after parameter nullification masks
  the intent. Pydantic preserves declaration order for `@model_validator(mode="after")`.
- **Empty-string `loss_name` rejected as well as `None`** — the validator uses
  `if not self.loss_name` rather than `is None`, so `loss_type="custom",
  loss_name=""` also raises (verified by `test_custom_with_empty_loss_name_raises`).
  Empty strings would otherwise propagate to `load_loss_plugin("")` and surface
  as a confusing "plugin not found" error instead of the actionable validation
  message.
- **Live plugin sanity check** — `test_custom_plugin_forward_pass_runs` copies
  the `_stub_loss_template.py` (committed in L1a) into a tmp dir, points
  `SIDERIUS_LOSS_DIRS` at it, and runs the full `get_criterion → _load_custom_loss
  → load_loss_plugin → StubCE.forward` chain on classifier-shaped tensors with
  `requires_grad=True`. This exercises the same code path production training
  will hit at L4.
- **Lint**: ruff (check + format) clean. Pyright clean (0 errors, 0 warnings).
- **Test results**: 25 new L2 tests + 14 pre-existing = 39/39 pass in
  `tests/unit/ml_models/test_loss_functions.py` in 0.76 s. Broader regression
  sweep: `tests/unit/ml_models/` + `tests/unit/core/` = **364/364 pass in 3.28 s**.
  Targeted evaluate-skill sweep (`-k "evaluate_vram or evaluate_time or skill"`)
  = **280/280 pass** — confirms the L2 routing change did not break any skill
  that calls `get_criterion` indirectly.

### Commit L3 — Schema changes (`ProposalOutput` + `ImplementorOutput`)

**Goal**: open the proposer → implementor → validator channel for loss specs without yet wiring any node logic. Safe to land before L4/L5 because `custom_loss_spec` defaults to `None` (back-compat).

**Code**:
- [x] `agent/schemas/proposal.py`
  - [x] Add `CustomLossSpec` BaseModel with 4 fields (loss_name, description, mathematical_definition, config_fields)
  - [x] Add `ProposalOutput.custom_loss_spec: CustomLossSpec | None = None`
  - [x] Add `@model_validator(mode="after")` on `ProposalOutput`: if `custom_loss_spec` is set, `baseline_config["loss_config"]["loss_type"]` MUST be `"custom"` AND `baseline_config["loss_config"]["loss_name"]` MUST match `custom_loss_spec.loss_name` — emit clear ValidationError on mismatch (validator named `_validate_custom_loss_spec_consistency`)
- [x] `agent/schemas/implementor.py` — add loss-specific fields to `ImplementorInput`:
  - NOTE: `task_description` and `forward_contract` fields already exist on
    `ImplementorInput` (added by `enable_global_task_config` T2, commit 8ac113d).
    L3 adds ONLY the loss-specific fields below — do NOT re-add task_description.
  - [x] `custom_loss_spec: CustomLossSpec | None = None`
  - [x] `loss_dir: str = "agent_generated/losses"`
  - [x] Also add `ImplementorOutput.loss_provenance: LossProvenance | None = None` (full audit trail; supersedes the earlier standalone `loss_file_path` proposal)
  - [x] No `loss_test_dir` field needed — loss plugins do NOT get a stub test file.
    Rationale: two validation layers already exist (dummy-tensor check in implementor +
    real training loop in validator). A third stub test would be redundant overhead.
- [x] `agent/schemas/protocols/ml_model_propose_to_ml_model_impl.py` — in `local_full_spec()`,
  add `custom_loss_spec=output.custom_loss_spec` to the `ImplementorInput(...)` constructor call.
  (Protocol previously forwarded 5 fields — doc said "4" but actual was 5 incl. storage; this adds the 6th.)
- [x] Update `ProposalOutput` and `ImplementorOutput` docstrings (loss-spec / loss_provenance field descriptions). description.md generation at the implementor node is deferred to L4 — at L3 there is no implementor logic change, only schema and protocol; the description.md template will be extended at L4 when the implementor actually writes the loss plugin.

**Tests** (pure-Python — run freely):
- [x] `tests/unit/agent/ml_model_proposal_agent/test_proposal_schemas.py` (extend — actual location; doc previously said `tests/unit/agent/schemas/...` which does not exist)
  - [x] `custom_loss_spec=None` → no validation error (back-compat)
  - [x] `custom_loss_spec` set but `baseline_config.loss_config.loss_type != "custom"` → ValidationError
  - [x] `custom_loss_spec.loss_name != baseline_config.loss_config.loss_name` → ValidationError
  - [x] Happy path round-trip
  - [x] **Bonus**: empty `loss_name` / `description` / `mathematical_definition` raise (min_length=1 on each)
  - [x] **Bonus**: `loss_type="custom"` + `custom_loss_spec=None` accepted (reuse-existing-loss path; schema is permissive here intentionally)
- [x] `tests/unit/agent/ml_model_implementor/test_implementor_schemas.py` (extend — actual location; doc previously said `tests/unit/agent/schemas/...` which does not exist)
  - [x] `loss_provenance=None` round-trip (back-compat)
  - [x] `loss_provenance=LossProvenance(action="generated", ...)` round-trip
  - [x] `loss_provenance=LossProvenance(action="reused", ...)` round-trip
  - [x] `ImplementorInput.custom_loss_spec=None` round-trip (back-compat)
  - [x] `ImplementorInput.loss_dir` default value matches schema (`"agent_generated/losses"`)
  - [x] **Bonus**: `loss_dir` override accepted (`"/custom/losses"`)
  - [x] **Bonus**: JSON model-dump round-trip preserves `loss_provenance` (required for `implementor_output_{run_name}.json` persistence)
  - [x] **Bonus**: `LossProvenance` schema enforcement: invalid `action`, empty `loss_name` / `loss_file_path`, `source_iteration=None` accepted for hand-curated registry entries
- [x] `tests/unit/agent/protocols/test_ml_model_propose_to_ml_model_impl.py` (extend)
  - [x] `local_full_spec` forwards `custom_loss_spec` end-to-end
  - [x] **Bonus**: `custom_loss_spec=None` forwards as `None` (built-in-loss path)
  - [x] **Bonus**: `loss_dir` falls back to schema default in the protocol output

**Out of scope**: no implementor logic, no proposer prompt changes, no CLI.

**Dependency**: independent of L1 / L2 — can land in parallel.

**Implementation notes**:
- **`CustomLossSpec` location** — placed in `agent/schemas/proposal.py` (right
  after `FalsifiablePrediction`, alongside the other leaf spec classes that
  feed into `ProposalOutput`) rather than in a new module. Rationale: it is
  produced exclusively by the proposer and consumed by `ProposalOutput` +
  `ImplementorInput`; promoting it to its own file would add an indirection
  without buying isolation. `implementor.py` imports it via
  `from agent.schemas.proposal import CustomLossSpec` — no circular-import
  risk (proposal.py does not import from implementor.py).
- **Consistency-validator name** — `_validate_custom_loss_spec_consistency`
  on `ProposalOutput`, matching the leading-underscore convention used by
  the existing `_validate_baseline_segmentation_size` validator. Runs after
  segmentation-size validation; declaration order matters because pydantic
  preserves it for `mode="after"` validators. No edge cases require a
  specific order between these two.
- **Permissive `loss_type='custom' + custom_loss_spec=None`** — the
  consistency validator only fires when `custom_loss_spec is not None`. A
  proposal that says "use loss_type='custom' with loss_name='snr_weighted_mse'"
  but omits the spec is **accepted** at the schema layer. This is the
  reuse-existing-registered-loss path: L4 will look up `loss_name` in the
  registry and skip the LLM generation call if a matching plugin exists.
  Surfacing this as a ValidationError would block the reuse path. The
  registry-lookup logic itself lives at L4; here we just keep the channel
  open.
- **`LossProvenance` placement** — in `agent/schemas/implementor.py`, before
  `ImplementorInput`. Rationale: provenance is produced by the implementor
  node and consumed via `ImplementorOutput` — co-locating it with the
  schemas that reference it avoids a third module. The class is also
  exported (the test file imports it directly: `from
  agent.schemas.implementor import LossProvenance`).
- **Protocol field count discrepancy** — the design doc said "Protocol
  currently forwards only 4 fields; this adds the 5th." Pre-read showed it
  was actually forwarding 5 (model_name, model_description,
  mathematical_definition, baseline_config, storage). Adding
  `custom_loss_spec` makes it 6. The doc bullet has been corrected.
  `loss_dir` is **not** forwarded by the protocol — it stays at the schema
  default ("agent_generated/losses"); the workflow overrides it directly
  at the call site to a per-run path (L4 wiring).
- **Test-file path discrepancy** — the design doc listed schema test files
  under `tests/unit/agent/schemas/`. Reality: proposal/implementor tests
  live under `tests/unit/agent/ml_model_proposal_agent/` and
  `tests/unit/agent/ml_model_implementor/` respectively. Only the protocol
  test path matched. The doc bullets have been corrected.
- **`description.md` template change deferred to L4** — the original L3
  bullet said "update description.md generation in the implementor's
  existing path to note the new optional fields." At L3 there is no
  implementor node logic change; the description.md template lives in the
  implementor agent module and will be extended at L4 when the loss
  plugin is actually written. Doc bullet annotated to reflect this.
- **Lint**: ruff check + format clean across all 4 modified source files
  + 3 modified test files. Pyright clean (0 errors, 0 warnings) on
  proposal.py, implementor.py, protocol file.
- **Test results**:
  - `test_proposal_schemas.py`: 30/30 (11 new + 19 pre-existing) in 0.74 s
  - `test_implementor_schemas.py`: 26/26 (16 new + 10 pre-existing) in 0.73 s
  - `test_ml_model_propose_to_ml_model_impl.py`: 4/4 (2 new + 2 pre-existing) in 0.88 s
  - **Broader regression sweep** across `tests/unit/agent/`: **2376/2376
    pass in 228.89 s**. No prior tests broke.
- **Planned git commit split** (per development principle 4 — L3 has clean
  seams): L3a (proposal.py schema + proposal tests) → L3b (implementor.py
  schema + implementor tests) → L3c (protocol forwarding + protocol test).
  Each commit is independently lint-clean and test-passing.

### Commit L4 — Implementor loss code generation

**Goal**: implementor reads `custom_loss_spec` and writes a valid loss plugin to disk + registers it. Depends on L1, L2, L3.

**Code**:
- [x] `nodes/ml_model_implementor/ml_model_implementor.py`
  - [x] New private method `_generate_loss(inp)` triggered when `inp.custom_loss_spec` is set *(L4b)*
    - [x] **Registry hit short-circuit** — iterates `self._registry.list(capability_type="loss")` and matches by `loss_name`; on hit, prints reuse log, returns `LossProvenance(action="reused", source_iteration=existing.source_iteration, loss_file_path=existing.file_path, dummy_tensor_validated=True)`. No LLM call, no file write. *(L4b)*
    - [x] **LLM call shape** — separate from model-code call; use the same `self.bridge`. Two-call pattern (reasoning + code), mirroring the model-code flow. Labels: `implementor.loss.reasoning` and `implementor.loss.code` (and `implementor.loss.repair` for retries). *(L4a — prompts only; L4b wires the call)*
    - [x] **Source assembly** — `_assemble_loss_plugin(loss_name, description, code)` helper mirroring `_assemble_plugin`. Signature: takes `loss_name` + one-line `description` (collapsed into the assembled class docstring) + LLM-returned code dict; returns assembled `.py` source. *(L4a)*
    - [x] **Dummy-tensor validation** — `_dummy_tensor_validate_loss(plugin_src, loss_name)`: instantiate, run forward with `inputs=randn(2,256,100, requires_grad=True)` + `targets=randint(0,256,(2,100), dtype=int64)`, assert scalar shape + `requires_grad` + finite. Returns `None` on success or an error string consumable by the repair prompt. *(L4a)*
    - [x] **Retry loop** — up to `inp.max_retries` repair attempts on validation failure, each feeding the validator error back into `IMPLEMENTOR_LOSS_REPAIR_PROMPT` + maintaining an `error_history` list so a fix doesn't reintroduce a prior mistake. Mirrors model-code repair-loop semantics. *(L4b)*
    - [x] **Write** — to `inp.loss_dir` (default `"agent_generated/losses"`; workflow overrides for run-scoped isolation — see workflow sub-bullet below). `os.makedirs(inp.loss_dir, exist_ok=True)` then write the assembled source to `{inp.loss_dir}/{loss_name}.py`. *(L4b)*
    - [x] **Register** — `self._registry.register(CapabilityMetadata(...))` with `source_iteration=inp.storage.local.run_name` (or `None` if non-local backend). `created_at` computed via `datetime.now(UTC).isoformat()`. Description normalised by `" ".join(spec.description.split())` to collapse newlines so the proposer's `{AVAILABLE_LOSSES}` rendering at L5 stays one-line. *(L4b)*
    - [x] Populate `loss_provenance` on the output with `action="generated"`, `source_iteration=inp.storage.local.run_name`, the absolute `loss_file_path`, and `dummy_tensor_validated=True` *(L4b)*
  - [x] Order in `run()`: generate loss BEFORE model. `loss_provenance` initialised to `None`; populated by `_generate_loss(inp)` when `inp.custom_loss_spec is not None`. Threaded into `ImplementorOutput(..., loss_provenance=loss_provenance)`. *(L4b)*
  - [x] `MLModelImplementor.__init__` gains a `capability_index_path: str | None = None` kwarg. When provided, `self._registry = CapabilityRegistry(index_path=capability_index_path)`; otherwise uses the canonical `agent_generated/_capability_index.json`. Lets unit tests pass a `tmp_path`-derived index without monkey-patching. *(L4b)*
- [x] `workflows/model_exploration.py` — override `impl_input.loss_dir` immediately after the `plugin_dir` / `test_dir` overrides:
  `impl_input.loss_dir = os.path.join(attempt_dir, "losses")`
  This mirrors the caller-sets-path, node-uses-path pattern used for model plugins. *(L4b)*
- [x] **Prompts live as inline string constants** in `nodes/ml_model_implementor/ml_model_implementor.py`,
  matching the existing convention for `IMPLEMENTOR_REASONING_PROMPT` /
  `IMPLEMENTOR_CODE_PROMPT` / `IMPLEMENTOR_REPAIR_PROMPT`. The original design
  doc proposed `agent/prompt_templates/implementor/*.md`, but the implementor
  module has no markdown-template loading infrastructure today (only
  `proposal/` and `literature_review/` have those folders); introducing one
  for L4 would add a loader without a parallel call site. The 3 inline
  constants added: *(L4a)*
  - `IMPLEMENTOR_LOSS_REASONING_PROMPT` — forward contract (`[B, 256, T]` × `[B, T]` → scalar), allowed-import allow-list, anti-patterns (no `torch.no_grad()`, no `.detach()`, scalar return required)
  - `IMPLEMENTOR_LOSS_CODE_PROMPT` — strict JSON schema (6 fields), fixed forward signature, scalar-return requirement
  - `IMPLEMENTOR_LOSS_REPAIR_PROMPT` — repeats the signature + scalar/`requires_grad` constraints so a wrong sig from attempt N doesn't survive into attempt N+1
- [x] `LOSS_PLUGIN_TEMPLATE` — fixed boilerplate with 8 named slots
  (`loss_name`, `LossClass`, `description`, `extra_imports`, `config_fields_code`,
  `config_validators_code`, `init_body`, `forward_body`). The 3 required
  PLUGIN_LOSS_* constants and the fixed forward signature are template-owned
  so the LLM cannot omit them. *(L4a)*

**Tests**:
- [x] `tests/unit/agent/ml_model_implementor/test_loss_generation_helpers.py` *(L4a — pure-Python helpers)*
  - [x] 30 tests across `_loss_class_name` × 4, `_assemble_loss_plugin` × 12, `_dummy_tensor_validate_loss` × 7, prompt constants × 5, template-placeholder × 2
- [x] `tests/unit/agent/ml_model_implementor/test_loss_generation_e2e.py` (mocked bridge — runs freely) *(L4b)*
  - [x] Registry hit → no LLM call; `loss_provenance.action == "reused"`; no file written by us this iteration
  - [x] Registry miss → mocked LLM returns valid loss code; dummy-tensor passes; file written; `CapabilityRegistry.register` called once; `loss_provenance.action == "generated"`
  - [x] First mocked LLM response fails the scalar-shape assertion → retry triggered; second response succeeds → file written
  - [x] All retries fail → `ValueError` raised with last assertion error; registry remains empty
  - [x] `custom_loss_spec=None` → `_generate_loss` not invoked; `loss_provenance` on output is `None` (regression guard)
  - [x] **Bonus**: full `run()` integration test verifying loss generated BEFORE model and `loss_provenance` threaded into `ImplementorOutput`
  - [x] **Bonus**: full `run()` integration test verifying registry-hit + model-only LLM call (loss reused, no `implementor.loss.*` labels in bridge call list)

**Test gate**: Gate 1 — Real LLM + pseudo training (see `docs/gates/gate_testing_standard.md`).
One real implementor LLM call generating a custom loss from a `CustomLossSpec`; assert generated
code compiles + passes dummy-tensor check. Needs user approval before running.

**Out of scope**: proposer awareness (L5). CLI is out of scope for this whole design doc (see Scope section).

**Implementation notes**:
- **L4a — Pure-Python groundwork (committed at `57029ea`)**:
  - `LOSS_PLUGIN_TEMPLATE` + 3 inline prompt constants + `_loss_class_name` + `_assemble_loss_plugin` + `_dummy_tensor_validate_loss`
  - Deviation from design doc: prompts live as inline string constants
    (not `agent/prompt_templates/implementor/*.md`) because the implementor
    has no markdown-template loading infra. Recorded in code.
  - `_dummy_tensor_validate_loss` uses the same `tempfile.mkdtemp` + manual
    cleanup pattern as `_smoke_test_plugin` (lint-clean, consistent style).
  - 30/30 tests pass; 142/142 pre-existing implementor tests still pass.
- **L4b — `_generate_loss` orchestration + run() integration + workflow override**:
  - Method signature: `_generate_loss(self, inp: ImplementorInput) -> LossProvenance`.
    Returns the provenance object; `run()` attaches it to the output.
  - **Registry-DI**: `MLModelImplementor.__init__` accepts
    `capability_index_path: str | None = None`. The constructor builds
    `self._registry = CapabilityRegistry(index_path=capability_index_path)`.
    Tests inject `tmp_path`-derived paths without monkey-patching.
  - **Source iteration**: derived from `inp.storage.local.run_name` when
    `storage.backend == "local"`; falls back to `None` for non-local
    backends (matches `LossProvenance.source_iteration: str | None`).
  - **Registry-hit lookup**: uses `self._registry.list(capability_type="loss")`
    + `next((m for m in ... if m.name == loss_name), None)` rather than
    `CapabilityRegistry.exists(...)`. The reason: reuse needs the actual
    metadata (file_path + source_iteration), not just a hit/miss bool;
    fetching the metadata in one pass is simpler than `exists` + a second
    fetch.
  - **Run order**: loss generated BEFORE model. A loss-generation failure
    short-circuits before any model LLM spend. The "model can reference
    the custom loss class" soft optimisation mentioned in the design doc
    is not yet exercised by any code path; if it ever is, the order is
    already correct.
  - **Workflow override**: added at `workflows/model_exploration.py:1478`,
    immediately after the `plugin_dir`/`test_dir` overrides. The per-run
    `attempt_dir` ensures concurrent iterations write to disjoint dirs;
    the sandbox executor (committed at L1b) injects this dir into
    `SIDERIUS_LOSS_DIRS` at training time so `load_loss_plugin` can find
    the freshly-written plugin.
  - **Bridge labels** (for telemetry / cost attribution):
    `implementor.loss.reasoning`, `implementor.loss.code`,
    `implementor.loss.repair`. Distinct from `implementor.reasoning` /
    `implementor.code` / `implementor.repair` for the model path.
  - **Failure semantics**: `ValueError` from `_generate_loss` propagates
    out of `run()` and aborts the implementor attempt. The workflow's
    existing `max_impl_attempts` retry loop will then re-invoke the
    implementor with a fresh proposal — the validation failure becomes
    `previous_validation_failure` on the next attempt.
  - **No registry pollution on failure**: the registry write is the last
    step of the success path. A retry-exhaustion `ValueError` raises before
    the registry call, so a failed run leaves the registry untouched
    (verified by `test_no_registry_entry_on_failure`).
- **Test results**:
  - `test_loss_generation_e2e.py`: 13/13 in 0.90 s
  - `test_loss_generation_helpers.py`: 30/30 in 0.78 s
  - Full `tests/unit/agent/ml_model_implementor/` regression: 185/185 in 1.20 s
  - Broader regression: `tests/unit/agent/` + `tests/unit/agent_generated/`
    + `tests/unit/ml_models/` + `tests/unit/core/` = **593/593 pass in 3.59 s**
  - Full `tests/unit/agent/` suite: **2419/2419 pass in 228.97 s**
  - Ruff (check + format) clean; Pyright clean (0 errors, 0 warnings)
- **Gate 1 not run yet** — the design doc specifies a single real LLM call
  validating that a generated loss from a `CustomLossSpec` compiles + passes
  dummy-tensor check. This needs the operator's go-ahead before invoking
  the bridge. Recommended command (drafted, not run):
  ```
  .venv/bin/python -m nodes.ml_model_implementor.ml_model_implementor \
      --workspace /tmp/loss_gate1_$(date +%s) \
      --run_name gate1_smoke \
      --provider openai \
      --model_id gpt-4o-mini  # (or gpt-5-mini per L4 needs)
  ```
  (a small wrapper script + minimal `CustomLossSpec` fixture would be
  added before invocation; this is a TODO for the Checkpoint L sign-off,
  not blocking L4b commit).

### Commit L5 — Proposer prompt + registry query

**Goal**: proposer becomes aware of the loss registry and emits a `custom_loss_spec` when proposing a novel loss (or chooses to reuse an existing one). Depends on L1, L3 — does NOT depend on L4 (the implementor will be ready when this lands).

**Code**:
- [x] Inject `{available_losses_block}` into the causal-reasoning + proposing stage **base** templates *(L5a)*:
  - `causal_reasoning_stage.md` — block injected in the "What you receive" section so the LLM knows which losses exist BEFORE the MANDATORY synthesis block kicks in. The mode-variant files (`_explore.md` / `_exploit.md`) inherit the rendered block via the `{# EXPLORATION_MODE_BLOCK #}` injection mechanism — no need to edit them directly. Deviation from doc bullet (which listed 6 files): only the 2 base files take `template_vars`; editing the 4 mode files would be a no-op for substitution and risk drift.
  - `proposing_stage.md` — block injected in the "What you receive" section + **Rule 9** added in "## Rules" with the 3-branch decision rule:
    * Branch A — Use a built-in loss: `loss_config.loss_type` ∈ {focal, focal_cw, ce, smooth_l1}, no `loss_name`, `custom_loss_spec: null`
    * Branch B — Reuse existing: `loss_config.loss_type="custom"`, `loss_config.loss_name=<from table>`, `custom_loss_spec: null`
    * Branch C — Generate new: `loss_config.loss_type="custom"`, fresh `loss_config.loss_name`, `custom_loss_spec` populated (must match `loss_name`)
  - Plus extended the JSON contract example: `loss_type` Literal lists all 5 values; `custom_loss_spec: null` added as a top-level field.
- [x] `agent/prompt_templates/proposal/__init__.py` — `render_available_losses(registry)` helper added. Empty registry → fallback message: "No custom losses registered yet — propose a new one grounded in lit-review findings, or use a built-in loss." Non-empty → markdown table `loss_name | source_iteration | description`, sorted by `created_at` descending (ISO-8601 string sort is chronologically correct). *(L5a)*
  - Duck-typed `registry` argument: any object with `list(capability_type=...)` returning meta-shaped items works. Lets tests pass a small stub without standing up a tmp index file.
  - Defensive normalisation: descriptions get newlines collapsed + `|` escaped so a hand-edited registry entry can't break the markdown table.
  - `None` source_iteration renders as em-dash `—` (hand-curated registry entries have no run_name).
- [x] `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py` — registry queried once per `_run_pipeline` call; rendered block threaded through `template_vars["available_losses_block"]` which `load_stage_prompt` substitutes into every stage that references the placeholder (causal_reasoning + proposing). Mode-variant files inherit the substituted base. *(L5b)*
  - `__init__` gained `capability_index_path: str | None = None` kwarg; `self._registry = CapabilityRegistry(index_path=capability_index_path)`. Mirrors L4b implementor DI pattern.
  - `_run_pipeline` imports `render_available_losses` (lazy import alongside `load_stage_prompt`, `render_agent_cards`, `render_expert_context`); `template_vars["available_losses_block"]` populated from `render_available_losses(self._registry)`.
  - Single registry snapshot per `run()`: rendered once before the stage loop so all stages see a consistent view of the registry (a concurrent implementor write during `run()` would not retroactively change earlier stages' context).
  - `_run_legacy` (pre-pipeline mode) unchanged — it doesn't use `load_stage_prompt`/`template_vars` so it doesn't need the wiring. Production callers always use pipeline mode; legacy mode is for back-compat fallback only.

**Tests** (mocked LLM — run freely):
- [x] `tests/unit/agent/ml_model_proposal_agent/test_loss_awareness.py` *(L5b)*
  - [x] **TestConstructorDI** × 3: `capability_index_path` accepted; default falls back to canonical `agent_generated/_capability_index.json`; register-then-list round-trip works on the custom-path registry
  - [x] **TestPipelineTemplateVarsWiring** × 2: pre-populated registry → `template_vars["available_losses_block"]` contains both loss names with correct sort order (most recent first); empty registry → fallback message lands in `template_vars`
  - [x] **TestThreeBranchOutputs** × 4 (regression guards for the 3-branch decision rule from L5a):
    - Branch A — built-in loss (no `loss_name`, no `custom_loss_spec`)
    - Branch B — reuse existing (`loss_type="custom"` + `loss_name`, `custom_loss_spec=None`)
    - Branch C — generate new (`custom_loss_spec` populated, `loss_name` matches)
    - Branch C mismatched names → `ValidationError` from L3's `_validate_custom_loss_spec_consistency`
- [x] `tests/unit/agent/prompt_templates/test_proposal_prompts.py` (extend) *(L5a)*
  - [x] `render_available_losses` empty-registry fallback
  - [x] `render_available_losses` single-entry table row
  - [x] `render_available_losses` multi-entry sorted most-recent first (created_at DESC)
  - [x] `render_available_losses` stable across calls (deterministic ordering)
  - [x] **Bonus**: `source_iteration=None` renders as em-dash (hand-curated entries)
  - [x] **Bonus**: pipe in description escaped to `\|` (table robustness)
  - [x] **Bonus**: newlines in description collapsed to one line (table robustness)
  - [x] `{available_losses_block}` placeholder present in `proposing_stage.md` + `causal_reasoning_stage.md`
  - [x] `load_stage_prompt` substitutes the placeholder via `template_vars` (for both stages)
  - [x] Rule 9 (3-branch decision rule) present with all 3 branches named + `MUST match` constraint
  - [x] `proposing_stage.md` lists all 5 `loss_type` values (`focal`, `focal_cw`, `ce`, `smooth_l1`, `custom`)

**Out of scope**: implementor LLM call (L4). CLI is out of scope for this whole design doc (see Scope section).

**Implementation notes**:
- **L5a — Prompt-template additions (committed at `d00bf22`)**:
  - `render_available_losses(registry)` helper in `agent/prompt_templates/proposal/__init__.py` — duck-typed registry arg; defensive table-cell rendering (pipe escape, newline collapse, em-dash for `None` source_iteration); sort by `created_at` descending (ISO-8601 strings sort chronologically).
  - `{available_losses_block}` placeholder added to the 2 base templates (`causal_reasoning_stage.md`, `proposing_stage.md`). Mode-variant files (`_explore.md` / `_exploit.md`) inherit via `{# EXPLORATION_MODE_BLOCK #}` — no separate edits needed.
  - `proposing_stage.md` extended: JSON schema example now lists 5 `loss_type` values + `custom_loss_spec: null`; Rule 9 added with the 3-branch (A/B/C) decision rule.
  - 14 new tests pass; 56/56 in the prompt-template suite.
- **L5b — Proposer node integration**:
  - `MLModelProposalAgent.__init__` gains `capability_index_path: str | None = None` kwarg → `self._registry = CapabilityRegistry(index_path=capability_index_path)`. Symmetric with the L4b implementor DI pattern.
  - `_run_pipeline`'s lazy-import block (line 1090) gains `render_available_losses`; the `template_vars` dict (line 1219 area) gains `"available_losses_block": render_available_losses(self._registry)`.
  - **One registry snapshot per `run()`**: the rendering happens once before the stage loop. A concurrent implementor write during the proposer's `run()` would NOT retroactively change earlier stages' context. This matches the intuition that a single proposal is built against a single registry snapshot.
  - **Lazy import** keeps the import-time cost off non-pipeline callers (legacy mode never imports `render_available_losses`).
  - **Legacy mode unchanged**: `_run_legacy` doesn't use `load_stage_prompt`/`template_vars`. Production callers always use pipeline mode; legacy mode is back-compat only and not used by any current workflow.
  - **Tests strategy**: rather than driving full `_run_pipeline` end-to-end (which would require building a substantial `ProposalInput` fixture and mocking the bridge), the wiring tests patch `load_stage_prompt` to capture the `template_vars` dict at the seam and assert. This isolates the L5b change cleanly and is fast (0.87 s for 9 tests).
- **Test results**:
  - `test_loss_awareness.py`: 9/9 (3 + 2 + 4) in 0.87 s
  - `test_proposal_prompts.py` (L5a): 56/56 still pass
  - `tests/unit/agent/ml_model_proposal_agent/`: 471/471 pass (462 pre-existing + 9 new)
  - **Broader regression sweep**: `agent/ml_model_proposal_agent/` + `agent/prompt_templates/` + `agent/ml_model_implementor/` + `agent_generated/` + `agent/schemas/` = **943/943 pass in 1.57 s**
  - Ruff + pyright clean
- **Gate 1 not run** — still recommended at Checkpoint L (alongside Gate 2) to amortise the real-LLM cost. A focused Gate 1 for L5 would verify the proposer LLM, given a registry with 2-3 entries, correctly picks one of the 3 branches when proposing.

### Checkpoint L — Behavioral validation

**Goal**: end-to-end real-LLM evidence that the L1–L5 implementation works in the closed loop. Both gates require real LLM calls and Gate 2 requires real training — **requires user approval before running** (per development principle 3).

---

#### Gate 1 — Real LLM + pseudo training

**Purpose**: prove the implementor can generate a syntactically and semantically valid loss plugin from a hand-crafted `CustomLossSpec`, *before* spending Gate 2's training budget.

**Command**:
```bash
.venv/bin/python scripts/checkpoint_l_gate1.py \
    --llm_config llm_configs/openai_tiered_v1.json \
    --workspace /tmp/checkpoint_l_gate1_$(date +%s)
```

The script constructs a `CustomLossSpec` for the **`expected_value_mse`** loss — a fully-differentiable ordinal-aware loss for [0, 256) ADC-bin classification (softmax-weighted expected bin index, squared distance to target, mean over [B, T]). Chosen for Gate 1 because it has no `argmax` / `.detach()` pitfalls, so the dummy-tensor check should pass on the first attempt with high probability.

The script then calls `MLModelImplementor._generate_loss(inp)` with the spec and asserts:
1. LLM completes without raising
2. Generated source compiles + `_dummy_tensor_validate_loss` returns `None` — scalar + finite forward output, **plus `loss.backward()` runs cleanly and produces a finite `inputs.grad` (Fix B, commit `5f6c918`)**. The backward()-based check catches `.detach()` bugs that the older `requires_grad`-only check would have missed.
3. `LossProvenance.action == "generated"` and `dummy_tensor_validated is True`
4. File written to `inp.loss_dir` and registered in the run-scoped `_capability_index.json`

**Estimated wall time**: ~2–5 min (1 reasoning + 1 code call; possibly 1 repair call if the first attempt fails).
**Estimated cost**: ~$0.05–0.20 (gpt-5.4 dominant).

**Pass criteria**:
- [x] Script exits 0 — verified 3× on 2026-06-22 (`expected_value_mse`, `ordinal_ce`, `emd_ordinal`)
- [x] Generated loss file at `{workspace}/losses/expected_value_mse.py` exists and parses — verified for all 3 variants
- [x] `{workspace}/_capability_index.json` contains the new entry with `capability_type="loss"`, `dummy_tensor_validated=True` — verified for all 3 variants (`source_iteration=gate1`, ISO timestamps captured)
- [ ] Generated source visually inspected and pasted into `docs/checkpoint_l_sign_off.md`

---

#### Gate 2 — Real LLM + real training (full chain)

**Purpose**: prove the closed loop — proposer reads the registry, picks Branch C (generate new), emits a `CustomLossSpec`; implementor generates the loss + model; training routes through the custom loss; the next iteration's proposer sees the registered loss in `{available_losses_block}`.

**Canonical command** (from `docs/gates/gate_testing_standard.md`, extended with the loss-advice file):
```bash
bash sdsc_submission_scripts/run_chain.sh \
    --mode lilab \
    --workspace /tmp/checkpoint_l_$(date +%s) \
    --run_name checkpoint_l_smoke \
    --num_iterations 2 \
    --max_rounds 2 \
    --max_proposal_attempts 3 \
    --max_epochs 1 \
    --trial_portion 0.02 \
    --train_portion 0.02 \
    --eval_portion 0.02 \
    --trial_time_budget_minutes 5 \
    --no-force_formal_round \
    --formal_time_budget_minutes 20 \
    --trial_vram_budget_gb 10 \
    --formal_vram_budget_gb 10 \
    --llm_config llm_configs/openai_tiered_v1.json \
    --advice advice/workflow/checkpoint_l_loss_advice.json \
    --seed_paths \
        /home/klz/Data/SIDEREIS_DATA/wavenet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json \
        /home/klz/Data/SIDEREIS_DATA/punet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json
```

**Critical parameters** (lesson learned, do NOT omit — see `gate_testing_standard.md` Gate 2 section):
- `--trial_portion 0.02` — keeps each training epoch under 5 min
- `--trial_time_budget_minutes 5` — engages the time-risk gate
- `--no-force_formal_round` — without it the chain's last round defaults to full-dataset formal training (2+ hours); all rounds should stay in trial mode for smoke tests (codified after the 2026-06-22 first Gate 3 run took 2h 02m in iter_002 round 2)
- `--formal_time_budget_minutes 20` — safety net if `--no-force_formal_round` is omitted or silently regressed
- `--trial_vram_budget_gb 10 --formal_vram_budget_gb 10` — keeps each chain under 10 GB so two chains can run in parallel on the 32 GB RTX 5090 (Gate 2 + Gate 3 launched concurrently in detached `screen` sessions; 20 GB total + ~12 GB OS/driver headroom)
- `--llm_config openai_tiered_v1.json` — gpt-4o-mini cannot reliably generate proposals that pass the validator
- `--advice advice/workflow/checkpoint_l_loss_advice.json` — directs the proposer toward Branch C with `expected_value_mse` as the primary recommendation

**Estimated wall time**: ~30–60 min (2 iters × 2 rounds × up to 3 proposal attempts × up to 5 min per training run).
**Estimated cost**: ~$1.50–2.50 (gpt-5.4 dominant role).

**Pass criteria**:
- [ ] Chain exits 0
- [ ] `run_output_*.json` written per iteration with non-null finite `denoising_score`
- [ ] At least one iteration's `implementor_*.json` has `loss_provenance.action == "generated"` (Branch C exercised)
- [ ] `agent_generated/_capability_index.json` (or the workspace-scoped index if `capability_index_path` is overridden) contains the new loss entry with `capability_type="loss"` after iter_001
- [ ] `agent_generated/losses/{loss_name}.py` (or workspace equivalent) exists and was loaded by the training subprocess (verify via `SIDERIUS_LOSS_DIRS` env in the per-attempt log)
- [ ] **Iter_002 proposer saw the iter_001 loss in `{available_losses_block}`** — verify by either:
  - **(Method A — preferred)** Inspect `{workspace}/iter002_attempt*/debug/iter002_attempt001_proposing_system_prompt.md` (when `--debug_dump_prompts` is on) and grep for the iter_001 `loss_name`. The block renders as a markdown table row; presence confirms registry visibility.
  - **(Method B — fallback when debug dumps are off)** Compare `proposer_<run_name>.json` token_usage `system_prompt_chars` between iter_001 (empty registry → fallback message ~150 chars) and iter_002 (1 loss → table row ~250–400 chars). A delta of ~200–400 chars in the system prompt is the expected fingerprint of the rendered `{available_losses_block}`.

**Failure handling** (see `docs/gates/gate_testing_standard.md` Gate 2 sub-section for the general checklist). Loss-specific additions:
- If `_generate_loss` raises `ValueError` after 2 retries → check the validator error message in the chain log; this is an LLM-quality issue, not an implementation bug. Confirm `--llm_config openai_tiered_v1.json` is used (not `certify_minimal.json`).
- If iter_002 proposer ignores the registered loss → check that `{available_losses_block}` rendered non-empty in the iter_002 system prompt; if empty, check that `MLModelProposalAgent` was constructed without an iteration-scoped `capability_index_path` (workflow currently uses the canonical default — verified in the L5b audit).

---

#### Gate 3 — Real LLM + real training + literature review (full closed loop)

**Purpose**: validate that lit-review findings actually shape the proposer's `CustomLossSpec`. Specifically: does the proposer ground its loss description / mathematical definition / loss_name in a finding cited from the literature, or are findings decorative? This is the loss-inventory-specific instance of the lit-review feature's Checkpoint D (see `docs/commit_plan_ml_literature_review.md` § Checkpoint D), narrowed to the loss-generation surface.

**Prerequisites** (do NOT skip):
1. Gate 2 has already passed and been signed off — Gate 3 is an *extension*, not a substitute.
2. §10 validation suite has a recent green entry in `docs/validation_suite_runs.md`. If any lit-review prompt / `ConfidenceRubric` / `transfer_tolerance` default has changed since the most recent §10 FULL sign-off, re-run §10 first.
3. Lit-review Commit 6 has landed (already true on master since `82bbf94`).

**Canonical command** (Gate 2 + lit-review enabled):
```bash
bash sdsc_submission_scripts/run_chain.sh \
    --mode lilab \
    --workspace /tmp/checkpoint_l_gate3_$(date +%s) \
    --run_name checkpoint_l_gate3 \
    --num_iterations 2 \
    --max_rounds 2 \
    --max_proposal_attempts 3 \
    --max_epochs 1 \
    --trial_portion 0.02 \
    --train_portion 0.02 \
    --eval_portion 0.02 \
    --trial_time_budget_minutes 5 \
    --no-force_formal_round \
    --formal_time_budget_minutes 20 \
    --trial_vram_budget_gb 10 \
    --formal_vram_budget_gb 10 \
    --llm_config llm_configs/openai_tiered_v1.json \
    --advice advice/workflow/checkpoint_l_loss_advice.json \
    --ml_lit_review_enabled \
    --seed_paths \
        /home/klz/Data/SIDEREIS_DATA/wavenet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json \
        /home/klz/Data/SIDEREIS_DATA/punet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json
```

The only diff vs Gate 2 is `--ml_lit_review_enabled`. The lit-review YAML controls root-paper loading, dynamic-search behavior, and synthesis prompts; `--ml_lit_review_config` defaults to `configs/lit_review_config.yaml` inside `run_one_iteration.py` (since `d96a6e5`, `--ml_lit_review_config` is no longer forwarded by the bash wrapper — operators wanting a non-default lit-review YAML must edit the default file or invoke `run_one_iteration.py` directly). The LLM routing for lit-review (`main` + `search` sub-bridges) is taken from the `llm_config`'s `lit_review` block — `openai_tiered_v1.json` ships with `deepseek-v4-pro` for both, isolating lit-review cost from the proposer/implementor/interpreter tier.

Note on time-risk gates (lessons codified in `docs/gates/gate_testing_standard.md` after the 2026-06-22 first Gate 3 run hit `force_formal_round=True` default and iter_002 round 2 ran for 2h 02m):
- `--no-force_formal_round`: mandatory; without it the last round goes to full-dataset formal training and the chain takes 2+ hours instead of ~35–70 min.
- `--formal_time_budget_minutes 20`: safety net in case `--no-force_formal_round` is accidentally omitted by a future caller or a regression silently re-enables formal forcing.
- `--trial_vram_budget_gb 10 --formal_vram_budget_gb 10`: pairs with VRAM-aware scoring; 20 GB max headroom on the 32 GB RTX 5090 leaves room for the OS + a second concurrent chain if needed.

**Estimated wall time**: Gate 2 (~30–60 min) + lit-review overhead (~2–5 min per iter × 2 = ~4–10 min) = **~35–70 min total**.
**Estimated cost**: Gate 2 (~$1.50–2.50) + lit-review (~$0.50–2 per iter × 2 iters ≈ $1–4) = **~$2.50–6.50 total**. Lit-review uses DeepSeek by default — cheaper than the OpenAI proposer tier.

**Pass criteria** (all 6 Gate 2 criteria + 5 new lit-review-specific):

Gate 2 criteria (unchanged — re-verify):
- [ ] Chain exits 0
- [ ] `run_output_*.json` per iter with non-null finite `denoising_score`
- [ ] At least one iter's `implementor_*.json` has `loss_provenance.action == "generated"`
- [ ] `agent_generated/_capability_index.json` (or workspace-scoped index) contains the iter_001 loss entry after iter_001
- [ ] `agent_generated/losses/{loss_name}.py` exists and was loaded by training
- [ ] Iter_002 proposer saw the iter_001 loss in `{available_losses_block}`

Lit-review-specific criteria (new):
- [ ] `{workspace}/iter_001/iteration_001/ml_literature_review_iter_001.json` exists with **non-empty `findings`** (at least 1 `ExpertContextItem`)
- [ ] Per iter, the proposer's *user* prompt (debug dump or reconstructed) contains a `## External Contributors` block with at least one `AgentCard` whose `Trust Level: soft_prior` matches the lit-review emission
- [ ] **Iter_001's `ProposalOutput.custom_loss_spec.description` OR `mathematical_definition` cites a real `source_ref` value that appears verbatim in the iter's lit-review `findings[*].source_ref`** — i.e. literature influence is *traceable*, not just present
- [ ] **No hallucinated `source_ref`s**: every `source_ref` string in the proposal's `motivation`, `custom_loss_spec.description`, or `custom_loss_spec.mathematical_definition` must match some real lit-review-emitted `source_ref`. Implemented via a Python audit script (no LLM):
      ```python
      proposed_refs = re.findall(r"source_ref=([^\s,)]+)", proposal_text)
      real_refs = {f.source_ref for f in lit_review_output.findings}
      hallucinated = set(proposed_refs) - real_refs
      assert not hallucinated, f"Hallucinated source_refs: {hallucinated}"
      ```
- [ ] Iter_002's loss-related decision (Branch B reuse / Branch C new) is *not contradicted* by iter_002's lit-review findings — e.g. if iter_002's lit-review surfaces a paper that explicitly evaluates against the iter_001 loss type, iter_002 should either reuse (Branch B) or refine (Branch C) rather than ignore. Subjective — verified by human review.

**Failure handling** (Gate 2 cases unchanged + lit-review additions):
- If lit-review finds nothing relevant → corpus/search-decision LLM problem, not a loss-inventory bug. Inspect `ml_literature_review_iter_001.json` `search_decisions` to see what queries fired. Consider amending `configs/lit_review_config.yaml` `root_papers` to seed loss-relevant papers (TIDMAD itself, focal-loss Lin et al. 2017, EMD/Wasserstein loss papers).
- If lit-review runs but proposal ignores the findings → the proposer's user-prompt rendering or the lit-review compression prompt is at fault. Re-run Checkpoint P audit on the captured iter_001 proposer prompt to verify the `## External Contributors` + `## Expert Context` blocks rendered correctly.
- If proposal hallucinates `source_ref`s → tighten the proposer's `causal_reasoning_stage.md` MANDATORY synthesis section to forbid citing source_refs not in the provided context.

#### Post-Gate-3 audit (human review — answers two open concerns)

Run after Gate 3 passes. Zero LLM cost — pure artifact reading. Results recorded in `docs/checkpoint_l_gate3_sign_off.md`.

**Concern 1 audit — proposer reasoning transparency**

Read `iter_001/iteration_001/proposal_iter_001.json`:
- [ ] Does `motivation` or the causal_reasoning output contain any `source_ref` string that appears verbatim in `ml_literature_review_iter_001.json → findings[*].source_ref`?
- [ ] If yes: quote the source_ref + the finding's content snippet + the proposal text that references it. Is the connection substantive (proposer adapted the finding's mechanism) or decorative (proposer mentioned the source_ref but the loss design is identical to what it would have proposed without lit-review)?
- [ ] If no source_refs appear anywhere in the proposal: state this explicitly — proposer ignored expert_context entirely. This is the strongest motivation for a facilitator layer that pre-digests findings into a single actionable directive before the proposer sees them.

Verdict options:
  - ✅ SUBSTANTIVE: proposer's CustomLossSpec.mathematical_definition or description directly adapts a mechanism from a cited finding
  - ⚠️ DECORATIVE: source_refs appear but loss design is unchanged from what the advice file alone would have produced
  - ❌ IGNORED: no source_refs appear; lit-review had no visible effect

**Concern 2 audit — findings volume vs single-proposal constraint**

Read `ml_literature_review_iter_001.json → findings`:
- [ ] How many ExpertContextItems were emitted?
- [ ] Do the findings point in the same direction (e.g. all suggest ordinal-aware losses) or in conflicting directions (e.g. one suggests EMD loss, another suggests SNR-weighted loss)?
- [ ] Which finding (if any) is most closely reflected in iter_001's `custom_loss_spec`? Quote the finding content + the spec text side by side.
- [ ] Were any findings completely ignored? If so, were they lower-confidence (< 0.60) or conflicting with higher-confidence findings?
- [ ] Did iter_002 reuse the iter_001 loss (Branch B) or propose a different loss (Branch C)? If Branch C, did the new loss reflect a finding that iter_001 ignored?

Verdict options:
  - ✅ COHERENT: proposer made a clear selection among findings; the selection is traceable to confidence scores or bottleneck relevance
  - ⚠️ ARBITRARY: proposer selected one finding but the selection logic is not visible in the output
  - ❌ OVERLOADED: proposer appeared to ignore all findings despite them being present in the prompt (see Concern 1 audit)

**Facilitator layer decision gate**

Based on both audits, record one of:
- FACILITATOR NOT NEEDED: Concern 1 = SUBSTANTIVE and Concern 2 = COHERENT → lit-review findings are being used well; no architectural change needed now
- FACILITATOR RECOMMENDED: any ⚠️ verdict → findings are present but underutilized; a facilitator layer would improve quality but is not blocking
- FACILITATOR REQUIRED: any ❌ verdict → proposer is ignoring findings; lit-review adds cost with no benefit until a facilitator layer pre-digests findings into actionable directives

#### Sign-off artifact for Gate 3

- [ ] `docs/checkpoint_l_gate3_sign_off.md` written after the run passes, with:
  - [ ] Gate 2 criteria pass/fail table (re-asserted for the Gate 3 run)
  - [ ] Lit-review summary per iter: emitted `AgentCard`, top 3 `findings` (source_ref + content snippet)
  - [ ] Full `iter_001.proposal.custom_loss_spec.{description, mathematical_definition}` text
  - [ ] Full `iter_002.proposal.custom_loss_spec.{description, mathematical_definition}` text (or note Branch B reuse with the iter_001 loss_name)
  - [ ] Cross-reference table: each `source_ref` cited by the proposal → does it match a lit-review-emitted finding? (yes/no)
  - [ ] Hallucination-check Python script output (zero hallucinations required)
  - [ ] Concern 1 + Concern 2 audit verdicts (from the Post-Gate-3 audit subsection above)
  - [ ] Facilitator layer decision gate verdict
  - [ ] Human judgment paragraph: "Did the literature actually shape the loss design? Cite specific examples." Either:
        ✅ "Yes — iter_001's `mathematical_definition` adapts equation (3) from `arxiv:1812.01187` verbatim …" OR
        ❌ "No — iter_001's `mathematical_definition` is identical in substance to the `expected_value_mse` example from the advice file; lit-review findings appear only as decorative `source_ref` mentions in `motivation`."
  - [ ] Decision: ready to merge / blocked on X / facilitator layer needed before merge

#### Why three gates instead of two

Gate 1 isolates the implementor's loss-generation path (one LLM call, no chain machinery). Gate 2 validates the closed loop without external findings (single-feature integration). Gate 3 layers in lit-review without changing the loss-inventory contract — a clean separation lets you tell *which* feature broke if Gate 3 fails despite Gate 2 passing. Each gate's failure mode is diagnostically distinct.

---

#### Sign-off artifact

- [ ] `docs/checkpoint_l_sign_off.md` written after Gate 2 passes, with:
  - [ ] Gate 1 wall-time + token cost (from the script's output)
  - [ ] Gate 2 wall-time + token cost (from the chain manifest)
  - [ ] Excerpt of the iter_001-generated loss source (first 30 lines)
  - [ ] Excerpt of the iter_002 proposer prompt's `{available_losses_block}` rendering — proof the registry was visible
  - [ ] Either: iter_002 picked Branch B (reuse) — desired ✓, OR iter_002 picked Branch C again with a different `loss_name` — acceptable, both prove the loop works
  - [ ] Final `denoising_score` per iteration
  - [ ] Decision: ready to merge / blocked on X

---

**Implementation notes**:

- **Gate 1 — three variants PASSED (2026-06-22)**. See in-conversation report; sign-off doc TBD at full Checkpoint L close.
- **Gate 2 first attempt killed by harness tmpfs exhaustion, not chain failure (2026-06-22)**. The chain itself was healthy (workspace 4.2 MB at end, cleanup_denoised working); the harness's task-output buffer overflowed from verbose chain stdout streaming. **Root cause is unrelated to the loss-inventory feature.**
- **Tmpfs leak fix (2026-06-22, commit `a13778a`) — `_generate_loss`-adjacent but actually in the TUNER**: post-mortem of the Gate 2 failure surfaced a real Q3-class HDF5 leak in `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py`. The denoised-HDF5 cleanup block (formerly at line ~2099) was in the success path of the per-attempt loop, AFTER the inference + scoring blocks but BEFORE their `continue` statements in the error handlers. When inference returned an error or scoring raised an exception, the existing handlers `continue`d the loop and skipped cleanup, leaving ~80 GB (formal) / ~1.6 GB (trial) of denoised HDF5 files per failed attempt. Fix: wrapped the inference + scoring + result-extraction block in `try:` and moved the cleanup into a paired `finally:`. Now fires on success, on `continue` from either error handler, AND on any uncaught exception. Glob remains keyed to `exp_id` so attempts don't clobber each other. 504/504 existing tuner unit tests pass unchanged.
- **No-tee mandate added to canonical Gate testing standard (2026-06-22, commit `b7fb000`)**: `tee` to a `/tmp` file duplicates the chain's stdout into a long-lived log file that accumulates over the run and can exhaust the harness's task-output tmpfs (~50 min of verbose HDF5-saved/scoring lines was enough to overflow). Future gates rely on the harness capture only; never `tee`.
- **Gate 2 + Gate 3 re-launched in parallel via detached `screen` sessions (2026-06-22)**:
  - Gate 2 → screen `checkpoint_l_gate2`, workspace `/tmp/checkpoint_l_1782174048`
  - Gate 3 → screen `checkpoint_l_gate3`, workspace `/tmp/checkpoint_l_gate3_1782174060`
  - `--trial_vram_budget_gb 10 --formal_vram_budget_gb 10` on both (20 GB total + ~12 GB headroom on the 32 GB RTX 5090; per operator experience this combination is safe for two concurrent chains)
  - Detached screens survive harness disconnects and terminal closes — verification runs against the workspace JSON artifacts when both chains exit. Monitor via `screen -r checkpoint_l_gate2` / `screen -r checkpoint_l_gate3`.
- _Sign-off docs (`docs/checkpoint_l_sign_off.md` and `docs/checkpoint_l_gate3_sign_off.md`) pending Gate 2 + Gate 3 completion._

### Issues discovered during Checkpoint L execution (2026-06-22/23)

The following issues were found during Gate 1/2/3 execution and fixed before
the final Gate 2/3 re-run. Each issue is recorded with root cause, fix, and
commit SHA for traceability.

#### I1 — Harness tmpfs exhaustion from `tee` (Gate 2 first attempt)
**Root cause**: `tee /tmp/checkpoint_l_gate2.log` wrote a duplicate of the
chain's verbose stdout to `/tmp`. Two parallel chains filled the harness
task-output tmpfs in ~50 min.
**Fix**: Removed `tee` from all gate commands. Harness capture file is
sufficient. Added to `gate_testing_standard.md` as a mandatory rule.
**Commit**: `b7fb000`

#### I2 — HDF5 cleanup not in `try/finally` (leak on inference OOM)
**Root cause**: `cleanup_denoised` block was in normal control flow after
scoring. On inference OOM or scoring crash, ~80 GB (formal) / ~1.6 GB (trial)
of denoised HDF5 files were leaked per failed attempt.
**Fix**: Wrapped inference + scoring + result-extraction in `try:` and moved
cleanup into a paired `finally:`. Fires on success, on `continue` from error
handlers, and on uncaught exceptions.
**Commit**: `a13778a`

#### I3 — Formal round had no time budget (Gate 3 first run iter_002 took 2h 02m)
**Root cause**: `force_formal_round=True` by default forces the last round to
use the full training dataset. `--trial_time_budget_minutes 5` only caps trial
rounds. No `--formal_time_budget_minutes` was set. Result: iter_002 round 2
ran for 2 hours instead of the expected ~5 min.
**Fix**: Added `--no-force_formal_round` and `--formal_time_budget_minutes 20`
to the bash wrapper (`_chain_common.sh`) and to the canonical Gate 2/3
commands in `gate_testing_standard.md` and this design doc.
**Commits**: `2c9e375` (`--no-force_formal_round` wrapper), `a59cd45`
(`--formal_time_budget_minutes` as mandatory in gate standard)

#### I4 — `--ml_lit_review_enabled` not forwarded by bash wrapper
**Root cause**: Same bash-wrapper gap pattern as I3. The flag existed in
`run_one_iteration.py` (added in lit-review Commit 6) but `_chain_common.sh`
never forwarded it. Gate 3's lit-review was silently disabled because the
wrapper rejected the unknown flag.
**Fix**: Added `--ml_lit_review_enabled` and `--no-ml_lit_review_enabled` to
`_chain_common.sh` arg parser with default `=0` (matching the YAML default
after I5). Forwards to `run_one_iteration.py` only when `=1`.
**Commit**: `d96a6e5`

#### I5 — `lit_review_config.yaml` default `enabled: true` silently activated lit-review for Gate 2
**Root cause**: The default `enabled: true` in `configs/lit_review_config.yaml`
silently activated lit-review for any chain that did not explicitly disable
it. Gate 2 was intended as a no-lit-review baseline, so this defeated the
"isolate the loss-inventory feature" purpose.
**Fix**: Changed default to `enabled: false`. Operators must explicitly
opt-in via `--ml_lit_review_enabled` (the wrapper flag from I4) or by editing
the YAML.
**Commit**: `7f29351`

#### I6 — Rule 9 in proposer prompt did not forbid Branch B with empty registry (phantom Branch B, prompt side)
**Root cause**: The proposer's `proposing_stage.md` Rule 9 described Branch B
(reuse a registered custom loss) as a legal choice but did not state that it
is illegal when the registry is empty. Combined with strong advice-file
direction toward `loss_name="expected_value_mse"`, every proposer attempt in
the first Gate 3 run emitted `loss_type="custom" + loss_name="expected_value_mse"
+ custom_loss_spec=None` — a phantom Branch B referencing a loss the registry
did not contain.
**Fix**: Added `⚠ BRANCH B CONSTRAINT` block to `proposing_stage.md`
immediately after the Branch B description, stating that Branch B is FORBIDDEN
when `{available_losses_block}` shows "No custom losses registered yet".
**Commit**: `ac35b07`

#### I7 — Implementor did not validate Branch B `loss_name` exists in registry (phantom Branch B, runtime side)
**Root cause**: When `custom_loss_spec=None`, the implementor silently skipped
loss generation. The downstream tuner planner then rewrote `loss_type="custom"`
to `loss_type="ce"` (the silent rewrite was a SEPARATE bug, surfaced later
during the Bug A audit — see I9). Training proceeded under cross-entropy with
a valid-looking `denoising_score`, producing a false-positive PASS. Branch B
happy path also never recorded `loss_provenance` (hidden defect).
**Fix**: Implementor `run()` now raises `ValueError` if `loss_type="custom"`
and `loss_name` is not in the registry. Also records
`LossProvenance(action="reused")` on the happy path so downstream consumers
have a credit-assignment trail.
**Commit**: `ac35b07`

#### I8 — Proposer agent silently dropped `custom_loss_spec` from LLM raw output (the L3 regression)
**Root cause**: When L3 (`a2ea559`) added the `CustomLossSpec` schema to
`ProposalOutput`, neither of the two `ProposalOutput.model_validate(...)` call
sites in `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py` was
updated to extract `custom_loss_spec` from the LLM `raw` dict. Result: even
when the LLM correctly emitted a fully populated `custom_loss_spec` object,
the agent code dropped it before validation. Every Branch C intent became a
phantom Branch B at runtime. This was the root cause of the
"12/12 attempts emit phantom Branch B" pattern observed in the Gate 2/3 re-run.
**Fix**: Three-layer defense — (a) add
`"custom_loss_spec": raw.get("custom_loss_spec")` to both `model_validate`
dicts in the proposer agent; (b) add a `model_validator` to `ProposalOutput`
that uses `info.context` to reject phantom Branch B at schema-validation time
when the caller provides `loss_registry_names`; (c) clarify
`proposing_stage.md` with an explicit "Loss field shapes" table and a
"⚠ SHAPE-CRITICAL" annotation on the JSON skeleton's `"custom_loss_spec": null`
line.
**Commit**: `a421192`

#### I9 — Tuner planner had no registry awareness (Bug A from the Gate 2/3 re-run audit)
**Root cause**: `PLANNER_PROMPT` in `agent/prompts.py` hardcoded
`{ce, focal, focal_cw, smooth_l1}` as the only valid loss types via the four
`loss_note` branches in `get_planner_user_prompt`. The LLM had no knowledge
that `loss_type="custom"` was legal or that any custom losses existed. Result
verified by post-Gate audit: 0/6 saved `loss_config_*.json` files used
`loss_type="custom"` across both Gate 2 and Gate 3 in the first successful
re-run. The custom loss plugin was generated, validated, and registered but
never trained on — the proof-of-loop never closed.
**Fix (L6b)**: Added `{available_losses_block}` placeholder to
`PLANNER_PROMPT` (mirrors L5a for the proposer). Threaded
`CapabilityRegistry` through `LLMBridge.plan` and
`get_planner_user_prompt`. Appended a custom-loss callout to each of the
four `loss_note` branches when the registry has entries. Tuner constructor
now takes `capability_index_path`. When the registry is empty, the prompt is
byte-identical to pre-L6b — preserves all snapshot tests.
**Commit**: `cb5222b`

#### I10 — `_register_plugin` did not propagate the loss plugin file (Bug B from the Gate 2/3 re-run audit)
**Root cause**: `_register_plugin` in `workflows/model_exploration.py` copied
the model file + description but not the loss plugin file. The implementor
wrote the loss to `{attempt_dir}/losses/{loss_name}.py` and no subsequent
code copied it anywhere. The sandbox set
`SIDERIUS_LOSS_DIRS = get_loss_dir(tuning_dir, run_name) = {tuning_dir}/losses/{run_name}/`
— a directory the workflow never populated. Per `_loss_loader.py`, the env
var is exclusive when set (no fallback to the global default), so the
training subprocess could never load any custom loss. This bug was hidden
behind I9 (planner never picked custom) until the first Gate 3 iter_001
forced custom via the BASELINE REFERENCE RULE and all 9 attempts failed
pre-training (`aborted_fail_rounds`).
**Fix (L6a)**: Extended `_register_plugin` with a `dest_loss_dirs` kwarg.
When `loss_provenance.action == "generated"`, copies
`loss_provenance.loss_file_path` to each dest as `{dest}/{loss_name}.py`.
Call site at the workflow now passes BOTH `get_loss_dir(tuning_dir, run_name)`
(so the sandbox finds it) AND `get_loss_dir(workspace, run_name)` (so
resume / cross-iter Branch B reuse finds it). Mirror of the existing
dual-dest model-plugin pattern. `action="reused"` is a no-op since the
chain-canonical copy from the originating iter is expected to persist.
**Commit**: `6837020`

#### I11 — Advice config did not handle concurrent-run registry pollution (Finding 1 from the Gate 2/3 re-run audit)
**Root cause**: Gate 2 and Gate 3 share the global
`agent_generated/_capability_index.json`. In a parallel launch, Gate 2's
iter_001 registers `expected_value_mse` first. Gate 3's iter_001 implementor
then sees the loss already in the registry → `action="reused"` →
`loss_file_path` points to Gate 2's workspace. Gate 3 ends up trained on
a Gate-2-generated plugin, defeating Gate 3's purpose of validating that
lit-review findings shape the loss design.

Registry sharing itself is a deliberate feature ("don't reinvent the wheel"
across the long-running chain), so the fix is scoped to the gate-testing
context only.

**Fix**: Added `LIT-REVIEW-DRIVEN MODE` block to
`advice/workflow/checkpoint_l_loss_advice.json` that activates only when the
proposer-side `## External Contributors` block contains lit-review findings
(Gate 3 only). The block forbids Branch B reuse of `expected_value_mse` from
the registry and requires iter_001 to emit Branch C with a fresh `loss_name`
grounded in a finding's mechanism, citing a `source_ref` verbatim in
`custom_loss_spec.description`. Gate 2 behavior is byte-identical to before
the advice update.
**Commit**: `84a3caf`

#### I13 — `evaluate_time_skill` and `train_engine_sandbox` routed `loss_type="custom"` targets to `.float()` (EMD dtype crash in v15)

**Root cause**: `evaluate_time_skill/wrapper.py` and `execute_tools/train_engine_sandbox.py`
hardcoded `("ce", "focal", "focal_cw")` as the classifier loss types that receive int64
targets. `loss_type="custom"` fell into the `.float()` branch (regressor path), causing
`F.one_hot()` to crash with `RuntimeError: one_hot is only applicable to index tensor of
type LongTensor` in any custom loss that uses integer class indices.

Same registry-asymmetry pattern as I9/I12 — a consumer of `LossConfig` was not updated
when `loss_type="custom"` was added. Discovered in v15 iter_001 when the proposer
generated an EMD-family loss using `F.one_hot(targets, num_classes=256)`.

**Why list-extension is the wrong fix**: not all custom losses are classifiers. A future
regressor-style custom loss (smooth_l1-shaped) would need `.float()`. The dtype contract
belongs with the plugin, not with a hardcoded consumer list.

**Fix**: Each loss plugin declares `PLUGIN_LOSS_TARGET_DTYPE = "long" | "float"` at module
scope (mirrors `PLUGIN_OUTPUT_TYPE` on model plugins). The loader registers it in
`LOSS_TARGET_DTYPE_REGISTRY`. A new `get_target_torch_dtype(loss_config) -> torch.dtype`
helper in `loss_models_sandbox.py` is the single source of truth for all consumers. Both
affected call sites replaced with the helper call. Stub template and implementor prompt
updated to require the declaration in all future generated plugins.
**Commits**: (to be filled after commit)

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

### Future: MLLossImplementor split (out of scope)

The implementor currently handles two artifact types (model code + loss code).
A future refactor could split this into MLModelImplementor + MLLossImplementor
with a dedicated protocol edge and symmetric MLLossValidatorAgent. Deferred —
the current dual-role design is architecturally complete and the split requires
a new design doc.
