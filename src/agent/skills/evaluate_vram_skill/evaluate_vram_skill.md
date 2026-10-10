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

For a composed attempt with an evaluation scope, `TaskProbeDataSpec` also
carries `evaluation_scope_payload`. Before training measurement, the isolated
worker materializes one real validation sample and executes an evaluation-mode
forward under the existing `single_probe_seconds` timeout and worker memory
limit. This uses the same `forward_inference_batch` boundary and
`resolve_inference_input_dtype` authority as production task-data-path inference.
The dataset's storage dtype is converted to the contract-selected representation;
neither integer dtype nor task identity is hardcoded. A `TypeError` reports the
phase, model class, storage/resolved/actual dtypes, shape and device, without
printing sample values. Runtime allocation errors retain their existing types.
The check restores the model's training mode and writes no deliverable or score.
Legacy callers without evaluation-scope transport skip this additional check;
an explicit empty or invalid evaluation scope fails closed. Passing one sample
checks an interface; it does not certify whole-scope inference, scoring or Health.

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
| `feasible` | whether the completed structural and applicable compute-intensity checks pass |
| `estimated_gb` | legacy diagnostic estimate on success; selected refused phase's structural estimate when VRAM binds, otherwise `None` — **not** driver-visible; full observations remain in typed evidence |
| `limit_gb` | the budget it was compared against |
| `verdict` | operator-facing explanation |
| `suggestion` | evidence-based inspection or configuration guidance; a static refusal does not establish GPU excess |
| `inference_batch` | selected inference batch, including when training checks refuse; absent when inference search refuses |
| `static_preflight_evidence` | versioned exact structural decisions; absent when no structural decision was observed |

On a CPU-only host it returns `feasible=True` with
`estimated_gb=0.0` and a verdict naming the device — there is no VRAM
constraint to evaluate, and that is not evidence that any model fits a
GPU. The response carries `static_preflight_bypass` with reason `cpu_only`
and the resolved estimator identity. The worker and parent validate this
explicit skip separately from structural decisions, including standalone
discovery without a parent hardware snapshot.

### Static decision evidence

`agent.schemas.preflight.StaticPreflightEvidence` owns the additive
`static-preflight-v2` contract for new results, including the exact estimator
identity. Archived `static-preflight-v1` evidence remains readable. Each of its
one or two unique phase entries
contains `phase`, `batch_size`, `vram_cap_bytes`, optional
`vram_estimate_bytes` and `estimator`, and optional paired
`intensity_product` / `intensity_limit`. The estimate and estimator must be
present together. Unknown estimates remain `None`; an unobserved estimate
cannot establish a passing decision. Binding constraints are derived from the
recorded comparisons, not from diagnostic prose or layer attribution.

Native training uses `training_registered_state_v1`; native inference admission
uses `inference_registered_state_v1`. An explicitly selected installed provider
may supply another qualified formula. These identify arithmetic, not measured
GPU peaks. The separate successful inference diagnostic still uses its existing
maximum-output proxy. A refusal reports the exact decision from the tested
candidate, including a custom minimum batch, without running another probe to
construct an explanation. The integer `resolve_inference_batch` API remains
available; `resolve_inference_decision` returns the typed decision, and
`BatchSearchRefused` remains a `ValueError` with a `.decision` attribute.
Allocation failures preserve their host/CUDA domain instead of becoming
structural VRAM estimates.

The worker emits `STATIC_PREFLIGHT_REFUSAL` for completed static refusals.
The parent validates the evidence, the adapter retains the existing
`status="success", feasible=False` disposition, and the tuner records the
historical status spelling `skipped_oom_risk`. That spelling alone is not proof
of an OOM. Neither this outcome nor compute-intensity evidence grants measured
GPU-capacity authority. Genuine measured failures retain their existing outcomes.
Passing static results retain the existing `COMPLETED_MEASUREMENT` spelling;
that legacy name does not turn their attached structural evidence into a peak
measurement.

Decision evidence crosses worker JSON separately from bounded diagnostics;
truncating `memory_killer` cannot erase a refusal cause. Tuner records preserve
`memory.static_preflight_evidence` and `memory.preflight_outcome` together,
including successful preflight followed by failed or invalid training.
`PhysicalRejection` also carries static evidence for proposer feedback.
Gate-exhaustion summaries retain the same evidence after repeated failures.
Static refusals cannot authorize architectural-pattern bans or unconditional
model-shrinking advice. Existing time-only feedback and measured failure
policies remain separate.
Stored observations are immutable inputs to any external historical prompt
adapter: experiment-owned, explicitly selected adapters may restore a verified
old presentation without altering infra defaults or inventing missing evidence.
Native accounting inventories registered model/loss state independently from
forward invocation counts and uses the production `optimizer_type`. Explicit,
versioned estimation providers can supply experiment-owned historical arithmetic;
installing one does not change the native default. Every new composition and
worker dispatch pins the selected provider and framework assembly. The worker
verifies this before task-data probing, and the parent verifies the returned
identity. A device-available successful inspection must include evidence.
See the [estimation contract](../../../../docs/reference/preflight-estimation.md)
for exact ownership, availability, formulas, migration and limitations.

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

### Inference search admission

Before any input allocation or structural forward, inference batch resolution
filters candidates using the selected profile's optional workload rule when temporal
geometry is declared. Native estimation has no universal product limit; an
explicit historical estimator may declare one. See the
[provider contract](../../../../docs/reference/preflight-estimation.md#explicit-static-workload-rules).
Rejected candidates cannot consume CPU probing time.
If no candidate passes, the diagnostic reports only the intensity refusal;
VRAM remains unmeasured. Tasks without temporal geometry retain probe-based
selection without an invented intensity constraint. Completed slow measurements
remain usable; neither the capacity threshold nor timeout policy is changed.


## Bounded inference verification in the production adapter

`preflight_adapter.run_production_preflight` retains `wrapper.run_skill`'s static
result and may attach a separate `inference_verification` evidence object.
The resolved task `inference_preflight` policy is documented in the
[composition reference](../../../../docs/reference/task-composition.md#inference-refusal-verification).
`core.runtime_control.inference_verification_evidence` owns its typed decision;
`inference_refusal_verification` owns dispatch and result accessors. Consumers
must use `preflight_allows_execution` and `preflight_inference_batch` instead of
inferring permission from the unchanged static `feasible` field.

Only an ordered passing training decision followed by a sole inference VRAM
refusal is eligible. One worker measures the final refused batch, reads bounded
real evaluation batches and shares production construction/dtype/forward/output
lifetimes. It uses remaining total preflight time and the same RSS/cap controls.
Source identity is pinned before static dispatch, verified by both workers
before/after execution, and checked in their replies. Device UUID, logical CUDA
index, full request, realized identity and no remaining process group are
required; wrong-device OOM is unavailable, not a capacity fact.

Admission requires complete setup/work driver coverage and per-hold reservation
acknowledgements bound to request/phase/sequence. Current reservation before and
after each hold must match; its observed maximum must cover byte-exact phase
reservation high-water. Driver/context and allocator bytes are not substituted
for one another. Arbitrary non-allocator transients, other dataset values and
trained-weight branches remain outside this bounded claim. Missing evidence
raises the tuner's existing inconclusive-preflight path without shrink advice.

`ExperimentMemory` and `PhysicalRejection` preserve the optional typed evidence;
absent evidence is omitted from their serialization. Raw samples/journal remain
in the external workspace, referenced by the compact record. The inference
observation does not replace the subsequent training requirement-table entry.
Historical consumers explicitly choose `static_only` in exp and qualify their
arithmetic/rendering providers; native behavior does not infer historical mode.
