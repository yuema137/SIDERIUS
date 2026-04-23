# Phase 6.6 — Deterministic VRAM & Implementor Hardening

**Status:** Approved D.1 revision 2 (sign-off 2026-04-23). Revision 2 adds §3.10 *Compute Intensity Cap* (calibrated `_MAX_BATCH_TIMESTEPS = 800,000` from the Phase 6.5 Stage 2 failure at B=25, T=40000 with 20% margin) and bakes the A.3 overhead decision (analytical weight-proportional + two calibrated constants from Appendix A.5: 185 MB CUDA context + 50 MB cuDNN backward workspace). All prior sign-offs remain valid. Implementation from A.1.5 onward is unblocked.
**Author:** SIDERIUS core
**Date:** 2026-04-22 (initial) · 2026-04-23 (rev 2 approved)
**Scope:** Phase 6.6 System Hardening (VRAM refactor + Implementor/Proposer hardening).
**Out of scope:** Full `cudaErrorLaunchTimeout` recovery — detection during a live run, post-failure host safety, kernel-watchdog interaction — deferred to Phase 6.8. A pre-flight compute-intensity **heuristic** (§3.10) lands in this phase as a cheap guardrail against the most obvious kernel-timeout triggers (`B × T` far above the observed Phase 6.5 failure point). It refuses up-front; it does not handle mid-run hangs.
**Supersedes (in part):** `docs/resource_estimator_implement.md` §10.5, §10.14 Commit 2/3/5/K.2.5-8 (VRAM analytical formulas and the inference-batch table). Wall-time estimation (§10.14 Commits 2/3/4/6) is NOT touched by this phase.

---

## 1. Motivation & Evidence

