# evaluate_vram_skill

Estimates how much GPU memory a candidate configuration would need, so a
round that cannot fit is skipped cheaply instead of discovered by an
out-of-memory error mid-training.

Created 2026-08-02 (V20 PR B, B-C5). This skill owns the quantity whose
misuse caused the V19 collapse, and it had no document.

---

## What it measures, and what that number is not

The skill runs a **structural probe** in an isolated worker (PR A,
`preflight_worker_main.py`) and composes a **predicted allocated peak**
from it.

> **A predicted allocated peak is not a driver-visible measurement.**

The two differ by a large, architecture-dependent factor. Measured on
this repository's own hardware (A6, `pr_a_isolated_preflight_wiring.md`
§24):

| Candidate | Predicted estimate | Driver-visible peak | Ratio |
|---|---|---|---|
| wavenet | 6.43 GB | **12.52 GiB** | 1.95x |
| punet | 1.65 GB | 3.00 GiB | 1.82x |

The difference is CUDA context, allocator fragmentation, cuDNN
workspaces and caching-allocator overhead — none of which a structural
probe can see.

**Consequences, all of them load-bearing:**

- The estimate is a **planning input**, and V20 PR B does not promote it
  to a resource fact. GPU admission (`core/runtime_control/admission.py`)
  refuses a predicted provenance in `formal` mode rather than using it.
- Comparing this estimate against a driver-visible ceiling is the exact
  defect PR B exists to remove. Do not reintroduce it behind a new
  guard.
- A gate rejection based on this estimate says the *estimate* did not
  fit. Only a **measured** capacity failure may tell a planner the model
  was too large — see §B-C3 of the PR B design.

---

## Hardware applicability — read before reusing any number

Every figure this skill produces is bound to the hardware it ran on.
The binding is by **GPU UUID**, not by device index: "GPU 0" is a
position, not an identity, and it changes with `CUDA_VISIBLE_DEVICES`.

A measurement is applicable only when **all** of these match:

```text
normalized candidate config
phase (training | inference)
task
dataset / data-shape class
runtime settings (batch, segment length, portions)
measurement type (predicted estimate vs driver-visible peak)
GPU UUID
```

**A measurement from one accelerator is not evidence for another.** Moving to
new hardware invalidates every stored figure for admission purposes, even for a
byte-identical candidate. See
[resource qualification](../../../../docs/guides/operating-a-run.md#resource-qualification)
for the caller-owned qualification boundary.

**This skill does not promote anything.** It measures and returns. It
does not decide whether a figure is applicable elsewhere, does not write
an authoritative record, and does not make a measurement reusable across
runs — that is PR C's responsibility, deliberately kept separate so
there is one measurement authority rather than two.

---

## Interface

Invoked through `_run_skill("evaluate_vram_skill", sandbox, ...)`, and in
production through `run_production_preflight`
(`preflight_adapter.py`), which routes to the isolated worker.

**Optional keyword arguments** (`run_skill`, `wrapper.py`):

| kwarg | Default | Meaning |
|---|---|---|
| `vram_budget_gb` | `None` | operator soft cap. `None` means *no operator ceiling*, never *unset*: the cap then comes from the hardware context's `usable_cap_gb`. An operator budget may only LOWER the 80 % physical ceiling, never raise it. |
| `hardware_context` | `None` | resolved `HardwareContext`. When absent the wrapper falls back to `core.hardware_context.discover()`, so the cap is physically correct but the on-disk manifest is not consulted. |
| `model_io_contract` | `None` | the **run-bound** normalized `ModelIOContract` (Step 05b). When supplied, the probe's float target is realized from it through `agent/skills/model_io_probe_skill` at the candidate's real batch and segmentation size, instead of from a `[B, 256, T]` literal. |
| `probe_input_sample` / `probe_target_sample` | `None` | a paired task-valid training batch materialized by the isolated worker through the composed run's existing `TaskDataPath.training_dataset` contract. Both must be supplied together. The wrapper applies the same declared input and objective target dtypes as training before probing. |
| `max_inference_batch_size` | `None` | optional task-semantic ceiling transported from `TaskInferenceBatching`. Resource probing may choose a smaller feasible batch but never a larger one. |

`model_io_contract` is always supplied **explicitly by the caller**; this
skill never resolves one of its own. A resource consumer that re-read an
ambient task configuration could price a run against a declaration the run
is not using — the defect the explicit transport exists to prevent.

Three things are deliberately unchanged when a contract is supplied:

- **dtype** still comes from the loss (`PLUGIN_LOSS_TARGET_DTYPE` via
  `get_target_torch_dtype`). The contract supplies shape only.
- **the class-index branch**: a long target is `[B, T]` class indices,
  carrying no contract-owned extent, and returns before any contract is read.
- **`hybrid`**: a legacy builtin adapter value, not a tensor semantic
  (Step-03 §8c). `fcnet` picks its emitted shape from `loss_type`, which no
  Model-I/O contract owns, so its shipped target is preserved.

A contract that cannot be realized — a `classifier` declaration under a
contract carrying no class axis, or a contract supplied without a
`model_type` — **fails loudly**. It never falls back to the literal shape:
a silently-wrong probe reports a capacity number for a different model.

For a composed run with a task-owned training scope,
`run_production_preflight` carries a typed `TaskProbeDataSpec` into the
isolated worker. The spec contains the already-resolved manifest identity,
serialized training scope, physical data root, epoch sampling parameters, and
the optional task-declared inference batch ceiling.
The worker verifies the composition fingerprint and obtains one full batch
through `TaskDataPath.training_dataset`; it does not invent target values from
shape and dtype. This is required for masked, sparse, graph, and other losses
whose target validity has semantic structure. Un-composed and single-file
runs retain the existing synthetic probe path. CPU-only runs still skip the
VRAM probe without reading task data.

The autograd-tape measurement accounts for saved sparse tensors by their
physical component buffers rather than by calling dense storage APIs on the
sparse tensor object. COO tensors contribute indices and values; compressed
CSR, CSC, BSR, and BSC tensors contribute their index and value buffers. An
unknown layout refuses explicitly instead of reporting a partial estimate.

**Key returned fields** (`wrapper.py`):

| Field | Meaning |
|---|---|
| `feasible` | whether the estimate fits the configured budget |
| `estimated_gb` | the predicted allocated peak — **not** driver-visible |
| `limit_gb` | the budget it was compared against |
| `verdict` | operator-facing explanation |
| `suggestion` | what to change, when the estimate is the binding constraint |
| `inference_batch_uncalibrated` | the inference estimate used an unregistered batch |

On a CPU-only host it returns `feasible=True` with
`estimated_gb=0.0` and a verdict naming the device — there is no VRAM
constraint to evaluate, and that is not evidence that any model fits a
GPU.

---

## What it must never do

Declared task-code integrity is not resource evidence. A named `LocalCodeError`
from package verification or a refused declared dependency propagates through
the worker and parent boundaries to the workflow's `code_package_integrity`
chain halt. It must not become measured overflow, inconclusive capacity, an
ordinary candidate rejection or a suggestion to shrink the model. Ordinary
probe failures and existing CPU/GPU applicability remain unchanged. See
[task-code transport](../../../core/local_code/README.md).

- Assume GPU 0, or any device index, rather than a resolved UUID.
- Reuse a figure measured on a different GPU UUID.
- Present `estimated_gb` as a driver-visible requirement.
- Authorise a candidate-shrinking instruction on its own — that
  authority belongs to a measured capacity failure (§B-C3).

---

## Related

- `core/runtime_control/admission.py` — consumes an applicable
  **measured** requirement; refuses a predicted one in formal mode.
- `core/runtime_control/failure_attribution.py` — decides whether an
  out-of-memory says anything about the candidate at all.
- `docs/design/v20_priorities/pr_b_gpu_aggregation_attribution.md` —
  the measurement/attribution design and the cross-hardware section.
- [`docs/getting-started/installation.md`](../../../../docs/getting-started/installation.md) — new-machine bring-up.