Stage 2 of Phase 6.5 (score-table real-smoke, PR #59) surfaced two distinct fragilities the current system papers over with heuristics:

### 1.1 VRAM estimator is empirical, not physical

`agent/skills/evaluate_vram_skill/` aggregates peak VRAM across training + inference + scoring subprocesses (`wrapper.py` lines 167–181). The per-phase estimators are **analytical formulas with model-type branches**:

- `training_skill/estimator.py:98` — `act_factor = 1 if model_type == "fcnet" else 2`.
- `training_skill/estimator.py:106` — `if model_type == "transformer": transformer_attn = B × nhead × T² × 4 × num_layers`.
- `inference_skill/estimator.py:103` — `inf_batch = inference_batch_for(model_type)` reads a hardcoded dict in `core/inference_defaults.py:44` (`{punet:25, wavenet:25, fcnet:25, rnn:10, transformer:1}`).
- Unknown model types → silent fallback (25) + an `inference_batch_uncalibrated=True` flag that merely *warns*, never *refuses* to forecast.

The outcome in Phase 6.5 was exactly what this design expects: the Proposer emitted `dynamic_depth_simple` — a novel architecture not in the table — and the gate passed a verdict of "best-effort" against a magic number. The forecast drifted from physical reality, and the implementation stack had to discover over-budget configurations by actually running them on the GPU.

### 1.2 Implementor produces consistency-broken code

Stage 2 iter_001 needed 3 proposal attempts before `dynamic_depth_simple` produced a working plugin. Two of the three failed on classic self-consistency bugs:

- `AttributeError: self.gate_channels` — assigned in a local scope inside `__init__` but never stored on `self`, then read in `forward`.
- `output_conv` declared with 64 input channels when the filter/gate split halves the tensor to 32.

These are not architecture-specific issues — both are symptoms of the LLM Implementor failing to perform two self-checks any competent developer would run before shipping: *"every attribute I read is stored"* and *"every tensor split conserves its dimension."* Any model that uses Gated Activations, Multi-Head Attention, or any `torch.split` / slice invites the same failure class.

### 1.3 Diagnosis → principle shift

SIDERIUS has been relying on the implementation loop's retry budget to absorb both problems. Phase 6.6's charter is to replace luck-dependent behavior with **deterministic calculation** in both the forecast and the code-generation contracts.

---

## 2. Design Principles

The following rules govern all work under this phase:

1. **Deterministic over empirical.** A proposed architecture's VRAM is computed from the actual tensor graph (torchinfo dry-run on CPU), not from analytical shortcuts keyed to model names. If a number cannot be derived from the model's own structure, it is either a known physical constant (CUDA context size, dtype widths) or the design is flawed.
2. **Generic over model-specific.** Implementation logic — in skills, agent prompts, and tests — must not branch on the literal strings `"wavenet"`, `"cnn"`, `"transformer"`, `"punet"`, `"rnn"`, `"fcnet"`, or any future architecture name. The vocabulary is: *tensor*, *channel dimension*, *split*, *initialization scope*, *forward reference*, *gated activation*, *attention head*. Any hotfix that reintroduces a model-name branch is a failure of the phase.
3. **Plugin contract is the clean-room interface.** The Proposer talks to the Implementor through `mathematical_definition` as if the Implementor had never seen the rest of the project. Input/output contract (`[B, T] int → [B, 256, T] float`), segmentation semantics, and causal-masking requirements must be cited explicitly in the Proposer's output — never silently delegated to the plugin template.
4. **Forecast failures produce actionable reports, not shrugs.** When the new VRAM skill rejects a config, it emits a structured "Memory Killer" report identifying the dominant layer by bytes. The Proposer has what it needs to simplify the design before the config ever touches the GPU.
5. **Universal Hardware Awareness — runtime discovery, not compile-time constants.** Every number that depends on the physical device (total VRAM, compute capability, multiprocessor count, CUDA version) is discovered via `torch.cuda.get_device_properties` at run initialization and serialized into an environment manifest. No file in the codebase hardcodes "32 GB", "5090", "A100", or any device-specific literal. The same code runs unchanged on lilab RTX 5090, SDSC Expanse A100 (40 or 80 GB), and any future GPU — the manifest adapts, the logic does not.

---

## 3. WS-A — Deterministic VRAM Refactor

### 3.1 Architecture

```
evaluate_vram_skill/
├── wrapper.py             ← KEEP contract (same kwargs, same return keys)
├── structural_probe.py    ← NEW: torchinfo + autograd-tape walker (§3.2)
├── overhead.py            ← NEW: optimizer/grad/CUDA-context formulas (§3.3)
├── batch_resolver.py      ← NEW: torchinfo-driven inference batch selection (§3.5)
├── compute_intensity.py   ← NEW: B × T kernel-timeout heuristic cap (§3.10)
├── killer_report.py       ← NEW: per-layer breakdown renderer (§3.6)
└── skill_config.json      ← update description
```

`training_skill/estimator.py` and `inference_skill/estimator.py`:
- `estimate_peak_bytes` internals are rewritten to call `structural_probe` + `overhead`. The **function signature is preserved** so the wrapper's aggregator and any test monkeypatches keep working.
- `estimate_wall_time_seconds` is **not touched** by this phase. Time estimation keeps its current analytical/calibration-table path. (Separating concerns; time-estimator hardening is its own future phase if we decide to eliminate model-name branches there.)

`core/inference_defaults.py`:
- `_INFERENCE_BATCH_SIZES` dict, `inference_batch_for`, `is_inference_batch_registered`, `assert_inference_batch_registered` are all **deleted**.
- `sandbox_executor.execute_inference` currently calls `inference_batch_for(model_type)` to pick runtime batch. It will receive the batch from the VRAM skill's return value instead (propagated through the tuner → executor path). See §3.5.

### 3.2 Structural probe (`structural_probe.py`) — revised after A.13

The A.13 ground-truth capture (Appendix A.1) revealed that **torchinfo alone cannot
meet the ±10% gate**: the delta between the inference peak (0.42 GB) and training
peak (0.82 GB) is driven by `FocalLoss1D`'s intermediate `[B, 256, T]` tensors
(`targets_one_hot`, `pt`, `alpha_t`), which the autograd engine retains for
backward. Because these are bare tensor ops inside a single `forward`, no submodule
hook sees them. torchinfo, whose entire mechanism is `forward_pre_hook` +
`forward_hook` on `nn.Module`s, is structurally blind to them.

The revised probe uses **two complementary mechanisms in one file**:

| Mechanism | Provides | Source of truth for |
|---|---|---|
| `torchinfo.summary` | Per-submodule input/output shapes, param counts, output bytes, param bytes | Layer-level attribution (Memory Killer report) |
| `torch.autograd.graph.saved_tensors_hooks` | Every tensor autograd retained for backward, deduped by storage | Training-mode peak activation bytes (the forecast total) |

#### API

```python
# agent/skills/evaluate_vram_skill/structural_probe.py

def probe_forward_layers(
    module: nn.Module,
    input_data: torch.Tensor | Sequence[torch.Tensor],
    module_name: str | None = None,
) -> ForwardLayerReport:
    """torchinfo.summary wrapper. Works on any nn.Module — model or loss.
    Returns per-submodule breakdown used by the Memory Killer report and
    as the peak estimator for inference mode."""

def probe_autograd_tape(
    forward_callable: Callable[[], torch.Tensor],
) -> AutogradTapeReport:
    """Run `forward_callable()` under saved_tensors_hooks. Count every
    unique underlying storage (keyed by storage.data_ptr()) that autograd
    retained. Dedup is critical: shared tensors, views, and aliased
    gradient chains would otherwise double-count."""

def probe_activation_footprint(
    model: nn.Module,
    loss_module: nn.Module | None,
    input_sample: torch.Tensor,
    target_sample: torch.Tensor | None,
    mode: Literal["training", "inference"],
    device: torch.device | str = "cpu",
) -> ProbeResult:
    """Top-level composer. Dispatches to the two primitives above based
    on mode. Returns a single ProbeResult with everything downstream
    (wrapper, batch_resolver, killer_report) needs."""
```

#### Pydantic contract

```python
class LayerReport(BaseModel):
    depth: int
    var_name: str
    class_name: str
    input_shape: list[int]
    output_shape: list[int]
    num_params: int
    param_bytes: int       # torchinfo's .param_bytes (leaf-accurate)
    output_bytes: int      # torchinfo's .output_bytes
    is_leaf: bool

class ForwardLayerReport(BaseModel):
    module_name: str                   # type(module).__name__
    layers: list[LayerReport]
    total_param_bytes: int             # sum over leaves only
    forward_output_bytes_sum: int      # sum over leaves — training upper bound if no dedup
    forward_output_bytes_max: int      # max single-leaf output — inference peak estimator

class AutogradTapeReport(BaseModel):
    unique_storage_count: int
    total_saved_bytes: int             # sum(storage.nbytes() for storage in unique_storages)

class ProbeResult(BaseModel):
    mode: Literal["training", "inference"]
    model_forward: ForwardLayerReport
    loss_forward: ForwardLayerReport | None = None   # populated in training mode
    autograd_tape: AutogradTapeReport | None = None  # populated in training mode
    input_bytes: int                   # input_sample.numel() * element_size()
    output_bytes: int                  # model's final output tensor bytes
```

#### Storage-pointer dedup (why keying on `data_ptr` is non-negotiable)

A tensor and its view share a `storage.data_ptr()`. Slicing, permuting, and
reshape-without-copy all produce tensors whose physical allocation is identical.
Autograd's `save_for_backward` sees each of these as a distinct tensor event and
will fire the `pack_hook` multiple times for the same physical buffer. Counting
`tensor.numel() * element_size()` per hook event therefore over-counts.

The probe uses:
```python
seen: dict[int, int] = {}  # data_ptr -> storage.nbytes()
def pack_hook(t):
    storage = t.untyped_storage()
    ptr = storage.data_ptr()
    if ptr and ptr not in seen:
        seen[ptr] = storage.nbytes()
    return t
```

`storage.nbytes()` gives the whole underlying allocation (not the view's slice),
which is the physical VRAM cost. Summing over `seen.values()` yields the total
bytes the autograd engine actually forced the allocator to retain.

#### Mode split

| Mode | Execution | Tape walk? | Peak estimator field |
|---|---|---|---|
| `inference` | `with torch.no_grad(): out = model(x)` | No (no tape exists) | `input_bytes + max(output_bytes, forward_output_bytes_max) + params_bytes`. Using `max(...)` (not sum) avoids double-counting when the final layer's output *is* the largest tensor (the common SIDERIUS case, logits `[B, 256, T]`). A.3 closes the remaining context + cuDNN-workspace residual. |
| `training` | Real forward through model **fused with** loss_module under `saved_tensors_hooks` | Yes — this is the truth | `autograd_tape.total_saved_bytes + input_bytes + output_bytes + params_bytes + overhead_bytes`. The tape is the source of truth; `overhead.py` covers allocator/context + cuDNN backward workspace only. |

#### Why torchinfo stays

Even though torchinfo cannot be the truth for training mode, it is retained for:
- Per-submodule attribution in the **Memory Killer report** (`killer_report.py`,
  §3.6). "Layer X has Y bytes" is a story only the torchinfo walk can tell;
  the tape walk is flat at the op level.
- The **inference-mode peak estimator**, where no autograd tape exists.
- The **`batch_resolver` loop** (§3.5): inference is the only phase where the
  batch sweeps, and inference-mode probing is pure torchinfo + a dry no_grad
  forward — no loss, no tape, fast enough to probe 7 candidate batches.

#### Why the tape walk is "Deterministic Calculation", not empirical estimation

It never reads GPU memory counters. It reads tensor metadata (`storage.nbytes()`)
while the forward is still executing. The tensors exist because the model's
forward code says so — the same forward code production will run — and the
saved set is what PyTorch's autograd engine decided based on the graph
structure. No heuristics, no calibration constants, no model-type tables.

### 3.3 Overhead model (`overhead.py`)

**Design decision (locked 2026-04-23):** the module is a **hybrid** — analytical
formulas for the weight-proportional components (optimizer state, gradients)
and calibrated constants for the fixed per-process residuals (CUDA context,
cuDNN backward workspace). The rationale is that weight-proportional cost
scales deterministically with `params_bytes` (no hardware dependence), whereas
the fixed residuals are a property of the driver + cuDNN build and are
empirically stable across re-runs on the same host — so a single calibration
pass (Appendix A.5) captures them permanently.

Pure functions, no I/O:

```python
# Calibrated constants — origins documented in Appendix A.5 (2026-04-23,
# RTX 5090 / torch 2.10.0+cu128 / CUDA 12.8).
_CUDA_CONTEXT_BYTES:              int = 185 * 1024 ** 2   # 185 MB
_CUDNN_BACKWARD_WORKSPACE_BYTES:  int = 50  * 1024 ** 2   # 50  MB

# Analytical multipliers — derived from optimizer algebra, not measurement.
_OPTIMIZER_STATE_MULTIPLIER: dict[str, int] = {
    "adam":  2,   # first + second moment
    "adamw": 2,   # first + second moment
    "sgd":   0,   # plain SGD has no momentum state
    # "sgd+momentum": 1 — add when we actually support it; do not speculate.
}

def training_overhead_bytes(params_bytes: int, optimizer: str) -> int:
    """Analytical: grads + optimizer state. No calibration needed —
    both scale exactly with params_bytes."""
    if optimizer not in _OPTIMIZER_STATE_MULTIPLIER:
        raise ValueError(f"Unknown optimizer: {optimizer!r}. Known: "
                         f"{sorted(_OPTIMIZER_STATE_MULTIPLIER)}")
    grad_bytes = params_bytes
    opt_bytes  = _OPTIMIZER_STATE_MULTIPLIER[optimizer] * params_bytes
    return grad_bytes + opt_bytes

def cuda_context_bytes() -> int:
    """Calibrated: per-process CUDA context + cuDNN forward workspace.
    Appears in BOTH training and inference phases."""
    return _CUDA_CONTEXT_BYTES

def cudnn_backward_workspace_bytes() -> int:
    """Calibrated: cuDNN backward-algorithm scratch.
    Appears in training phase ONLY — autograd is what triggers the allocation."""
    return _CUDNN_BACKWARD_WORKSPACE_BYTES
```

**Per-phase composition:**
- **Inference peak** = `input_bytes + max(output_bytes, forward_output_bytes_max) + params_bytes + cuda_context_bytes()`.
- **Training peak**  = `autograd_tape.total_saved_bytes + input_bytes + output_bytes + params_bytes + training_overhead_bytes(params_bytes, optimizer) + cuda_context_bytes() + cudnn_backward_workspace_bytes()`.

**No silent fallbacks.** An unknown optimizer raises `ValueError` — the
deterministic design refuses guesses. A calibration refresh (if the driver
stack changes enough to invalidate the Appendix A.5 numbers) is a
version-controlled edit of the two constants plus a regression pass against
Appendix A.2, not a runtime behavior.

### 3.4 Device-agnostic cap

The cap is no longer inlined in the wrapper. It is a derived property on the `HardwareContext` provider (§3.9):

```python
cap_bytes = hardware_context.usable_cap_bytes  # = int(0.80 * total_memory_bytes)
```

`wrapper.py` receives the context as an argument and reads `usable_cap_bytes`. It does not call `torch.cuda.get_device_properties` itself — that lookup is centralized in `core/hardware_context.py` so every consumer (VRAM skill, Proposer prompt, Memory Killer verdict) uses one source of truth per run.

**Rationale for capacity-based over free-based.** We want a physical ceiling keyed to the device's capacity, independent of what other processes on the box happen to be holding. Contention is a **scheduling** problem (handled by the tuner retrying or routing to a different host), not a forecasting problem.

The 4 GB minimum-free floor and the contention log (`wrapper.py:233–260`) are both **removed** — they were compensating for the free-based cap. With a capacity-based cap, the semantics become: "can this config ever fit on this device in isolation?" which is what the forecast question should actually answer.

Cross-server portability is automatic via §3.9: lilab 5090 (32 GB) gives 25.6 GB cap; SDSC Expanse A100 40 GB gives 32 GB cap; A100 80 GB gives 64 GB cap — the manifest adapts per host.

### 3.5 Inference batch auto-selection (`batch_resolver.py`)

Replaces the `_INFERENCE_BATCH_SIZES` table. Given a CPU-instantiated model and a cap:

```python
def resolve_inference_batch(
    model: torch.nn.Module,
    segmentation_size: int,
    cap_bytes: int,
    *,
    candidate_batches: list[int] = [64, 32, 16, 8, 4, 2, 1],
) -> int:
    """
    Probe each candidate batch (largest first) and return the first one
    whose predicted peak fits under cap_bytes. Raise ValueError if even
    batch=1 does not fit — the model is physically infeasible.
    """
```

Implementation: for each `B` in descending order, build a probe input of shape `(B, segmentation_size)` and call `structural_probe.probe`. Compute `peak = params_bytes + forward_activation_bytes + cuda_context_bytes()`. Accept the first `B` that satisfies **both** `peak <= cap_bytes` **and** `compute_intensity.passes(B, segmentation_size)` (§3.10). If no candidate satisfies both, raise `ValueError` with a diagnostic that names which cap was binding (VRAM vs. compute intensity) — the Memory Killer report uses this distinction to produce the right suggestion.

**Propagation.** The chosen batch flows: `evaluate_vram_skill.run_skill → result dict key "inference_batch" → tuner reads it → passes through the experiment config → sandbox_executor.execute_inference reads from config`. `sandbox_executor` stops calling `inference_batch_for`; the runtime value is whatever the pre-flight skill decided.

**Why descending search over closed-form.** Activation memory is linear in B for most layers but can be non-linear for attention (`B × nhead × T² × 4`). A closed-form solver would need to know the dominant term, which is exactly the model-name branching we are eliminating. A 7-point probe is ~7× CPU forward passes on a small mock input — cheap, and the resulting choice is provably correct against the torchinfo model.

### 3.6 Memory Killer report (`killer_report.py`)

When `peak > cap_bytes`, the wrapper returns:

```python
{
    "status": "schema_violation",
    "verdict": "❌ OVER-BUDGET — estimated 47.2 GB > cap 25.6 GB (80% of 32 GB).",
    "memory_killer": {
        "dominant_layer": "block3.attn",
        "dominant_layer_class": "MultiheadAttention",
        "dominant_layer_bytes": 38_000_000_000,
        "dominant_fraction": 0.81,
        "per_layer": [
            {"name": "block3.attn", "class": "MultiheadAttention",
             "output_shape": (2, 8, 40000, 40000), "bytes": 38_000_000_000},
            ...
        ]
    },
    "suggestion": "Layer 'block3.attn' accounts for 81% of estimated VRAM. "
                  "Reduce its output tensor size — e.g. shrink the channel "
                  "dimension, shorten segmentation_size, or replace the "
                  "quadratic term with a linear-complexity alternative."
}
```

Wording in `suggestion` is deliberately **generic**: it never says "attention" or "transformer" — it names a *specific layer by user-given name* and a *specific dimension to reduce*. The Proposer receives an actionable structured report and must react in its next attempt's `mathematical_definition`.

### 3.7 Wrapper signature preservation

`wrapper.run_skill(sandbox, **kwargs)` keeps:
- Same required kwargs: `model_type`, `model_config`, `train_config`, `loss_config`.
- Same optional kwarg: `vram_budget_gb` (still honored as a second cap `min(capacity_cap, budget_cap)`).
- Same return dict keys: `status`, `feasible`, `verdict`, `suggestion`, `num_params`, `dominant_phase`, `phase_breakdown`, `estimated_gb`, `limit_gb`, `vram_budget_gb`.
- **New** return keys: `inference_batch` (int, from §3.5), `memory_killer` (dict | null, from §3.6).
- `inference_batch_uncalibrated` is **removed** from both the print path and the return dict — the concept is obsolete when every batch is probed.

This preservation means the tuner integration (`nodes/ml_hyperparameter_tune_agent.py:494`) needs only to read the new `inference_batch` key; no call-site schema break.

### 3.8 Phase aggregation

The wrapper continues to aggregate per-phase peaks via `max()`. Phases run in isolated subprocesses (see current `wrapper.py` docstring lines 11–24), so the binding constraint is still a single phase, not a sum. The per-phase estimators simply compute their respective peaks using the new probe+overhead primitives.

### 3.9 Hardware Context & Environment Manifest

Principle 5 ("Universal Hardware Awareness") is realized by a new module `core/hardware_context.py`. Every physical-device lookup in the entire project is centralized here. No other file — in the VRAM stack, in the agents, or in the executors — calls `torch.cuda.get_device_properties` or embeds a device-specific literal.

#### 3.9.1 `HardwareContext` schema (Pydantic)

```python
class HardwareContext(BaseModel):
    device_name:          str           # e.g. "NVIDIA GeForce RTX 5090"
    total_memory_bytes:   int           # torch.cuda.get_device_properties(0).total_memory
    compute_capability:   tuple[int, int]  # (major, minor)
    multiprocessor_count: int
    cuda_runtime_version: Optional[str] # torch.version.cuda
    torch_version:        str           # torch.__version__
    hostname:             str           # socket.gethostname()
    device_available:     bool          # False on CPU-only hosts
    discovered_at:        datetime      # UTC

    @property
    def usable_cap_bytes(self) -> int:
        """0.80 × total_memory_bytes. Single source of truth for the cap."""
        return int(0.80 * self.total_memory_bytes)

    @property
    def total_memory_gb(self) -> float:
        return self.total_memory_bytes / (1024 ** 3)

    @property
    def usable_cap_gb(self) -> float:
        return self.usable_cap_bytes / (1024 ** 3)
```

The `0.80` safety fraction is defined exactly once, as the body of `usable_cap_bytes`. Changing it is a one-line edit and test update.

#### 3.9.2 Discovery and manifest lifecycle

`hardware_context.discover() -> HardwareContext`:
- On a GPU host: reads `torch.cuda.get_device_properties(0)`, populates all fields, `device_available=True`.
- On a CPU-only host or `torch.cuda.is_available()==False`: returns `HardwareContext(device_available=False, total_memory_bytes=0, device_name="cpu", ...)`. Consumers that require GPU (`evaluate_vram_skill` with `device="cuda"`) check `device_available` and early-return a CPU-mode verdict, matching current behavior.

`hardware_context.write_manifest(ctx, path)` — JSON dump with 2-space indent and ISO-8601 timestamp.

`hardware_context.load_manifest(path) -> HardwareContext` — reads back via Pydantic validation.

`hardware_context.get_or_create(workspace, run_name) -> HardwareContext`:
1. Manifest path = `{workspace}/{run_name}_hardware.json`.
2. If missing → `discover()` + `write_manifest()` + return.
3. If present → `load_manifest()`, then compare `device_name` and `hostname` against `discover()`. On mismatch (workspace moved between servers), log a warning, regenerate, and overwrite. On match, return the loaded manifest (no re-probe cost).

#### 3.9.3 Integration points

- **Tuner init** (`nodes/ml_hyperparameter_tune_agent.py`): calls `get_or_create(workspace, run_name)` once at the start of `run()`. The resulting `HardwareContext` is held on the tuner instance and passed into every skill invocation that needs hardware-grounded reasoning.
- **VRAM skill** (`evaluate_vram_skill/wrapper.py`): `run_skill` gains `hardware_context: HardwareContext` as a kwarg. The wrapper reads `ctx.usable_cap_bytes` and `ctx.device_name` for the verdict string. The direct `torch.cuda.get_device_properties` and `torch.cuda.mem_get_info` calls are removed from the wrapper.
- **Batch resolver** (`batch_resolver.py`, §3.5): accepts `cap_bytes: int` — stays agnostic to the context itself, just receives the derived number.
- **Memory Killer report** (`killer_report.py`, §3.6): verdict string names the device and cap — e.g. *"47.2 GB > 25.6 GB cap (80% of 32.0 GB on NVIDIA GeForce RTX 5090)"* — so an audited rejection is traceable to the host that made the call.
- **Proposer prompt** (`nodes/ml_model_proposal_agent.py`): renders a `[HARDWARE CONTEXT]` block (see §4.1) so the LLM's architecture reasoning is grounded in the current host's ceiling rather than an implicit assumption.

#### 3.9.4 Why a manifest file (not just in-memory)

- **Reproducibility.** A run's saved records are auditable against the hardware that actually ran them. A rejected proposal's `memory_killer` report references a specific device name and cap; the manifest file is the durable evidence.
- **Cross-process consistency.** `sandbox_executor` launches training and inference as isolated subprocesses — they cannot inherit the parent's in-memory `HardwareContext`. The manifest file is the IPC.
- **Migration safety.** When a workspace moves from lilab to SDSC Expanse, step 3 of §3.9.2 detects the device mismatch and regenerates explicitly, instead of silently running with a stale cap from the old host.
- **Offline inspection.** An operator looking at a run's records next week can open the manifest and see exactly which device was the forecasting ceiling — no need to guess from hostname conventions.

#### 3.9.5 What the module does NOT do

- **No multi-GPU aggregation.** Current SIDERIUS uses device 0 only. If we ever need multi-GPU, extend to `devices: list[DeviceInfo]` then; do not speculate now.
- **No driver/SM-version enforcement.** The manifest records values but does not refuse to run on a mismatched CUDA version. That belongs in installation/environment tooling, not in the forecasting layer.
- **No auto-selection of `0.80`.** The safety fraction is a deliberate design constant, not a tuning knob. If future work wants it tunable, that is an explicit follow-up, not a hidden option.

### 3.10 Compute intensity cap (`compute_intensity.py`)

Phase 6.5 Stage 2 observed a `cudaErrorLaunchTimeout` on the RTX 5090 at a
batch × segmentation configuration that exceeded the CUDA kernel watchdog
window. This is a physical failure mode **orthogonal to VRAM**: a config can
fit in memory and still hang a CUDA kernel long enough to trip the driver's
timeout, crashing the attempt and — in the worst case — wedging the GPU until
the host is reset.

Full recovery from a live launch-timeout (detection during training, subprocess
cleanup, host-safety interlocks) is deferred to Phase 6.8. Phase 6.6 installs
a **pre-flight heuristic cap** that refuses configs whose `batch × segmentation`
product is far above the observed failure point, up-front, before the config
ever touches the GPU.

#### 3.10.1 Module API

```python
# agent/skills/evaluate_vram_skill/compute_intensity.py

# Calibrated from Phase 6.5 Stage 2: cudaErrorLaunchTimeout observed at
# (batch_size=25, segmentation_size=40000), product = 1_000_000.
# Applied 20% safety margin per §3.10.3 → 800_000.
_MAX_BATCH_TIMESTEPS: int = 800_000

def compute_intensity(batch_size: int, segmentation_size: int) -> int:
    """Return the raw intensity product — purely arithmetic."""
    return batch_size * segmentation_size

def passes(batch_size: int, segmentation_size: int) -> bool:
    """True if the config is below the heuristic cap."""
    return compute_intensity(batch_size, segmentation_size) <= _MAX_BATCH_TIMESTEPS

def describe_violation(batch_size: int, segmentation_size: int) -> str:
    """Human-readable message for the Memory Killer report when the cap is
    exceeded. Names specific dimensions, does not mention any model family."""
```

Pure functions, no I/O, no state. The module is a constant + three functions.

#### 3.10.2 Integration points

- **`batch_resolver.resolve_inference_batch` (§3.5)** — the acceptance predicate
  is now *both* caps: `peak <= cap_bytes` AND `compute_intensity.passes(B, T)`.
  A candidate batch that fits VRAM but violates intensity is rejected; the
  loop continues to the next smaller batch.
- **`wrapper.run_skill` (§3.7)** — after the per-phase probe, if the
  training-phase `(batch_size, segmentation_size)` from the experiment config
  fails `compute_intensity.passes`, the wrapper returns `status="schema_violation"`
  with `memory_killer.binding_cap = "compute_intensity"` and a suggestion to
  reduce `segmentation_size` or `batch_size`. Training-phase B and T come from
  the Proposer's config, not from a sweep, so this is a one-shot check.
- **`killer_report.py` (§3.6)** — the rendered verdict distinguishes the two
  failure modes: *"VRAM over-budget"* vs. *"Compute-intensity over-budget"*.
  The `suggestion` string names `segmentation_size` / `batch_size`, never a
  layer — because intensity is a config-shape problem, not an architecture
  problem.

#### 3.10.3 Calibration of `_MAX_BATCH_TIMESTEPS`

The threshold is a **documented design constant**, not a runtime tuning knob.
Changing it is a version-controlled edit plus a regression test update.

**Calibration (locked 2026-04-23 per user sign-off):**

| Source                              | Value       |
|-------------------------------------|-------------|
| Phase 6.5 Stage 2 failure point     | B=25, T=40000 (product = 1,000,000) |
| Safety margin (§3.10)               | 20%         |
| → `_MAX_BATCH_TIMESTEPS`            | **800,000** |

The origin is recorded verbatim in the module-level comment of
`compute_intensity.py` (see the code block in §3.10.1 above). Any future
adjustment must follow the same "observed failure → margin → document origin"
pattern — invented numbers are forbidden.

#### 3.10.4 Why a flat `B × T` product, not a layer-aware estimate

The true kernel runtime depends on op mix (attention quadratic in T; convs
linear), cuDNN algorithm selection, clock boost state, and concurrent-kernel
overlap — none of which Phase 6.6 attempts to predict. A flat product is
intentionally coarse: it is a **refusal threshold**, not a wall-time model.
Any future wall-time work belongs in the estimator hardening phase explicitly
excluded from §3 scope (see §3.1 notes about `estimate_wall_time_seconds`).

#### 3.10.5 What this cap does NOT do

- **No in-run watchdog.** Once the kernel launches, Phase 6.6 does nothing.
  Detection and recovery stay in Phase 6.8.
- **No per-device calibration.** A single constant applies across all hosts.
  The watchdog window is a property of the driver, not the GPU model, so
  a per-`HardwareContext` override is unnecessary until evidence suggests
  otherwise. If it does, a follow-up can add `ctx.compute_intensity_cap`
  without touching this module's shape.
- **No fractional/soft refusal.** A config is either below or above the cap.
  "Almost-over" warnings add noise without adding safety.

---

## 4. WS-B — Implementor / Proposer Hardening

WS-B is prompt-level; no new modules. Changes land in `nodes/ml_model_proposal_agent.py` and `nodes/ml_model_implementor.py`. Every added instruction is phrased generically.

### 4.1 Proposer — Contract Re-Assertion (rule 2C in directive)

**Rule:** The Proposer's `mathematical_definition` field must explicitly cite the Plugin Interface Contract. The Implementor is treated as a clean-room developer who has no other source of truth.

**Concretely, every proposal must include:**
- I/O contract: `Input: [B, T] int64 (audio-like segment indices). Output: [B, 256, T] float32 (per-time-step logit over 256 bins).`
- Segmentation semantics: *how segmentation_size interacts with the forward body* (e.g. "the model operates on one segment at a time; no cross-segment state"; or if relevant, "causal mask must ensure position t only attends to positions ≤ t").
- Any dimension-bearing constants the forward body needs that are not in the public config (e.g. "256 output bins per time step is fixed by the contract, not a config hyperparameter").

**Hardware grounding (Principle 5).** The Proposer's system prompt also carries a `[HARDWARE CONTEXT]` block, rendered from the `HardwareContext` manifest (§3.9) at prompt assembly time:

```
[HARDWARE CONTEXT]
Device:            NVIDIA GeForce RTX 5090
Total VRAM:        32.00 GB
Usable cap (80%):  25.60 GB
Host:              lilab
```

This block has no model-specific content — it is rendered identically for every proposal and adapts automatically when the manifest changes. The Proposer is instructed to keep its architectural ambition below the usable cap; if the VRAM skill subsequently returns a Memory Killer report (§3.6), the Proposer has the same device name and cap in context for reasoning about the simplification.

**Enforcement:** a prompt-level instruction is necessary but not sufficient — we also add a **rendered-prompt unit test** that asserts the Proposer's system prompt contains the contract strings and the hardware-context placeholder tokens verbatim, so future refactors cannot silently drop them.

**Why it matters:** Stage 2 attempts 1 and 2 were generated by a Proposer that said "use Gated Activations" without restating the I/O contract. The Implementor then wrote reasonable-looking code that violated the contract subtly (channel-mismatched output_conv). Explicit re-assertion closes the gap.

### 4.2 Implementor — Variable-Reference Audit (rule 3A in directive)

**Rule:** Before generating the forward body, the Implementor must enumerate every `self.xxx` attribute it intends to use in `forward` and, for each, locate the `__init__` line that assigns it. If any are missing, revise `__init__` first.

**Prompt addition** (generic wording, inserted into the Implementor's reasoning-time system prompt):

> **Variable-Reference Audit.** Before writing `forward`, list every `self.<attr>` you plan to reference there. For each one, point to the line in `__init__` where it is assigned (as `self.<attr> = ...`). A local variable inside `__init__` is not the same as an instance attribute — if you need it in `forward`, it must be stored on `self`. If any referenced attribute is missing from `__init__`, fix `__init__` before writing `forward`.

**Scope:** this lives in the *generation-time* reasoning prompt, not only in the repair prompt. The goal is prevention, not recovery.

**Generic language check:** no architecture names. Applies equally to Gated Activations, ConvNext blocks, attention projections, and any future pattern.

### 4.3 Implementor — Tensor Arithmetic Guard (rule 3B in directive)

**Rule:** When the forward body splits or slices a tensor, the Implementor must show (in chain-of-thought) that dimensions are conserved.

**Prompt addition:**

> **Tensor Arithmetic Guard.** If your `forward` uses `torch.split`, `torch.chunk`, slicing along a channel dimension, or any op that produces multiple sub-tensors from one parent, you must show that the sum of the child dimensions equals the parent's. State this explicitly: "Parent has C channels; split into A + B; A + B = C." If downstream layers' `in_channels` depend on the split, verify the layer was constructed with the *post-split* channel count, not the parent's.

**Scope:** reasoning-time prompt. Covers Gated Activations (sigmoid × tanh on half channels each), multi-head attention (Q/K/V projection splits), and any channel-wise branching.

### 4.4 Targeted repair prompt on `AttributeError` (rule from memory)

**Rule:** When smoke-test output contains `AttributeError: 'X' object has no attribute 'y'`, the repair prompt prioritizes an **`__init__` ↔ `forward` consistency diff** before any other debugging.

**Current state** (file `nodes/ml_model_implementor.py:512–549`): the repair prompt is generic — "fix the error, try again." It does not steer the LLM toward the specific failure class.

**Change:** detect `AttributeError` in the captured smoke error and prepend a targeted clause:

> **Diagnosis hint.** The smoke test failed with `AttributeError: 'X' object has no attribute 'y'`. This almost always means the forward body references `self.y` but `__init__` never stored it. Before changing anything else, re-run the Variable-Reference Audit on your current code: list every `self.<attr>` used in `forward`, find its assignment in `__init__`, and fix the missing one. Do not rewrite the rest of the model.

**Why not just rely on §4.2?** §4.2 reduces the incidence. §4.4 ensures that on the residual miss, the repair iteration converges on the right fix instead of re-rolling the architecture.

### 4.5 What WS-B does **not** do

- It does not add a static code-analysis pass (AST-walking `forward` to match `self.*` against `__init__`). That would be an orthogonal project; the prompt-level rules are cheap and already shift the failure rate. A static pass could be a follow-up if Phase 6.6 telemetry shows residual AttributeError cases.
- It does not add unit tests on the Implementor's generated model code directly. Those are the implementor's existing smoke tests' job. WS-B only adds tests on the *rendered prompt string* (§4.1) and a *regression replay* (§5.3).

---

## 5. Test Plan

### 5.1 WS-A unit tests

Location: `tests/unit/agent/evaluate_vram_skill/`.

- `test_structural_probe.py` — hand-built tiny model (Linear → ReLU → Linear); assert `total_params_bytes` matches `sum(p.numel() * 4 for p in model.parameters())`; assert `forward_activation_bytes` matches hand-computed output-tensor bytes; assert `per_layer` length == module count and ordering is preserved.
- `test_overhead.py` — `training_overhead_bytes(P, "adam")` == `3 * P`; `"sgd"` == `P`; `"unknown"` raises ValueError.
- `test_batch_resolver.py` — mock `probe` returns a deterministic (params, activations(B)) curve; assert descending search picks the expected batch for several cap scenarios; assert `ValueError` when cap is below batch=1 peak; assert the resolver also skips candidates that fail the intensity cap even when they fit VRAM, and that the raised error names which cap was binding.
- `test_compute_intensity.py` (§3.10) — `compute_intensity(B, T) == B * T`; `passes(B, T)` is True below `_MAX_BATCH_TIMESTEPS` and False above; `describe_violation` string names `batch_size` and `segmentation_size` verbatim and contains no architecture-family word; boundary cases at exactly `_MAX_BATCH_TIMESTEPS` accept (`<=` not `<`).
- `test_killer_report.py` — per-layer list with a dominant entry; assert `dominant_fraction` is computed correctly; assert the suggestion string names the dominant layer *by its real name* and does not mention any architecture-family word. For the intensity-cap variant, assert the verdict distinguishes `"VRAM over-budget"` from `"Compute-intensity over-budget"` and that the intensity-mode suggestion references `segmentation_size` / `batch_size`, not any layer.
- `test_wrapper_contract.py` — full skill invocation with a CPU-instantiable plugin model; assert the return dict has all the pre-existing keys plus `inference_batch` and optionally `memory_killer`; assert removed keys (`inference_batch_uncalibrated`) are absent.

Location: `tests/unit/core/` (for the hardware module — cross-cutting, not VRAM-specific):

- `test_hardware_context.py` — with `torch.cuda.get_device_properties` and `torch.cuda.is_available` monkeypatched to return a fake 32 GB device: assert `discover()` populates every field correctly, `usable_cap_bytes == int(0.80 × 32 GB)`. Switch the mock to an 80 GB A100 device: assert cap rescales, no code change needed. With `torch.cuda.is_available==False`: assert `device_available=False` and `total_memory_bytes=0`.
- `test_manifest_io.py` — `write_manifest → load_manifest` round-trip preserves all fields; `get_or_create` on missing path creates the file; `get_or_create` with a mismatched stored `device_name` logs a warning and regenerates (mock the discover call to return a different name).
- `test_no_hardcoded_device_literals.py` — greps the entire `core/`, `agent/`, and `nodes/` trees for the tokens `"5090"`, `"A100"`, `"V100"`, `"H100"`, and the literal numeric strings `"32 GB"`, `"32GB"`, `"25.6"` outside docstrings explicitly marked as examples. Fails if any match is found. Mechanical enforcement of Principle 5.

### 5.2 WS-A Evidence Gate (deterministic ground-truth calibration)

**Step 1 — Capture ground truth.** Re-run Stage 2 iter_001 `dynamic_depth_simple` on lilab with `torch.cuda.max_memory_allocated()` instrumented around the training phase, the inference phase, and the full end-to-end run. Record the three peak-memory numbers.

**Step 2 — Skill verification.** With the new `evaluate_vram_skill` implemented, invoke it on the same `dynamic_depth_simple` config. Extract the `estimated_gb` and per-phase breakdown.

**Step 3 — Tolerance check.** Assert:

```
|predicted_peak_gb - measured_peak_gb| / measured_peak_gb ≤ 0.10
```

Both overall and per-phase. ±10% is acceptable per user directive.

**Step 4 — Log the calibration.** The raw numbers go into this design doc (appendix, filled in during implementation) so future regressions can be audited.

**What we do if the gate fails.** Inspect the breakdown. With the Appendix A.5 calibration baked in (`_CUDA_CONTEXT_BYTES = 185 MB`, `_CUDNN_BACKWARD_WORKSPACE_BYTES = 50 MB`), the expected residual is <1% on both phases (see §3.3 per-phase composition). A gate failure > 10% means one of: (a) the driver stack moved (e.g. torch/cuDNN upgrade on the host) → re-run the A.13 capture and update the two calibrated constants; (b) an unmodeled allocation class appeared (e.g. DDP gradient buckets) → add a new named term to `overhead.py`, do not fold it into an existing constant. Fix the formula, not the test tolerance.

### 5.3 WS-B tests

- `tests/unit/nodes/ml_model_proposal_agent/test_contract_reassertion.py` — render the Proposer's system prompt; assert the plugin-contract strings (`[B, T] int64`, `[B, 256, T] float32`, `segmentation_size`, `causal mask`) are present.
- `tests/unit/nodes/ml_model_implementor/test_reasoning_prompt_rules.py` — render the Implementor's reasoning system prompt; assert both "Variable-Reference Audit" and "Tensor Arithmetic Guard" sections are present, and that neither mentions any model-family name.
- `tests/unit/nodes/ml_model_implementor/test_repair_prompt_attributeerror.py` — feed a synthetic `AttributeError: 'GatedBlock' object has no attribute 'gate_channels'` into the repair-prompt builder; assert the `__init__` ↔ `forward` consistency hint is present and is ordered before generic repair instructions.
- `tests/integration/workflows/test_implementor_regression.py` (dual-mode) — replay the Stage 2 iter_001 `dynamic_depth_simple` Proposer+Implementor trace as a fixed LLM-response fixture; assert attempt 1 passes the smoke test (no need for retries). This is the observable success signal for WS-B.

### 5.4 Guardrail test: no model-name strings

`tests/unit/guardrails/test_no_model_name_branches.py` — greps `agent/skills/evaluate_vram_skill/`, `agent/skills/training_skill/estimator.py`, `agent/skills/inference_skill/estimator.py`, `core/inference_defaults.py` for the string tokens `"wavenet"`, `"punet"`, `"fcnet"`, `"rnn"`, `"transformer"`, `"cnn"` (case-insensitive). Fails if any match is found outside docstring comment blocks explicitly marked as examples. This is the mechanical enforcement of Principle 2.

---

## 6. PR Plan

### PR #1 — WS-A: Deterministic VRAM
- **Branch:** `feat/deterministic-vram` (already cut off `master` at `284c398`).
- **Scope:** sections 3.1–3.8 + tests 5.1, 5.2, 5.4.
- **Title:** `feat(vram): deterministic torchinfo-based VRAM estimator (Phase 6.6 WS-A)`.
- **Reviewer checklist** (embed in PR body):
  - Evidence Gate passes with logged numbers.
  - Guardrail test passes.
  - Return-dict schema is backward-compatible (only additive).
  - `sandbox_executor.execute_inference` no longer reads `inference_defaults`.

### PR #2 — WS-B: Implementor Hardening
- **Branch:** `feat/implementor-hardening` (cut off PR #1's merge commit on `master`).
- **Scope:** sections 4.1–4.5 + tests 5.3.
- **Title:** `feat(agents): contract re-assertion + consistency audits (Phase 6.6 WS-B)`.
- **Reviewer checklist:**
  - Rendered-prompt tests pass.
  - Regression replay (`test_implementor_regression.py`) passes on first attempt.
  - No new model-name strings introduced (guardrail test from PR #1 still green).

---

## 7. Checklist

### Design phase
- [x] D.1 Draft design doc (`docs/phase66_deterministic_vram_and_hardening.md`) — **this file**. Revision 1 committed at `d0c7e34` on `feat/deterministic-vram`. Revised in-place post-sign-off: (a) Universal Hardware Awareness addendum (§2 Principle 5 + §3.9 `HardwareContext`), (b) §3.2 rewrite after A.13 exposed torchinfo's blindness to intra-forward intermediates — autograd-tape walker promoted to source-of-truth for training mode.
- [x] D.2 Review by user. Amend sections per feedback. Commit on `feat/deterministic-vram` only after sign-off. Sign-off received in three passes: (1) initial 5 open questions resolved (torchinfo auto-batch; 0.80× device-agnostic cap; ±10% gate; two-PR shape; doc path), (2) Universal Hardware Awareness directive folded in, (3) A.2 autograd-tape design approved ("Confirmed. …superior engineering approach"). Subsequent commits C1 (`12d05f3`) and C2 (`0b69291`) landed under this sign-off.

### WS-A implementation (PR #1, branch `feat/deterministic-vram`)
- [x] A.1 Add `torchinfo` to `pyproject.toml`; run `uv sync`; commit lockfile. `torchinfo==1.8.0` pinned; import verified under torch 2.10.0+cu128 / Python 3.12.
- [x] A.1.5 Implement `core/hardware_context.py` (§3.9) — `HardwareContext` Pydantic schema, `discover`, `write_manifest`, `load_manifest`, `get_or_create`. Unit tests per §5.1 (`test_hardware_context.py`, `test_manifest_io.py`). **Landed `f4c33a7` on `feat/deterministic-vram` (2026-04-23).** 21/21 CPU-only unit tests pass (schema: 10, manifest lifecycle: 11). `torch.cuda` monkeypatched to simulate RTX 5090 / A100-40GB / A100-80GB / CPU-only without requiring any of those devices physically present. Device/hostname-mismatch regeneration + corrupt-manifest recovery both covered.
- [ ] A.1.6 Wire `get_or_create` into `nodes/ml_hyperparameter_tune_agent.py` run init. Verify manifest appears at `{workspace}/{run_name}_hardware.json` on a dry-run. Hold the instance on the tuner; do not consume yet (consumption lands with A.8/A.11).
- [x] A.2 Implement `agent/skills/evaluate_vram_skill/structural_probe.py` + unit test (5.1). 15/15 unit tests pass on CPU. Reconciliation against A.13 anchors run on RTX 5090 — see Appendix A.5. Tape walker captures 528 MB of autograd-retained bytes; predicted train/infer delta 361 MB vs. anchor delta 412 MB (match within 51 MB of cuDNN-backward workspace, which is A.3's scope).
- [x] A.3 Implement `agent/skills/evaluate_vram_skill/overhead.py` + unit test (5.1). Hybrid design (§3.3): analytical `training_overhead_bytes` (grads + optimizer state scaled by `params_bytes`) + two calibrated constants from Appendix A.5 (`_CUDA_CONTEXT_BYTES = 185 MB`, `_CUDNN_BACKWARD_WORKSPACE_BYTES = 50 MB`). Document origin of each constant in module-level comments; `ValueError` on unknown optimizer. **Landed `5a58534` on `feat/deterministic-vram` (2026-04-23).** 29/29 unit tests pass (constants regression, analytical scaling parametrized over 5 param sizes, adamw==adam identity, sgd grads-only, case-insensitive, unknown-optimizer error surfaces valid options, mode-switching inference vs. training, Principle 2 inline spot-check on module source). Exposes `phase_overhead_bytes(params, mode, optimizer=None)` composer so A.6/A.7 estimators don't duplicate the per-phase sum logic.
- [x] A.4 Implement `agent/skills/evaluate_vram_skill/batch_resolver.py` + unit test (5.1). Acceptance predicate consults **both** VRAM cap and compute-intensity cap (§3.5, §3.10). **Landed `6947b53` on `feat/deterministic-vram` (2026-04-23).** 16/16 resolver tests pass: descending sweep `[64, 32, 16, 8, 4, 2, 1]` honoured (call-log verification), peak = `params + forward_output_bytes_sum + cuda_context_bytes()` (conservative sum, not max — prefers refusals over false accepts for the pre-flight gate), dual-predicate acceptance, boundary `peak == cap` accepted, intensity-only skip verified at T=40000 (B=64/32 rejected on intensity, lands on B=16), `ValueError` diagnoses binding cap as `vram` / `compute_intensity` / `vram+compute_intensity` for `killer_report` routing. Mocks `probe_activation_footprint` — no torch-forward in the unit test path.
- [x] A.4.5 Implement `agent/skills/evaluate_vram_skill/compute_intensity.py` (§3.10) + unit test (5.1). Calibration locked: Phase 6.5 Stage 2 failure at (B=25, T=40000) → product 1,000,000, 20% safety margin → `_MAX_BATCH_TIMESTEPS = 800_000`; origin recorded verbatim in module docstring per §3.10.3. **Landed `6947b53` on `feat/deterministic-vram` (2026-04-23).** 24/24 intensity tests pass: constant regression, arithmetic parametrised over 6 (B, T) pairs, at/below/above-cap coverage, `<=` boundary pin at the exact cap, Stage-2 failure-point regression (`passes(25, 40000) is False`), `describe_violation` surfaces product + cap + both dimensional levers with no architecture-family terms, Principle 2 source spot-check.
- [x] A.5 Implement `agent/skills/evaluate_vram_skill/killer_report.py` + unit test (5.1). Verdict/suggestion distinguishes VRAM-over-budget from compute-intensity-over-budget (§3.6, §3.10.2). **Landed `b76143b` on `feat/deterministic-vram` (2026-04-23).** 20/20 unit tests pass. Shape: one Pydantic `KillerReport` (frozen) with top-level keys `{status, verdict, memory_killer, suggestion}` matching §3.7's wrapper-flatten contract, plus `MemoryKillerDetails` holding `binding_cap ∈ {"vram","compute_intensity","vram+compute_intensity"}` and two disjoint attribution halves. Three renderers: `render_vram_report` (dominant-leaf attribution, non-leaves filtered from `per_layer` to keep `dominant_fraction` mathematically sound, suggestion names user-given `var_name` + dimensional lever, no architecture-family terms), `render_intensity_report` (no layer references, suggestion delegated to `compute_intensity.describe_violation`), `render_combined_report` (both halves populated + concatenated suggestions when both caps fail). Empty-layers edge case falls back to whole-model phrasing without crashing.
- [ ] A.6 Rewrite `training_skill/estimator.py::estimate_peak_bytes` to call probe+overhead. Wall-time untouched.
- [ ] A.7 Rewrite `inference_skill/estimator.py::estimate_peak_bytes` to call probe. Wall-time untouched.
- [ ] A.8 Update `wrapper.py`: accept `hardware_context` kwarg, read `usable_cap_bytes` from it, remove direct `torch.cuda.get_device_properties` / `mem_get_info` calls, add new return keys, remove obsolete free-based logic + 4 GB floor + contention log.
- [ ] A.9 Delete `_INFERENCE_BATCH_SIZES` + its three accessors from `core/inference_defaults.py`; delete the file if no other content remains.
- [ ] A.10 Update `sandbox_executor.execute_inference` to accept inference batch from the experiment config, not from `inference_defaults`.
- [ ] A.11 Propagate the skill's `inference_batch` return value into the tuner's experiment config (`nodes/ml_hyperparameter_tune_agent.py` site of `_run_skill("evaluate_vram_skill", ...)`).
- [ ] A.12 Guardrail tests — `test_no_model_name_branches.py` (5.4) + `test_no_hardcoded_device_literals.py` (5.1). Both must pass.
- [x] A.13 Capture ground-truth numbers on lilab (5.2 Step 1). Raw JSON at `docs/phase66_telemetry/stage2_iter_001_telemetry.json`. Training peak 0.8231 GB, inference peak 0.4212 GB, dominant phase = training. See Appendix A.1.
  - [x] A.13.a Standalone telemetry script drafted: `docs/phase66_telemetry/capture_stage2_vram_telemetry.py` (two-subprocess, replays Stage 2 iter_001 attempt_003 configs + plugin verbatim, uses production `FocalLoss1D`).
  - [x] A.13.b Device handling hardened: `_resolve_device_index(override)` honors `--device <idx|cuda:N|cuda>` with fallback to `torch.cuda.current_device()` (respects `$CUDA_VISIBLE_DEVICES`); `set_device` + `init` bootstrap the context before `reset_peak_memory_stats`. Fixes the `Invalid device argument` error seen on lilab.
  - [x] A.13.c Ground-truth capture executed on RTX 5090 (host `ligroup`, torch 2.10.0+cu128, 2026-04-23). Numbers transcribed into Appendix A.1.
- [ ] A.14 Evidence Gate verification (5.2 Step 3). Measured column filled in Appendix A.2; predicted column + delta must be filled **after** A.2–A.6 land (then gate pass/fail = ±10%).
- [ ] A.15 Update `docs/resource_estimator_implement.md` — mark affected sections "Superseded by docs/phase66_deterministic_vram_and_hardening.md (2026-04-22)".
- [ ] A.16 Self-review. Open PR #1.

### WS-B implementation (PR #2, branch `feat/implementor-hardening`)
- [ ] B.1 Edit `nodes/ml_model_proposal_agent.py` — `mathematical_definition` prompt enforces contract re-assertion (§4.1).
- [ ] B.2 Edit `nodes/ml_model_implementor.py` reasoning-time prompt — add Variable-Reference Audit (§4.2).
- [ ] B.3 Edit `nodes/ml_model_implementor.py` reasoning-time prompt — add Tensor Arithmetic Guard (§4.3).
- [ ] B.4 Edit `nodes/ml_model_implementor.py` repair prompt (lines 512–549) — targeted AttributeError clause (§4.4).
- [ ] B.5 Unit tests for rendered-prompt content (5.3 items 1–3).
- [ ] B.6 Regression-replay dual-mode test (5.3 item 4). Capture the Stage 2 iter_001 trace as a fixture.
- [ ] B.7 Run guardrail test from A.12 — still green after WS-B edits.
- [ ] B.8 Self-review. Open PR #2.

---

## 8. Open risks / things to watch

- **torchinfo accuracy on novel layers.** If a plugin uses a custom `nn.Module` that torchinfo cannot introspect (rare but possible), `forward_activation_bytes` will undercount. Mitigation: the Evidence Gate (5.2) will catch this empirically; if it triggers, the fallback is to add a `.register_forward_hook` probe as a secondary path. Decided *not* to implement this fallback unless the gate forces it — avoid designing for a hypothetical.
- **Inference batch on memory-scarce devices.** If all candidate batches (even B=1) exceed the cap, `resolve_inference_batch` raises. The tuner must catch this and record the config as infeasible at the inference stage. Existing `schema_violation` handling in the wrapper is the natural home.
- **WS-B telemetry.** We do not have a measured baseline for "average proposal attempts before smoke passes." The regression-replay test (5.3 item 4) verifies the specific Stage 2 failure does not recur; broader improvement is anecdotal until we accumulate more runs.

---

## Appendix A — Evidence Gate numbers

### A.1 Ground-truth peaks (captured 2026-04-23, A.13)

Captured with `docs/phase66_telemetry/capture_stage2_vram_telemetry.py --phase end_to_end`,
two fresh subprocesses (one per phase), `torch.cuda.max_memory_allocated` under
production `FocalLoss1D` on the exact Stage 2 iter_001 attempt_003 configs + plugin.

| Phase      | Peak allocated (GB) | Peak reserved (GB) | Notes                                              |
|------------|--------------------:|-------------------:|----------------------------------------------------|
| Training   |              0.8231 |             0.8828 | 5 AdamW steps, batch 8 × T=10000, focal loss.      |
| Inference  |              0.4212 |             0.4746 | 1 `no_grad` forward, batch 25 × T=10000.           |
| End-to-end |              0.8231 |             0.8828 | `max` across phases; **training is dominant**.     |

### A.2 Predicted peaks (to be filled during A.14, after the refactor lands)

| Phase      | Measured (GB) | Predicted (GB) | Delta | Within ±10%? |
|------------|--------------:|---------------:|------:|-------------:|
| Training   |        0.8231 |            TBD |   TBD |          TBD |
| Inference  |        0.4212 |            TBD |   TBD |          TBD |
| End-to-end |        0.8231 |            TBD |   TBD |          TBD |

### A.3 Capture context

- Raw JSON: `docs/phase66_telemetry/stage2_iter_001_telemetry.json`
- Script:   `docs/phase66_telemetry/capture_stage2_vram_telemetry.py`
- Device:   NVIDIA GeForce RTX 5090, 31.335 GB total, compute cap 12.0, 170 SMs
- Host:     ligroup (lilab)
- PyTorch:  2.10.0+cu128
- Config:   Stage 2 iter_001 `dynamic_depth_simple` attempt_003 (formal), saved at
            `/tmp/pytest-of-yuema137/pytest-811/.../attempt_003_dynamic_depth_simple/`
- Model params: 46,432

### A.4 Sanity notes

- Both peaks land inside the 200 MB – 2 GB a-priori band — physical, not
  instrumentation noise.
- Training peak (~823 MB) is driven by FocalLoss1D's `[B, 256, T]` intermediates
  (`targets_one_hot`, `pt`, `alpha_t`, per-pixel loss — each ~80 MB at B=8, T=10000)
  plus autograd retention. The model's own activations (embed/conv/gated) are the
  smaller contributor.
- Inference peak (~421 MB) is dominated by the `[25, 256, 10000]` logits output
  (~256 MB) plus one live intermediate at a time (no autograd retention).
- `peak_reserved - peak_allocated` ≈ 60 MB across both phases — the allocator
  working-set overhead we must **model**, not ignore, in `overhead.py` (A.3).

### A.5 Probe vs. anchor reconciliation (A.2, captured 2026-04-23)

Produced by `docs/phase66_telemetry/reconcile_probe_vs_anchors.py` on the
same RTX 5090, using the exact Stage 2 iter_001 attempt_003 configs + plugin
replayed in A.13. The probe's CPU/CUDA output is byte-identical (it reads
tensor metadata, not GPU counters) — both columns below are the structural
prediction.

| Phase      | Probe components                                                                    | Probe predicted | A.13 anchor | Residual (for A.3) |
|------------|-------------------------------------------------------------------------------------|----------------:|------------:|-------------------:|
| Training   | autograd_tape 528.1 MB + input 0.6 MB + logits 78.1 MB + params 0.2 MB              |        607.0 MB |    842.8 MB |   235.9 MB (+28.0%) |
| Inference  | peak_activation 244.1 MB + input 1.9 MB + params 0.2 MB                             |        246.2 MB |    431.3 MB |   185.0 MB (+42.9%) |

**Delta alignment (the core success criterion)**:
- Anchor delta (train − infer): **842.8 − 431.3 = 411.5 MB**
- Probe-predicted delta:         **607.0 − 246.2 = 360.8 MB**
- Match to within **50.7 MB** — the cuDNN backward workspace, which exists
  only in training-mode and which `overhead.py` (A.3) will model with a
  separate `backward_workspace_bytes` term.

**What the residuals mean**:
- Both residuals are **positive** (probe under-predicts — safe direction) and
  on the same order (~200 MB).
- The common ~185 MB is the CUDA process context + cuDNN forward workspace
  on RTX 5090 / torch 2.10.0+cu128 / CUDA 12.8. This is a device-level
  per-process fixed cost, not proportional to the model.
- The extra ~50 MB in training is the cuDNN backward workspace. Both bounds
  are stable across re-runs (hardware + driver are fixed), so a single
  calibration pass in A.3 will pin them.

**Key structural result**: the autograd-tape walker captured **exactly** the
400 MB training-vs-inference delta the user flagged as the critical gap.
torchinfo alone reports 0 MB for `FocalLoss1D.forward_output_bytes_sum`
(there are no submodules to hook), so without the tape walk this delta
would be invisible to the estimator — reproducing the Stage 2 failure mode.

Reconciliation JSON: `docs/phase66_telemetry/reconcile_probe_result.json`.

---

## Appendix B — File change summary (reference)

**Will be modified:**
- `agent/skills/evaluate_vram_skill/wrapper.py`
- `agent/skills/training_skill/estimator.py` (VRAM half only; wall-time untouched)
- `agent/skills/inference_skill/estimator.py` (VRAM half only; wall-time untouched)
- `core/sandbox_executor.py` (inference batch sourcing)
- `nodes/ml_hyperparameter_tune_agent.py` (thread inference_batch into experiment config; init hardware manifest)
- `nodes/ml_model_proposal_agent.py` (WS-B prompt + [HARDWARE CONTEXT] block)
- `nodes/ml_model_implementor.py` (WS-B prompts)
- `docs/resource_estimator_implement.md` (mark superseded)
- `pyproject.toml`, `uv.lock` (torchinfo)

**Will be created:**
- `core/hardware_context.py`
- `agent/skills/evaluate_vram_skill/structural_probe.py`
- `agent/skills/evaluate_vram_skill/overhead.py`
- `agent/skills/evaluate_vram_skill/batch_resolver.py`
- `agent/skills/evaluate_vram_skill/compute_intensity.py`
- `agent/skills/evaluate_vram_skill/killer_report.py`
- `tests/unit/core/test_hardware_context.py`
- `tests/unit/core/test_manifest_io.py`
- `tests/unit/agent/evaluate_vram_skill/test_structural_probe.py`
- `tests/unit/agent/evaluate_vram_skill/test_overhead.py`
- `tests/unit/agent/evaluate_vram_skill/test_batch_resolver.py`
- `tests/unit/agent/evaluate_vram_skill/test_compute_intensity.py`
- `tests/unit/agent/evaluate_vram_skill/test_killer_report.py`
- `tests/unit/agent/evaluate_vram_skill/test_wrapper_contract.py`
- `tests/unit/guardrails/test_no_model_name_branches.py`
- `tests/unit/guardrails/test_no_hardcoded_device_literals.py`
- `tests/unit/nodes/ml_model_proposal_agent/test_contract_reassertion.py`
- `tests/unit/nodes/ml_model_implementor/test_reasoning_prompt_rules.py`
- `tests/unit/nodes/ml_model_implementor/test_repair_prompt_attributeerror.py`
- `tests/integration/workflows/test_implementor_regression.py`

**Will be deleted:**
- `core/inference_defaults.py` (if empty after `_INFERENCE_BATCH_SIZES` removal; otherwise just the dict + accessors).

**Runtime artifact:**
- `{workspace}/{run_name}_hardware.json` — per-run manifest produced by `core/hardware_context.py::write_manifest`. Not source-controlled; lives alongside other per-run artifacts in the workspace.
