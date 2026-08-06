# Design: V20 PR C — Measured evidence and formal admission

- **Status**: **COMPLETE — both PRs merged, both gates PASSED.**
  - Umbrella architecture and the ten §8.C operator decisions:
    **APPROVED 2026-08-03 UTC**.
  - **PR C1: MERGED 2026-08-03** — PR #161, `781e3e8a`.
  - **PR C2: MERGED 2026-08-04** — PR
    [#164](https://github.com/Galileo-Sandbox/SIDERIUS/pull/164), merge
    commit `40d17f69c2f4b74cb14e6624a9c72a5ef82d5dac`. Master CI green at
    the merge commit.
  - **Gate 1: N/A** — C2 changes no LLM-facing prompt, schema or decision
    surface.
  - **Gate 2 Lite-A (RTX 5090): PASSED.**
  - **Gate 2 Lite-B (H100 80GB HBM3): PASSED.**
  - **Gate-tested SHA**: `7302c467d81a575e3e35a8f81821eb5dbd63e451`.
  - **Final CI-tested head**: `5dca28f9652ae003c4f2d3d229aedc03c1ccd730`.
    The diff between the two is type annotations, one `cast`, one typing
    import, comments, docs and tests — no runtime behaviour — so Lite-A and
    Lite-B were **not** rerun. See *Type-only carry-forward* below.
  - Historical note: this header previously read "PR C2 implementation:
    NOT AUTHORIZED … no implementation has begun; neither branch exists",
    and later "NOT MERGEABLE YET — exact-head CI is red". Both are
    superseded: C2 is merged and CI is green.
- **Implementation shape**: this document is the umbrella design and
  launch-blocker record. Implementation is **two PRs** — C1 (calibration
  identity, reachability, promotion) and C2 (authoritative GPU requirement
  acquisition and delivery). See §15. Each is cut from the then-current
  `master` when approved.
- **Parent plan**: `docs/design/v20_priorities.md` §20.5 (PR C scope),
  §13.1 (launch gate), §1.4 (genericization contract)
- **Audited against**: `master` @ `5c58c29` (2026-08-02), i.e. after PR A
  (#152, `5c18946`), PR B (#153, `4472f15`), and the three production
  hotfixes #156 / #157 / #159.
- **Dependencies**: PR A **MERGED**, PR B **MERGED**. Both are on `master`;
  neither is pending.

---

## 1. Problem statement

PR B built a formal GPU admission gate and wired it into production. That
gate asks one question — *does an applicable, authoritative measurement of
this candidate's requirement exist?* — and in production the answer is
always **no**, because nothing produces such a measurement.

PR C's job is to make the answer sometimes yes, and to make "yes" mean
something specific: *this measurement describes this task, this data shape,
this candidate, this phase, and this machine.*

It is **not** "wire calibration into admission", for two separate reasons.

First, the calibration machinery exists and is almost entirely unreachable;
the identity it would key on is incomplete; and the persistence format
cannot accept new identity fields without invalidating every record already
written.

Second, and more fundamental: **the calibration registry measures
milliseconds, and PR B's gate needs mebibytes** (§3). Restoring the registry
end to end produces a better time calibration and leaves `requirement_mib`
exactly where it is — `None`. PR C is therefore two tracks sharing one
identity/applicability framework, not one chain.

---

## 2. Confirmed evidence

Everything in this section was verified against `master` @ `5c58c29` during
this audit. Line numbers are from that commit. Claims inherited from earlier
documents were re-derived, not carried forward; §4 lists the ones that
changed, and §3 records a physical-quantity error the first draft made.

### 2.1 There are two disjoint measured-evidence systems

The existing design vocabulary blurs them. They share no records, no
identity, and no store.

| | **System A** | **System B** |
|---|---|---|
| Record | `RuntimeObservation` — `core/runtime_control/records.py:342` | `CalibrationObservation` — `core/runtime_control/registry_schemas.py:114` |
| Store | JSONL per workspace — `observation_store.py:181` | content-addressed dir per **machine** — `calibration_registry.py:81` |
| Root | `{sandbox.base_dir}/runtime_observations` | `~/.siderius/runtime_calibration` (or `$SIDERIUS_CALIBRATION_DIR`) |
| Identity | 9-part string — `observation_store.py:78` | 7-part `bucket_key` — `calibration_policy.py:311` |
| Written in production | **yes, every successful attempt** | **effectively never** (§2.3) |
| Read in production | yes, but **trial only** | **never — zero readers** |

A third, older store also exists: the legacy per-GPU k-table at
`agent/skills/evaluate_time_skill/calibration.py`, 313 KB on this machine,
not registered in the registry (`legacy_sources: []`).

### 2.2 The promotion and applicability layer is dead

AST-precise call-site count across `core/`, `nodes/`, `agent/`,
`execute_tools/`, `workflows/` — definitions and same-module recursion
excluded:

```
applicability_for_request       0 production call sites
as_estimate                     0
classify_model_family           0
downgrade_for_applicability     0
evaluate_promotions             0
record_promotion                0
evaluate_bucket                 1  — from evaluate_promotions, itself dead
bucket_key                      8  — all inside calibration_policy.py, plus
                                     calibration_registry.py:427 inside the
                                     dead as_estimate
record_observation              2  — probe_wiring.py:172 (gated, §2.3)
                                     bootstrap.py:357 (operator CLI)
```

**Name-collision warning, recorded so a future audit does not repeat it.**
`ml_hyperparameter_tune_agent.py:4708` calls `detect_drift` and looks like a
live consumer. It calls `time_calibration.detect_drift` — the **legacy
k-table** function at `agent/skills/evaluate_time_skill/calibration.py:228`,
not the registry function at `calibration_policy.py:507`. The registry one
is dead.

### 2.3 System B is written only through a gate that the happy path cannot open

`record_observation` is reached from `probe_wiring.py:172`, which requires
`runtime_decision == "REQUEST_PROBE"` (`ml_hyperparameter_tune_agent.py:924`).
That decision has one production branch — `decision_policy.py:308-320` —
requiring `evidence_channel == "probe_absent"` **and** `phase == "formal"`
**and** `not estimate.blocking_eligible`.

- On a real formal GPU run with `data_dir` set, the warm-up succeeds,
  `ms_source = "real_dataset_warmup"`, so `blocking_eligible` is True and
  no probe is requested.
- On a CPU/pseudo box the probe *is* requested, but
  `probe_runner_availability()` is False, so the tuner stamps
  `probe_resolution = "unavailable"` and proceeds.

The residual window is CUDA present + `data_dir` present + warm-up returned
`None` — a failure path, not the happy path.

**Measured consequence, on this machine's live registry:**

```
generation      : 24
observations    : 20      promotions: 0
model_family    : "unknown" x 20
provenance      : "bounded_live_probe" x 20
operation       : training x 10, inference x 10
software_stack  : {} x 18, populated x 2   (the 2 are operator-CLI bootstrap)
```

Zero promotions is the load-bearing number. `bucket_status` reads authority
from promotion records, so even if `as_estimate` were called it could never
return `promoted_measurement`.

### 2.4 PR B's admission gate has no production input

`core/sandbox_executor.py:489` reads `getattr(sandbox, "measured_requirements", None)`.
**No production code assigns it.** The only writers are
`scripts/bg_admission_validation.py:456` (the validation harness, not the
product) and tests. Production says so itself, in two comments:
`admission.py:134` and `ml_hyperparameter_tune_agent.py:2273`.

So `_phase_requirement` always returns `(None, None)`, and formal admission
always lands at `admission.py:437-445` — `policy_unavailable`, whose message
already names this PR:

> *no applicable authoritative requirement for this candidate exists …
> producing one is PR C's responsibility (D-B5)*

`AUTHORITATIVE_PROVENANCE = {"measured", "promoted_measurement"}`
(`admission.py:127`) is currently unsatisfiable: no producer emits either
string.

Related dead field: `GpuAdmissionPolicy.measurement_source`
(`admission.py:165`) is written in production
(`ml_hyperparameter_tune_agent.py:2305`, from `--gpu_admission_measurement_source`)
and **never read**. It is a reference string with no resolver.

### 2.5 Identity is lost at two production call sites

Both in `_resolve_time_check_probe_request`:

- `ml_hyperparameter_tune_agent.py:947-957` constructs `ProbeRequest` with
  `model_identity=model_type` but **omits `model_family`**, which then takes
  its default `"unknown"` (`probe_lifecycle.py:69`) and is forwarded
  faithfully to `CalibrationObservation.model_family` — bucket component 6.
  The model type is in scope at `:895`; it is simply not passed.
  `classify_model_family` (`calibration_policy.py:259`) exists and has zero
  callers.
- `ml_hyperparameter_tune_agent.py:978` passes `software_stack={}`, so
  `stack_identity({})` yields one constant digest for every record the
  system could write — bucket component 7, and the documented drift anchor.

### 2.6 The bucket key does not contain task, dataset, or device instance

`bucket_components` (`calibration_policy.py:296-309`) has exactly seven
dimensions: operation, measurement_unit, concurrency_identity,
hardware_compatibility_id, execution_environment_id, model_family,
stack_identity.

Absent from the key **and from every calibration schema**: `task`,
`dataset` / data-shape class, GPU **UUID**. Verified:
`grep -cE "\btask\b|\bdataset\b|\buuid\b" registry_schemas.py` → `0`.

Absent from the key but present as untyped payload: `batch_size`,
`segment_length` (in `workload`), `dtype`, `parameter_count` (in
`realized_model`).

`DeviceIdentity.uuid` exists (`gpu_accounting.py:66`) and is persisted — but
into `ExperimentRecord.gpu_evidence`, never into the registry.

The registry root is `~/.siderius/...`: **one directory serves every task,
every dataset and every chain on the host.** With no task or dataset
dimension in the key, records from different tasks are eligible to land in
the same bucket.

`applicability_for_request` (`:599-627`) is the compensating read-side check
over batch/segment/param ranges and does fail closed — but it is a separate
call from `bucket_status`/`as_estimate`, and it has zero callers.

### 2.7 The content address *is* the schema

`CalibrationObservation.observation_id` is `content_id(hash_payload())`, and
`hash_payload()` dumps the whole model minus `timestamp_metadata`
(`registry_schemas.py:181-188`). `schema_version` is **inside** the hash
(`:124`).

Verified empirically against a live record:

```
file stem                          09e767d8ff1806736840
recomputed id                      sha256:09e767d8ff1806736840   matches
with ONE new optional field=None   sha256:6cff7c0d9b9a727e3a92   DIFFERENT
```

So **any** added field — optional, defaulted, `None` — changes every
existing record's identity. `load_observation` (`calibration_registry.py:244-250`)
then raises *"content-hash mismatch … (corruption or tampering)"*, and
`rebuild_index` silently drops all 20 records into its `rejected` list and
commits an empty manifest. Bumping `REGISTRY_SCHEMA_VERSION` is
indistinguishable from corruption.

Symmetric and useful: unknown keys on read are **ignored** (no `extra`
policy → Pydantic default), so old code reading new records degrades
quietly rather than refusing.

System A is the opposite: a new optional field is safe; a new required field
makes `model_validate` fail per line at `observation_store.py:230`, which is
caught at `:231` and **printed**, not raised — the line silently vanishes
from `read_all`.

### 2.8 The measured-evidence path is gated on the TIDMAD dataset

This is the single most consequential genericization finding, because it
sits directly in PR C's path.

`core/runtime_control/probe_wiring.py:72-79` — `probe_runner_availability()`
returns `False` unless `TIDMAD_DATA_DIR` is a readable directory, and its
success string is `f"CUDA + dataset at {TIDMAD_DATA_DIR}"`. The tuner
consults exactly this before any bounded live probe
(`ml_hyperparameter_tune_agent.py:936`).

**So on a non-TIDMAD task the entire measured-probe path silently disables
itself**, and the run proceeds on static priors — the V19 posture. The same
import appears at `bootstrap.py:439-443` (whose operator remedy is *"Point
the run at a readable TIDMAD directory"*) and `probe_production.py:137-145`.

Related, in generic infrastructure:

- `probe_production.py:147` — `segmentation_size` defaults to `40_000`, a
  divisor of TIDMAD's 10,000,000-sample segment.
- `estimate_types.py:155` — `segment_length` is a **required** field of the
  generic `RuntimeEstimateRequest`; a task with no 1-D segment cannot
  construct a request.
- `observation_store.py:120` — `seg_size` is a required member of
  `calibration_context`, so an observation from a task without segment
  sizes is structurally uncalibratable.
- `campaign.py:38` — `CampaignTrack = Literal["A_matrix", "B_legacy_fcnet",
  "C_pairwise"]` bakes a TIDMAD model name into a persisted type.
- `evaluate_time_skill/wrapper.py:65` — `SEGMENT_LENGTH as
  PSD_SEGMENT_LENGTH` reads generic; its value is `10_000_000`, and it is a
  divisor in the time model at `:353` and `:737`.

`configs/task_config.yaml` is a **prompt-injection seam, not a runtime
seam** — nothing in `core/runtime_control/`, either time or VRAM skill, or
the tuner reads it. Its own closing comment (`:38-43`) lists `num_files`,
`data_dir` and `metric_name` as still-hardcoded, and all three still are.

### 2.9 `model_family` has three incompatible meanings

They meet without conversion:

1. **Classified structural family** — `classify_model_family`
   (`calibration_policy.py:259-273`), the designed meaning, zero callers.
2. **The registered model_type string** — `evaluate_time_skill/wrapper.py:499`
   passes `model_family=model_type` into `calibration_key`.
3. **Nothing** — the probe path defaults to `"unknown"` (§2.5).

So the two evidence producers write **two different family namespaces into
two different stores**, and `estimator.py:242` papers over a third case with
`request.model_identity or request.model_family or "unknown"`, using
identity and family interchangeably.

### 2.10 Fail-open defaults already present

Recorded because PR C must not add to this list:

| Site | Default | Effect |
|---|---|---|
| `registry_schemas.py:134` | `model_family="unknown"` | intended as a separate bucket; in practice the only bucket |
| `probe_lifecycle.py:69` | `model_family="unknown"` | production never overrides it |
| `observation_store.py:96` | `(torch_version or "unknown")` | two unknown stacks share a key |
| `observation_store.py:101` | `gpu or "unknown"` | two unknown GPUs share a key |
| `observation_store.py:97` | `log2_bucket = 0 if param_count <= 0` | missing param count aliases onto the smallest real bucket |
| `observation_store.py:132` | `batch_size = int(ctx.get("batch_size", 0))` | not in the `required` tuple; missing → `bs=0` |
| `registry_schemas.py:126,143,144` | `str` with no `min_length` | `""` passes the schema |

---

## 3. Measurement kinds and authoritative producers

**This section corrects a structural error in the first draft.** That draft's
commit ladder assumed the chain

```
registry observation -> promotion -> applicability -> PR B GPU admission
```

holds. It does not, and the reason is physical: **the calibration registry
does not measure GPU memory.**

Verified on the 20 live records:

```
CalibrationObservation.measured_value_ms : float, Field(gt=0.0)
measurement_unit                         : "optimizer_step" x10, "inference_batch" x10
measured_value_ms range                  : 0.77 ms .. 289.79 ms
```

PR B's gate consumes `requirement_mib` (`admission.py:289`) — mebibytes of
GPU memory. Milliseconds per optimizer step and mebibytes of VRAM are
different quantities. **Restoring the registry's write path, promotion and
applicability produces a better *time* calibration and still leaves
`requirement_mib` at `None`.** Any ladder that ends at PR B's gate by way of
the registry alone is wrong.

### 3.1 The five kinds

**Re-audited from code on 2026-08-03 UTC.** An earlier revision of this table
attributed allocated, reserved and driver-visible values all to
`GpuAccountingSnapshot`. That was inferred from the class name and is wrong;
the three come from different places, and one of them has no producer at all.

| Kind | Producer, verified | Unit | Vantage point |
|---|---|---|---|
| **Runtime duration** | bounded probe → `probe_observations` (`probe.py:518`); warm-up in `evaluate_time_skill/wrapper.py` | ms per `optimizer_step` / `inference_batch` | in-process timing |
| **GPU allocated** | `torch.cuda.max_memory_allocated()` — **exactly one production call site**, `core/runtime_control/probe_production.py:223` | GiB | **inside** the candidate process; PyTorch allocator |
| **GPU reserved** | `torch.cuda.max_memory_reserved()` — **no production call site anywhere.** This kind has **no producer today** | — | would be in-process; PyTorch caching allocator |
| **GPU driver-visible** | `GpuAccountingSnapshot` via **two bounded `nvidia-smi` queries** (`gpu_accounting.py:315` device totals, `:335` per-process rows; backend field at `:77`) | MiB | **outside** the process; driver/NVML |
| **Host memory** | `HostMemoryEvidence` (isolated pre-flight); `read_process_rss_bytes` | GiB / bytes | OS |

**Why the vantage point is the whole point.** The allocator sees what the
candidate asked for; the driver sees what the device gave out, including
caching-allocator retention, CUDA context and other clients. A6 measured the
gap at **1.95x and 1.82x**, which is exactly why an estimate compared against
a driver-counted quota cannot protect it. A requirement expressed in
allocator terms is not a requirement in the units a host quota enforces.

**The field C2 needs already exists.** `GpuAccountingSnapshot.own_tree_mib`
(`gpu_accounting.py:168`) is *"summed over processes whose ancestry reaches
`root_pid`"* — candidate-owned, driver-visible, in MiB. Its siblings make
the accounting auditable rather than merely plausible: `other_mib` (not
ours), `per_pid_total_mib`, `unattributed_mib` (context overhead, graphics
clients, other users' processes), and `accounting_skew_mib`, deliberately
**signed** so a disagreement between the two accounts is visible instead of
clamped away.

`telemetry_available` is a first-class field, and its comment states the
rule C2 must honour: when False *"every quantity below is then `None`, and
the caller must not read that as 'nothing'."*

Separately, and not a measurement: `evaluate_vram_skill` produces
`estimated_gb` (`wrapper.py:660`) — a **prediction** from a structural
probe. V19 established it holds no rejection authority.


### 3.2 The producer→consumer chain PR B's requirement actually needs

The only real GPU-memory measurement in production today:

```
GpuPhaseObserver                      core/runtime_control/gpu_observer.py:114
  -> GpuEvidenceBundle.observed_peak  gpu_observer.py:84  (GpuAccountingSnapshot)
  -> _with_gpu_evidence               core/sandbox_executor.py:739-753
  -> ExperimentRecord.gpu_evidence    agent/schemas/hyperparam_tuning.py:314
       written at sandbox_executor.py:1390 (training), :1633 (inference)
```

It is real, per-attempt, per-phase, and already persisted. It is **not** in
the calibration registry, has no bucket, no promotion path, and no
applicability rule.

**Three properties make it unusable as a requirement without treatment**, and
each is a design obligation rather than a detail:

1. **It is a sampled lower bound.** `gpu_observer.py:107-111` says so, and
   guards on `valid_sample_count < 2 or observed_peak is None`. A lower bound
   admitted as a requirement under-states need — the failure direction that
   causes an OOM.
2. **It is observed occupancy, not candidate requirement.** Under
   concurrency it includes neighbours unless attributed. PR B's
   `gpu_accounting.sample` already splits ours/other by process ancestry;
   PR C must use that split, not the raw peak.
3. **It is measured *during* the phase it would gate.** The first attempt of
   a new configuration has no prior measurement by construction — the cold
   start D-B5 assigned to PR C.

### 3.3 What this means for the ladder

Two distinct pieces of work, sharing a framework and nothing else:

- **Track 1 — time calibration.** Repair identity, reachability, promotion
  and applicability for the existing registry. Consumer: time-budget
  decisions. Does **not** feed PR B.
- **Track 2 — GPU requirement.** A **dedicated isolated bounded pre-phase
  measurement** of the concrete candidate produces a typed authoritative
  requirement in MiB, which resolves to `requirement_mib`. Consumer: PR B's
  gate. Per O-10, normal-phase `observed_peak` is **not** the producer: it is
  runtime telemetry, used afterwards to corroborate or contradict a promoted
  requirement (O-8), never to originate the first one.

They should **share the identity, applicability and promotion machinery**
(§8's three-model split) and share **nothing else**. `measurement_kind` must
be a first-class identity dimension so that `promoted_measurement` can never
mean "we promoted a millisecond and handed it to a memory gate".

The commit ladder in §15 is ordered so the checkpoint that creates PR B's
authoritative requirement is explicit and separate — see C-C6, and the
ladder note at the head of §15.

---

## 4. Corrections to earlier assumptions

| Earlier statement | Status after this audit |
|---|---|
| "production observations are collected" | **Split.** True for System A (every successful attempt). False in practice for System B. |
| "promotion evaluation is reached in production" | **False.** Zero call sites. |
| "promotion recording is reached in production" | **False.** Zero call sites; zero promotion records on disk. |
| "`model_family` is lost" | **True for System B**, at `ml_hyperparameter_tune_agent.py:947-957`. **Already repaired in System A** — `train_engine_sandbox.py:817` sets it and `observation_store.py:120,129` consumes it. |
| "formal admission can terminate at `ADVISORY`" | **False as spelled, true in effect.** The formal branch returns `REQUEST_PROBE` before any `ADVISORY` return is reachable. But that request resolves to nothing when no probe runner exists (`:936-946`, printed as *"Recorded as advisory — this is NOT a measured production decision"*) and the attempt proceeds; and the GPU gate's refusal is downgraded to `would_refuse` under `observe_only`. Two advisory terminations, neither labelled `ADVISORY`. |
| "an applicable measurement is available before formal admission" | **Partly.** Time: yes, the real-dataset warm-up. Historical: **no in formal** — `allow_store_reuse=is_trial` (`:887`). VRAM/resource: **no**. |
| "PR B's consumer has the input PR C provides" | **False.** §2.4. |
| PR B is "conditional" (`v20_priorities.md:2139` ladder row) | **Stale.** Resolved to REQUIRED on 2026-08-01 (§20.4, `:2326`) and since merged. |

---

## 5. Scope

1. **Complete the identity contract.** Make a calibration record state
   explicitly which task, data-shape class, model family, configuration,
   phase and device instance it measured. Populate the two fields production
   currently drops.
2. **Make the registry reachable.** Give the write path a trigger that the
   happy path can actually open, and give the read path a production
   consumer.
3. **Resolve the migration constraint** created by content-addressing
   (§2.7), explicitly, with an operator decision.
4. **Feed PR B's gate.** Produce the authoritative requirement that
   `_phase_requirement` reads, with provenance that can satisfy
   `AUTHORITATIVE_PROVENANCE`, or replace that duck-typed read with a typed
   boundary.
5. **Report calibration state honestly** — collected / bucketed /
   unbucketed / eligible / promoted / rejected / unusable, with reasons.

## 6. Out of scope

- Changing PR B's lane semantics, attribution vocabulary, or shrink
  authority.
- Raising any memory ceiling.
- The legacy k-table's own behaviour (only its registration as a legacy
  source — out of scope for both C1 and C2).
- Repository-wide test pruning.
- HealthGate formal policy (PR D) and campaign-scoped control (PR E).
- FU-B-18 (`_MAX_REASONING_RETRIES`).

---

## 7. High-level evidence and authority invariants

Carried forward from V19's central lesson — *one signal standing in for
something it did not measure* — and from PR B's lane discipline.

1. Static estimates are **priors only**. They never gain rejection
   authority.
2. Historical evidence alone is **not** a final admission gate.
3. Validated calibration becomes authoritative **only when its applicability
   to this concrete candidate is established**. A matching bucket key is
   **not** applicability — it is a candidate set requiring further checks.
4. An inconclusive measurement must not silently become allow **or** reject.
5. A live measurement must be **correctly classified and correctly
   attributed** before it carries authority.
6. Candidate / environment / contention / timeout / host-memory / unknown
   causes stay distinguishable. PR B's three lanes are not merged.
7. **No missing field or unknown state may fail open into "safe to
   proceed."** §2.10 is the existing list; PR C adds nothing to it.

### 7.1 Three categories that must not collapse

```
Measured fact          what was observed about this candidate, phase,
                       process and device
Configured policy      thresholds, promotion requirements, admission rules,
                       expiry, allowed evidence tiers, fallback behaviour
Task interpretation    what THIS task calls a model family, data-shape
                       class, valid workload, scientific metric, collapse
```

A measured fact is not policy. A policy value is not evidence. A task
interpretation is not a framework rule. The current design collapses all
three into one seven-part string.

---

## 8. Decisions, in three classes

The first draft listed 31 items as operator decisions. Most were not:
they were already settled by V19/V20 principles, or resolvable from the code.
Presenting them as open would have spent operator review on questions whose
answers are not actually free.

### 8.1 Three models, not one bucket key

The current design puts identity, applicability and policy into one
seven-part string (§2.6). That is why a bucket match reads as applicability,
and why adding a dimension is indistinguishable from corruption. PR C keeps
them separate:

```
MeasurementIdentity          — WHO this measurement is about. Exact match.
  measurement_kind             (§3: duration | gpu_allocated | gpu_reserved |
                                gpu_requirement | host_memory)
  task
  data_shape_class
  candidate_config_hash
  model_family
  phase
  hardware_uuid
  runtime_stack

ApplicabilityEnvelope        — WHO ELSE it may speak for. Bounded ranges.
  observed batch range
  segment / data-shape range
  parameter range
  concurrency condition
  other bounded numeric ranges

PromotionPolicy              — WHEN it becomes trustworthy. Configured.
  minimum samples
  consistency threshold
  allowed provenance
  allowed contention class
  expiry / invalidation
```

Exact-match identity fields answer "is this the same thing?". Envelope
fields answer "is this candidate inside the region we actually observed?" —
and a dimension with no measured range must fail closed, as
`classify_applicability` already does at `calibration_policy.py:612-616`.
Policy fields are operator configuration and belong to
`CalibrationPolicy`'s identity hash, not to a record.

This split is what makes the 8.A invariants expressible: cross-task,
cross-UUID, cross-phase and cross-kind reuse fail on **identity**, not on a
similarity heuristic.


### 8.A Frozen — inherited from V19/V20, not open

These are **invariants**. Implementation must satisfy them; it may not
re-open them, and a design that cannot meet one is a design to reject.

Status key: `[x]` = satisfied and asserted by a named test in C1;
`[C2]` = belongs to the GPU-requirement PR and is not yet in force.

- [x] `model_family = "unknown"` is **never** authoritative. It is a
      bucketing failure, not a family.
      → `test_an_unknown_family_never_inherits_known_family_calibration`,
      `test_an_unknown_model_family_is_never_authoritative`
- [x] A matching bucket is **not** applicability. It identifies a candidate
      set that must then be checked.
      → `evaluate_candidate_authority` checks identity, then bucket state,
      then the envelope; `test_out_of_range_candidate_is_refused_despite_identical_identity`
- [x] Cross-**task** reuse fails. → `IDENTITY_ROWS[cross-task]`
- [x] Cross-**data-shape-class** reuse fails. → `IDENTITY_ROWS[cross-data-shape]`
- [x] Cross-**GPU-UUID** reuse fails. A 5090 measurement is never
      H100-authoritative. → `IDENTITY_ROWS[cross-device-uuid]`
- [x] Cross-**phase** reuse fails; training and inference never substitute
      for each other (PR B measured them 1.8x apart).
      → `IDENTITY_ROWS[cross-phase]`
- [x] Cross-**measurement-kind** reuse fails (§3). A promoted millisecond is
      never a memory requirement. → `IDENTITY_ROWS[cross-measurement-kind]`,
      plus `TestHistoricalDurationCannotReachGpuAdmission` (2 tests) proving
      the millisecond system cannot even be imported by GPU admission
- [x] Missing identity **never** fails open into "safe to proceed".
      → `test_an_observation_without_identity_is_refused`,
      `test_a_dimension_with_no_measured_evidence_fails_closed`,
      `TestIdentityIsNotFabricated`
- [x] Zero authoritative buckets is **never** reported as active
      calibration. → C-C7 `is_active` is defined by validated buckets, never
      by record count; `test_observations_without_promotion_are_still_inactive`,
      `test_a_provisional_bucket_is_not_authoritative`
- [C2] PR B receives evidence through a **typed production boundary**, not
      the unfulfilled duck-typed `getattr(sandbox, "measured_requirements")`.
      That read is how the gap survived PR B and its whole test suite.
      *C1 delivers no evidence to PR B by design — duration is milliseconds.*
- [x] Static estimates remain priors; historical evidence alone is not a
      final gate; an inconclusive measurement becomes neither allow nor
      reject. *Satisfied in C1 in the strongest available form: after the
      C-C5b cancellation the v2 registry is not a gate input at all.*
      → `test_historical_duration_is_observability_only.py` (9 tests)
- [C2] PR B's three refusal lanes keep distinct statuses, budget accounting
      and shrink authority. *C1 touches no admission lane.*

### 8.B Implementation choices — resolvable from the code

Claude resolves these during implementation and records the resolution and
its evidence in the commit message. They return to the operator only if the
code turns out not to determine them.

- Representation of full config identity: normalized hash vs enumerated
  fields (weigh completeness against legibility in reports).
- Where the applicability evaluator and evidence-selection boundary live,
  and which of §10.1's three hooks each uses.
- Report shape, counts and rejection-reason representation (the former
  the former D-C28/D-C29/D-C31) — subject to the 8.A rule that zero buckets is
  reported honestly.
- Which of the seven provenance fields each admission record carries and how
  they are typed (the former D-C30) — the *set* is fixed by 8.A, the encoding is
  not.
- Whether `measurement_source` (`admission.py:165`, written and never read)
  is resolved or removed.
- Whether `probe_lifecycle.ProbeRequest.model_family` becomes required.

### 8.C Operator decisions — APPROVED 2026-08-03 UTC

All ten answered. They are binding on implementation; a design that cannot
meet one is a design to bring back, not to work around.

- **O-1 — Migration.** Create a **new schema version in a new registry
  tree**. Preserve the existing 20 records read-only in the old tree; do
  **not** re-hash them.
- **O-2 — Incomplete identity.** Write to an explicit
  **`unusable` / quarantine namespace**. Such records stay auditable but are
  never bucketed, promoted, or authoritative.
- **O-3 — Promotion trigger.** After each successful eligible observation
  write, **idempotently evaluate only the affected bucket** and record the
  result.
- **O-4 — Thresholds.** Preserve the **currently configured values** for v1;
  invent nothing. Read from `CalibrationPolicy`
  (`core/runtime_control/calibration_policy.py:74-92`) on `master` @
  `5c58c29`:

  | Field | Value | Class |
  |---|---|---|
  | `provisional_min_observations` | **2** | D4 |
  | `validated_min_observations` | **3** | D4 |
  | `consistency_max_min_ratio` | **1.5** | D4 |
  | `contention_memory_floor_gb` | 1.0 | D3 |
  | `contention_memory_fraction` | 0.10 | D3 |
  | `contention_utilization_pct` | 20.0 | D3 |
  | `contention_window_seconds` | 10.0 | D3 |
  | `contention_sample_interval_seconds` | 2.0 | D3 |
  | `derating_throttle_mask` | 248 | D3 |

  Resolved policy identity today: `calibration_policy@1.0.0+b83994605c57`.

  **Consequence, and the reason this is not a free change:** the identity
  hash covers **every** field (`:91-95`). Changing any one moves
  `runtime_policy_identity`, which trips `validate_run_invariants`
  (`core/run_invariants.py:284-300`) for **every existing workspace**, whose
  only v1 remedy is a new workspace. These values gain authority **only
  after** the Layer-2 validation passes.
- **O-5 — Contention.** Duration measurements may be promoted only **inside
  the exact recorded concurrency class**. **Contended GPU occupancy may
  never become a candidate GPU requirement.**
- **O-6 — Historical authority.** Applicable historical calibration may
  **ALLOW**, never **REJECT**. Rejection requires a live measurement of the
  concrete candidate.
- **O-7 — Inconclusive or unavailable probe.** Stop the current attempt
  **before the GPU phase**. It consumes an attempt, produces no completed
  round, carries **no candidate blame and no shrink advice**. Only the
  existing outer attempt budget may lead to another attempt — **add no
  same-attempt retry loop.** (This is PR B's lane 1 discipline, and the
  no-new-retry clause keeps LLM call count and cost unchanged.)
- **O-8 — Conflict.** A live measurement **wins for the current admission
  decision**. A contradictory bucket is preserved but marked
  **contradicted and non-authoritative** until revalidated.
- **O-9 — Expiry.** **No wall-clock expiry in v1.** Identity changes fork
  evidence; live contradiction invalidates authority.
- **O-10 — Authoritative GPU producer.** Normal-phase
  `GpuPhaseObserver.observed_peak` is **telemetry and consistency evidence
  only**. It is **not** the authoritative requirement producer.

  The authoritative GPU requirement comes from a **dedicated isolated,
  bounded, pre-phase measurement** of the concrete candidate:

  ```
  before the formal phase starts
    -> isolated subprocess, same candidate
    -> target GPU, actual phase, batch, segment, config, runtime settings
    -> measure the candidate process tree's own driver-visible peak
    -> record sampling completeness, attribution, GPU UUID, phase
    -> on success: a typed authoritative requirement
    -> hand to PR B's admission gate
  ```

  If it cannot produce a trustworthy measurement, **it produces no
  requirement** — and O-7 governs what happens next.

  *Rationale, recorded because it is the crux of this PR:* a peak sampled
  **during** a phase cannot decide whether that phase should start. It is
  also a lower bound and describes occupancy rather than need. Promoting it
  would under-state the requirement — the failure direction that causes an
  OOM.


### Superseded decision list

The original D-C1..D-C31 numbering is retained below for traceability with
the first draft. **It is not the live decision list** — §8.A/§8.B/§8.C is.
Mapping:

| First draft | Now |
|---|---|
| D-C1 | O-2 |
| D-C2 | 8.A (unknown is never authoritative) + 8.B (which resolver) |
| D-C3 | O-1 |
| D-C4, D-C5 | 8.B |
| D-C6 | O-3 |
| D-C7, D-C8 | O-4 |
| D-C9 | O-5 |
| D-C10 | O-9 |
| D-C11 | 8.B |
| D-C12..D-C19 | 8.A (all reuse rules frozen); encoding is 8.B |
| D-C20, D-C21 | O-6 |
| D-C22, D-C23, D-C24 | O-7 |
| D-C25, D-C26 | O-8 |
| D-C27 | 8.A (typed boundary is frozen) |
| D-C28..D-C31 | 8.B, except the honesty rule which is 8.A |
| — | **O-10 is new**: which chain formally produces PR B's GPU requirement (§3) |

31 items became 10 operator decisions, 12 frozen invariants and 6
implementation choices.

### Identity and persistence

- **D-C1 — Mandatory identity before persistence.** Which fields must be
  present for an observation to be *written at all*? Options: (a) reject at
  write time; (b) write with an explicit `unusable` marker and exclude from
  bucketing. Consequence: (a) loses evidence, (b) grows a store of records
  that look like data. *Recommendation:* (b) with an explicit typed reason,
  because a refused write is invisible and an unusable record is auditable.
- **D-C2 — Can `model_family="unknown"` ever be authoritative?**
  *Recommendation:* no — it is a bucketing failure, not a family. Requires
  §2.5 to be fixed first, or every existing record becomes unusable.
- **D-C3 — Migration strategy under content-addressing (§2.7).** This is the
  decision with the widest blast radius. Options:
  1. **New schema version, new directory.** Leave the 20 records in place,
     start a v2 tree. Old records readable by old code; no rewrite; no
     history destroyed. Costs: two trees to reason about.
  2. **Re-hash migration.** Read all records with the old model, re-emit
     under the new one, rebuild the index. Costs: a migration script that
     must be exactly right, and the old ids stop resolving.
  3. **Exclude identity fields from the hash.** Hash a stable subset.
     Costs: two records differing only in task would share an id — which is
     precisely the confusion PR C exists to remove. *Not recommended.*
  *Recommendation:* option 1, given 20 records and 0 promotions, the blast
  radius is small and the evidence is worth preserving.
- **D-C4 — Full config identity.** A normalized config hash
  (`identity.config_hash12` is the existing primitive) versus enumerated
  fields. Trade-off: a hash is complete but opaque in reports; enumerated
  fields are legible but never complete.
- **D-C5 — Reading historical records without the new fields.** Ties to
  D-C3. Must state explicitly what an old record means, not merely whether
  it parses.

### Promotion policy

- **D-C6 — What triggers promotion evaluation in production?** Currently
  nothing does.
- **D-C7 — Minimum observation count.** `CalibrationPolicy` has
  `provisional_min_observations` / `validated_min_observations`; the
  operator must confirm the values rather than inherit the defaults.
- **D-C8 — Consistency threshold.** `consistency_max_min_ratio` is currently
  1.5. Confirm or change with evidence.
- **D-C9 — May contended measurements be promoted?** `concurrency_identity`
  is already a bucket dimension, so contended evidence forms its own bucket.
  Decide whether that bucket may ever be authoritative.
- **D-C10 — Expiry.** By time, software stack, hardware change, driver
  generation, or task-config change? *Note:* stack and hardware are already
  bucket dimensions, so a change forks the bucket rather than expiring it —
  the operator should decide whether forking is sufficient.
- **D-C11 — How are rejected promotions reported?**

> **Do not invent thresholds to complete this draft.** D-C7 and D-C8 are
> left unfilled deliberately.

### Applicability

- **D-C12** — which identity fields must match **exactly**;
- **D-C13** — which numeric dimensions may match by **bounded range**;
- **D-C14** — what makes a candidate out-of-range;
- **D-C15** — does a bucket match establish applicability, or only a
  candidate set? (§6 invariant 3 says the latter; this makes it binding.)
- **D-C16** — how cross-hardware reuse is prohibited. **A 5090 measurement
  must never become H100-authoritative.** GPU UUID is currently absent
  entirely (§2.6).
- **D-C17** — how task and dataset/data-shape mismatch is prohibited.
- **D-C18/D-C19** — how phase-specific evidence stays separate, and how
  training and inference measurements are prevented from substituting for
  each other. PR B already established these are 1.8× apart and not
  interchangeable.

### Admission authority

- **D-C20 — May applicable validated calibration both allow *and* reject?**
- **D-C21 —** Or may it only allow, with rejection still requiring a live
  measurement? *Recommendation:* the asymmetric form. A wrong allow costs an
  OOM; a wrong reject costs a scientific conclusion, which is the V19
  failure mode.
- **D-C22 —** When is a bounded live probe mandatory?
- **D-C23 —** What happens when the probe is inconclusive? (Must not become
  allow or reject — invariant 4.)
- **D-C24 —** What happens when no bounded probe is available?
- **D-C25 —** What happens when live evidence contradicts validated
  calibration?
- **D-C26 —** Does live evidence invalidate, supersede, or annotate the
  bucket?
- **D-C27 —** Does PR C supply `measured_requirements` as-is, or replace the
  duck-typed `getattr` with a typed boundary? *Recommendation:* the typed
  boundary — a duck-typed read that no production code satisfies is how this
  gap survived PR B.

### Reporting and provenance

- **D-C28** — counts for collected / bucketed / unbucketed / eligible /
  promoted / rejected / unusable.
- **D-C29** — representation of rejection reasons.
- **D-C30** — every admission record must identify: evidence source,
  evidence tier, bucket identity, sample count, applicability decision,
  final authority, resolved policy source.
- **D-C31** — how the campaign avoids claiming calibration is active when
  zero authoritative buckets exist. **Today that claim would be false on
  this machine: 20 observations, 0 promotions.**

---

## 9. Genericization impact and in-passing refactor

Binding per `v20_priorities.md` §1.4. Answers to the seven required
questions.

**1. Which touched modules are generic infrastructure?**
`core/runtime_control/` in full — `registry_schemas.py`,
`calibration_policy.py`, `calibration_registry.py`, `observation_store.py`,
`probe_lifecycle.py`, `probe_wiring.py`, `admission.py`,
`core/sandbox_executor.py`.

**2. Which are task-, dataset- or hardware-owned?**
The estimator's model-family knowledge (already correctly placed outside the
generic worker layer, per the 2026-08-01 hardcoding audit); the task's own
notion of data-shape class; `configs/task_config.yaml`.

**3. What TIDMAD-specific assumptions cross into generic code?**

Two kinds, and the second is worse.

*By presence* — §2.8 in full: the probe path is gated on `TIDMAD_DATA_DIR`
(`probe_wiring.py:72-79`), `segment_length` is a required field of the
generic estimate request (`estimate_types.py:155`), `seg_size` is required
for calibration eligibility (`observation_store.py:120`), a TIDMAD model
name is inside a persisted `Literal` (`campaign.py:38`), and a constant
named `SEGMENT_LENGTH` carries a TIDMAD value into the time model
(`evaluate_time_skill/wrapper.py:65`).

*By absence* — the decisive one: the calibration registry has no `task` and
no `dataset` dimension (§2.6) while living at a single per-user root. That
is only safe if there is exactly one task per account. An assumption
expressed by omission is harder to find than a hardcoded constant, and it
fails silently: two tasks with the same `model_family`, hardware and stack
**share a bucket**.

Secondary: `operation` is `setup/training/inference/io`
(`registry_schemas.py:36`) while `RuntimePhase` is
`setup/training/inference/scoring/orchestration` (`phases.py:18`). Neither
is a superset, so a task with a scoring phase cannot express it in the
registry at all, though `RuntimeObservation.components` is keyed by the
five-value vocabulary.

Worth recording as the counter-example: `core/runtime_control/` is otherwise
clean of score name and score direction. `denoising_score` and
higher-is-better appear in the **tuner**
(`ml_hyperparameter_tune_agent.py:1024, 1043, 1061, 1417` and five record
builders), not in the framework. The framework/metric boundary holds at the
`core/` line and breaks inside `nodes/` — which is the right place for it to
break, but PR C must not carry `denoising_score` back across it. Note that
`_build_resource_admission_record` — the builder PR C will reuse — emits a
literal `"denoising_score": None` via `_build_skip_record` (`:424`).

**4. What will PR C move behind a typed boundary?**
Task identity and data-shape class become explicit, typed, required
dimensions of calibration identity — not free text in `workload`. Device
instance identity (UUID) becomes explicit. `model_family` resolution moves
behind the task/plugin boundary via `classify_model_family` or its
successor, rather than defaulting to `"unknown"` in a generic dataclass.

**5. What remains deferred, and why?**
Unifying the `operation` and `RuntimePhase` vocabularies touches every
runtime record and is not bounded by PR C's scope — file as a follow-up.
Unifying System A and System B is a larger architectural question; PR C
should make them *consistent in identity*, not merge them.

**6. How is TIDMAD compatibility preserved explicitly?**
Through configuration and task-owned adapters, with the current values
declared as a labelled compatibility default. **Not** through
`if task == "tidmad":` inside generic runtime modules.

**7. What proves the generic path is not TIDMAD-specific?**
A synthetic second task in the Layer-2 matrix (§10) whose records must land
in a different bucket than a TIDMAD record with otherwise identical
workload numbers. If they collide, the identity contract has failed.

**8. New hardcoding introduced?** Target: none. Any value that must be
chosen (thresholds, ranges) is configured policy, declared as such, with
provenance.

**9. Provenance of resolved values?** Every operational value carries its
resolved source. `GpuAdmissionPolicy.provenance` is the existing pattern,
though it is an untyped dict — PR C should not copy that shape.

---

## 10. Responsibility-oriented decomposition and orchestration impact

Binding per CLAUDE.md. `HyperparamTuningAgent.run()` previously reached
2,487 lines and sat exactly on pyright's complexity ceiling; past it, strict
mode does not degrade — it abandons the whole function, and every annotation
inside goes unverified.

**Measured on `master` @ `5c58c29`:** `run()` spans lines 2692-5092 =
**2,401 lines**, with 236 flow-relevant AST nodes (`If` 73, `IfExp` 70,
`BoolOp` 54, `Try`/`Except` 18, loops 5, comprehensions 16). A wider node
set gives 291. Pyright counts binder flow nodes rather than AST nodes, so
both figures are approximations of the same quantity — but both sit at or
above the 258/259 boundary. The ~86 lines removed since the rule was written
bought no meaningful headroom.

> **Follow-up to file, not to fix here.** `pyrightconfig.json:28` sets
> `"typeCheckingMode": "basic"` with no per-path `strict` list, while the CI
> step at `.github/workflows/ci.yml:43` is named *"Type check — pyright
> (strict, blocking)"*. Pyright does run in CI and is blocking — the PR #160
> claim stands — but the label and the configured mode disagree.
> Reconciling them changes what CI enforces repository-wide and is out of
> PR C's scope.

**PR C must not add promotion, applicability, evidence-selection, reporting
or final-admission branching into `run()`.**

### 10.1 The three existing hooks, in order of preference

1. **`_handle_admission_refusal(...) -> bool`**
   (`ml_hyperparameter_tune_agent.py:537-589`) — already called at exactly
   two points, `:3882` (training) and `:3951` (inference), each a bare
   `if ...: continue`. A per-phase admission-adjacent step belongs inside
   this function or a sibling with the same `-> bool` contract called at the
   same two points, so it adds **zero** new branches to `run()`.
   `_handle_in_subprocess_rejection` (`:2432`, called at `:3897`) already
   establishes the second-handler-at-the-same-seam pattern.
2. **`_emit_record(sandbox, record, *, status=None)`** (`:498-517`) — the
   *declared* seam for evidence reaching a record. Its docstring says so:
   *"the single seam through which runtime evidence reaches a record, so a
   later admission refusal has exactly one place to attach its own."* New
   evidence arrives via `_attach_runtime_evidence` (`:519`) behind this
   call, never as a key set inline at one of the 11 call sites.
3. **`_build_admission_policy(...) -> GpuAdmissionPolicy`** (`:2269-2327`),
   called once per attempt at `:3869`. Resolving `measurement_source` — the
   reference that currently resolves to nothing (`admission.py:165-172`) —
   belongs here or behind it.

Executor-side, if the step must run *at* phase start rather than after:
`core/sandbox_executor.py:540-645` already reads `sandbox.admission_policy`,
samples, calls `evaluate_gpu_admission` and splits enforce/observe-only.
`_phase_requirement` (called at `:555`) produces the
`(requirement_mib, requirement_provenance)` pair that `admission.py:286-295`
documents as PR C's responsibility to supply.

### 10.2 Caveat on the existing extractions

Per CLAUDE.md — *"a helper that still reads and mutates arbitrary outer
state is not a completed decomposition"* — several PR-B-era helpers are
**parameter-passing extractions, not typed boundaries**:
`_handle_admission_refusal` takes 11 arguments, `_check_and_record_guardrail_skip`
15, `_build_skip_record` 13, `_build_resource_admission_record` 12. They do
not mutate outer state, which is the important half. But the nine-field
identity block (`exp_id`, `model_type`, `file_index`, `record_params`,
`expert_advice_str`, `hypothesis`, `round_index`, `attempt_in_round`) is
re-threaded by hand at every call site and is not itself a typed object.

**There is no `AttemptContext` model.** It stays **optional and bounded**:

- Reuse PR B's existing typed boundaries first — `GpuAdmissionPolicy`,
  `_build_admission_policy`, `_handle_admission_refusal`, `_emit_record`,
  `_attach_runtime_evidence`, the record builders.
- Introduce a context object **only if** PR C's own call sites cannot stay
  explicit without it.
- Do not re-thread every call site for theoretical tidiness. **PR C must not
  become a tuner-context refactor PR** — that is a separate piece of work
  with its own parity evidence, filed as FU-C-3.

Intended shape:

```
orchestrator (run)
  -> obtain typed candidate/workload identity        [new boundary]
  -> focused observation/promotion boundary          [new boundary]
  -> focused applicability evaluator                 [new boundary]
  -> focused evidence-selection boundary             [new boundary]
  -> receive a typed admission result                [PR B's, reused]
  -> apply a small high-level transition
```

Each extracted unit needs explicit typed inputs, a typed result, one
documented responsibility, bounded side effects, no arbitrary outer-state
mutation, focused deterministic tests, and **a reachability test that fails
when the production path bypasses it** — the control that was missing
everywhere in §2.2.

PR B's `_build_admission_policy`, `GpuAdmissionPolicy`, the admission record
builders and the B-C4a0 control boundary are the existing seams to reuse.
Retry behaviour, phase order, attempt/round accounting, timeouts,
persistence and scientific behaviour must not change while extracting.

---

## 11. Validation design

Three layers, per the V20 principle.

### Layer 1 — deterministic delivery and authority

Must prove:

- production observations reach promotion evaluation;
- promotion decisions reach the registry;
- real family/config identity reaches the observation (the §2.5 defect);
- missing mandatory identity cannot become authoritative;
- task / data-shape / phase / hardware mismatch blocks applicability;
- formal admission cannot terminate at an unlabelled advisory (§3);
- inconclusive evidence cannot silently allow or reject;
- every evidence source and final authority is recorded;
- **removing the production call site fails a reachability test**;
- **hand-built intermediate dicts cannot substitute for the real
  producer→consumer path.**

The last two are not boilerplate. Every defect in §2 survived a large test
suite because helpers were tested in isolation and the composed path was
not — the same shape as #156, #157, #159 and the A5 field-drop.

### Layer 2 — controlled applicability matrix

At minimum:

```
same task / same data shape / same hardware / same config
same family, materially different config
same model name, different task
same task, different data-shape class
same candidate, different GPU UUID
training evidence applied to inference
inference evidence applied to training
idle evidence vs contended evidence
insufficient sample count
inconsistent observations
expired or stack-mismatched calibration
validated calibration contradicted by a live measurement
missing model family
unknown model family
inconclusive live probe
```

Repeated samples where promotion quality depends on statistical
consistency.

#### Layer-2 completion matrix — C1 `[x]`

Every row below is asserted by a named test. The identity rows are
parametrised from `IDENTITY_ROWS` in `test_calibration_read_authority.py`,
each varying **exactly one** dimension so a green row names precisely which
reuse rule refused.

| Row | Outcome | Test |
|---|---|---|
| matching identity, in-range workload | **authoritative** | `test_matching_identity_and_in_range_candidate_is_authoritative` |
| cross-task | refused | `IDENTITY_ROWS[cross-task]` |
| cross-data-shape | refused | `IDENTITY_ROWS[cross-data-shape]` |
| cross-GPU-UUID | refused | `IDENTITY_ROWS[cross-device-uuid]` |
| cross-phase (training↔inference) | refused | `IDENTITY_ROWS[cross-phase]` |
| cross-measurement-kind | refused | `IDENTITY_ROWS[cross-measurement-kind]` |
| runtime-stack mismatch | refused | `IDENTITY_ROWS[cross-stack]` |
| cross-family / cross-candidate-config | refused | `IDENTITY_ROWS[cross-family, cross-candidate-config]` |
| in-range workload | granted | `test_the_candidate_is_in_range_in_every_identity_row` |
| out-of-range workload, identical identity | refused | `test_out_of_range_candidate_is_refused_despite_identical_identity` |
| dimension with no measured evidence | **fails closed** | `test_a_dimension_with_no_measured_evidence_fails_closed` |
| missing identity | refused | `test_an_observation_without_identity_is_refused` |
| unknown model family | never authoritative | `test_an_unknown_family_never_inherits_known_family_calibration` |
| insufficient observations (1 < 2) | candidate only | `test_one_observation_stays_candidate_only` |
| 2 consistent / 3 consistent | provisional / validated | `test_two_consistent_observations_are_provisional`, `test_three_consistent_observations_are_validated` |
| inconsistent observations (ratio > 1.5) | promotion blocked | `test_ratio_above_limit_blocks_promotion` |
| ratio exactly at the limit | promotes | `test_boundary_ratio_exactly_at_limit_promotes` |
| concurrency-class separation | separate buckets | `test_each_dimension_separates_buckets`, `test_idle_bucket_is_never_polluted_by_pairwise_writes` |
| contended / unknown contention | never eligible | `test_contended_and_unknown_are_never_calibration_eligible` |
| duplicate event / re-evaluation | idempotent | `test_re_evaluating_an_unchanged_bucket_is_idempotent`, `test_recording_the_same_promotion_twice_is_idempotent` |
| quarantine | kept, never authoritative | `test_calibration_quarantine.py::TestQuarantinedEvidenceHasNoAuthority` (5 tests) |
| empty registry | INACTIVE, reason given | `test_an_empty_registry_is_inactive_and_says_why` |
| unreadable registry | UNREADABLE ≠ empty | `test_an_unreadable_registry_is_not_reported_as_empty` |
| unusable registry root | UNREADABLE, never raises | `test_an_unusable_root_is_reported_not_raised` |
| zero authoritative buckets | INACTIVE despite evidence | `test_observations_without_promotion_are_still_inactive` |
| historical contents vs live verdict | **no effect** | `test_the_verdict_is_a_function_of_the_live_measurement_only` |

*Rows deferred to C2, with reason.* `validated calibration contradicted by a
live measurement` and `inconclusive live probe` both describe a **consumer**
resolving stored evidence against a live one. C1 has no such consumer — the
C-C5b cancellation means the live measurement is the only production input,
so there is nothing to contradict. `expired calibration` likewise needs a
consumer to expire *for*. These move to C2 with the GPU-requirement gate.

#### Layer-1 reachability checks — C1 `[x]`

| Claim | Test |
|---|---|
| successful production events write duration observations | `test_the_derivation_is_called_in_production`, `test_it_is_called_from_run` |
| System A is durable before the derived view | `test_it_runs_after_the_system_a_append` |
| failure/timeout/rejection never enter calibration | `test_no_failure_handler_derives_calibration` (parametrised), `test_the_shared_append_helper_does_not_derive` |
| exactly one derivation seam | `test_the_derivation_is_called_exactly_once_in_the_tuner` |
| promotion trigger is production-reachable | `test_the_promotion_trigger_is_reachable_from_production` |
| only an eligible write triggers promotion | `test_promotion_is_triggered_only_by_an_eligible_write` |
| quarantined evidence never reaches promotion | quarantine records are structurally disjoint from `iter_observations()`, which is promotion's only input (`test_the_two_lists_are_disjoint_by_construction`) |
| System B failure never costs an attempt | `TestLosingCalibrationNeverCostsAnAttempt` (4 tests) |
| identity is never fabricated | `TestIdentityIsNotFabricated` (2 tests) |
| reporting is production-reachable | `test_bootstrap_render_survives_an_unusable_registry_root` |
| historical data is NOT production-decision-reachable | `test_historical_duration_is_observability_only.py` (9 tests) |

### Layer 3 — bounded real confirmation, one per PR

The two PRs measure different quantities and must be confirmed separately.
**C1's success must not depend on PR B admission, and C2 must never accept a
duration promotion as GPU evidence.**

**C1 — time calibration**

```
real duration observation (normal formal run)
  -> v2 identity: task, data-shape class, family, phase, GPU UUID,
     measurement_kind = duration
  -> promotion evaluated under the O-4 values
  -> applicability checked against the envelope
  -> the calibration-state report
```

> **Corrected 2026-08-02.** This flow previously ended `-> time-budget
> consumer and the calibration-state report`. The time-budget consumer was
> cancelled (see C-C5b above); historical duration is observability-only, so
> the report is the terminus. C1 Layer-3 therefore confirms the **write,
> promotion and reporting** path end-to-end, not a consumption path.

Passes without any GPU requirement existing. Formal admission still reports
`policy_unavailable` throughout — expected after C1, not a defect.

**C2 — GPU requirement**

```
real candidate
  -> isolated bounded PRE-PHASE measurement on the target GPU
     (actual phase, batch, segment, config, runtime settings)
  -> candidate-owned driver-visible peak, with sampling completeness
     and attribution recorded
  -> typed authoritative requirement (MiB), measurement_kind = gpu_requirement
  -> PR B admission gate
  -> phase allowed, or stopped under O-7
  -> decision, authority and provenance persisted
```

**Hardware rule, unchanged:** a measurement promoted as H100-authoritative
must be collected on the H100 itself; a 5090 measurement is never
H100-authoritative. Implementation and unit tests need no H100. Not run
while drafting.

---

## 12. Gate assignment and bounded real validation

§11 gives the three validation layers. This section assigns the **named
gates** from `docs/gates/gate_testing_standard.md`, because "Layer 3" and
"Gate 2" are not the same thing and the difference decides what actually has
to be run before each merge.

No real GPU or LLM run in this section may start without operator approval,
with the exact command and expected cost presented first.

### 12.1 PR C1

**Gate 1 — NOT REQUIRED.**

Gate 1 exists for *"any commit that changes an LLM-facing system prompt or
schema (implementor, proposer, validator, interpreter)"*. C1 changes
calibration identity, persistence, promotion, applicability and reporting.
None of it is LLM-facing.

If implementation later touches a proposer, implementor, validator or
interpreter prompt or output schema, **that specific change requires Gate 1
before merge** — the exemption is scoped to what C1 is planned to touch, not
to the PR as a whole.

**Standard Gate 2 — NOT REQUIRED, and would be the wrong instrument.**

Gate 2 drives a real LLM, which may propose a *different candidate on every
attempt*. C1's subject is repeated observations of the **same** identity
reaching a promotion threshold. A normal agent chain would produce a handful
of unrelated candidates and exercise the thing under test barely or not at
all — expensive, slow, and uncontrolled for this purpose.

**C1 requires instead: one bounded, no-LLM, real-training calibration
validation**, through the real production entry points:

```
fixed candidate and configuration
  -> repeated real duration observations
  -> v2 registry write
  -> affected-bucket promotion evaluation (O-3)
  -> applicability evaluation
  -> calibration-state report          <- terminus (C-C5b cancelled)
```

Requirements — see §17a for the pre-registered plan and §17b for the executed
evidence:

- [x] a **temporary v2 registry**; the live v1 tree is read-only evidence
      and is never written to or rebuilt;
- [x] the same candidate and configuration repeated enough times to cross
      the frozen O-4 threshold (`validated_min_observations = 3`, with
      `consistency_max_min_ratio = 1.5`);
- [x] every identity dimension recorded: task, data-shape class, phase,
      model family, GPU UUID, runtime stack, measurement kind;
- [x] a mismatching task, GPU UUID, phase or measurement kind is **rejected**
      — the frozen §8.A isolation rules, proven on real records rather than
      constructed ones;
- [x] the report says calibration is **inactive** while zero authoritative
      buckets exist.

**A Gate is evidence, not a checkbox.** Every box above is claimed only
against §17b, which records the exact command, the Git SHA it ran at, the
candidate and configuration, the temporary registry and workspace paths, the
expected versus actual duration, the retained artifacts, the promotion
results, the reporting results, and the two negative proofs (registry history
does not move the live verdict; the v1 tree is byte-identical). A box ticked
without a matching §17b entry is a defect in this document.

**Recorded acceptance-gate determination for C1:**

| Gate | Determination | Reason |
|---|---|---|
| **Gate 1** | **N/A — not applicable** | C1 changes no LLM-facing prompt, schema or decision surface. It touches calibration identity, persistence, promotion, applicability and reporting only. Scoped exemption: if any later commit on this branch touches a proposer/implementor/validator/interpreter prompt or output schema, that commit requires Gate 1 before merge. |
| **Standard Gate 2** | **N/A — not applicable, and the wrong instrument** | Gate 2 drives a real LLM, which proposes a different candidate per attempt. C1's subject is *repeated observations of the same identity* crossing a threshold; a normal chain would exercise it barely or not at all. |
| **C1 Layer-3 bounded validation** | **REQUIRED — executed, see §17b** | Fixed candidate, no LLM, real production entry points, real training, temporary registry. |

Neither Gate 1 nor Gate 2 is described as *passed*. They are recorded as **not
applicable, with the reason**, which is a different claim.

This is a real-system validation and it is deliberately **not** Gate 2: no
LLM is involved, and its subject is the calibration chain rather than the
agent loop.

### 12.2 PR C2

**Gate 1 — NOT REQUIRED BY DEFAULT.** C2 changes resource measurement and
admission plumbing. It becomes required if C2 changes planner/proposer
resource feedback, an LLM-facing status or schema, or any prompt text that
explains an admission or measurement outcome.

**Gate 2 Lite — REQUIRED BEFORE MERGE.** C2 changes what happens *before a
formal GPU phase starts*, so it must be proven in a real chain that reaches
a formal round. Canonical Lite Plan (`gate_testing_standard.md` §"Gate 2
parameter plans"), quoted rather than reinvented:

| Parameter | Value |
|---|---|
| `--num_iterations` / `--start_iteration` | 1 |
| `--max_rounds` | 2 (1 trial + 1 forced formal) |
| `--max_proposal_attempts` | 3 |
| `--data_scope` | `4-9` (6 files) |
| `--health_gate_files` | `4,5,6,7,8,9` (matches scope exactly, DS8-mandatory) |
| Seeds | **NONE — cold start** |
| trial / train / eval portions | 0.02 / 1.0 / 0.01 |
| formal / formal_train / formal_eval | 0.02 / 1.0 / 0.01 |
| `--max_epochs` | 1 |
| `--trial_time_budget_minutes` | 5 |
| `--formal_time_budget_minutes` | 30 |
| VRAM budgets | 24 / 24 (generous — the VRAM gate must not eat a Gate attempt) |
| `--runtime_watchdog` | on |
| `force_formal_round` | **ON** — required, since the feature under test is formal admission |
| `--llm_config` | `openai_tiered_v1.json` |

Estimated ~30-45 min, ~$1.

**In addition to the standard Gate 2 criteria, C2 must prove:**

- [ ] the isolated pre-phase measurement starts **before** the formal GPU
      phase;
- [ ] it uses the concrete candidate, actual phase, batch, segment, task and
      target GPU;
- [ ] candidate-owned **driver-visible process-tree** memory is recorded
      (`own_tree_mib`), not the device total;
- [ ] sampling completeness and attribution are recorded;
- [ ] the typed authoritative requirement reaches PR B's gate;
- [ ] admission no longer resolves to `policy_unavailable`;
- [ ] the formal GPU child starts **only after** admission allows it;
- [ ] training and inference requirements remain distinct (B-G0 measured
      them 1.8x apart);
- [ ] timeout, unavailable measurement, host-memory failure and contention
      produce **no candidate blame and no shrink advice**;
- [ ] evidence, authority and final disposition are all persisted.

### 12.3 C2 refusal-path validation — executor level, not Gate 2

A full Gate 2 run per refusal case would be slow, expensive and
non-deterministic, and a refusal that only ever happens by luck is not
really tested. Drive the **real production executor** directly for:

- pre-phase measurement unavailable;
- pre-phase measurement inconclusive;
- wrong GPU UUID;
- wrong task or data-shape identity;
- phase mismatch;
- contention-attributable evidence.

Pass criteria for the inconclusive and unavailable cases (O-7):

- [ ] the GPU phase does not start;
- [ ] the attempt is consumed;
- [ ] no completed round is recorded;
- [ ] no candidate blame;
- [ ] no shrink advice;
- [ ] **no same-attempt retry loop is introduced** — only the existing outer
      attempt budget may produce another attempt.

### 12.4 The final V20 Gate

C1 and C2 passing their own validation does **not** replace it.

After PR C1, C2, D and E are complete, one bounded final Gate runs through
the real production entry points and exercises the composition:

- calibration reachability;
- authoritative pre-phase GPU measurement;
- PR B admission;
- HealthGate formal policy (PR D);
- zero-valid-trial behaviour;
- campaign-scoped control state (PR E).

Its subject is how the launch blockers behave **together**. It is not the
first validation of any individual PR, and a PR that has not passed its own
gate does not enter it.

---

## 13. Stop conditions

Stop and report rather than proceeding if:

- the migration decision (O-1) would destroy or orphan existing evidence;
- a change would let any lane's refusal produce shrink advice;
- a change would alter retry behaviour, LLM call count, or cost;
- an applicability rule cannot be stated without a task-specific special
  case inside generic code;
- production is found to still admit formally on non-authoritative evidence
  in a way not described here.

## 14. Merge criteria

- All Layer-1 tests pass, each with a mutation proof against real production
  source;
- Layer-2 matrix complete, every row with an expected outcome;
- the per-PR bounded real validation assigned in §12 — C1's
  fixed-candidate no-LLM calibration run, C2's Gate 2 Lite — each approved
  by the operator before it runs;
- neither PR's validation substitutes for the final V20 Gate (§12.4), whose
  subject is how the launch blockers behave together;
- no new fail-open default (the §2.10 table unchanged in length);
- `run()` gains no new responsibility;
- exact-head CI green, including the repository's configured blocking
  pyright check — currently `typeCheckingMode: "basic"`
  (`pyrightconfig.json:28`), despite the CI step being *named*
  "strict, blocking". PR C must not claim strict; see FU-C-1 in §14;
- every operator decision in §8.C answered in this document before
  implementation.

## 15. Deferred

- Unifying `operation` and `RuntimePhase` vocabularies.
- Merging System A and System B.
- Registering the legacy k-table as a legacy source.
- `_ROLE_DEFAULT_RSS_GB` keyed by task phase name (FU-B-6).
- The dead seams listed in §2.2 that PR C does not revive — each should be
  either wired or removed, not left as apparent coverage.
- **FU-C-1**: `pyrightconfig.json:28` says `basic` while the CI step
  (`.github/workflows/ci.yml:43`) is named `strict` (see §10). Repository-wide effect; needs its own decision.
- **FU-C-2**: `CampaignTrack` (`campaign.py:38`) bakes the TIDMAD model name
  `fcnet` into a persisted `Literal`.
- **FU-C-3**: the `AttemptContext` typed object (§9.2) if PR C's own
  checkpoints do not need it.
- **FU-C-4**: `evaluate_time_skill/trigger_policy.py:34` `SEG_SIZE_BOUNDS =
  (2500, 40_000)` — parameterised in the signature but never overridden by
  its sole production caller (`evaluate_time_skill/wrapper.py:518-530`), so
  the TIDMAD divisors are effectively constants.
- **FU-C-5**: `_build_resource_admission_record` emits a literal
  `"denoising_score": None` through `_build_skip_record` (`:424`) — a metric
  name inside a resource-admission record.
- **FU-C-6**: `core/runtime_control/probe_production.py` is in practice a
  **TIDMAD-specific probe runner**. It falls back to `TIDMAD_DATA_DIR` at
  `:137` when no `data_dir` is supplied, and loads TIDMAD-shaped batches
  through `execute_tools.probe_data.load_probe_batch` at `:148`. Supporting
  a second task needs a **task/dataset adapter**, not more branching inside
  generic runtime-control. Not blocking C-C3b, whose subject is the
  capability gate; recorded so the next task port starts from the adapter
  rather than from an `if task ==` inside `core/`.
- **FU-C-7**: `core/runtime_control/bootstrap.py:439` imports
  `TIDMAD_DATA_DIR` for its dataset readiness check. It is an **operator
  CLI** for this task and sits outside the production decision path, so it
  is not on the critical gate; it should move behind the same adapter as
  FU-C-6 when that exists.
- **FU-C-8**: `.claude/settings.json:9` registers the commit-approval hook by
  absolute path (`/home/yuema137/SIDERIUS/.claude/hooks/...`). The hooks are
  developer tooling rather than production code or tests, so this is not a
  breach of the portability rule in `CLAUDE.md` — but in a checkout at any
  other path the guard **silently stops running** rather than failing, which
  is the worse failure mode for a safety hook. Found while inspecting the
  hook for its sanctioned approval mechanism during C-C4. Unrelated to
  calibration; deliberately **not** fixed inside PR C1.

---

## 16. Implementation splits into two PRs

**This document remains the umbrella design and launch-blocker record.
Implementation is two separately reviewable PRs.**

§3 established two causal systems with different units, producers,
consumers and authority. Once O-10 fixed the authoritative GPU producer as a
*dedicated pre-phase probe* rather than the registry, they stopped being one
chain in any sense — so one PR would violate the project rule that a PR
addresses one causal problem.

```
PR C1  calibration identity, reachability and promotion
       unit: milliseconds        consumer: time-budget decisions
       does NOT feed PR B

PR C2  authoritative GPU requirement acquisition and delivery
       unit: mebibytes           consumer: PR B's admission gate
       depends on C1's identity framework, not on its values
```

They **share** `MeasurementIdentity`, `ApplicabilityEnvelope` and
`PromotionPolicy` (§8.1), established by C1. They **must never share a
physical measurement value or an authority**: `measurement_kind` is an
exact-match identity dimension precisely so a promoted millisecond can never
answer a memory query.

### 15.1 PR C1 — calibration identity, reachability and promotion

Scope: schema v2 and the new registry tree (O-1); the three-model split; the
generic task/dataset measurement capability (§15.3); time-calibration
write-path reachability; promotion (O-3, O-4, O-5) and applicability;
honest calibration-quality reporting.

Checkpoints: **C-C1, C-C2, C-C3, C-C4, C-C5, C-C7, C-C8** below.

**Merge criteria** (in addition to §14):

- Layer 1 deterministic tests, each with a mutation proof against real
  production source;
- Layer 2 identity/applicability matrix;
- **the fixed-candidate, no-LLM, real-training calibration validation of
  §12.1** — not a standard Gate 2, which would drive an LLM proposing a
  different candidate each attempt and so barely exercise repeated
  observations of one identity;
- **Gate 1 only if** implementation ends up touching an LLM-facing prompt or
  schema;
- a normal formal run leaves a duration observation in the **new** tree; a
  bucket reaches `validated` only under the frozen O-4 values; the report
  tells the truth about an uncalibrated system; the v1 tree is untouched and
  still readable.

**Explicit non-goal:** C1 delivers **no** GPU requirement to PR B. Formal
admission continues to report `policy_unavailable` after C1, and that is
correct, not a regression.

### 15.2 PR C2 — authoritative GPU requirement acquisition and delivery

Scope: the dedicated isolated pre-phase GPU measurement (O-10);
candidate-owned driver-visible process-tree memory; cold-start acquisition
(the D-B5 case PR B deferred); the typed evidence-selection boundary;
delivery to PR B's gate; O-7 behaviour when the probe is inconclusive or
unavailable.

Checkpoints: **C-C5a, C-C6** below, re-scoped around the pre-phase probe.

**C2 implementation is NOT yet authorized.** Before any production code, C2
must complete a **read-only producer audit** and bring its findings back:

- [ ] PR A's isolated worker (`agent/skills/evaluate_vram_skill/isolated_probe.py`)
      — can it host the pre-phase measurement, or is a separate worker needed?
- [ ] The training/inference sandbox entry points, and how the actual phase
      settings reach them, so the probe measures the configuration that will
      really run.
- [ ] How a **short bounded** probe can be shown to cover the steps that
      actually produce the peak — a probe that stops before the peak
      under-states the requirement.
- [ ] How the candidate-owned driver-visible **process-tree** peak is
      measured (`own_tree_mib`, §3.1) rather than the device total.
- [ ] How sampling completeness is decided, and what makes a sample
      incomplete rather than merely small.
- [ ] Whether the probe itself perturbs allocator behaviour or otherwise
      under-reads the real phase — the caching allocator retains memory
      across a process's life, and a fresh probe process may not reproduce
      steady-state retention.

The last two are the ones that decide whether this PR is safe at all. Until
they are answered, writing the producer would mean choosing the architecture
of the most safety-critical measurement in the system while implementing it.

**Merge criteria** (in addition to §14):

- Layer 1 deterministic tests with mutation proofs;
- the controlled GPU applicability scenarios of §11;
- **Gate 2 Lite (§12.2) — required**, cold start, no `--seed_paths`,
  partial `--data_scope 4-9` with matching `--health_gate_files`, one forced
  formal round, plus the ten PR-C-specific pass criteria;
- the §12.3 executor-level refusal cases, driven directly rather than by
  repeated Gate 2 runs;
- **Gate 1 only if** C2 changes planner/proposer resource feedback, an
  LLM-facing status or schema, or admission/measurement prompt text;
- an applicable pre-phase measurement produces `requirement_mib` with
  provenance in `AUTHORITATIVE_PROVENANCE`; an inconclusive probe stops the
  attempt per O-7 with no candidate blame and no shrink advice; **PR B's
  three refusal lanes remain distinct**
  (`test_refusal_lane_distinctness.py` unchanged and green).

**Explicit non-goal:** C2 changes no enforcement default. Flipping
`observe_only` to `enforce` is a production-default change needing its own
evidence and approval.

### 15.2.1 Producer audit — findings (read-only, 2026-08-03 UTC)

Two findings change what C2 can be built on. Both were verified directly, not
inherited from the audit report.

**F1 — PR A's isolated worker cannot host this measurement: it never touches
the GPU.**

Verified: there is **no** `.cuda()`, `max_memory_allocated`,
`reset_peak_memory_stats` or `memory_reserved` anywhere in
`agent/skills/evaluate_vram_skill/`, and `structural_probe.py:231` declares
`device: torch.device | str = "cpu"` with every call site omitting the
argument. The pre-flight runs a **CPU structural trace plus arithmetic**:
there is no real backward (`unpack_hook` raises by design), no optimizer at
all, and the CUDA context and cuDNN workspace are two frozen constants
(`overhead.py:52-53`). Its `cuda_peak_allocated_gb` and
`cuda_peak_reserved_gb` fields are declared and never written.

**This contradicts PR B's design document.**
`pr_b_gpu_aggregation_attribution.md:2080-2085` proposes *"Direction C —
reuse the pre-flight worker's own measurement… that worker really allocates
— its in-process ancestor is what held 6,962 MiB in V19."* The 6,962 MiB was
V19's **in-process** pre-flight, which PR A replaced; the worker PR A shipped
allocates nothing on the device. A C2 plan built on that paragraph would
inherit a false premise. Corrected in place in that document.

What PR A's worker *does* contribute is its process-control shell — own
process group, parent-side RSS bound, TERM/grace/KILL, orphan detection,
atomic bounded result, and a typed outcome vocabulary with explicit authority
semantics. That shell is sound; its measurement core is not what C2 needs.

**The realistic host is a different subsystem that already exists:**
`core/runtime_control/probe_subprocess.py` + `probe_worker_main.py` +
`probe_production.py` — real model, real optimizer mirroring the trainer
(`probe_production.py:158-168`), real data with no synthetic fallback
(`:135-152`), real forward/backward/step (`:195-199`), 3 warmup + 7 timed
steps (`probe.py:60-68`), own process group, hard deadline, and a parent-side
device-sampling seam (`probe_subprocess.py:397-401`). It is not currently
reachable from the chain.

**F2 — the existing probe reports one cumulative peak, not per-phase peaks.**

`probe_production.py` calls `reset_peak_memory_stats()` **exactly once**
(one occurrence in the file), inside `_setup` at `:123`. `_peak_vram_gb`
(`:219-223`) then returns `max_memory_allocated()` — a running maximum over
setup **plus** 10 training steps **plus** 5 inference batches, in one
process. So `ProbeResult.peak_vram_gb` is a single end-to-end number, and the
inference portion runs with the model, gradients and optimizer state still
resident.

That is incompatible with the per-phase contract `_phase_requirement`
requires (`core/sandbox_executor.py:467-500`), whose own docstring records
B-G0 measuring the same PUNet candidate at **1,476 MiB training vs 2,716 MiB
inference — 1.8x apart on one card, in one run**.

**Classified as a C2 producer limitation, not a live production defect.**
Verified consumption:

- `_phase_requirement` **never reads** `peak_vram_gb`; it reads
  `sandbox.measured_requirements`, which has no producer (§2.4). So nothing
  today consumes this value as a phase-specific requirement.
- The one production consumer is `decision_policy.py:286-300`, a
  **whole-candidate** budget check (`estimate.peak_vram_gb > budget.vram_gb`).
  A cumulative maximum **over-states** there, which is the conservative
  direction for a rejection gate — it can refuse too eagerly, never admit too
  eagerly.

No hotfix in C1. C2 must reset per phase and record two independent peaks.

**F3 — the under-read risk is unbounded by evidence, and every axis points
the same way.**

The repository states outright that there are **zero data points** on
worker-peak versus training-peak (`pr_b:2087-2091`). The only retention
measurement is ~60 MB of reserved-minus-allocated in a 5-step process
(`docs/phase66_deterministic_vram_and_hardening.md:821-822`), which cannot
explain A6's 1.95x gap at 12.5 GiB — so most of that divergence is something
a short probe would not reproduce. Divergence axes, all in the OOM
direction: allocated < reserved < driver-visible; one reused batch < a
DataLoader's pipeline; 10 steps < an epoch; solo < two concurrent chains.

This is the question §15.2 says decides whether C2 is safe at all, and it
remains open.

**F4 — smaller, recorded for correctness of this document.** §3.1 describes
`GpuAccountingSnapshot` as *"one bounded nvidia-smi query"*.
`gpu_accounting.sample` issues **two** (`:315` for device totals, `:335` for
per-process rows), each with its own 10 s timeout.


### 15.3 Shared prerequisite — a typed measurement capability

`probe_runner_availability()` (`probe_wiring.py:72-79`) refuses unless
`TIDMAD_DATA_DIR` is readable, so on any other task the measured path
disables itself silently (§2.8). This is a **named checkpoint in C1**, not a
remark in another commit's scope, because C2's pre-phase probe inherits the
same gate.

Generic runtime-control consumes a typed object and stops importing
`TIDMAD_DATA_DIR`:

```
ResolvedMeasurementCapability
  task_identity
  dataset_adapter
  data_shape_class
  probe_available
  target_device
  supported_phases
  unavailability_reason      # never silently False
```

`unavailability_reason` is required when `probe_available` is False — an
unavailable probe must say why, per O-7 and the no-fail-open invariant.

---

## 16-STATUS. C1 final state — reconciled against code, Git, PR and artifacts

Reconciled 2026-08-03 by inspecting the working tree, `git log`, PR #161, the
test suite and the retained validation artifacts — **not** by trusting an
earlier summary. Corrections found during reconciliation are listed at the end
of this section.

### The governing principle

> **The current live measurement of the concrete candidate is the sole runtime
> evidence used by the production time-budget decision.**

May remain in the decision — these are **configured policy**, not learned
experience:

* the operator-configured time budget;
* the deterministic projection from the current live measurement;
* the configured safety factor (`SAFETY_MULTIPLIER = 1.3`).

May **not** influence the decision: legacy v1 `k`; v1 historical duration data;
v2 historical duration data; promoted calibration buckets; calibration reports.

Historical duration is **observability-only** — collected, identity-checked,
quarantined, promoted, reported, available for offline analysis and drift
detection. It may not support ALLOW or cause REJECT.

### Legacy v1 status — five explicit answers, each verified from code

| Question | Answer | Evidence |
|---|---|---|
| **v1 production read** (into a verdict) | **NONE** | no `lookup_k`/`load_table` call remains in `core`, `nodes`, `agent`, `execute_tools`, `workflows` outside the legacy module itself |
| **v1 production decision influence** | **NONE** | `estimator.py` no longer multiplies by `k`; `k_correction` removed from the breakdown; 14 guards + 3 positive controls |
| **v1 production write** | **NONE** | the tuner's Phase F post-flight and its import are removed; a repo-wide scan for `save_table`/`update_k`/`make_entry` finds no production caller |
| **v1 audit-only readability** | **PRESERVED** | `calibration.py` stays importable; `load_table`/`lookup_k` still work (asserted). `estimate_types.from_legacy_calibration_entry` is called **only** by the offline `scripts/runtime_replay/legacy_migration.py`, and emits `applicability="not_applicable"`, `confidence="low"` — never blocking-eligible |
| **v1 data integrity** | **UNCHANGED** | tree digest `c1065a8b612fb691…`; `time_calibration_nvidia_geforce_rtx_5090.json` sha256 `6933829e145400dd…`, 313 596 bytes, mtime 2026-07-20 — re-verified after every run |

Both statements are therefore true at the same time, which is the only
acceptable configuration: **legacy v1 is read-only** *and* **C1's legacy-v1
work is complete**. Until `7341840` only the first half of that was true, and
this document said so rather than claiming both.

### Checkpoint reconciliation

| Checkpoint | Status | Evidence |
|---|---|---|
| identity + applicability envelope, per-major registry (O-1), quarantine (O-2) | **COMPLETE** | `f3ab878`, `df10dd7`, `31d1b0c` |
| C-C1 identity-field population | **COMPLETE** | `fa0a43e` |
| C-C2 typed measurement capability | **COMPLETE** | `3927d06`, `7a0de4d` |
| C-C3 derivation → v2 → success-path wiring | **COMPLETE** | `09aa6a3`, `e86d6dd`, `cddc307`; failure paths excluded, one seam only |
| C-C4 affected-bucket promotion (O-3) | **COMPLETE** | `9c8a421`; thresholds 2/3, ratio 1.5 frozen |
| C-C5a applicability safety | **COMPLETE** | `7574ae6`, `bf73a83` |
| shared calibration context / config hash (D-4) | **COMPLETE** | `8f97251`, `8606b47`, `d901412` |
| **C-C5b production consumption of history** | **CANCELLED BY OPERATOR DECISION** | implemented in `95c4539`/`b920b22`/`0d32187`, then **removed forward** in `689fea3`; `wrapper.py` byte-identical to its pre-C-C5b state |
| forward removal + negative guardrails | **COMPLETE** | `689fea3`, `4934ab3` — 9 guards + positive control |
| **legacy v1 `k` removed from the verdict** | **COMPLETE** | `afc009e`, `bc14b97`, `6700261` — §16a-BD |
| **legacy v1 write stopped (FU-C-11)** | **COMPLETE** | `7341840` — §16a-BD-2 |
| C-C7 calibration-state reporting | **COMPLETE** | `ce327bf`; INACTIVE-with-reason, quarantine excluded, UNREADABLE ≠ empty, never raises |
| C-C8 documentation sync | **COMPLETE** | `cd73bb4` … `c4f3982`, `5a5e7b5`, and this section |
| Layer-1 reachability | **COMPLETE** | §11 table |
| Layer-2 matrix | **COMPLETE** (3 rows **DEFERRED** to C2 with reason) | §11 matrix |
| Layer-3 bounded real validation | **COMPLETE** | §17b |
| C-C5a/C-C6 GPU-requirement work | **NOT APPLICABLE to C1** | belongs to C2 |

### Open C1 follow-up

**FU-C-9 — DEFERRED. Does not block C1.** FU-C-10 and FU-C-11 are both closed
by implementation.

**What it is.** `execute_tools/workload_resolvers.py::resolve_training_workload`
iterates `sample_set.items()` with no `None` guard. When `sample_set is None`
it raises `AttributeError: 'NoneType' object has no attribute 'items'`, which
surfaces as `Time check error: TimeEval error: ...` and aborts the round.

**Exactly when it fires.** The tuner picks its mode as:

```python
if plan.is_trial:      mode = "trial"        # SampleSet built
elif trial_allowed:    mode = "formal"       # SampleSet built
else:                  mode = "single_file"  # sample_set = None  ← crash path
```

with `trial_allowed = agent_input.is_trial`. So the crash path is reached
**iff `agent_input.is_trial == False`** — the deprecated single-file
`--file_index` mode.

**Why it does not affect C1 correctness or acceptance:**

1. **C1 never touched it.** `workload_resolvers.py` is not in
   `git diff origin/master...HEAD`, and the unguarded `sample_set.items()`
   is present on `origin/master` at the same line. C1's only change to
   `training_skill/estimator.py` was removing the legacy `k`, which sits
   **downstream** of `_total_train_steps` — the diff touches neither
   `_total_train_steps` nor `sample_set`. The crash was also observed during
   Layer-3 run 2, *before* the `k` removal existed.
2. **The production formal path is unaffected.** A forced formal round sets
   `plan.is_trial = False` while `trial_allowed` stays `True`, so it resolves
   to `mode = "formal"` and **does** build a SampleSet. Formal rounds do not
   traverse the crash path.
3. **The production chain does not reach it.** `run_one_iteration.py` defaults
   `--is_trial` to `True` (`BooleanOptionalAction`); the documented standard
   command in `CLAUDE.md` passes `--is_trial` explicitly.
4. **It changes no C1 behaviour.** It is a missing input guard in a deprecated
   mode — it cannot alter calibration identity, promotion, applicability,
   reporting, or the live-only time authority C1 establishes.

**How it is reachable.** An operator running `scripts/run_comparison.py`
*without* `--is_trial` (that flag is `store_true`, so its default is `False`).
That is the legacy single-file relic the project already treats as deprecated.

**Follow-up scope and owner.** A separate small PR outside C1: either guard
`resolve_training_workload` against `None` with an explicit typed error naming
the mode, or refuse `single_file` mode at input validation. It belongs with
whoever owns the deprecation of single-file mode, not with the calibration
subsystem. **Not a hotfix** — it fails loudly and immediately at pre-flight,
does not corrupt data, and cannot produce a wrong scientific result.

### Corrections made during this reconciliation

1. The status text asserting legacy v1 was "out of C1 scope" was **stale** —
   the operator extended the decision and it was implemented. Corrected.
2. `from_legacy_calibration_entry` was audited rather than assumed: it is a
   read-only adapter whose sole caller is an offline replay script, so it does
   not contradict "no production v1 read".
3. C-C5b is recorded as **CANCELLED**, never as complete, in every place it
   appears — including the checkpoint map, where its three commits are listed
   as superseded rather than dropped.

---

## 16a-BD. Behavior Delta: legacy v1 `k` removed from production time authority

**Operator decision, 2026-08-03.** Supersedes FU-C-10, which is now **closed by
implementation** rather than deferred.

**Before**

```text
current live timing measurement (ms/step, this candidate, now)
  → × legacy v1 historical k        (asymmetric EMA over past runs,
                                     ~/.siderius/time_calibration_<gpu>.json)
  → × SAFETY_MULTIPLIER             (configured)
  → seconds → verdict
```

**After**

```text
current live timing measurement (ms/step, this candidate, now)
  → × SAFETY_MULTIPLIER             (configured)
  → seconds → verdict
```

**Reason.** Runtime depends on current machine conditions, current GPU
contention and current caching. A stored correction prices today's work with
yesterday's clock. This is the same principle that cancelled C-C5b, applied to
the one remaining path that still violated it.

**Runtime evidence authority.** The live measurement of the concrete candidate
is now the **sole** runtime evidence. No v1 `k`, no v1 history records, no v2
history records, no promoted buckets, no calibration report can influence the
verdict.

**Configured policy retained — removing history is not removing safety.**
`SAFETY_MULTIPLIER = 1.3` is unchanged; the operator's time budget is
unchanged; the deterministic projection from the live measurement is unchanged.
These are configured rules, not learned experience.

**Failure semantics.** Unchanged and deliberately re-verified: when the live
measurement is unavailable, the estimator still falls back to the **static
prior** stamped `formal_execution_eligible: False`. **No historical fallback
was introduced** — asserted by
`test_a_missing_live_measurement_does_not_fall_back_to_history`.

**Retry / attempt / round accounting.** No change. Nothing in the removal
touches attempt consumption, round transitions or retry policy.

**LLM impact.** None. **GPU cost impact.** None — one multiplication removed.

**Legacy data handling.** `~/.siderius/time_calibration_<gpu>.json` is
**preserved, not deleted or rewritten**. Verified byte-unchanged (mtime still
2026-07-20). The `calibration.py` module remains importable for audit and
historical inspection; it is now structurally unable to reach the production
verdict, which is what the guard tests assert.

> **Open question deliberately NOT decided here.** The tuner's Phase F
> post-flight (`ml_hyperparameter_tune_agent.py:4861-4863`) still *writes* to
> the legacy table via `update_k`/`save_table`. The operator's instruction was
> to remove the production **read and application**; the write influences no
> verdict, and stopping it is a separate behaviour change. Left in place so the
> historical series stays continuous for drift analysis — which is exactly the
> observability-only role history now has. **Flagged for the operator**: if the
> legacy table should become fully frozen, the write is a one-line follow-up.

**Files and functions changed**

| File | Change |
|---|---|
| `agent/skills/training_skill/estimator.py` | `load_table`/`lookup_k` calls and the `* k` multiplication removed; `k_correction` removed from the breakdown; `calibration` import removed; docstrings corrected |
| `agent/skills/evaluate_time_skill/wrapper.py` | `k_correction` pass-through removed (it was a required key access) |

`k_correction` was **removed, not pinned to `1.0`**: a neutral-valued
correction field reads as "no correction today" and is a socket for one
tomorrow. Its absence is the contract.

**Tests proving the change** —
`tests/unit/core/test_live_timing_is_the_sole_runtime_evidence.py` (11 tests):
structural (no import, no call, no field, no republish), behavioural (an
extreme `k=50` table does not move the estimate; `gpu_name` is inert; an absent
table is identical), and **positive controls** (a slower live measurement
increases the estimate; the projection is exactly linear in it; the configured
margin is still applied).

**Mutation proofs**

| Mutation | Result |
|---|---|
| reintroduce `lookup_k(load_table(...))` into the estimate | **5 tests fail** — 2 structural, 2 behavioural (1625 s → 3250 s), 1 in the inverted estimator test |
| disconnect the live measurement (pin `ms_per_step`) | **3 positive controls fail**, while every absence-guard stays green — the exact blind spot the controls exist to close |

**Gate 1: N/A** — no LLM-facing prompt, schema or decision surface changes.
**Gate 2: N/A** — this implements no GPU-requirement acquisition and touches no
PR B admission path. **C1 Layer-3: re-run required at the new head.**

**Inverted test, recorded.**
`test_ms_per_step_passthrough_applies_gpu_calibration` asserted the *opposite*
of this decision (k=2.0 → 3250 s). It is renamed
`test_a_gpu_name_no_longer_applies_historical_calibration` and inverted rather
than deleted — it is the one test that named the removed behaviour, so it is
where a reader will look for the change.

**Commit SHAs:** `afc009e` (production), `bc14b97` (tests), `6700261` (docs).

## 16a-BD-2. Behavior Delta: legacy v1 table becomes read-only (FU-C-11 closed)

**Operator decision, 2026-08-03 (second part).** The policy is stronger than
"v1 does not decide":

> Existing legacy v1 data is preserved **read-only** for compatibility and
> audit. Production must no longer read from **or write to** the legacy v1 `k`
> table.

**Before.** Every successful run fed its observed-vs-predicted ratio through
an asymmetric EMA into `~/.siderius/time_calibration_<gpu>.json`
(`ml_hyperparameter_tune_agent.py` Phase F post-flight).

**After.** The Phase F post-flight block and its import are removed. Successful
runs write **v2 evidence only** (C-C3c).

**Reason — this is not cosmetic.** A legacy store that keeps growing still
*looks* like a live production system. Three concrete consequences: it presents
as active when it is not; it invites someone to reconnect it to a decision; and
it contradicts the read-only policy while nominally satisfying "does not
decide".

**Authority.** Unchanged from the previous delta — the live measurement was
already the sole runtime evidence. This closes the *producer* side.

**Failure semantics / retry / attempt / round / LLM / scientific results.** All
unchanged. The removed block was wrapped in its own defensive `try/except` and
produced only an operator log line; nothing downstream consumed it.

**Legacy data handling.** Nothing deleted, migrated, rewritten, or neutralised.
The file keeps its contents and its 2026-07-20 mtime. `calibration.py` stays
importable and `load_table`/`lookup_k` keep working — asserted by
`test_the_legacy_module_remains_readable_for_audit`, because the policy is
read-only *preservation*, not removal.

**Drift analysis** moves to the v2 registry, which C1 built for exactly that.

**Tests** (`TestProductionNeverWritesTheLegacyTable`, 3 tests):

| Guard | Proves |
|---|---|
| the tuner imports no calibration module | the only production writer's import is gone |
| **no production module calls `save_table`/`update_k`/`make_entry`** | scanned across `core`, `nodes`, `agent`, `execute_tools`, `workflows` — a writer *moved elsewhere* would satisfy the import guard alone |
| the legacy module still reads | preservation, not deletion |

**Mutation proof.** Reinstating `load_table`/`save_table` in the tuner fails
both the import guard and the repo-wide writer scan (2 tests).

**Gate 1: N/A** — no LLM-facing surface. **Gate 2: N/A** — no GPU-requirement
acquisition, no PR B admission path.

**Commit SHAs:** recorded with the checkpoint map.

### FU-C-11 Layer-3 re-validation (run 5) — the producer side, proven

**The earlier runs could not have proven this.** `SIDERIUS_CALIBRATION_DIR`
governs both the v2 tree *and* the legacy v1 table, so isolating it isolates
the legacy table too: an isolated run says nothing about whether production
still writes v1. Run 5 therefore **seeds a copy of the operator's real legacy
table** into the temporary dir. A surviving writer mutates the copy visibly,
while the real table stays out of reach.

| Evidence | Before | After 3 real training rounds |
|---|---|---|
| seeded legacy copy sha256 | `6933829e145400dd…` | **`6933829e145400dd…` — UNCHANGED** |
| real v1 tree digest | `c1065a8b612fb691…` | `c1065a8b612fb691…` |
| real legacy table sha256 | `6933829e145400dd…` | `6933829e145400dd…` |
| real legacy table size / mtime | 313 596 B / `1784563816` | 313 596 B / `1784563816` |
| `~/.siderius/` contents | 2 entries | 2 entries — no stray `runtime_calibration_v2` |

**v2 accumulated normally in the same run:**

```
calibration: ACTIVE — 2 validated bucket(s) from 6 eligible observation(s)
```

| bucket | n | level | ms/step | max/min |
|---|---|---|---|---|
| `training \| optimizer_step \| single_candidate_idle` | 3 | **validated** | 37.517 / 37.791 / 37.946 | **1.011** |
| `inference \| inference_batch \| single_candidate_idle` | 3 | **validated** | 15.218 / 15.262 / 15.304 | **1.006** |

Full identity on every record, real GPU UUID
`GPU-c30b6678-…`, one `candidate_config_hash` (`cfg:c23fbeb88652`) across rounds
— the same hash as run 4, on a different day and a different registry, which is
itself a stability check on the identity definition.

**So the chain the operator asked for holds end to end:**

```
real training
  → v2 accumulates and promotes normally
  → v1 completely unchanged (copy AND original)
  → live-only time judgement still stands
```

Absolute step times differ from run 4 (37.5 vs 48.7 ms/step training) because
the shared GPU was less contended. That is the point of measuring live rather
than storing: the same candidate is genuinely a different speed on a different
day, which is precisely why a stored `k` should not price it.

---

### Re-validation at the new head — production entry points

The previous exact-head acceptance (`3f5fa23`) **no longer counts**: it
validated code that still applied `k`. Re-run at `6700261`.

**What is reused and why that is legitimate.** The Layer-3 O-4
promotion/reporting evidence (§17b) stands: this change touches only
`training_skill/estimator.py` and `evaluate_time_skill/wrapper.py`, and the
calibration write/promotion/reporting path is byte-identical at this head. The
**time-decision proof** is the part that had to be redone, and it was.

**Bounded production validation — `verdict_invariance.py`.** Drives the REAL
production functions (`estimate_wall_time_seconds`, the changed code, and
`_gate_decision`, the verdict) against REAL on-disk registries — a legacy v1
table carrying an extreme `k=50.0` **and** a v2 tree seeded from the Layer-3
run-4 registry with its two `validated` buckets:

| Case | Registries | live ms/step | seconds | verdict |
|---|---|---|---|---|
| **A** | v1 `k=50.0` + v2 validated buckets | 48.7 | **7.914** | `ALLOW` |
| **B** | both empty | 48.7 | **7.914** | `ALLOW` |
| **C** | v1 `k=50.0` + v2 validated buckets | 40 000 | 6500.000 | **`REJECT`** |

* **INVARIANCE (A ≡ B): PASS.** Identical seconds, verdict and provenance. A
  `k` of 50 would have made A fifty times B.
* **POSITIVE CONTROL (C): PASS.** The verdict genuinely flips `ALLOW → REJECT`
  when only the live measurement changes.

*Control defect found and fixed during this run, recorded because it matters.*
The control first used a 10× slower step (487 ms) and **reported FAIL** — the
seconds moved 7.914 → 79.138, but 79 s still fits a 60-minute budget so the
verdict correctly stayed `ALLOW`. The fault was in the control, not the code: a
positive control for a *verdict* must make the verdict move, not merely the
number feeding it. Re-run with a budget-breaking step time.

**Registry integrity after re-validation:** v1 tree byte-identical
(`c1065a8b612fb691…`); legacy `k` table mtime still 2026-07-20 — the validation
wrote only into temporary trees.

---

## 16b. C1 checkpoint → commit SHA map

Branch `feature/v20-pr-c1-calibration-identity-promotion`.

| Checkpoint | Commits | What landed |
|---|---|---|
| pre-C-C1 groundwork | `f3ab878`, `df10dd7`, `31d1b0c` | measurement identity + applicability envelope; per-major registry tree (O-1); quarantine namespace (O-2) |
| **C-C1** | `fa0a43e` | populate the two identity fields production dropped |
| **C-C2** | `3927d06`, `7a0de4d` | typed measurement-capability boundary, resolved at the task boundary |
| **C-C3** | `09aa6a3`, `e86d6dd`, `cddc307` | derive duration records; persist to the v2 registry; wire to the successful-attempt seam |
| test isolation | `a28b86f` | session-scoped fixture so no test reaches the operator's real registry |
| portability fix | `e44d61f` | remove task-specific GPU names from registry schema docs |
| **C-C4** | `9c8a421`, `55eb2f8` | promotion evaluated for the affected bucket only (O-3) |
| **C-C5a** | `7574ae6`, `bf73a83`, `ae6a0eb` | applicability required for measured authority |
| shared identity (D-4) | `8f97251`, `8606b47`, `d901412` | one calibration context across read and write; dimensions derived from evidence; canonical config-identity helper |
| **C-C5b** (later cancelled) | `95c4539`, `b920b22`, `0d32187` | production read wiring — **superseded, removed forward** |
| **C-C5b cancellation** | `689fea3`, `4934ab3` | wrapper restored byte-identically; `calibration_prelaunch` deleted; nine negative guards + positive control |
| **C-C7** | `ce327bf` | calibration-authority state reporting, wired into `BootstrapReport.render()` |
| **C-C8** | `cd73bb4`, `0cd63bd`, `2f28aef`, `70facb0`, `f77d169`, `b06ef87`, `c3c01c7` | cancellation record, Layer-2 matrix, deviation register, scope correction, gate determinations, registry-safety finding, Layer-3 evidence |

---

## 16a. C1 deviation register — where the implementation departs from this plan

Maintained continuously. Every row is a place the merged code does **not**
match the plan as originally written, with the evidence that forced the
change. A deviation that is not written here is a deviation that will be
rediscovered as a bug.

| # | Plan said | Code does | Why | Evidence |
|---|---|---|---|---|
| D-1 | C-C5b wires the read seam into the time-budget consumer | No production consumer of v2 duration exists | **Operator decision 2026-08-02**: runtime is live; a stored duration prices today's work with yesterday's clock | C-C5b cancellation section; 9 guards + positive control |
| D-2 | (unstated) "current live measurement is the sole time-decision input" | **Now true outright** — after the 2026-08-03 removal of legacy v1 `k`. It was true only of the v2 registry for one day in between, and this document said so rather than overclaiming | The audit found the legacy `k` still scaling the estimate; the operator then decided to remove it inside C1 rather than defer | Behavior Delta §16a-BD; `test_live_timing_is_the_sole_runtime_evidence.py` |
| D-3 | Applicability envelope over a fixed dimension list | Dimensions derived from the evidence (`_measured_dimensions`) | A fixed list silently excluded whichever producer vocabulary it did not name (`seg_size` vs `segment_length`) — a never-match that looks exactly like an empty registry | `8606b47`; `TestTheEnvelopeVocabularyFollowsTheEvidence` |
| D-4 | Each side computes its own config identity | One shared `candidate_config_hash` in `calibration_context.py` | The engine counted `requires_grad` params, the pre-flight counted all of them — identical for a fully-trainable model, silently divergent for any frozen layer | `8f97251`, `d901412`; `test_the_derivation_does_not_define_its_own_hash` |
| D-5 | C-C7 report reads a registry object | C-C7 takes `root=` and constructs inside its own guard | `CalibrationRegistry.__init__` mkdirs six directories, so construction was the one raising step *outside* the "never raises" guarantee | Mutation proof under C-C7 §6 |
| D-6 | C-C7 asserted against a read-only copy of the live v1 registry | Asserted against a fixture reproducing the v1 shape | The live tree is preserved evidence; no test opens it. The fixture reproduces "evidence collected, none promoted" exactly | `test_observations_without_promotion_are_still_inactive` |
| D-7 | Layer-2 covers "validated calibration contradicted by a live measurement", "inconclusive live probe", "expired calibration" | Deferred to C2 | All three describe a **consumer** resolving stored against live evidence. After D-1, C1 has no such consumer — there is nothing to contradict or expire for | §11 Layer-2 matrix, deferred-rows note |
| D-8 | C1 Layer-3 runs a "normal formal run" | Runs `is_trial=True` with a fixed plan | `is_trial=False` falls through to **legacy single-file mode**, which builds no SampleSet and crashes the time estimator on `None`. Pre-existing, deprecated path, unrelated to C1 | FU-C-9; §17a |

**Follow-ups filed from C1**

| ID | Finding | Disposition |
|---|---|---|
| FU-C-9 | `is_trial=False` (legacy single-file mode) builds no SampleSet; `resolve_training_workload` raises `AttributeError: 'NoneType' object has no attribute 'items'` | Pre-existing defect in a deprecated path; not touched by C1 |
| ~~FU-C-10~~ | Legacy v1 per-GPU `k` let history scale the production time estimate | **CLOSED BY IMPLEMENTATION 2026-08-03.** The operator decided the rule extends to the legacy mechanism, and it was removed inside C1. See Behavior Delta §16a-BD. Not deferred. |
| ~~FU-C-11~~ | The tuner's Phase F post-flight still *wrote* the legacy k table, though nothing read it into a verdict | **CLOSED BY IMPLEMENTATION 2026-08-03.** The operator's policy is read-only preservation, which is stronger than "does not decide": a legacy store that keeps growing still looks like a live production system, and that is what invites reconnection. Phase F removed; v2 is the only producer. See the Behavior Delta above |

---

## 16-RECON. C2 design reconciliation onto merged master

**Source.** C2 sections were ported from `audit/v20-pr-c2-producer-audit`
@ `2bd2953` onto `master` @ `781e3e8` (the PR #161 merge commit).

**Why a port and not a merge or rebase.** The audit branch was cut from
**pre-C1 master**. `git diff master audit/…` on this file reported
**510 insertions / 1576 deletions** — merging it would have *deleted* 1576
lines of merged C1 content, resurrecting the cancelled C-C5b wiring and the
superseded "legacy v1 is out of C1 scope" text. The whole file was therefore
never taken; only the C2-only region was.

**Carried forward** (audit-branch lines 1544-1958, verified to contain no C1
text): §16c audit findings · D-C2-1 decision packet and its approval · the
frozen measurement-authority rules · the O-7 implementation boundary · the
two-stage Gate 2 Lite plan · the case matrix · the 5090-vs-H100 split · the
remaining Q11-Q16 answers · the branch-handling procedure.

**Deliberately NOT carried forward:**

* the **superseded single-stage "Gate 2 Lite — plan (NOT executed)" table** —
  replaced by the two-stage Lite-A / Lite-B plan the operator approved on
  2026-08-03. Carrying both would have left two conflicting gate definitions
  in one document.
* **everything else in the file** — all C1 content comes from merged master,
  not from the audit branch.

**Post-port verification.** The reconciled document still states, from the
merged-C1 side: live timing is the sole production runtime evidence
(§C-C5b, §16a-BD); v1 is preserved read-only (§16-STATUS); v2 duration history
is observability-only; C-C5b production consumption is `CANCELLED BY OPERATOR
DECISION`; C1 is complete and merged; and C2's GPU authority is separate from
C1's duration calibration ("C1 delivers no evidence to PR B by design —
duration is milliseconds").

---

## 16c. C2 producer/consumer audit — READ-ONLY findings (2026-08-03)

Branch `audit/v20-pr-c2-producer-audit`, cut from `origin/master` `169899e`.
**No production code changed.** Every finding below is quoted from source, not
inferred from names.

### The headline: there are TWO probe systems, and neither is C2-ready

| | `agent/skills/evaluate_vram_skill/` (PR A) | `core/runtime_control/probe_production.py` |
|---|---|---|
| purpose | VRAM sizing pre-flight | runtime (duration) probe, C10 bootstrap |
| isolation | **yes** — separate process group, RSS-capped worker | in-process executors |
| real forward | yes | yes |
| **real backward** | **NO** | **yes** (`loss.backward()`, `:198`) |
| **real optimizer step** | **NO** | **yes** (`optimizer.step()`, `:199`) |
| memory reported | structural estimate + `cuda_peak_allocated/reserved_gb` | `torch.cuda.max_memory_allocated()` |

**Q4 — does the isolated probe perform a real forward/backward/optimizer
step? NO.** `structural_probe.py:177` says so in its own words — *"because we
never call `backward()` — the probe only measures"* — and `:201` **raises** if
`backward()` is ever invoked. It intercepts `save_for_backward` pack/unpack
hooks to compute what the autograd tape *would* retain.

That is a legitimate design for sizing, and it is **not** an authoritative
requirement: gradients, optimizer state (Adam's two moments), and cuDNN
workspace allocations during backward are estimated, never observed.

**Q2 — can the existing probe subprocess be reused? Partially, and not as-is.**
PR A supplies the *isolation* C2 needs (process group, RSS cap, timeout,
typed outcomes). `probe_production.py` supplies the *real training step*.
Neither supplies both, and the memory figure each reports is the wrong kind
(below).

### The measurement-kind gap — the load-bearing finding

**Q5 — where are CUDA peak stats reset?** Exactly once, in
`probe_production.py:123`, inside `_setup()` **before the model is
constructed**.

**Q6/Q7 — which phases are in the reported peak? All of them, cumulatively.**
`_peak_vram_gb()` (`:221-223`) returns `max_memory_allocated()` whenever
called; with a single reset in setup, the value is the maximum over
setup **+ every training step + every inference batch** since. Training and
inference **cannot** be separated from it. This directly contradicts the
requirement that `sandbox_executor.py:478-487` encodes — a table **keyed by
phase**, with *"deliberately no fallback — not to the other phase, not to the
larger of the two"*, because PR B measured the two 1.8× apart.

**Q9 — do driver-visible and allocator-visible disagree? Yes, structurally.**
`torch.cuda.max_memory_allocated()` is **allocator-visible, single-process**.
It excludes the CUDA context (~300-600 MiB), workspaces outside the caching
allocator, and reserved-but-unallocated blocks. `gpu_accounting.py` samples
**driver-visible** memory via `nvidia-smi` and splits *ours* vs *other* by
**process ancestry from `root_pid`** (`:292-302`) — which is what PR B's
admission actually reasons about.

**Q8 — process-tree coverage.** `max_memory_allocated()` is per-process and
**cannot see a child**. Only `gpu_accounting.sample()` covers the tree. Any C2
requirement built on the torch allocator figure would under-report exactly the
chain/pair topology PR B exists to constrain.

**Q10 — can sampling miss short peaks? Yes.** `gpu_accounting.sample()` is a
polled `nvidia-smi` query; a transient allocation between two samples is
invisible. Sampling **completeness must therefore be recorded and carried**,
not assumed — it is already modelled in PR A's result shape and must survive
into the C2 requirement.

**Q14 — how the result reaches PR B.** Through
`sandbox_executor.py:489` — `getattr(sandbox, "measured_requirements", None)`,
a **duck-typed read**, with a phase-keyed mapping of
`{"requirement_mib", "provenance"}`. A missing phase yields `(None, None)` and
is refused in formal mode. §8.A already flags this untyped read as the gap
that *"survived PR B and its whole test suite"*; C2 must replace it with a
typed boundary rather than populate it.

### DECISION REQUIRED — D-C2-1: what produces the authoritative figure

**Decision.** Build C2's pre-phase measurement as (a) a new isolated worker
combining PR A's process isolation with a real forward/backward/optimizer
step, measured by driver-visible process-tree sampling; or (b) extend PR A's
existing worker to run a real training step; or (c) extend
`probe_production.py` with isolation and driver-visible sampling.

**Why material.** It determines what "authoritative GPU requirement" means,
which process owns it, whether attempt accounting changes (O-7), and the GPU
cost of every formal launch.

**Verified code facts.** PR A never runs backward (`structural_probe.py:177,201`).
`probe_production.py` runs a real step but reports an allocator-visible,
phase-conflated, single-process peak (`:123, :185-202, :221-223`). PR B
consumes a phase-keyed driver-visible requirement (`sandbox_executor.py:478-499`).

**APPROVED: (a)** (operator, 2026-08-03). (b) would put a real optimizer step inside a worker whose
documented contract forbids backward, invalidating its structural
measurements. (c) would add isolation to an in-process runtime probe whose
peak is already phase-conflated — two changes to a component whose duration
role is in production use, risking C1's calibration path.

**Impacts.** Production behaviour: new pre-phase execution before formal GPU
launch. Authority: creates a new authoritative measurement kind. Retry/attempt:
O-7 must define whether a failed pre-phase consumes an attempt. GPU cost: one
extra bounded execution per formal candidate. **Gate 1: N/A** — no LLM-facing
surface. **Gate 2 Lite: required.**

**Work that continues without this decision:** the remaining call-graph
verification, test inventory, mutation design and the Gate 2 Lite command plan.

### D-C2-1 full decision packet — three options, side by side

> ## ✅ APPROVED — operator decision, 2026-08-03
>
> **Option (a) is approved**: a new dedicated isolated pre-phase GPU
> measurement worker, combining PR A's process isolation with a real
> production-equivalent model/data/optimizer path, real forward/backward/
> optimizer execution, phase-specific measurement, and parent-side
> driver-visible candidate-process-tree sampling.
>
> **Neither existing probe may be reused as the final C2 producer**, for the
> reasons the audit established from code:
>
> * PR A's isolated worker — **does not execute a real backward/optimizer
>   step** (`structural_probe.py:177`, and `:201` raises if backward runs).
> * `probe_production.py` — **in-process**, resets the peak **once** in
>   `_setup()`, therefore **conflates setup / training / inference**, and
>   reports **allocator-visible single-process** memory.
>
> The new worker **may reuse bounded components from both** (PR A's launcher,
> RSS cap, timeout and typed outcome vocabulary; the real-step shape from
> `probe_production`) but must carry a **new explicit C2 contract** rather than
> inheriting either component's existing one.

### Measurement authority — frozen by this decision

The authoritative GPU requirement **must** be:

| Property | Rule |
|---|---|
| freshness | measured **live** |
| device | on the **current physical GPU** |
| subject | the **exact candidate and configuration** |
| granularity | **phase-specific** (training and inference never merged) |
| timing | produced **before** formal execution |
| basis | **candidate-owned driver-visible process-tree** memory |

* PyTorch **allocator peak is supplemental diagnostic evidence**, never the
  sole authority.
* Normal-phase `observed_peak` **remains telemetry only** and may not be
  promoted to admission authority (O-10).
* **Historical GPU measurements, and measurements from another GPU, are never
  production admission authority.** This is the C1 principle carried into C2:
  the current live measurement of this candidate on this device decides.

Every result must be bound to the current GPU UUID, the current candidate, the
current configuration and the specific phase.

| Dimension | **(a) NEW isolated pre-phase worker** *(recommended)* | **(b) EXTEND PR A's worker** | **(c) EXTEND `probe_production.py`** |
|---|---|---|---|
| Description | new worker combining PR A's isolation with a real training step, measured by parent-side driver-visible tree sampling | teach the structural pre-flight worker to run a real fwd/bwd/step | add isolation + driver sampling to the in-process runtime probe |
| Production call graph | candidate → new pre-phase worker → classification → phase-keyed requirement → PR B admission → launch/stop | candidate → existing preflight worker (extended) → … | candidate → probe_production (extended) → … |
| Worker/process isolation | **new process group, RSS-capped** (reuses PR A's launcher) | already isolated | **must be added** — currently in-process |
| Real model construction | yes | yes | yes |
| Real optimizer construction | **yes (new)** | **must be added** | yes |
| Real data path | production loader, bounded | production loader, bounded | production loader (`F-1a`) |
| Forward | yes | yes | yes |
| **Backward** | **yes (new)** | **must be added — `structural_probe.py:201` currently RAISES if backward runs** | yes (`:198`) |
| **Optimizer step** | **yes (new)** | **must be added** | yes (`:199`) |
| Phase separation | **per-phase reset + per-phase peak, by construction** | must be added | **must be fixed** — one reset in `_setup()` conflates setup+train+infer |
| Allocator-visible memory | recorded as secondary | already recorded | already recorded (primary today) |
| **Driver-visible tree memory** | **primary authority** via `gpu_accounting.sample()` | must be added | must be added |
| Peak-sampling completeness | recorded and carried into the requirement | PR A already models it | must be added |
| Short-peak under-read | mitigated by sampling cadence + completeness flag; **cannot be eliminated** | same | same |
| Probe perturbation risk | **unknown — measured in Gate 2 Lite, not assumed** | same | higher: shares the process that later trains |
| Distributed/process-group | out of scope; single-device asserted | same | same |
| Timeout / crash / unavailable / incomplete / OOM / above-cap | **reuse PR A's typed vocabulary unchanged** | native | must be added |
| O-7 attempt consumption | new typed boundary owns it | same | same |
| Production authority change | **creates a new authoritative measurement kind** | same | same |
| Retry/attempt/round change | only via O-7 boundary | same | same |
| Implementation size | medium — new worker + boundary, reuses launcher & vocabulary | medium-large | large |
| Touched boundaries | new module + PR B seam | **mutates a component in production use for VRAM sizing** | **mutates a component in production use for C1 duration** |
| Required tests | isolation, real-step reachability, phase separation, tree coverage, classification, O-7 | same + regression on existing VRAM sizing | same + regression on C1 duration calibration |
| Gate 1 | N/A | N/A | N/A |
| Gate 2 Lite | required | required | required |
| Advantages | no existing production behaviour mutated; PR A and C1 paths untouched | least new code | reuses a real training step |
| **Risks** | one more component to own | **invalidates PR A's structural measurements** — its contract forbids backward, and its tape accounting assumes it never ran | **risks C1's just-validated duration path**, and inherits a phase-conflated peak |

**Why (a) is recommended.** (b) and (c) each mutate a component that is
currently in production use and just validated — PR A's sizing pre-flight and
C1's duration probe respectively. (b) is worse than it looks: the worker's
autograd-tape accounting is *premised* on backward never running, so adding a
real step does not extend it, it invalidates it.

**APPROVED 2026-08-03** — see the decision block at the head of this packet.

### Control-flow rule: exceptions are not the O-7 protocol

**Operator refinement, 2026-08-03.** C2-1's `as_admission_entry()` raises when
asked to extract an untrustworthy requirement. That is correct **as a
fail-closed accessor** — it stops a caller from reading a figure that must not
be read.

It is **not** the production control-flow mechanism. Normal outcomes travel as
**typed values**, not exceptions:

```text
worker      → typed measurement result   (never raises for a measured failure)
classifier  → typed outcome + evidence   (never raises for a classified failure)
O-7 boundary→ typed disposition          (PROCEED / STOP_*)
tuner       → consumes the disposition
```

A measured CUDA OOM, an above-cap requirement, a hard timeout and an
unavailable GPU are all **expected results** of a measurement, not errors in
taking one. Raising for them would collapse six operator-distinguishable
outcomes into one `except` block — the exact "generic failure" collapse §6
forbids — and would put O-7's accounting inside exception handling, where the
frozen rules (consume the attempt, no completed round, no blame, no shrink, no
same-attempt retry) are hardest to see and easiest to get wrong.

**Rule.** An exception may only signal a *programming* error or a genuinely
unexpected condition. Every measurement outcome that O-7 has a rule for must
arrive as a typed value.

### O-7 implementation boundary — required decomposition

**Do not add another large inline branch to the tuner's `run()`.** That method
is the giant orchestrator the decomposition rule governs; adding pre-phase
measurement, classification, admission and disposition to it inline would be
four more responsibilities in a scope that already has too many.

**Extract a focused typed boundary** that owns, end to end:

```text
run isolated pre-phase measurement
  → classify the typed result
  → validate that an authoritative requirement exists
  → call PR B admission
  → return ONE disposition
```

The tuner consumes only the disposition:

| Disposition | Meaning |
|---|---|
| `PROCEED` | authoritative requirement obtained and admitted |
| `STOP_MEASUREMENT_UNAVAILABLE` | no measurement could be produced |
| `STOP_OVER_CAP` | measured requirement exceeds the configured cap |
| `STOP_MEASURED_OOM` | the candidate OOMed during measurement |
| `STOP_TIMEOUT` | measurement exceeded its bounded deadline |
| `STOP_INFRASTRUCTURE_FAILURE` | the measurement system itself failed |

**O-7, preserved exactly.** On any `STOP_*`:

* stop **before** formal GPU work;
* **consume the attempt**;
* record **no completed round**;
* assign **no scientific blame** to the candidate;
* perform **no proposal shrinking**;
* perform **no same-attempt retry** — only the existing outer loop advances.

The boundary needs explicit inputs, a typed result, bounded side effects,
focused tests, and **reachability evidence** — a test that fails when the
production path bypasses it.

### Gate 2 Lite — TWO REQUIRED STAGES (operator decision, 2026-08-03)

**Both stages must pass before C2 merges.** The split exists because the two
answer different questions, and one cannot substitute for the other.

#### Gate 2 Lite-A — RTX 5090 mechanism validation

*Purpose: prove the machinery is correct, cheaply and locally.*

Validates: process isolation · real forward/backward/optimizer step · training
vs inference phase separation · typed outcome classification · parent-side
candidate-process-tree sampling · allocator **and** driver-visible reporting ·
timeout / crash / unavailable / measured-OOM behaviour · PR B consumer
reachability · O-7 attempt accounting · no completed round, no blame, no
shrinking on a failed pre-phase measurement · **deleting any critical
producer→consumer link makes a test fail**.

**Explicitly does NOT establish an H100 requirement.**

#### Gate 2 Lite-B — H100 production validation

*Purpose: prove the real chain on the hardware that will run it.*

Repeats the production-critical cases on the **target H100**, with a fixed
candidate and fixed configuration: successful measurement and admission ·
measured requirement above cap → refusal · unavailable/inconclusive · bounded
timeout or controlled failure · phase-specific requirement · process-tree
coverage · authoritative PR B consumption · formal launch **only** after
successful admission · the authoritative result demonstrably comes from **this
H100 live measurement**.

> **A 5090 result is never H100-authoritative.** Lite-A finds almost all code
> and semantic defects at low cost; Lite-B confirms the real chain on the
> target production hardware. Neither replaces the other.

Each stage records **separately**: exact command · workspace and temporary
registry · candidate/config · hardware · expected runtime and GPU cost ·
expected typed result and admission outcome per case · attempt accounting ·
pass criteria · stop criteria · retained artifacts · **exact Git SHA**.

~~**Neither stage runs until its exact commands and bounded resource
estimates are prepared and operator-approved.**~~ Both stages were prepared,
approved and **executed**; see *Gate results* for outcomes.

**Gate 1 remains N/A** unless C2 changes an LLM-facing prompt, schema or LLM
decision surface — in which case that specific commit requires Gate 1 before
merge.

### Case matrix (applies to Lite-A; the production-critical subset repeats in Lite-B)

Every case records: entry point, candidate/config, hardware, exact command,
expected runtime, expected GPU use, expected typed result, expected admission
result, attempt accounting, pass criteria, stop criteria, artifacts, exact SHA.
The template is fixed; per-case values are filled when the architecture is
chosen, because the entry point differs per option.

| # | Case | Expected typed result | Expected admission | Attempt |
|---|---|---|---|---|
| 1 | successful measurement | `COMPLETED_MEASUREMENT` | ALLOW | not consumed |
| 2 | requirement above configured cap | `MEASURED_PEAK_ABOVE_VRAM_CAP` | REFUSE | consumed |
| 3 | unavailable / inconclusive | `PROBE_INFRASTRUCTURE_FAILURE` | REFUSE (formal) | consumed (O-7) |
| 4 | hard timeout | `MEASURED_HARD_TIMEOUT` | REFUSE | consumed |
| 5 | measured CUDA OOM | `MEASURED_CUDA_OOM` | REFUSE | consumed |
| 6 | process crash / infra failure | `PROBE_INFRASTRUCTURE_FAILURE` | REFUSE | consumed |
| 7 | training vs inference separation | two distinct requirements | per-phase | n/a |
| 8 | parent + child both resident | tree total > single-process | per-phase | n/a |
| 9 | candidate-owned tree coverage | ours/other split correct | n/a | n/a |
| 10 | allocator vs driver-visible | driver ≥ allocator, gap recorded | n/a | n/a |
| 11 | short-peak / sampling completeness | completeness flag carried | n/a | n/a |
| 12 | probe perturbation | peak with vs without probe, delta bounded | n/a | n/a |
| 13 | O-7 attempt consumption | — | — | **consumed exactly once** |
| 14 | failed pre-phase | — | — | **no completed round recorded** |
| 15 | failed pre-phase | — | — | **no scientific blame, no shrink advice** |
| 16 | formal launch | — | only after authoritative ALLOW | n/a |

**Stop criteria (all cases):** any write outside a temporary registry; any
observed change to attempt accounting beyond O-7; wall time beyond the agreed
bound; any live v1/v2 registry mutation.

### Hardware: what a 5090 can and cannot establish

**RTX 5090 CAN validate (mechanism):** worker isolation; real
forward/backward/optimizer execution; phase separation; typed classification;
process-tree sampling mechanics; the allocator-vs-driver relationship;
timeout/crash/unavailable handling; O-7 behaviour; PR B consumer reachability.

**RTX 5090 CANNOT establish:** an authoritative **H100** GPU requirement;
H100 memory availability; H100 contention behaviour; H100 production admission
outcomes.

**Therefore, proposed split — requires operator confirmation:**

1. **Gate 2 Lite (mechanism)** on the 5090 — cases 1-16, validating that the
   machinery is correct.
2. **H100 production-authority validation** — a later, separate run on the
   target H100 before any H100 formal campaign relies on it.

A 5090 measurement is **never** transferred to an H100 requirement (§11
hardware rule, frozen). If the operator prefers a single gate, Gate 2 Lite
itself must run on the H100 — but then it cannot be run until H100 time is
available, which is why the split is proposed.

### Branch handling after C1 merges — operator-specified procedure

`audit/v20-pr-c2-producer-audit` was cut from **pre-C1 master** and therefore
does **not** contain C1's sections of this document. A blind merge would
resurrect stale C1 text — including the cancelled C-C5b wiring and the
superseded "legacy v1 is out of scope" claims.

**Required order, after PR #161 merges:**

1. **Do not merge this audit branch.**
2. Start the **C2 implementation branch from updated master**.
3. **Selectively carry forward** the C2-only audit/design content from
   `5745eb2` (and the decisions recorded here) — not the whole file.
4. **Verify the reconciled design document** contains the final C1 text:
   legacy v1 read-only, C-C5b `CANCELLED`, live-only time authority,
   FU-C-10/FU-C-11 closed, FU-C-9 deferred.
5. Only then begin C2 production edits.

Concretely, the C2-only regions are: the §16c audit findings, the D-C2-1
packet, the measurement-authority rules, the O-7 boundary, and the two-stage
Gate 2 Lite plan. Everything else in this file belongs to C1 and must come
from merged master.

### Remaining answers

**Q13 — failure classification already exists and is good.** PR A defines a
typed outcome vocabulary (`isolated_probe.py:58-85`):
`COMPLETED_MEASUREMENT`, `MEASURED_CUDA_OOM`, `MEASURED_PEAK_ABOVE_VRAM_CAP`,
`MEASURED_HARD_TIMEOUT`, `PROBE_INFRASTRUCTURE_FAILURE`, with authority
predicates (`has_capacity_authority`, `may_recommend_vram_downsizing`) and a
validator that **refuses** a `MEASURED_HARD_TIMEOUT` whose elapsed time did not
reach the deadline — added after a 65.6 s inspection was mis-filed as a timeout
on 2026-07-31 (`:282-296`). **C2 should reuse this vocabulary, not invent one.**

**Q11 — does the probe perturb memory?** Not established by the code, and it
cannot be answered by reading. It needs a measurement: same candidate, peak
with and without a preceding pre-phase probe in the same process tree. Added to
the Gate 2 Lite plan rather than asserted.

**Q12 — distributed/process-group setup.** No `torch.distributed` /
`init_process_group` call appears in either probe path. Single-device is the
current reality; C2 should state that as a scope boundary rather than silently
assume it.

**Q15 — does any production path already treat a cumulative peak as
authoritative?** `probe_production.py::_peak_vram_gb` is the only producer of a
CUDA peak in `core/runtime_control/`, and it is consumed by the **duration**
probe path, not by admission. `sandbox_executor.py:489` — admission's only
input — reads `measured_requirements`, which **nothing populates**. So the
answer is *no*: no production path currently supplies an authoritative GPU
requirement at all. That is the gap C2 exists to close, and it is why formal
admission reports `policy_unavailable` today.

**Q16 — O-7 attempt accounting is NOT implemented.** `admission.py:152` says
the policy is *"resolved once per attempt"*, but no code consumes a
pre-phase failure to decide whether an attempt is consumed. Enforcement would
have to live in the tuner's attempt loop, which is the giant orchestrator the
decomposition rule governs — so C2 must **extract a typed boundary first**
rather than add another branch there. Flagged as a design constraint on C2's
decomposition, not a defect.

---

## 16d. C2 implementation record

Updated as each checkpoint lands, not at the end. `[x]` means implemented
**and** evidenced here.

### Module layout — one responsibility each

The O-7 boundary must not become another giant orchestrator, so the
producer chain is split before it is written rather than after:

| Module | Responsibility | Checkpoint |
|---|---|---|
| `gpu_requirement.py` | the typed authority contract | C2-1 `[x]` |
| `gpu_measurement_spec.py` | the parent↔worker IPC contract | C2-2 `[x]` |
| `gpu_measurement_phases.py` | executing the real phases, in-process | C2-2 `[x]` |
| `gpu_measurement_worker_main.py` | the isolated process that hosts them | C2-2 `[x]` |
| `gpu_measurement_sampler.py` | parent-side driver-visible tree sampling | C2-3 `[x]` |
| `gpu_measurement_runner.py` | launch + sample + join into phase measurements | C2-4 `[x]` |
| `process_group.py` | shared supervision primitives | C2-4 `[x]` |
| `gpu_measurement_classifier.py` | typed outcome with evidence validation | C2-5 `[x]` |
| `gpu_requirement.MeasuredRequirementTable` | typed delivery to PR B | C2-6 `[x]` |
| `prephase_admission.py` | typed pre-phase disposition (O-7) | C2-7 `[x]` |
| `gpu_measurement_identity.py` | planned + realized identity | D-C2-7 `[x]` |
| tuner `_handle_prephase_gpu_measurement` | the production call site | C2-8 `[x]` |

### C2-1 — typed authoritative GPU requirement contract  `[x]`  `7864f83`

`core/runtime_control/gpu_requirement.py` (+22 tests). `authoritative` is a
computed property over the six frozen conditions; `as_admission_entry()`
raises rather than emitting a placeholder. `PreflightOutcome` and
`VRAM_CAPACITY_OUTCOMES` are imported from PR A, not re-declared.

### C2-2 — the isolated pre-phase measurement worker  `[x]`

**Files.**

| File | What it owns |
|---|---|
| `core/runtime_control/gpu_measurement_spec.py` | `GpuMeasurementSpec`, `PhaseExecutionReport`, `RealismEvidence`, `WorkerMeasurementReport`, `WorkerStatus`, `PhaseStatus` |
| `core/runtime_control/gpu_measurement_phases.py` | `CandidateComponents`, `PhaseJournal`, `run_measured_phases`, `_run_training`, `_run_inference` |
| `core/runtime_control/gpu_measurement_worker_main.py` | `resolve_device`, `validate_candidate_configs`, `build_production_components`, `measure`, `main` |
| `execute_tools/train_engine_sandbox.py` | `build_training_optimizer` (extracted — see D-C2-4) |

**Verified call graph** (worker side; the parent half arrives in C2-3):

```text
main(spec.json)
  → GpuMeasurementSpec           validate the IPC payload
  → measure(spec)
      → resolve_device           CUDA present? UUID == request.device_uuid?
      → validate_candidate_configs   schema rejection BEFORE the timed window
      → run_measured_phases(build_components=build_production_components(spec))
          → [setup]      reset peaks → build → read peaks → journal
          → [training]   reset peaks → zero_grad/forward/loss/backward/step ×N
            or [inference]         reset peaks → no_grad forward ×M
          → read peaks → journal
      → WorkerMeasurementReport  (atomic write to result_path)
```

**Behaviour.** A real forward, a model-connected loss, a real
`loss.backward()`, a real `optimizer.step()`, and a proof that a trainable
parameter moved. Inference runs under `torch.no_grad()` with the grad-free
property read off the OUTPUT tensor rather than from the fact that the
context was entered. The model, the optimizer, the input/target dtypes and
the fcnet `loss_type` argument all mirror `train_engine_sandbox`.

**Authority.** None is claimed here. The worker produces evidence; the
authority decision stays in `MeasuredGpuRequirement`. A CPU run cannot
become authoritative structurally — `observed_device_uuid` stays `None` and
the contract's UUID match cannot succeed.

**Failure semantics.** Every measurable outcome is a typed `WorkerStatus`
value: `COMPLETED`, `CUDA_OOM`, `DEADLINE_EXCEEDED`, `DEVICE_UNAVAILABLE`,
`DEVICE_MISMATCH`, `CONFIG_REJECTED`, `WORKER_FAILURE`. `run_measured_phases`
raises for nothing it can measure. Two Pydantic validators close
silent-success shapes: a `COMPLETED` worker whose target phase is absent or
unreached is refused, and a phase window may not run backwards.

**Attempt / retry / round impact.** None yet. C2-2 adds no call site; the
worker is not reachable from the chain until C2-6/C2-7 wire it.

**Tests.** `tests/unit/core/test_gpu_measurement_phases.py` (22),
`tests/unit/core/test_gpu_measurement_worker.py` (25),
`tests/unit/execute_tools/test_training_optimizer.py` (5). All use a real
`nn.Module` on the CPU: a mock would let a detached loss, a missing
backward or a no-op step pass, which are the exact failures being ruled
out.

**Mutation proofs — five load-bearing edges, each killed by a named test.**

| # | Mutation | Test that fails |
|---|---|---|
| M1 | delete `loss.backward()` | `test_gradients_reach_the_parameters` (+2) |
| M2 | build the optimizer locally instead of via `build_training_optimizer` | `test_the_optimizer_is_productions_own[adamw/adam]` |
| M3 | drop the fcnet `loss_type` branch | `test_fcnet_receives_the_loss_type_the_trainer_passes` |
| M4 | `parameter_update_verified = True` | `test_an_optimizer_over_the_wrong_module_is_caught` |
| M5 | skip device verification | `test_an_unreadable_uuid_fails_closed` (+4) |

Restored from backups (never `git checkout --`), `__pycache__` cleared
before each run, baseline re-run green afterwards: 52 passed.

**Regression.** `tests/unit/execute_tools/`, `tests/unit/guardrails/`,
`test_calibration_context.py`, `test_rt1_step_resolver.py`,
`test_silent_train_crash_routing.py` — 607 passed, 4 xfailed, covering the
`build_training_optimizer` extraction.

**Remaining work.** C2-3 through C2-7, then the two gate packets.

### C2-3 — parent-side candidate-tree driver sampler  `[x]`

**File.** `core/runtime_control/gpu_measurement_sampler.py` —
`TreeMemorySample`, `WindowMeasurement`, `GpuTreeSampler`, `measure_window`,
`_largest_gap`. Plus one field added to C2-1's `SamplingCoverage`:
`max_gap_seconds`.

**NVIDIA query mechanism — audited before choosing.**

| Mechanism | Verdict |
|---|---|
| `nvidia-smi` via `gpu_accounting.sample` | **selected** |
| NVML / `pynvml` | rejected |

`gpu_accounting.sample` already splits *ours* from *everyone else's* by
**process ancestry** from a root PID — the only test that claims a child
started with `start_new_session=True`, which is exactly what the C2-2
worker is. It already refuses to substitute a device whose UUID is absent,
and already keeps `telemetry_available=False` distinct from zero.
**Measured cost on this deployment: ~72 ms per sample** (two bounded
queries — device totals and per-process rows, audit finding F4).

`pynvml` is **not installed** (`No module named 'pynvml'`), so it would be
a new dependency, and it would create a *second* definition of
"driver-visible" beside the primitive PR B's admission already reasons
about. Two answers to that question is how a measurement and a gate come
to disagree invisibly.

**Behaviour.** `poll()` samples at a cadence; `poll(force=True)` takes the
boundary samples the caller wants right after spawn and just before
reaping. `measure_window(started_at, ended_at)` reduces the raw series to
one phase's peak plus its `SamplingCoverage`. The peak is the **sum over
every own process alive at one instant, maximized across samples** —
taking one process's maximum would under-read a tree, and summing each
process's own maximum across different instants would over-read a state
the machine was never in.

**Three distinctions it refuses to collapse.** No observation ≠ 0 MiB (a
failed query stays `None` and counts as *missed*); sampled zero ≠ no
observation (the driver was asked and answered); one PID ≠ the candidate.

**Authority.** None. It produces the driver-visible figure and its
coverage; `MeasuredGpuRequirement` decides whether that may be admitted.

**Failure semantics.** A raising device sampler is a missed sample, not an
exception out of `poll()`. Zero samples in a window yields
`driver_tree_peak_mib=None` and `coverage.complete=False` — an unwatched
phase has an *unknown* requirement, not a smaller one.

**Attempt / retry / round impact.** None. Still no call site.

**Tests.** `tests/unit/core/test_gpu_measurement_sampler.py` (22), on a
fake clock and an injected device sampler — no GPU, no sleeps, no threads.

**Mutation proofs — five edges, each killed by a named test.**

| # | Mutation | Test that fails |
|---|---|---|
| S1 | peak from the largest single process | `test_the_peak_sums_every_own_process_alive_at_that_instant` |
| S2 | a failed query becomes 0 MiB | `test_a_failed_query_carries_no_figure` (+2) |
| S3 | ignore the window boundaries | `test_a_sample_outside_the_window_is_not_consulted` |
| S4 | `covered_whole_phase` always True | `test_a_watch_that_started_late_is_not_complete` (+1) |
| S5 | gaps measured between samples only | `test_the_largest_gap_includes_the_window_edges` (+2) |

Restored from backups, `__pycache__` cleared before each run, baseline
re-run green (22 passed). Regression: `test_gpu_accounting.py`,
`test_gpu_requirement_contract.py`, `test_gpu_admission_wiring.py` — 156
passed with the new `max_gap_seconds` field.

**Design note — `max_gap_seconds` is risk, not incompleteness.** It is
recorded on `SamplingCoverage` but deliberately excluded from `complete`.
Every polled watch is blind between polls; treating that as disqualifying
would mean no measurement could ever be authoritative. Quantifying the
largest unwatched stretch — **including the window edges**, since a window
whose only sample sits at its start was unwatched for the rest of it —
keeps the exposure travelling with the number instead of living in a
caveat somebody has to remember.

**Design note — a sampler, not a thread.** The parent already runs a
supervision loop (deadline, host-RSS bound, reaping) and `poll()` slots
into it. That makes the whole component deterministic under test, so the
tests exercise the real attribution logic rather than a timing
approximation of it. The cost is honest: a stalled parent loop misses
samples, and that shows up as a larger `max_gap_seconds`.

**Remaining work.** C2-4 through C2-7, then the two gate packets.

### C2-4 — phase-specific measurement, joined from two observers  `[x]`

**Files.** `core/runtime_control/gpu_measurement_runner.py` —
`run_prephase_measurement`, `PhaseMeasurement`, `PrephaseMeasurementRun`,
`ProcessEvidence`, `HostMemoryBound`, `_in_flight_phase`, `_load_report`.
Plus `core/runtime_control/process_group.py` (see below).

**Why a join and not one instrument.** Neither observer is sufficient:

| Observer | Knows | Blind to |
|---|---|---|
| worker | where its phases began/ended; its own allocator peaks | children, the CUDA context, non-allocator workspaces |
| parent | driver-visible memory for the whole candidate tree | which phase is running |

The parent samples continuously; the worker marks the boundaries; this
module joins them **by wall-clock window**. That join is what makes a
requirement phase-specific instead of cumulative.

**Each `PhaseMeasurement` records** phase boundaries, elapsed time, the
driver-visible tree peak **and its source**, the allocator peak and
reserved peak **and their source**, the full `SamplingCoverage`, the own
PIDs, `max_concurrent_own_processes`, units executed vs requested, status
and detail. The two memory figures live in separate fields with separate
`*_source` strings; there is no fallback from one to the other, and a
mutation adding one fails a named test.

**Failure semantics.** Never raises for anything it can observe: a launch
failure, a hung worker (TERM → grace → KILL on the process group), a crash,
and a malformed report are all recorded outcomes. A malformed report is
**no** report — half a measurement must never read as a whole one. When
there is no report there are no windows, so samples are retained raw and
unattributed, and `in_flight_phase` comes from the journal — the difference
between "the candidate OOMed during training" and "something failed".

**Authority.** None. It records; C2-5 classifies and C2-1 decides.

**Attempt / retry / round impact.** None. Still no call site.

**Tests.** `tests/unit/core/test_gpu_measurement_runner.py` (24). Each
drives a **real subprocess** — a fake worker that reports, or hangs, or
dies mid-phase — with an injected device sampler, so the actual `Popen`,
deadline and reap paths are under test rather than a simulation.

**Mutation proofs.**

| # | Mutation | Test that fails |
|---|---|---|
| R1 | join over all samples, ignoring the window | `test_a_spike_during_setup_does_not_become_the_training_requirement` |
| R2 | driver peak falls back to the allocator figure | `test_the_allocator_figure_never_becomes_the_driver_figure` |
| R3 | remove the closing forced sample | `test_the_watch_takes_a_final_look_after_the_process_ends` |
| R4 | journal never names the in-flight phase | `test_the_journal_names_the_phase_that_was_in_flight` |
| R5 | a report *file* counts as a report | `test_a_malformed_report_is_no_report` |

**Regression.** Full `tests/unit/core/` — **1630 passed, 2 skipped**.

**Two corrections the mutation and guardrail work forced.**

*A redundant forced sample was deleted rather than kept.* The first
mutation of the OPENING `poll(force=True)` killed no test, because `poll()`
already samples unconditionally on its first call. Rather than write a test
to justify code that does nothing, the line was removed. The CLOSING forced
sample is load-bearing and now has a test that proves it — but only after
the test was rewritten with a cadence slower than the run: at a 10 ms
interval the assertion held whether or not the final sample existed, so the
first version of that test was decoration.

*A rival `DeviceIdentity` constructor was written and removed.*
`gpu_measurement_sampler.device_identity_for(uuid)` failed
`test_it_is_the_only_translation_point`, a PR B guardrail asserting that
`gpu_accounting.device_identity_from_hardware` is the sole translation
point. **The guardrail was right.** The helper had to guess
`physical_index=0`, which is precisely what that module warns against —
*"filling in device 0 ... would silently conflate two cards of the same
model, and every measurement attributed to the wrong one would look
perfectly valid."* `run_prephase_measurement` now **requires** a
`DeviceIdentity` from discovery; the deliberate absence is documented at
the former call site so it is not re-added.

**D-C2-5 — supervision primitives extracted to `core/runtime_control/process_group.py`.**
*Behaviour Delta: none* — the bodies moved verbatim.
`isolated_probe.py` and `probe_subprocess.py` had each grown identical
`_process_group_alive` / `_signal_group`, and C2-4 needed those plus the
tree-RSS read. A third and fourth copy of a kill path is four places where
one supervision bug can be fixed in one and survive in the others.
`isolated_probe` now delegates (its private names kept as aliases, since
its own tests and readers use them). **`probe_subprocess` deliberately does
not**: it sits on C1's just-validated duration path.

**Remaining work.** C2-5 through C2-7, then the two gate packets.

### C2-5 — classification with evidence validation  `[x]`

**File.** `core/runtime_control/gpu_measurement_classifier.py` —
`classify_measurement`, `_outcome_for`, `_no_report_outcome`,
`_deadline_evidence`, `_no_coverage`.

**Vocabulary reused, not invented.** `PreflightOutcome`,
`VRAM_CAPACITY_OUTCOMES` and `NO_DOWNSIZING_AUTHORITY` are PR A's, imported.
A second outcome system would be a second policy about what a failed
measurement means.

**Routing** — most specific established fact first.

| Evidence | Outcome |
|---|---|
| parent's host-RSS bound exceeded | `MEASURED_HOST_MEMORY_EXCEEDED` |
| no report, deadline reached | `MEASURED_HARD_TIMEOUT` |
| no report, deadline not reached | `PROBE_INFRASTRUCTURE_FAILURE` |
| worker `CONFIG_REJECTED` | `SCHEMA_REJECTED` |
| worker `DEVICE_UNAVAILABLE` / `DEVICE_MISMATCH` | `PROBE_INFRASTRUCTURE_FAILURE` |
| worker `CUDA_OOM` | `MEASURED_CUDA_OOM` |
| worker `DEADLINE_EXCEEDED` | `MEASURED_HARD_TIMEOUT` (soft budget as evidence) |
| worker `WORKER_FAILURE` | `PROBE_INFRASTRUCTURE_FAILURE` |
| phase absent / not completed | `INCONCLUSIVE_MEASUREMENT` |
| no driver figure | `INCONCLUSIVE_MEASUREMENT` |
| sampling incomplete | `INCONCLUSIVE_MEASUREMENT` |
| complete, over the configured cap | `MEASURED_PEAK_ABOVE_VRAM_CAP` |
| complete, within the cap | `COMPLETED_MEASUREMENT` |

**Four claims checked before they are made.**

*A timeout must have reached a deadline.* Two deadlines exist — the
parent's hard one and the worker's soft budget — and the reported evidence
is **whichever actually fired**. The soft budget sits below the hard one by
construction, so reporting the parent's for a clean worker-side stop would
produce a timeout whose elapsed time never reached it, which is the
2026-07-31 mislabelling exactly. `PrephaseMeasurementRun` therefore carries
`soft_deadline_seconds` for this purpose alone.

*A CUDA OOM is never inferred.* Only the worker can observe one, because
only it holds the exception. `_no_report_outcome` cannot return
`MEASURED_CUDA_OOM` at all — "died while holding a lot of memory" is the
inference that would blame a candidate for the machinery. The parallel
host-memory inference is safe only because the parent measured that bound
itself.

*Infrastructure is not candidate blame.* Device faults, worker crashes,
schema rejections and inconclusive results all land inside PR A's frozen
`NO_DOWNSIZING_AUTHORITY`.

*Incomplete sampling yields an unknown requirement, not a smaller one.*

**Deliberate conservatism, with its cost stated.** An incomplete watch that
observed a peak ABOVE the cap is classified `INCONCLUSIVE_MEASUREMENT`, not
`MEASURED_PEAK_ABOVE_VRAM_CAP` — per the frozen rule that above-cap
requires an otherwise-authoritative measurement. The observed peak is a
genuine lower bound, so this is strictly more conservative than the
evidence allows. The reason is that above-cap carries authority to tell an
agent to **shrink its model**, and a gappy watch is not a safe basis for
that instruction. **The cost:** the run stops either way (neither outcome
carries authority), so what is lost is only the shrink advice. The observed
figure is preserved verbatim in `detail`.

**A note on the two ways this can end.** `classify_measurement` returns a
value for every input — the control-flow rule. It CAN raise, but only
through `MeasuredGpuRequirement`'s own validators, and only if the
classifier were to build an incoherent claim (a timeout against an
unreached deadline, a `COMPLETED_MEASUREMENT` with no figure). That is an
invariant violation — a programming error — and it fails **closed**. Two of
the six mutations below were killed exactly that way.

**Attempt / retry / round impact.** None. Still no call site.

**Tests.** `tests/unit/core/test_gpu_measurement_classifier.py` (28). Every
classification is asserted together with its authority consequence: naming
the outcome is half of it, and the other half is that the wrong ones cannot
reach admission.

**Mutation proofs.**

| # | Mutation | Test that fails |
|---|---|---|
| C1 | every missing report becomes a timeout | `test_a_worker_that_died_early_is_not_a_timeout` (+1) |
| C2 | a killed worker inferred as a CUDA OOM | `test_a_killed_worker_holding_memory_is_not_an_oom` |
| C3 | incomplete sampling still yields above-cap | `test_an_incomplete_watch_over_the_cap_is_inconclusive_not_above_cap` |
| C4 | incomplete sampling admitted as a measurement | `test_each_incompleteness_yields_an_unknown_requirement` (all 3 ids) |
| C5 | the soft budget is not reported as the deadline that fired | `test_a_worker_side_budget_reports_the_budget_that_actually_fired` (+1) |
| C6 | the host bound is outranked by the worker report | `test_the_parent_bound_produces_a_host_outcome` (+1) |

**Remaining work.** C2-6 and C2-7, then the two gate packets.

### C2-6 — typed delivery to PR B's gate  `[x]`

**Files.** `core/runtime_control/gpu_requirement.py`
(`MEASURED_PROVENANCE`, `MeasuredRequirementTable`, corrected
`as_admission_entry`), `core/sandbox_executor.py` (`_phase_requirement`).

#### The defect this checkpoint found in C2-1 — `7864f83` was wrong

`as_admission_entry()` emitted a **descriptive** provenance string:

```text
isolated_prephase_measurement:training:punet:cfg:…:GPU-…
```

`evaluate_gpu_admission` does not read provenance as a description. It
tests **membership**:

```python
requirement_provenance in AUTHORITATIVE_PROVENANCE   # admission.py:429
AUTHORITATIVE_PROVENANCE = frozenset({"measured", "promoted_measurement"})
```

So every C2 requirement would have been delivered, judged
non-authoritative, and refused as **`policy_unavailable`** — the exact
failure C2 exists to remove, one layer deeper and considerably harder to
see, because the requirement would be *present* and still not count. Every
C2-1 test passed, because they asserted on the string C2-1 itself produced.

**Fixed:** `provenance` is now `MEASURED_PROVENANCE`, defined **from**
`AUTHORITATIVE_PROVENANCE` with an import-time guard (a `raise`, not an
`assert` — `python -O` strips asserts). The description travels beside it
as `measurement_detail`, a key `_phase_requirement` ignores. Two C2-1 tests
were rewritten to assert the category rather than the string.

**Behavior Delta — `_phase_requirement` gains a typed channel.**
*Before:* one duck-typed `getattr(sandbox, "measured_requirements", None)`,
which **no production code set**, so it returned `(None, None)` on every
run and formal admission always reported `policy_unavailable`.
*After:* a typed `measured_requirement_table` is read first; the duck-typed
dict remains for the B-G validation harness, whose runs are evidence about
this gate's behaviour. Same shape as the existing
`admission_policy` / `admission_mode` pair — typed first and authoritative
when present, so the requirement can never be read from two disagreeing
places.
*Production behaviour today is unchanged:* nothing sets the typed
attribute yet (see the wiring note under C2-7).

**Only an authoritative measurement can be assembled.**
`MeasuredRequirementTable.from_measurements` calls `as_admission_entry()`,
which **raises** on a refused measurement. It deliberately does not skip:
skipping would produce a table missing a phase, which `_phase_requirement`
reads as `(None, None)` — indistinguishable from never having measured, and
in trial mode that proceeds.

### C2-7 — the O-7 disposition boundary  `[x]`

**File.** `core/runtime_control/prephase_admission.py` —
`PrephaseDisposition`, `PrephaseAdmissionOutcome`,
`decide_prephase_admission`, `attach_measured_requirements`.

**O-7 is expressed as computed properties, not prose.** `attempt_consumed`,
`records_completed_round`, `carries_candidate_blame`,
`permits_shrink_advice`, `permits_same_attempt_retry`,
`may_launch_formal_phase` are derived from the disposition, so the tuner
cannot get them wrong by reading the wrong field — there is no field to
read. Tested per disposition rather than for a representative one, plus a
`PROCEED` positive control so the table cannot pass on a boundary that
stops for everything.

**Disposition mapping** is a table, not a chain of `if`s, so a new outcome
cannot fall through a gap into an accidental `PROCEED`. PR B refusals split
by reason: `policy_unavailable` / `measurement_unavailable` →
`STOP_MEASUREMENT_UNAVAILABLE`; anything else → `STOP_OVER_CAP`.

**A measured OOM records insufficiency without issuing advice.**
`requirement.establishes_insufficient_capacity` stays True and
`permits_shrink_advice` stays False: the fact is preserved for whoever is
allowed to act on it, and O-7 freezes this boundary as no proposal
shrinking.

**Tests.** `tests/unit/core/test_prephase_admission.py` (33), including the
reachability cuts: removing the attach step, or the executor's typed read,
each fails a named test.

**Mutation proofs.**

| # | Mutation | Test that fails |
|---|---|---|
| P1 | descriptive provenance instead of the accepted category | `test_the_provenance_is_the_category_admission_accepts` (+8) |
| P2 | executor stops reading the typed table | `test_the_requirement_reaches_the_executors_read` (+1) |
| P3 | the attach step never delivers | `test_the_requirement_reaches_the_executors_read` (+1) |
| P4 | a non-authoritative measurement is skipped, not refused | `test_a_refused_measurement_cannot_be_assembled` |
| P5 | a stop still permits a formal launch | `test_the_frozen_accounting` (all 6 stops) |
| P6 | a stop no longer consumes the attempt | `test_the_frozen_accounting` (all 6 stops) |

**D-C2-6 — one disposition added: `STOP_PROBE_HOST_MEMORY_EXCEEDED`**
`[x] APPROVED (operator, 2026-08-03)`, with the clearer name adopted.
Named for the PROBE, not the run, so it cannot be read as a host-memory
policy about formal training. Its frozen contract:

```text
consume the attempt · no completed round · no scientific blame
no proposal shrinking · no same-attempt retry · no formal GPU launch
no authoritative GPU requirement
NEVER call PR B capacity admission with the host-memory figure
```

**Behavior Delta.** A host-memory excess previously had no disposition at
all (C2 had no call site). It now stops the attempt and files a
`measurement_unavailable` record — and structurally cannot deliver a
figure: `MEASURED_HOST_MEMORY_EXCEEDED` is not `COMPLETED_MEASUREMENT`, so
`authoritative` is False, so no table is built and `evaluate_gpu_admission`
is never called. A test monkeypatches PR B's gate to raise and proves the
host path never reaches it; another proves `_phase_requirement` sees
nothing. Host RSS is never VRAM demand — on 2026-07-31 a candidate reached
60.5 GB of host RSS with the GPU at 273 MiB.

**Superseded record of the original proposal:**
*Plan:* six dispositions (`PROCEED` plus five `STOP_*`), introduced as
"expected dispositions **include**".
*Implemented:* a seventh, for `MEASURED_HOST_MEMORY_EXCEEDED` and
`HOST_MEMORY_ALLOCATION_FAILURE`.
*Why:* the alternative was `STOP_OVER_CAP`, and PR A is emphatic that a
HOST-memory result must **never** be phrased as a VRAM verdict — on
2026-07-31 a candidate reached 60.5 GB of host RSS with the GPU at 273 MiB.
Inside a GPU-admission boundary, `STOP_OVER_CAP` reads as a VRAM cap.
*Impact on O-7: none.* Every accounting property is identical across all
stops, and the per-disposition test table asserts that. This changes only
the operator-facing name.
*Operator note:* collapsing it into `STOP_OVER_CAP` is a one-line change if
preferred — flagged for review rather than assumed.

**Also mapped without a dedicated disposition:** `SCHEMA_REJECTED` →
`STOP_INFRASTRUCTURE_FAILURE`. A configuration the validator already
accepted being rejected at measurement time is an inconsistency in our own
pipeline, not a fact about the candidate — and O-7 forbids candidate blame
regardless.

**Remaining work.** The tuner call site — blocked on D-C2-7 below.

### D-C2-7 — dual identity  `[x] APPROVED and implemented (operator, 2026-08-03)`

**Option C approved.** The parent sends and preserves a **planned**
identity; the isolated worker constructs the real candidate and returns a
**realized** identity; both stay in the measurement record.

| | Role | Authority |
|---|---|---|
| planned identity | binds the request the parent issued | request-binding + audit evidence, **never** capacity authority |
| realized identity | identifies what was actually constructed and measured | **THE** authoritative measurement identity |

**File.** `core/runtime_control/gpu_measurement_identity.py` —
`PlannedCandidateIdentity`, `RealizedCandidateIdentity`,
`build_planned_identity`, `build_realized_identity`, `compare_identities`,
`COMPARABLE_FIELDS`.

**The realized hash uses C1's builder, called not restated.**
`build_realized_identity` invokes `build_calibration_context` +
`candidate_config_hash`, so a C2 requirement and a C1 duration observation
describe "same realized configuration" identically — the D-4 divergence
avoided rather than repeated. A test asserts the hash equals what C1's
builder produces for the same inputs.

**The planned hash is a different key set under a different name**, over
only what the parent can know before construction. It is never offered as
the measurement's identity. `param_count` and `precision` are deliberately
absent from it: demanding that the parent predict them is exactly what
would weaken the realized identity to fit the parent's blindness.

**Verified before authority is granted** — `compare_identities`, ordered
most-fundamental first:

1. `request_id` nonce matches (else the result is not this request's at
   all, and a field diff would describe the wrong pair of objects);
2. realized identity is present;
3. realized hash is non-empty;
4. every `COMPARABLE_FIELDS` entry matches — `model_type`, `model_family`,
   `optimizer_type`, `seg_size`, `batch_size`.

Plus, on `MeasuredGpuRequirement`: device UUID matches, phase is
admissible, sampling is complete, outcome qualifies.

**A mismatch fails closed** as `PROBE_INFRASTRUCTURE_FAILURE` →
`STOP_INFRASTRUCTURE_FAILURE`, checked **before** any outcome that could
carry authority. Two new `AuthorityRefusal` members —
`candidate_identity_mismatch` (previously declared and never returned) and
`realized_identity_absent`. It is never candidate blame, never GPU capacity
evidence, never a scientific failure.

### Historical: the question as it stood before approval

**What was being built.** The last edge: the tuner runs the pre-phase
measurement before a formal launch, consumes the disposition, and attaches
the requirement. The helper follows the existing `_handle_admission_refusal`
shape exactly — one call and one `if … continue`, no inline block — and
sits behind an off-by-default `prephase_gpu_measurement_enabled`, like
`runtime_watchdog_enabled`, so a merge cannot turn a new bounded GPU
execution on everywhere. That flag was written and then **reverted**: an
input that promises behaviour and delivers none is the "built and never
called" shape this PR exists to remove. It lands with the wiring.

**Where it stopped.** `GpuMeasurementSpec` embeds
`CandidateMeasurementRequest`, whose `candidate_config_hash` C2-1 documents
as *"Reuses C1's `candidate_config_hash` shape so one definition of 'same
configuration' serves both subsystems — see C1 deviation D-4, where two
definitions silently diverged."* But C1's
`candidate_config_hash(build_calibration_context(...))` requires
**realized** values — `param_count` from the instantiated module and
`precision` from its parameter dtype (`calibration_context.py:99-105`).

The tuner does not have those before launching, and **cannot** get them:
PR A's isolation rule is that *"the parent must not instantiate the
candidate model — once the model is in the parent, a child limit is already
too late."* Only the worker can compute a C1-shaped hash, and the spec that
launches the worker needs the hash first.

The design does not resolve this, and picking silently would produce the
exact D-4 divergence C2-1's own docstring cites.

**Options.**

| | Approach | Cost |
|---|---|---|
| **A** | Compute C1's hash in the parent | **Rejected on inspection** — requires instantiating the candidate in the parent, which the isolation rule forbids and PR A exists because of. |
| **B** | Hash the PLANNED config (`model_type` + the three config payloads) with the same `config_hash12` primitive | Simple; one field, one meaning. But two `cfg:`-shaped hashes then exist meaning different things, which is D-4's shape even if the values never meet. |
| **C** *(recommended)* | The spec carries a **planned-config** hash; the WORKER computes the C1-shaped realized hash and echoes it back on the report; the requirement records both | Correct and traceable — a requirement can be matched against a C1 duration bucket for the same realized candidate. Costs one extra field on the worker report and one on `MeasuredGpuRequirement`, and the identity check against the request uses the planned hash. |

**Recommendation: C.** It is the only option that keeps one definition of
"same realized configuration" while respecting the isolation rule, and it
makes the two subsystems comparable rather than merely similarly shaped.

**Impacts.** No change to O-7 accounting, retry, round or phase semantics —
this is an identity field. It does change `MeasuredGpuRequirement` (a new
recorded field under C), and it decides whether C2's identity can ever be
joined to C1's.

**Work that continued without this decision:** everything through C2-7, the
mutation proofs, and the two gate packets below.

### C2 deviations from the plan

**D-C2-2 — one worker measures ONE phase, not all three.**
*Plan:* "phase-specific measurement" inside a single worker.
*Implemented:* `GpuMeasurementSpec` carries exactly one target phase and the
parent launches one worker per phase it needs.
*Why:* production runs training and inference as separate subprocesses,
each of which constructs the model and then does its own work. Measuring
both in one process would run inference with the gradients and Adam's two
moment buffers still resident — a process production never launches — and
would leave open the cumulative-peak trap (`probe_production.py` resets
once in `_setup()`, audit finding F2). One phase per process makes
separation a property of the topology rather than of bookkeeping.
*Cost:* one extra bounded worker per candidate when both phases are needed.

**D-C2-3 — the hard deadline is the PARENT's; the worker holds a soft budget.**
*Plan:* "obey a hard deadline" listed under the worker.
*Implemented:* the worker checks `soft_deadline_seconds` between steps and
stops cleanly with partial evidence; the parent owns TERM→grace→KILL.
*Why:* a worker wedged inside a CUDA call runs no Python, so it can enforce
nothing on itself — which is the case a deadline exists for. Enforcement
has to live on the side that can act. A validator refuses a soft budget at
or above the parent's deadline, because such a budget never fires and the
partial evidence would be lost every time with nothing saying so.

**D-C2-4 — `build_training_optimizer` extracted from the trainer.**
*Behaviour Delta: none.* Two byte-identical blocks in `run_experiment` and
`run_experiment_streaming` became one function, same branches, same
arguments, same order. `optimizer_type` is a `Literal["adam","adamw","sgd"]`,
so the final branch is SGD in both the old and the new form.
*Why it is in this PR:* the measurement must build the optimizer the phase
will really use, and the optimizer is a first-order term in the memory
being measured — AdamW and Adam each keep two full-size moment buffers,
SGD without momentum keeps none. Measuring SGD for a run that trains with
AdamW under-states by two parameter tensors, the OOM direction. A fifth
hand-written copy of that switch is how the divergence would arrive.
*Scope held:* `probe_production.py` and `evaluate_time_skill/wrapper.py`
keep their own copies. Both are on C1's just-validated duration path and
retrofitting them is a separate in-passing change, not C2's.

### C2-8 — the production call site  `[x]`

**Files.** `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py`
— `_handle_prephase_gpu_measurement`, `_prephase_worker_memory_limit_bytes`,
`_prephase_device_snapshot`, `_PREPHASE_REASON_CODE`, and one call in
`run()`.

**No feature flag.** An input that promises behaviour and delivers none is
the built-and-never-called shape this PR exists to remove. The measurement
is on the production path.

**The call site is one call and one `continue`**, in the shape
`_handle_admission_refusal` already uses. The helper delegates: identity
comparison, classification, authority validation and PR B admission all
live in `prephase_admission`, which returns ONE disposition. `run()` is the
giant orchestrator the decomposition rule governs, and none of that logic
is reimplemented there.

**Two applicability rules, neither a feature flag.**

*Trial rounds are not measured.* O-7 governs formal execution, and trial
admission already proceeds while recording what it could not prove.

*A run with no real device is untouched.* The same conclusion
`_admission_refusal` reaches — no card means nothing to measure and nothing
for admission to decide.

**Behavior Delta.** A formal attempt on a real GPU now runs a bounded
isolated pre-phase measurement before any formal GPU work, and stops the
attempt on any `STOP_*` with the frozen O-7 accounting
(`counts_toward_attempt_budget=True`, `counts_toward_completed_rounds=False`,
no blame, no shrink, no same-attempt retry). Formal admission receives a
real requirement instead of `policy_unavailable`. Trial rounds, CPU runs and
pseudo runs are unchanged. `gpu_admission_enforcement` is untouched —
flipping `observe_only` to `enforce` remains a separate decision.

**Dispositions are filed under PR B's existing three lanes**
(`_PREPHASE_REASON_CODE`); the disposition itself survives in
`admission_evidence`, so the narrowing loses nothing and the lanes stay
distinct.

**A defect this found, worth recording.** The first applicability check was
`if device_identity is None: return False`. `getattr` on a `MagicMock`
returns a truthy **mock**, so the gate silently activated in **53** mocked
formal tests — and in production would have accepted any object at all as a
device. Fixed by type-checking against `DeviceIdentity`, which is the
principle the whole PR rests on: a typed boundary, never a duck-typed read.
Three tests now cover it, including a positive control.

**Tests.**
`tests/unit/agent/tune_ml_hyperparam_agent/test_prephase_measurement_reachability.py`
(21). They cut the production edges rather than testing the component
again: deleting the call from `run()` fails; calling the boundary and
discarding its disposition fails; the call must precede
`_run_skill("training_skill", …)`.

**Mutation proofs.**

| # | Mutation | Test that fails |
|---|---|---|
| W1 | delete the call from `run()` | `test_run_consumes_the_disposition` (+2) |
| W2 | call the boundary, discard the disposition | `test_run_consumes_the_disposition` |
| W3 | identity mismatch no longer blocks authority | `test_a_missing_realized_identity_is_refused` (+3) |

**No LLM-facing change.** The measurement makes no model calls (proved in
C2-2), and no prompt, schema or LLM decision surface is touched. **Gate 1
remains N/A.**

**D-C2-8 — the gate had no runnable entry point; a thin harness was added.**
*Original plan:* gate commands would invoke an existing production entry
point.
*Observed in code (static validation, 2026-08-03):*

* `python -m core.runtime_control.gpu_measurement_worker_main <spec>` runs
  the **child alone** — no parent sampling, therefore no driver-visible
  peak and no coverage. That is the allocator half, which is never the
  authority.
* `run_prephase_measurement` and `decide_prephase_admission` are
  **library-only**; their sole production caller is the tuner.
* `scripts/run_comparison.py` has **zero** `add_argument` entries matching
  gpu/ceiling/admission, so the chain cannot set the cap, deadline or
  sampling interval that cases 2, 4 and 11 require.

*Chosen correction:* `scripts/c2_prephase_validation.py`, a thin acceptance
entry point calling the exact production boundary — the same three
functions the tuner calls, asserted by a structural test against the tuner
itself. PR B set this precedent with `bg_admission_validation.py`.
*Behavior Delta:* **none in production.** No production module changed; this
adds an explicit acceptance entry point and nothing else.

**D-C2-9 — cases 12a/12b: a harness-only formal control path**
`[x] APPROVED (operator, 2026-08-03)`.

*Validation-infrastructure extension. **Behavior Delta for normal
production: none.*** No production module changed and no feature flag was
added; the ordinary production path is untouched.

Both arms call `TidmadSandbox.execute_training` — exactly what
`agent.skills.training_skill.wrapper.run_skill` calls — with the sample set
built by the production `build_sample_set`. The harness supplies inputs and
runs none of the training itself. A test asserts the control path is
**unreachable from `core/` and `nodes/`**, so the no-probe arm cannot become
something production can take.

```text
A: prephase measurement -> worker/process cleanup -> bounded formal execution
B: bounded formal execution, no preceding prephase measurement
```

**Three paired repetitions with alternating order** (A/B, B/A, A/B), each
arm in a fresh process and workspace, so a warmed driver or a cached
dataset page cannot masquerade as a perturbation.

**Superseded, 2026-08-04 — see D-C2-19.** This deviation originally read
"a pair with any foreign process is marked `contaminated: true` and
excluded from evidence". That rule is withdrawn. **The presence of another
GPU process is not contamination**; only a *change* in the external
environment that could alter this case's conclusion is. A steady neighbour
affects both arms alike and is valid production context, recorded as
headroom evidence. Environment is now assessed over the whole timestamped
sample series rather than from two endpoint snapshots.

**The formal workload is bounded by live stability, not by an operator
portion — see D-C2-20.** The training arm ends when the driver-visible peak
has demonstrably settled on the machine under test. `--formal_seed` remains
required; the portion flags are no longer Case 12's workload definition.

**No correction factor exists anywhere.** The manifest records
`correction_factor_applied: false`, and a test forbids the tokens that would
introduce one. The repeatability envelope comes from the three repetitions,
not from an invented percentage.

**Lite-A is `INCONCLUSIVE` and stops for review if:** formal execution is
systematically higher than the probe by more than the observed
within-condition repeatability · the difference changes PR B admission under
the configured ceiling · sampling is incomplete · identity or GPU UUID
differs · the external environment **changed materially between the arms of
a pair** (D-C2-19 — not merely that a neighbour was present) · a formal
training arm did not reach live stability (D-C2-20) · the result is not
reproducible.

An affected pair reruns as a new immutable sub-attempt. **The Gate as a
whole is not invalidated**, and the contaminated artifact is preserved
rather than deleted.

**D-C2-10 — case 5's oversized configuration, resolved statically.**
`batch_size=512` was **not** safe to assume. The audit (arithmetic and an
HDF5 read, no GPU work):

| Fact | Value |
|---|---|
| probe batch host cost | `B x 40000 x 8` bytes — **312.5 MiB at B=1024** |
| host RSS cap | 24 GiB (`default_worker_memory_limit_bytes`) |
| forward output alone | `B x 256 x 40000 x 4` bytes = **39.06 GiB at B=1024** |
| RTX 5090 capacity | 32087 MiB = **31.33 GiB** |
| segments per training file | **50,250** (2,010,000,000 samples / 40,000) |

Three things follow. **Host memory can never pre-empt the CUDA OOM**: at
B=1024 the host batch is 312.5 MiB against a 24 GiB cap, a factor of ~78,
so `STOP_PROBE_HOST_MEMORY_EXCEEDED` cannot fire first for any B below
roughly 78,000. **B=1024 provably OOMs on the device** from the single
forward output tensor alone — 39.06 GiB against a 31.33 GiB card —
*independently* of PUNet's activation structure, which is why it is chosen.
**The dataset cannot turn c5 into an infrastructure failure**: `load_probe_batch`
raises when `len(dataset) < batch_size`, and one file holds 50,250 segments
against a request for 1,024.

**B=1024 is not the smallest such configuration**, and that is deliberate.
B=512 gives 19.53 GiB of output against 31.33 GiB and would very likely OOM
once activations, gradients and Adam's moments are added — but "very likely"
rests on PUNet's activation multiplier, which this audit did **not**
establish. Trialling configurations to find the smallest would be running
the gate under another name. B=1024 is the smallest value provable from
arithmetic alone.

**D-C2-11 — the first Lite-A packet named a flag that did not exist, and
its formal arm ran only half the comparison.** Found while wiring the
approved parameters in, before any gate case ran.

*Original packet:* `--formal_eval_portion` (which the harness did not
implement — it had `--formal_trial_portion`, a different quantity: SampleSet
coverage, with no eval slice at all), and `run_formal_execution` calling
only `execute_training`.

*Why both were blockers.* The first would have made the executed command
differ from the approved one, with a silent substitution standing in for an
operator decision. The second is worse: case 12b compares the probe's
**inference** peak against a formal inference peak, and with
`execute_inference` never called, 12b would have reported the training half
and read as complete — the silent partial answer this PR exists to remove.

*Corrected:* distinct required `--formal_train_portion` /
`--formal_eval_portion` / `--formal_seed`; separate production train and
eval sample sets, exactly as production carries `sample_set` and
`eval_sample_set`; the formal arm calls **both** `execute_training` and
`execute_inference`; and each portion is applied **once** — at sample-set
construction, with `execute_training(train_portion=1.0)` so the approved 1%
slice is not reduced a second time per epoch, which would have shrunk the
formal run below what was approved and quietly favoured the probe.

*Completeness is enforced on the result, not the source:* `formal_phases_complete`
requires both phase results to be present in **both** arms of **every**
pair, and a comparison missing either is reported `INCONCLUSIVE` rather
than as a case that ran. A call that exists and silently returns nothing
would pass a source scan; this does not.

*Behavior Delta for normal production: none.* Validation infrastructure
only.

*Mutation-proved, five edges:* removing the `execute_inference` call ·
reducing the slice a second time · one flag feeding both sample sets ·
completeness ignoring the inference phase · the seed not reaching training.
Each is killed by a named test.

### Gate 2 Lite-A attempt 1 — FAILED at c1, `b7a59ce6`

The gate found what no unit test could: the tests inject a batch, so the
real data path was only reachable with the real dataset.

| | |
|---|---|
| Expected | `COMPLETED_MEASUREMENT` → `PROCEED` |
| Observed | `MEASURED_HOST_MEMORY_EXCEEDED` → `STOP_PROBE_HOST_MEMORY_EXCEEDED` |
| Worker | TERMed at **24.10 GiB** tree RSS against the 24.00 GiB cap, `exit_code -15` |
| Phases | **none** — killed during setup, before model construction |
| Realism | 0 forward, 0 backward, 0 optimizer steps |
| Wall | 22 s · 76 driver samples retained · no orphans |
| Registry | `live_registry_unchanged: true` |

Artifacts preserved at `/tmp/c2_lite_a/artifacts/c2_lite_c1_manifest.json`
(+ `.sha256`). Cases c2-c12 were never started.

**D-C2-12 — bounded data access for the C2 worker**
`[x] APPROVED (operator, 2026-08-03)`.

*Root cause.* `load_probe_batch` → `TIDMADDataset.pull_event_from_dir` reads
the WHOLE channel before `max_segments` is applied
(`train_engine_sandbox.py:110-132`): `np.array(channel0001).astype(np.int8)`,
`np.array(channel0002).astype(np.int16)`, two reshaped index copies and a
`bincount` temporary — ~13 GiB live at once for one 2,010,000,000-sample
file. `max_segments` truncates the *event list* at line 131, after all of
it, so it bounds nothing. To build a batch occupying **0.31 MiB** on the GPU.

*Rejected: raising the cap.* It would conceal a real probe defect and impose
~24 GiB of host cost on every formal attempt — and two concurrent chains
each holding a worker is the arithmetic PR A's cap exists to prevent.

*Chosen: `core/runtime_control/gpu_measurement_data.py`.* Reads exactly the
`batch_size × segment_length` samples by HDF5 slicing. With `sample_size=1`
the production path reduces to contiguous slicing
(`alltrain[i*seg : (i+1)*seg]`, `random_offset` always 0), so the bounded
read reproduces it exactly, including the int8 → int16 → `+128` cast chain
and the `channel0001` input role.

*Where equivalence is required, and where it is not.* The tensor delivered
to the device, the model, the optimizer, dtype, shape, channel order, the
loss and forward/backward/step are all production-equivalent. Reproducing an
**avoidable host-side full-file copy** is not: the same device tensor is
constructible from bounded reads, and the trainer's host cost is not the GPU
requirement.

*Measured against the real dataset:*

| | before | after |
|---|---|---|
| host peak RSS, batch 1 | 24.10 GiB (killed) | **0.52 GiB** |
| host peak RSS, batch 1024 (c5) | — | **0.92 GiB** |
| bytes read | whole channel | 40 KiB (**0.00199 %** of the file) |
| wall | 22 s to failure | 0.72 s |

*No fallback.* Bounded access failing raises and is reported as an
infrastructure condition. Silently reaching for `load_probe_batch` would
restore the failure this removes — guarded by
`test_it_never_calls_the_unbounded_loader`.

*Equivalence proved*, not asserted: `test_gpu_measurement_data.py` (15) runs
BOTH loaders against a miniature HDF5 fixture with the production structure
and compares tensors, shape, dtype, channel role, segment boundaries, the
class-index offset and three geometries. The fixture's two channels hold
different values, so a channel swap fails. Bounded-ness is checked over the
**AST** — this module documents the forbidden `np.array(channel)` in a
comment, and a substring scan cannot tell an explanation from an
instruction.

*Behavior Delta:* production trainer **none**; C2 pre-phase worker host
loading becomes bounded; GPU measurement authority **unchanged**; O-7
**unchanged**. `STOP_PROBE_HOST_MEMORY_EXCEEDED` still exists for a genuine
bounded-loader host failure, still calls no PR B admission, still carries no
candidate blame.

*Follow-up, deliberately not fixed here:* `probe_production.py` (C1's
duration probe) calls the same `load_probe_batch` — in-process and
**uncapped**, so the same ~13 GiB host cost exists today and has simply
never been bounded. Its own finding; C2 does not touch C1's validated path.

### Gate 2 Lite-A attempt 2 — INCONCLUSIVE at `1fa95d87`

D-C2-12 confirmed: c1 host RSS **24.10 GiB (killed) → 1.515 GiB**, model
built (6,762,568 params), forward/backward/steps 4/4/4, parameter moved
1.98e-3, driver 1388 MiB > allocator 807 MiB, PR B admitted on
`source=measured`, `PROCEED`. B-G0 measured the same candidate at 1,476 MiB.

| Case | Outcome | Disposition | |
|---|---|---|---|
| c1 | `COMPLETED_MEASUREMENT` | `PROCEED` | PASS |
| c2 | `MEASURED_PEAK_ABOVE_VRAM_CAP` | `STOP_OVER_CAP` | PASS |
| c4 | `COMPLETED_MEASUREMENT` | `PROCEED` | **FAIL** — deadline not reached |
| c6 | `PROBE_INFRASTRUCTURE_FAILURE` | `STOP_INFRASTRUCTURE_FAILURE` | PASS |
| c7 | `INCONCLUSIVE_MEASUREMENT` | `STOP_MEASUREMENT_UNAVAILABLE` | **FAIL** — zero in-phase samples |
| c11 | `INCONCLUSIVE_MEASUREMENT` | `STOP_MEASUREMENT_UNAVAILABLE` | PASS |

Registry `62540aab…` unchanged; GPU back to 273 MiB; no orphans. Artifacts
at `/tmp/c2_lite_a/artifacts/`; attempt 1 preserved read-only at
`/tmp/c2_lite_a_failed_b7a59ce6/`.

**c4 — Gate-parameter correction, not a production change.** The bounded
loader made the whole measurement ~10x faster (2.39 s total), so a 3 s
deadline is never reached. **Corrected to `--deadline_seconds 1`.**

**D-C2-13 — short phases must be observable**
`[x] APPROVED (operator, 2026-08-03)`.

*What c7 exposed.* Inference ran in **0.138 s** against a 0.25 s cadence, so
**zero** driver samples fell inside the window. `driver_tree_peak_mib` was
`None` and the classifier refused — correctly, *"an unobserved requirement
is unknown, not zero"*. But it means a fast candidate's phase is
structurally unmeasurable, and every such formal attempt would be stopped
and consumed.

*Rejected:* accepting it · raising the Gate's batch count so c7 alone passes
· merely polling faster, which still misses short peaks.

*Implemented.* An authoritative phase requires
`MINIMUM_AUTHORITATIVE_SAMPLES = 3` valid in-phase readings —
enforced on the **observation** side, because the worker can lengthen a
phase but only the parent knows how many samples actually landed. Zero, one
or two now fail closed.

```text
worker announces phase readiness
  -> parent confirms sampling is ACTIVE (a real driver sample succeeded)
  -> worker executes the exact phase workload
  -> repeats that exact workload until the window can hold the readings
  -> phase ends
```

*Preserved across repetitions:* candidate, configuration, batch shape,
dtype, precision, data construction, model behaviour, and training vs
inference semantics. **Repetition count is measurement protocol, not
candidate identity**, and it never leaves the disposable worker.

*Bounded:* `max_phase_repetitions` (40), `max_phase_seconds` (60) and the
existing deadline. Reaching a bound without enough samples yields
`INCONCLUSIVE_MEASUREMENT`. A failing phase is never repeated — that would
multiply the failure and hide when it first occurred.

*Recorded per phase:* required and observed sample counts, repetitions,
elapsed time, sample timestamps, phase boundaries, driver peaks, allocator
diagnostics, `observation_bound_reached` and `sampler_ready`.

*The handshake is evidence, not a promise.* The parent touches the ready
marker only after a **successful** driver sample; a failing query proves
nothing is being observed. A stale marker from an earlier run is removed at
launch, or a phase could open on a previous run's signal.

*Behavior Delta:* formal execution **unchanged** — repetition is confined to
the measurement worker. The pre-phase measurement takes marginally longer
for short phases and now refuses thin evidence it previously would have
admitted on one sample. O-7 **unchanged**.

*Mutation-proved:* dropping the minimum-sample requirement · never extending
a short phase · removing the handshake · signalling readiness without a
successful sample · keeping a stale marker. Each killed by a named test.

### Gate 2 Lite-A attempt 3 — INCONCLUSIVE at `4b2e430f`

**c1 PASSED, and the 3-sample rule paid for itself immediately:**

| | attempt 2 (1 sample) | attempt 3 (4 samples) |
|---|---|---|
| driver peak | 1388 MiB | **1474 MiB** |

The single-sample measurement **under-read the candidate by ~6 %**, and the
4-sample figure lands on B-G0's independent 1,476 MiB. 22 repetitions,
handshake confirmed before the phase opened.

**c7 FAILED, and showed the remaining defect was mine:** 40 repetitions ran
120 inference batches in **0.344 s** and captured **one** sample — the fixed
repetition ceiling terminated the phase long before the meaningful duration
bound (60 s) was anywhere near. ~8.6 ms per repetition means ~120
repetitions were needed; the ceiling was 3.4x too low.

Also found: `PhaseMeasurement` did not carry `repetitions`,
`observation_bound_reached` or the handshake state at all — they existed
only on the worker's report, so the evidence could be recovered only by
reading the private journal after the fact. The artifact was incomplete.

**D-C2-14 — the parent ends the phase**
`[x] APPROVED (operator, 2026-08-03)`.

*Rejected: replacing 40 with a larger guess.* A repetition COUNT cannot
express a duration target when the per-repetition cost is unknown. Any fixed
number is wrong for some candidate; it only moves where it breaks.

```text
worker announces phase readiness
  -> parent obtains a successful driver sample, marks the sampler ready
  -> worker repeatedly executes the exact bounded phase workload
  -> parent COUNTS valid in-phase samples
  -> at the required count the parent signals completion
  -> worker leaves the phase cleanly
```

`max_phase_repetitions` is **removed**, not raised. The normal bounds are
`max_phase_seconds` (60) and the global deadline; repetitions are recorded
as an outcome, never a stop condition. Verified on the real GPU: the same
inference phase that died at 40 now completes at **135 repetitions**, 3
observed samples, `sample_target_reached`, `COMPLETED_MEASUREMENT` →
`PROCEED`.

*Only samples inside the OPEN window count.* The parent learns the boundary
from the journal the worker flushes; a closed phase returns none, so
completion can never be signalled after the fact.

*Observation evidence now travels through the TYPED result* —
`repetitions`, `required_samples`, `observed_in_phase_samples`,
`completion_reason`, `max_phase_seconds`, `observation_bound_reached`,
`sampler_ready`, `sampler_ready_at`. The harness reconstructs nothing from
private journals; a missing field means the artifact is incomplete and the
result carries no authority.

*A budget that trips inside a step is a deadline, not a failure* — found by
a test that labelled one as the other.

*Behavior Delta:* formal execution **unchanged**; repetition stays inside
the disposable worker. Repetition count is measurement metadata, not
candidate identity. O-7 **unchanged**.

*Mutation-proved:* removing the parent signal · restoring a fixed
40-repetition stop · authority with two samples · dropping metadata in the
runner join · counting samples from before the phase opened.

### Gate 2 Lite-A attempt 4 — INCONCLUSIVE at `09f4d3fe` (cases 1-11 PASSED)

**Every case through c11 passed**, in ~3 min wall, ~9 bounded GPU
executions.

| Case | Outcome | Disposition | Evidence |
|---|---|---|---|
| c1 | `COMPLETED_MEASUREMENT` | `PROCEED` | 13 reps · 3/3 samples · driver **1474** MiB |
| c2 | `MEASURED_PEAK_ABOVE_VRAM_CAP` | `STOP_OVER_CAP` | 10 reps · 3/3 |
| c3 | `INCONCLUSIVE_MEASUREMENT` | `STOP_MEASUREMENT_UNAVAILABLE` | 360 samples, **0** with telemetry · `duration_bound` |
| c4 | `MEASURED_HARD_TIMEOUT` | `STOP_TIMEOUT` | budget 1.0 s, **elapsed 1.168 s**, TERM sent, no KILL, no orphans |
| c5 | `MEASURED_CUDA_OOM` | `STOP_MEASURED_OOM` | *"Tried to allocate 6.10 GiB"* · driver **31314** MiB · host only **1.09 GiB** |
| c6 | `PROBE_INFRASTRUCTURE_FAILURE` | `STOP_INFRASTRUCTURE_FAILURE` | injected crash |
| c7 | `COMPLETED_MEASUREMENT` | `PROCEED` | **124 reps** · 3/3 · driver 1050 MiB |
| c9 | `COMPLETED_MEASUREMENT` | `PROCEED` | own **1474** vs other **2026** MiB on a 3784 MiB device |
| c11 | `INCONCLUSIVE_MEASUREMENT` | `STOP_MEASUREMENT_UNAVAILABLE` | 0 in-phase samples at a 120 s cadence |

c8 — single-PID tree at `batch_size=1`; the reported figure is the tree SUM,
and multi-process residency is proved by unit test rather than fabricated.
c10 — driver ≥ allocator in **every** phase, gap 611-1877 MiB
(1.06x-3.79x), which is why the allocator figure is never the authority.
O-7 correct in all nine. Registry `62540aab…` unchanged; no orphans.

**c5 confirms D-C2-10's static audit:** host peaked at **1.09 GiB** against
the 24 GiB cap while the GPU reached 31314 MiB — host memory cannot
pre-empt the CUDA OOM, exactly as the arithmetic predicted.

**Stopped before c12: the harness could not honour its own safeguard.**
`run_formal_comparison` ran all three pairs in one invocation, so there was
no point at which pair 1's timing could be measured and the 90-minute
projection applied. Running it anyway would have bypassed an approved
control.

**Two procedural findings, recorded honestly.**

*c3's first induction was invalid.* `PATH=…/nosmi:/usr/bin:/bin` still
reached `/usr/bin/nvidia-smi`, so nothing was injected and c3 ran as an
ordinary successful measurement. Re-induced with a failing `nvidia-smi`
shim — the documented "driver query cannot be taken", through the real
subprocess seam.

*And the corrected rerun OVERWROTE the invalid artifact.* **That artifact is
unrecoverable.** It is not preserved anywhere, and this section is the only
record that it existed. The record of a mistake is often the most useful
part of a Gate, and it was destroyed by a predictable filename.

**D-C2-15 — execution control and artifact immutability**
`[x] APPROVED (operator, 2026-08-03)`.

*Case 12 budget checkpoint.* One invocation now runs pair 1, flushes and
hashes it, computes the projection, and continues only within budget:

```text
T_formal = max(pair-1 formal WITH probe, pair-1 formal WITHOUT probe)
T_probe  = pair-1 prephase wall time
projected_case12 = 6 x T_formal + 3 x T_probe
projected_total  = prior_cases_wall + projected_case12
```

`T_formal` is the **slower** arm, not the mean: an optimistic projection
would authorise a run that then overruns, which is what the checkpoint
exists to prevent. Exceeding the budget yields `STOPPED_BY_TIME_BOUND` — a
budget decision, **not a failure**, and nothing is shrunk to fit.

*Artifact immutability.* Every artifact is
`c2_lite_a<attempt>_<sha12>_<case>__sub<N>.json`; an existing path produces
the next sub-attempt rather than a replacement. This covers an invalid
setup, a contaminated run, a corrected injection and a rerun after failure.
`--gate_attempt` is required.

*Synthetic-injection provenance* is recorded with the result: method, the
harness command, the shim path, its **sha256**, its content and whether it
is executable. A synthetic result is only interpretable alongside what was
injected — and attempt 4 proved an injection can silently fail to happen at
all.

*Behavior Delta for normal production: **none**.* Validation infrastructure
only; no production skill, node or agent behaviour changes.

*Mutation-proved:* overwriting instead of sub-attempting · `T_formal` as the
mean · running pairs 2-3 regardless of the projection · not recording
provenance. The last two initially SURVIVED — the projection was computed
but nothing proved it controlled the loop, and provenance was built but
never asserted — and tests were added for both.

### Gate 2 Lite-A attempts 20-22 — PASSED at `7302c467`

Attempts 6-19 were superseded before execution by the corrections recorded
in D-C2-16 through D-C2-21; no GPU time was spent on them.

| attempt | SHA | scope | outcome |
|---|---|---|---|
| 20 | `7f8e9ffa` | c1-c11 + full 3-pair Case 12 | c1-c11 **PASS**; Case 12 measurements valid but **false-negative comparability** |
| 21 | `adabf4fb` | one Case 12 pair | **DISAGREED** with replay -- identity adapter read two non-existent keys |
| 22 | `7302c467` | one Case 12 pair | **PASS**, all acceptance conditions |

**Attempt 20 is the incident that produced D-C2-21.** Every case passed and
Case 12's six arms measured an identical 1476 MiB, yet all three pairs were
refused because a neighbour oscillated 132-150 MiB against a 64 MiB pooled
threshold. The artifacts refuted the refusal they were subjected to. Total
harness execution: ~295 s; Case 12 alone 120 s for three pairs.

**Attempt 21 is why the one-pair live check exists.** After the
comparability fix, the replay of attempt 20's sealed series passed while the
first LIVE pair failed -- `summarize_formal_arm` read
`formal["realized_identity"]` and `stability["candidate_id"]`, neither of
which is ever written to a formal-arm record. The replay only passed because
it hand-fed the value. **Two constructions of one mapping, drifting exactly
as the adapter's own docstring warned**, and invisible because no test built
an `ArmEnvironment` from a real formal-arm record.

Both defects were found by running the real call chain. Neither was
reachable by testing components, and both were in validation-only code that
would have silently voided a Gate rather than a production run.

**Attempt 22** (41 s wall, two bounded executions): `pair_comparable: true`,
no blocking reasons, both arms `STABLE` at 554/569 steps, 1476 MiB training
and 3434 MiB inference on both, identity sourced from
`training_status.runtime_verification.calibration_context`, registry
unchanged, no orphans. `STOPPED_BY_TIME_BOUND` after pair 1 is the budget
checkpoint bounding the run to the single authorized pair, not a failure.

### Gate 2 Lite-A attempt 5 — STOPPED_BY_TIME_BOUND at `2de114ef`

**Cases c1-c11 reproduced in 194 s**, immutable artifact names working
(`c2_lite_a5_2de114efb3c8_<case>__sub1.json`), c3's shim recorded with
sha256 `275239824e00e61b…`.

**The budget checkpoint fired, and was right.** Pair 1 completed; the
projection then stopped the run:

| | |
|---|---|
| `T_formal` (slower arm) | **886.7 s** — 870.4 s training, 16.3 s inference |
| `T_probe` | 3.0 s |
| projected Case 12 | 5329.1 s |
| + cases 1-11 (194 s) | **5523.1 s** vs a 5400 s budget |
| decision | stop after pair 1; nothing shrunk |

It missed by **123 s — 2 %**. Run blind, it would have overrun.

**D-C2-16 — the formal arms were never measured**
`[x] APPROVED (operator, 2026-08-03)`.

Attempt 5's pair-1 artifact contains **no formal GPU peak at all**:
`own_tree_mib`, `observed_peak`, `driver`, `peak_vram` and `allocator` are
all absent. `training_status` and `inference_status` carry timing,
admission and loss history — not memory.

Three defects, one root cause:

1. **the formal arms were unsampled.** `GpuTreeSampler` ran only inside
   `run_prephase_measurement`; nothing watched the process tree during
   `execute_training` / `execute_inference`.
2. **`formal_phases_complete` accepted a non-empty status as complete.** So
   pair 1 reported `formal_phases_complete: true` after 886 s of GPU work
   that produced no admissible comparison data.
3. **the summary crashed** with `KeyError: 'requirement'` after the
   manifest was written — it rendered a comparison result as a measurement
   one. No evidence was lost, but a run ending in a traceback is not a
   clean Gate execution.

**Case 12B could therefore never have been answered by what was built.** It
compares probe peaks against formal peaks, and the formal peaks did not
exist. This is the silent-half-answer shape one level up from c7: "did both
phases run?" was fixed, and "did we measure them?" was never asked.

*Corrected.* `BackgroundTreeSampler` polls the production `GpuTreeSampler`
on a thread while the blocking production boundary runs — the ownership
rule, the gap-is-not-a-zero rule and the window reduction all stay
production's. Training and inference get **separate** windows; a cumulative
peak would answer neither. The full timestamped series is retained, so a
peak-versus-time curve can be reconstructed.

`formal_phases_complete` now requires, for **both** phases: the phase
executed, valid boundaries, sampling occurred, sampling is complete, and a
driver-visible peak exists. Rendering dispatches on result **shape**, and an
unrecognised shape says so rather than raising.

*The sampler guardrail is narrowed, not dropped.* The harness may construct
`GpuTreeSampler` **only** inside `BackgroundTreeSampler` — the formal arms
have no production runner to sample them — and a test enforces that scope
plus the absence of any sampler of its own.

*Behavior Delta for normal production: **none**.* Validation infrastructure
only.

*Mutation-proved:* restoring the status-only completeness condition ·
unsampled training · unsampled inference · the comparison-shape crash ·
discarding the raw series. Three initially SURVIVED — the assertions
checked that keys existed, not that they carried sampler output — and were
strengthened to require `driver_source`, `samples_taken`,
`sampling_complete`, `max_gap_seconds` and a non-empty timestamped series.

**Case 12 cannot be shortened yet.** The saturation analysis needs a
peak-versus-step curve that does not exist in any preserved artifact. A
bounded characterization run must produce it first.

### Single-arm characterization — `c12char`, NOT a Gate case

Case 12 cannot be shortened without a peak-versus-time curve, and no
preserved artifact contains one (D-C2-16). This mode produces it at the cost
of **one arm** rather than a pair.

```text
prephase measurement -> bounded formal training -> formal inference
```

**Only the production-order arm runs.** The no-probe arm answers the
*perturbation* question, not the saturation one, and would double the cost
for no distinct evidence here. It stays in Case 12.

*Same boundaries as the Gate* — `run_case_measurement` then
`run_formal_execution`. Nothing is a second implementation, and
`gate_pass: false` is recorded in the result.

**What it reports**, separately for training and inference: final peak,
first time that peak was seen, **last time the cumulative peak increased**,
the stable tail in seconds and as a fraction of the phase, sample count, and
the monotone cumulative-peak curve.

**Resolution is seconds, not steps.** The production training loop emits no
per-step marker the sampler can key on, so a step figure would be invented.
Whether seconds suffice to choose a safe shorter workload is exactly what
this run establishes; if they do not, the smallest instrumentation change
is proposed separately rather than assumed now.

**Cost justification.** From attempt 5's measured timings: formal training
~870 s, formal inference ~16 s, prephase probe ~3 s — **~15 min**, against
~30 min for a full pair. Stop if the projection materially exceeds 20 min.

### D-C2-17 / D-C2-18 — the inference measurement, corrected twice

**D-C2-17, inference batch.** The probe took its batch from
`train_config["batch_size"]` while `execute_inference` resolves
`inference_batch_for(model_type)` = 25 for punet. Attempt 6 measured
**1050 MiB** for a phase that really held **3642 MiB** — a 3.47x under-read
that would have reached admission. Fixed by resolving the batch from the
canonical production source, with `inference_batch_size` added to the
phase-aware identity so a batch-1 measurement can never answer for batch 25.
Training's identity and its validated 1474/1476 MiB result are untouched.

**D-C2-18, observation timing.** With batch 25 the probe then reported
**4870 MiB** against formal's 3642 — a 1.34x OVER-read, which is not
"safe": at a 4 GiB ceiling it refuses a candidate formal inference would
run.

*A hypothesis this document previously carried was wrong.* The gap was
attributed to allocator-pool growth across the 14 measurement-only
repetitions. **The artifact does not support that**: `allocator_reserved` is
**4266 MiB in both** the 14-repetition run and a 3-batch run. Repetition did
not grow the pool.

The verified cause is **observation timing**. The driver was sampled at
moments when cached blocks inflated its view. The correction holds the real
post-forward state open instead:

```text
parent confirms sampling is active
  -> worker executes the EXACT configured inference workload
  -> after the forward completes and synchronizes, while the output is still
     GPU-resident and before any CPU transfer or cleanup, the worker HOLDS
  -> parent obtains its three valid samples
  -> worker releases and continues
```

Holding allocates nothing. Only the configured batches execute — no
measurement-only forwards. Training is unchanged and still repeats.

*A defect in the first attempt at it:* the hold was wired to the
**non-blocking** marker probe, so it released instantly — 3 holds, 1 sample,
`INCONCLUSIVE`. Training *polls*; inference must *block*. That single
distinction is the difference between 4870 and 3434 MiB.

**Result:** probe **3434 MiB** vs formal **3642 MiB** (0.943x), 3/3 samples,
1 repetition, exactly 3 batches, 0.80 s. The two now agree on admission at
24 GiB, 4 GiB and 2 GiB.

**Not yet settled.** The probe sits **208 MiB (5.7 %) BELOW** formal — an
under-read, small but on the wrong side, and a systematic one would open a
false-admission band near a ~3.5 GiB ceiling. A short repeatability
characterization decides whether it is sampling noise or a real difference.
No correction factor is applied either way.

### Lifecycle audit of the 208 MiB gap — RESOLVED, cause verified

**The question.** The corrected inference probe reads **3434 MiB**; formal
inference holds **3642 MiB**. Three alternating runs produced **zero
spread** on both sides (probe 3434/3434/3434, formal 3642/3642/3642), so
the **208 MiB (5.7 %)** is deterministic, not sampling noise. An under-read
is on the wrong side: near a ~3.5 GiB ceiling it opens a false-admission
band, admitting a candidate the real phase cannot fit.

**No correction factor and no safety multiplier is authorised**, and none
has been applied. Comparing final peaks again cannot locate the cause;
comparing the two processes *at the same lifecycle points* can.

**Milestones 1-3, measured directly — EQUAL, hypothesis falsified.**

| milestone | probe | formal | delta |
|---|---|---|---|
| 1 process start | 0 MiB | 0 MiB | 0 |
| 2 after imports | 0 MiB | 0 MiB | 0 |
| 3 after CUDA initialization | **596 MiB** | **596 MiB** | **0** |

The probe's heavier import surface (`build_training_optimizer`,
`get_criterion`, the full `MODEL_REGISTRY`) costs **nothing** on the device
against formal inference's leaner one, and the CUDA context is identical.
**The leading hypothesis — that the gap originates in context or library
residency — is dead**, and acting on it would have been wrong. The
divergence lies at or after model construction.

**Arithmetic that constrains the remaining candidates.** punet is 6,762,568
parameters x 4 B = **25.8 MB**, so checkpoint-load transients cannot account
for 208 MiB *on their own*. The output tensor is far larger: at the
production inference batch of 25, `[25, 256, 40000]` float32 = **976 MiB**.

**Suspects at the time**, in the order they were considered plausible:
checkpoint loading (the one step the two paths do not share), the
argmax/`.cpu()` output lifecycle, and loop composition across many batches.

### Milestone audit result — attempt 17 at `7344a726`, EXECUTED

Two runs, no training: one prephase inference (`c7 --phase inference`,
4.4 s) and one reused-checkpoint formal inference (`c12inf`, 17.0 s), each
writing its own immutable trace. **22.6 s total**, inside the authorised
2-4 min envelope. Both baselines reproduced exactly — probe **3434 MiB**,
formal **3642 MiB** — a third independent confirmation. Live registry
fingerprint unchanged on both.

| milestone | b | probe tree | formal tree | Δ | probe alloc/resv | formal alloc/resv |
|---|---|---|---|---|---|---|
| process_start | | 0 | 0 | 0 | –/– | –/– |
| after_imports | | 0 | 0 | 0 | 0/0 | –/– |
| after_cuda_init | | 0 | 0 | 0 | 0/0 | –/– |
| after_model_construction | | 496 | 0 | +496 | 0/0 | –/– |
| **after_model_to_device** | | **732** | **732** | **0** | 218/236 | 218/236 |
| **after_checkpoint_load** | | — | **960** | **+228** | — | **218/464** |
| after_input_to_device | 0 | 850 | 960 | −110 | 230/256 | 226/464 |
| **post-forward, output resident** | 0 | **3434** | **3642** | **−208** | 1206/2830 | 1202/3038 |
| after_output_to_cpu | 0 | — | 3642 | — | — | 1202/3038 |
| after_output_cleanup | 0 | — | 3642 | — | — | 218/3038 |
| post-forward | 1 | **4870** | 3642 | +1228 | 1206/**4266** | 1202/3038 |
| before_exit | | 4870 | 3642 | | 0/4266 | 218/3038 |

**FINDING 1 — the 208 MiB first appears at `after_checkpoint_load`, and
the cause is verified.**

The two paths are **identical at `after_model_to_device`**: 732 MiB tree,
allocator 218/236 on both sides. Nothing before that point differs by a
single MiB. Then formal runs
`model.load_state_dict(torch.load(model_path, map_location=DEVICE))` and
the allocator columns say exactly what happened:

```text
reserved   236 -> 464   (+228 MiB)
allocated  218 -> 218   (unchanged)
```

`map_location=DEVICE` materialises a **second full parameter set on the
device**; `load_state_dict` copies it into the model; the temporary state
dict is then freed — which is why *allocated* returns to 218 — but the
caching allocator **retains the freed segments as reserved**, and
driver-visible memory counts reserved, not allocated. The checkpoint is
216.9 MiB (227,442,408 B); +228 MiB reserved is that plus segment
alignment.

The arithmetic closes with no residual:

```text
pre-forward reserved   formal 464 - probe 256          = 208
the forward adds       2830-256 = 3038-464 = +2574     identical both sides
post-forward overhead  tree - reserved = 604           identical both sides
final gap              3038 - 2830                     = 208 MiB
```

So the entire gap is allocator-pool residue created by the device-side
checkpoint load and carried unchanged through a forward that costs the two
sides *exactly* the same. It is **not** context size, not library
residency, not the output tensor, not sampling noise, and not any property
of the candidate.

**FINDING 2 — the probe has a separate, independent output-lifetime
defect.** The probe reaches **4870 MiB at batch 1** but reports 3434. Its
parent stops sampling once the hold satisfies the sample target, so
batches 1-2 run unobserved. The 4870 comes from the probe's own loop
shape: `output = model(input)` computes the new output while the previous
one is **still bound**, so two 976 MiB tensors coexist and reserved grows
2830 -> 4266. Formal never does this — `process_batch` returns between
batches and its reserved stays flat at 3038.

The reported 3434 is the formal-equivalent state and is the right number,
**but it is right by accident**: it depends on the parent stopping
observation before the artifact appears. An authoritative measurement must
not rest on sampling stopping early. Fixed separately, under "probe output
lifetime" below.

**CORRECTION to D-C2-18's recorded explanation.** That entry attributed
the 4870 MiB over-read to "observation timing" — the driver being sampled
at moments when cached blocks inflated its view. **The milestone evidence
does not support that phrasing and it is superseded.** The cause is
specific and structural: two live outputs during the loop's rebinding.
This also supersedes the *earlier* hypothesis, already retracted once,
that repetition grew the allocator pool — repetition is not the mechanism;
simultaneous residency is. Recorded here rather than quietly edited above,
because a hypothesis that was wrong twice is worth leaving visible.

**No correction factor and no safety multiplier is applied, proposed or
implied by any of this.**

**Resolution, operator decision 2026-08-03 (Option A).** The gap is closed
by removing the waste, not by adjusting the measurement:

* **formal inference** loads the checkpoint on the **host**
  (`map_location="cpu"`, then `load_state_dict`, then release), so no
  second parameter set is ever materialised on the device. Real GPU usage
  falls ~228 MiB and predictions are unchanged. This is a production
  behaviour change to inference, **explicitly separated into its own
  hotfix PR off master** rather than folded into C2 — C2 must not carry a
  standalone production optimisation's responsibility.
* **the probe** releases each output before the next forward begins, so no
  two outputs are ever resident and the measurement cannot depend on
  observation stopping early.

Option B — having the probe reproduce formal's pool residue — was rejected.
The pre-phase measurement runs *before* training, so no checkpoint exists
to load, and allocating-then-freeing a parameter-sized block purely to
inflate a reading is manufacturing a number.

Both corrections are pending; **neither is implemented in this commit**.

### Reconciliation onto master after the hotfix — 2026-08-04

PR #163 (`fix(inference): load the checkpoint on the host, not the device`)
merged to master as `9533c65d`. This branch took it by **merge, not
rebase**: C2 is already published with 28 commits, and rewriting that
history would force every reader to re-fetch a different one for no
benefit. No force-push was used.

**One conflict**, exactly where both sides edited the same region of
`execute_tools/inference_single.py` — the hotfix at the checkpoint load,
C2 at the milestone call site. Resolved by keeping master's host-side load
verbatim and retaining C2's `after_checkpoint_load` milestone, **moved to
after the host copy is released** so it captures the settled post-load
state rather than a transient.

That milestone's purpose inverts with the fix. It was written to expose a
defect; it now guards against the defect returning: with the host-side
load, allocator reserved must stay at the model-only baseline there
instead of rising by a checkpoint, so a regression that moved the load
back onto the device would surface at exactly this point. The comment was
rewritten to say so rather than left describing behaviour that no longer
exists.

**Verified preserved after the merge**, each present exactly once: the
final merged C1 text (`16-STATUS`), both C1 Behavior Deltas (`16a-BD`,
`16a-BD-2`), the complete C2 audit history including `Milestone audit
result — attempt 17`, `FINDING 1`, `FINDING 2` and the `CORRECTION to
D-C2-18`, and the host-side checkpoint Behavior Delta in
`docs/optimize_inference_and_scoring.md`. **C-C5b remains recorded as
CANCELLED** in all six places that reference it, with no stale pre-C1 text
restored anywhere.

### Parity validation — attempt 18 at `bc71fbb5`, PASSED

Two runs, no training, 22.2 s total. **Probe 3434 MiB, formal 3434 MiB —
exact parity, zero gap.** Post-forward allocator reserved 2830 MiB on both.

| milestone | probe | formal | Δ |
|---|---|---|---|
| after_model_to_device | 732 | 732 | 0 |
| **after_checkpoint_load** | — | **732** (resv 236→**236**) | — |
| post-forward b0 | **3434** | **3434** | **0** |
| post-forward b1 | **3434** | **3434** | **0** |
| post-forward b2 | **3434** | **3434** | **0** |

Both corrections confirmed at their own milestones: the checkpoint load
strands nothing (was 236 → 464), and the probe holds one output per batch
across all three (batch 1 was 4870 MiB with reserved 4266).

**Admission agrees at every ceiling** — ADMIT at 24 / 4 / 3.5 GiB, REFUSE at
2 GiB. 3434 MiB = 3.354 GiB, leaving **150 MiB** below the 3.5 GiB ceiling.
No correction factor.

*The omitted CPU transfer is not a defect.* Formal's `after_output_to_cpu`
reads 3434 / 1202 / 2830 — identical to its own post-forward — so the
argmax and `.cpu()` allocate nothing beyond the pool and the probe's
omission of the decode is **measurably invisible**. Measured rather than
assumed, which is why no speculative fix was added.

Integrity: 3/3 and 64/0 samples with `covered_whole_phase`,
`outputs_released == inference_batches == 3`, identity/UUID/batch matched,
registry `b5f7c5a5…` unchanged, no orphans.

**Standing regression evidence** (operator, 2026-08-04) — these must keep
holding, and are cheap to check in any future artifact:

* `after_checkpoint_load` stays at the model-only allocator baseline;
* `outputs_released == inference_batches`;
* every configured inference batch reports the same peak;
* sampling does not stop early and conceal a later peak.

### WITHDRAWN — the fixed-integer Case 12 packet (2000 / 160)

**Operator decision 2026-08-04.** The section below is retained as the
derivation record; its integers are **RTX 5090 observations and are not a
portable workload definition**. They must never become H100 Gate constants.

Two things were wrong with using them as the definition:

1. **They encode one machine's speed.** 2000 steps and 160 batches came
   from 8.0762 ms/step and 0.705 s/file measured on a 5090. On an H100 the
   same integers buy a different amount of execution and nothing in the
   design would notice.
2. **They were partly measuring storage.** Of the 14.45 s inference phase
   they were derived from, **4.25 s (29 %) was filesystem** — input read
   2.27 s, output write 0.72 s, per-file residual 1.27 s. A duration target
   for a GPU property was partly a disk benchmark.

Replaced by the live stability rule below. See *Live stability completion*.

### Live stability completion — implemented `[x]`

Completion is decided from execution on the machine under test, never from
another card's clock:

```text
prepare the bounded input        (outside the measured window, timed separately)
-> open the measured GPU phase
-> real forward / backward / optimizer step
-> every COMPLETED step recorded, device synchronized first
-> parent watches the driver-visible cumulative peak
-> peak increases -> stable-step counter AND post-peak reading count reset
-> peak unchanged for 500 completed steps with >= 3 readings since
   -> parent signals stop
-> trainer stops BETWEEN steps, never mid-update
```

**Criterion** (all required): the first optimizer step has completed; an
authoritative driver-visible peak exists; the cumulative peak has not risen
for **500** subsequent completed steps; at least **3** valid readings after
the last increase; sampling complete; identity and GPU UUID match.

500 is a margin expressed in *real work*, not converted from a duration —
a faster card simply reaches it sooner.

**Backstops**: 5000 completed steps and a configurable wall-clock cap, each
per-Gate. Reaching either returns `INCONCLUSIVE` — the peak was still
moving, so no requirement is claimed and no limit is raised mid-Gate.
Stability is checked *before* the backstops, so a phase that settles on its
last allowed step still passes.

**The parent owns the decision**, for D-C2-13's reason: the trainer cannot
see its own process tree's driver-visible memory. It emits evidence and
obeys a signal; it never concludes.

**Inference completion is unchanged and already correct**: resolve the
machine's own `inference_batch_for(model_type)`, run the configured real
batches, hold each output until the samples land, release before the next
forward, require complete observation. No inherited duration.

**Validation-only, disabled by default.** `SIDERIUS_C2_FORMAL_STABILITY`, a
Pydantic-validated JSON channel; no production CLI, no config key, no
default changed. The trainer never names the variable — it goes through
`channel_from_environment`, the one place the channel is parsed.

**Tests** — `tests/unit/core/test_formal_stability.py` (33). They fail
when: the control is reachable without a channel or by a production flag; a
partial step can be recorded; events from another run are counted; the log
acquires a decision method; 499 stable steps pass; 500 steps with too few
readings pass; enough readings without enough steps pass; a later peak
increase fails to reset; a repeated peak is treated as an increase; a
failed reading is read as a fallen peak; the first step becomes optional; a
backstop reports `STABLE`; the event precedes the optimizer update; the
stop is checked before the event; the event is unsynchronized; a phase or
inference concept leaks into the training rule; or a 5090 timing constant
appears in the portable rule.

**Behavior Delta (production): none.** Every flag, default, config key and
scientific output is unchanged, and with no channel the loop is identical.

### D-C2-19 — external activity: change, not presence `[x]` APPROVED (operator, 2026-08-04)

**Decision.** No case requires an idle GPU. The rule that voided a pair
whenever any foreign CUDA process existed is withdrawn.

**Why the old rule was wrong in three independent ways.**

1. **It flagged presence, not effect.** The candidate's requirement is
   `own_tree_mib`, attributed by process **ancestry** — a neighbour's memory
   is excluded by construction. Case c9 exists precisely to prove that split
   holds with an unrelated CUDA process resident, so a rule voiding every
   case with a neighbour contradicted the case demonstrating neighbours are
   handled. Attempt 4's c9 evidence was itself taken on a busy card (own
   1474 MiB vs other 2026 MiB) and was valid.
2. **`own = {os.getpid()}` was a single PID.** It excluded our *own*
   descendants — the measurement worker, the training subprocess, the
   inference subprocess. It survived only because the two snapshots were
   taken between arms, when the children had exited; any overlap and a
   Case 12 pair would have declared itself contaminated by its own work.
3. **Two snapshots cannot see a transient** (operator amendment). A
   neighbour starting after the "before" shot and exiting before the
   "after" shot leaves both endpoints identical while having perturbed the
   entire run.

**Three questions, kept apart.**

```text
what does the candidate need?   own_tree_mib, by ancestry
                                -> external processes NEVER added
can this device fit it now?     device used / free / external occupancy
                                -> external processes ALWAYS considered
did the environment shift?      external PID membership and MiB over time
                                -> THIS is what "contaminated" may mean
```

**What is recorded for every real case**: the candidate-owned process tree;
external PID membership over time; external memory over time; total device
used and free; whether external conditions changed materially; and whether
that change affected the result.

**A case is invalid only when** external activity materially affects
process attribution · sampling completeness · OOM or timeout causality ·
current-capacity evaluation · paired-comparison comparability. Then the
affected case or pair is marked contaminated, its artifact is **preserved**,
and **only that pair reruns** under a new immutable sub-attempt. The Gate is
never invalidated as a whole.

**Per-case requirement** (`requirement_for_case`, one place so the matrix
cannot drift from the rule enforcing it):

| requirement | cases | meaning |
|---|---|---|
| `stable` | default (c1, c2, c7, c10, c11, c4, c5, …) | a neighbour is allowed; movement is not |
| `comparable` | c12a, c12b, c12char | the arms met comparable conditions — a steady neighbour satisfies this |
| `controlled_neighbour` | c9 | a neighbour is **required**; it is the evidence |

There is deliberately **no `quiet` requirement.** An earlier draft demanded
an empty card for c4, c5 and Case 12. That was wrong on each: c4 verifies a
deadline stops the work and cleans up, not how fast anything runs; c5's
configuration exceeds the whole card by construction, so what must be
established is that the OOM came from the candidate's own allocation path —
a statement about **causality**, checked on the RESULT rather than on the
surroundings; and Case 12 compares paired arms, so it needs the arms
*comparable*, which a steady neighbour provides.

For OOM and timeout cases the typed result states the causality explicitly:
whether refusal came from **requirement-exceeds-cap** or from
**insufficient current free capacity**. Those are different facts about the
device and must not be reported as one.

**Implementation**: `core/runtime_control/environment_stability.py`
(`assess_environment`, `summarize_environment`, `requirement_for_case`).
`GpuAccountingSnapshot` and `TreeMemorySample` now retain *which* processes
were external, not only how many — a count cannot distinguish "the same
neighbour throughout" from "one left and another arrived".

**Tests**: `tests/unit/core/test_environment_stability.py` (22). Failing
cases include: a steady neighbour voiding an attribution case; our own
descendants counted as foreign; a transient hiding behind equal endpoints;
a same-PID memory move going unseen; driver jitter read as a change; a
failed sample read as an empty device; c9 passing with no neighbour.

**Behavior Delta (production): none.** Environment assessment runs only in
the validation harness.

### D-C2-20 — the parent-side live-stability controller `[x]` implemented

**The gap.** D-C2-13 established that only the parent can see the tree's
driver-visible memory, and the live-stability rule was written on that
basis — but nothing polled, nothing signalled, and nothing collected a
result. Two further defects made the gap invisible:

1. **The trainer wiring was in the wrong engine.** `_stability_log()` and
   the step emission sat in `run_experiment`, the legacy single-file path
   reached only when `sample_set is None`. Every Gate arm and every chain
   round runs `run_experiment_streaming`. **No formal arm would have
   emitted a single step event**, and every phase would have run to its
   backstop with the stop rule silently inert.
2. **The guard test named the right function and checked the whole file.**
   `_training_loop_calls()` documented itself as "inside the streaming
   training loop"; its body was `ast.walk(tree)` over the module. Three
   assertions passed on wiring that existed only in the other function. It
   is now scoped by function name and parameterized over both engines.

**The boundary.** `core/runtime_control/formal_stability_controller.py` —
not inline in the harness, because correlating step progress with driver
samples, deciding, signalling and reporting is a responsibility, and
`HyperparamTuningAgent.run()` reached 2,487 lines by absorbing one more of
those at a time.

```text
trainer                              parent (the controller)
completed optimizer step
  -> append StepEvent          --->  read events (run_id AND candidate_id)
                                     read the driver sample series
                                     -> evaluate_stability
                                     -> peak rose?  both counters reset
                                     -> settled?    touch stop_path
  <- read stop_path (between steps)
break, save the checkpoint
                                     -> completion() -- typed result
```

**Four separations.**

* **Stopping is not certifying.** The signal ends the phase;
  `FormalPhaseCompletion.succeeded` decides whether the peak may be quoted.
  A backstop stops and certifies nothing.
* **An incomplete watch cannot certify.** A peak that rose inside an
  unwatched stretch is invisible to the arithmetic, so `succeeded` also
  requires `sampling_complete`. The honest outcome is a rerun of that arm.
* **Steps come from steps.** Never inferred from elapsed time or sample
  count — a stalled trainer emits samples at full cadence and no steps, and
  a rule counting readings would call that stability.
* **Identity before arithmetic.** Events are matched on **both** `run_id`
  and `candidate_id`. Case 12 runs six formal arms under one Gate; an arm
  counting a sibling's steps would reach the threshold without executing it.

**Misuse raises, outcomes are values.** A pre-existing `stop_path` would
stop the trainer at step 1 and report a single step's peak as settled; a
pre-existing events log carries this run's identity by construction and
would be counted as this phase's work. Both raise
`FormalStabilityMisuse`. The guard caught its first defect immediately —
the first draft of the new tests built the controller *after* writing
events, and every case errored. The tests were fixed, not the guard.

**Races proved**: a step event and a peak sample at the same instant (the
tie resolves conservatively — the step is not credited to the stable tail,
so simultaneity delays stability rather than manufacturing it); the signal
written while the trainer is between steps; the trainer finishing before
stability; a stale event from another run or another arm; a torn trailing
line; an incomplete sample stream; a crash before any evaluation.

**Reachability**, structurally over the harness AST: the formal arm
constructs the controller; the watcher **spans** the blocking
`execute_training` call (polling after it returns is not watching); the
completion reaches the returned record under a `stability` key; the channel
is set in `os.environ` and **restored in a `finally`**, so one arm's channel
cannot follow the next five.

**Tests**: `tests/unit/core/test_formal_stability_controller.py` (33),
`tests/unit/core/test_formal_stability.py` (41). Mutation-proved: removing
the streaming wiring fails 2 tests **on the streaming parameter only**;
deleting the watcher fails the reachability tests; suppressing the
stop-path touch fails 4; discarding the completion fails 1.

**Behavior Delta (production): none.** Without
`SIDERIUS_C2_FORMAL_STABILITY` no file is opened, no event is written, no
signal is read, and both training loops are byte-for-byte the loops they
were.

### D-C2-21 — comparability is effect-based `[x]` APPROVED (operator, 2026-08-05)

**Decision.** External occupancy drift is not, by itself, contamination.
`environment_shift_observed` and `pair_comparable` are separate facts, and a
shift may be observed while the pair remains perfectly comparable.

**What forced it.** Gate 2 Lite-A **attempt 20** produced valid measurements
and a **false-negative comparability result**. Six formal arms ran with a
live neighbour (`/home/wenyu/summer/.venv/bin/python`) oscillating
692–844 MiB. All three pairs were refused. The same artifacts refute the
refusal:

| arm | external MiB | range | candidate peak |
|---|---|---|---|
| p1 with_probe | 824–824 | 0 | 1476 |
| p1 without_probe | 694–844 | 150 | 1476 |
| p2 with_probe | 704–704 | 0 | 1476 |
| p2 without_probe | 692–824 | 132 | 1476 |
| p3 with_probe | 704–824 | 120 | 1476 |
| p3 without_probe | 694–844 | 150 | 1476 |

Every arm measured **1476 MiB** training and **3434 MiB** inference, with
`admitted` on all six. Six arms cannot agree to the megabyte if the drift
had moved the thing being compared.

**Two errors produced it.**

1. **Concatenation.** The rule pooled both arms' series and took one
   min/max. That cannot distinguish *oscillation within an arm* — which
   affects both alike and leaves them comparable — from *a shift between
   arms*, the only thing that breaks a paired comparison. In pair 1 the
   with-probe arm was **flat at 824 MiB**; the "150 MiB shift between arms"
   was entirely its partner's internal wobble.
2. **An absolute threshold.** 64 MiB means nothing without reference to
   what is measured. Against a 1476 MiB candidate with ~21 GiB headroom and
   ancestry-based attribution, 150 MiB of neighbour drift cannot change
   attribution, capacity, causality or the peak. **The threshold is removed
   and not replaced by a larger one.**

**Per-arm analysis, never pooled.** Each arm records, from its own series:
external PID membership · min / median / max external MiB · external range ·
minimum free device memory · candidate-owned peak · admission result ·
sampling completeness. The two arms are then compared.

**A pair is comparable when** candidate-owned attribution is complete ·
sampling is complete · candidate/configuration/GPU identity matches · both
arms completed without external-capacity-induced OOM or termination ·
sufficient device headroom existed for each arm · and external activity did
not change the candidate peak, the admission verdict, or the acceptance
property being compared.

**For Case 12 the acceptance property is GPU-memory peak and admission
equivalence** — not wall-clock performance under compute contention. A
neighbour that slows both arms equally does not touch the claim.

**A pair is never refused merely because** the same external process
oscillates · a within-arm range exceeds some fixed number · external
occupancy is nonzero · a process appears in only one arm (recorded, and
invalidating only when it affected the result).

**The rule keeps its power.** Different peaks under *matched* conditions
remain comparable and are reported as a genuine probe effect — otherwise
Case 12 could never detect the thing it exists to detect. A difference is
unattributable only when the arms' external bands do not overlap at all.

**Implementation**: `core/runtime_control/environment_stability.py` —
`ArmEnvironment`, `summarize_arm`, `assess_pair_comparability`. The harness
translates once, in `summarize_formal_arm`, so a replay from a sealed
artifact and a live arm reach the assessor through the same code.

*Also fixed here*: the artifact's `environment_samples` key held the series
as Pydantic objects, which the manifest writer's `default=str` turned into
repr strings — recorded but not machine-readable, so no replay could
re-derive the assessment from the artifact. It is removed; `raw_samples`
was already proper JSON and is now the single copy.

**Tests**: `tests/unit/core/test_environment_stability.py` (43), with
`tests/fixtures/c2_lite_a20_case12_environment.json` — the **real** six-arm
series from attempt 20 — as the regression fixture. Mutation-proved:
reintroducing a 64 MiB refusal fails 4; pooling the arms fails the
structural guard; dropping sampling completeness fails its own case.

**Behavior Delta (production): none.** Environment assessment exists only in
the validation harness.

### Historical derivation — the withdrawn fixed-integer bound

The long arm ran **863.8 s of training** whose peak stopped moving after
**5.883 s** (99.32 % stable tail) and **15.6 s of inference** whose peak
stopped moving after **1.342 s** (91.4 % stable tail). Everything after
those points is cost with no acceptance value.

**Derived from integers, not from a percentage.** A slice cannot say how
many steps will run — `--formal_train_portion 0.01` produced ~107,000
steps. The bound comes from the measured per-unit costs in the `c12char`
artifact (`d48c7b34`):

```text
training   8.0762 ms/step  (steady state, 62 steady units)
inference  0.705 s/file    (20 files x 2 PSD segments, 14.1 s total)
geometry   10,000,000 / 40,000 = 250 model segments per PSD segment
           = 250 training steps per PSD segment at batch_size 1
```

| target | smallest integer exceeding it | realized |
|---|---|---|
| 15 s training | 1858 steps → **8 PSD segments** (7 gives 1750 steps = 14.13 s) | **2000 steps = 16.15 s** |
| 5 s inference | **8 files** (7 gives 4.94 s) | **160 batches = 5.64 s** |

Realized as **8 files × 1 PSD segment** (training) and **8 files × 2 PSD
segments** (inference), so the per-file path is exercised eight times
rather than collapsed into one file.

**Margins over saturation**: training 16.15 s against 5.883 s (2.7×);
inference 5.64 s against 1.342 s (4.2×). Both peaks are established with
room to spare, and neither window ends while the peak is still rising —
which the Gate checks rather than assumes.

**Harness-only bounded control.** `execute_training` has no step cap and
the trainer has no `--max_steps`, so four validation-only flags were added
to the harness — `--formal_train_files`, `--formal_train_psd_per_file`,
`--formal_eval_files`, `--formal_eval_psd_per_file`. **No production CLI
was added and no formal default changed.** The sample sets are still built
by the production `build_sample_set` under a real `DataScope`, so DataScope
enforcement is byte-identical; only the *selection* is stated as integers.

**The realized counts are verified, not assumed.** `trial_portion` is a
fraction of `segments_per_file` and rounding could yield one segment more
or fewer than requested; a Case 12 that silently ran a different workload
than the one derived from the saturation evidence would invalidate the
margin it exists to provide. A mismatch raises **before any GPU work**, and
half a bound (files without segments, or the reverse) is refused outright.
The executed integers are recorded in the artifact as `workload_bound`,
together with the per-unit costs they were derived from — carried for
audit, never used to scale or correct a measured peak.

**All three alternating pairs are kept**, and every formal arm still
performs production model and checkpoint loading, real data construction, a
real forward, a model-connected backward, the first optimizer step and its
state allocation, enough further training to clear the margin, real formal
inference, and complete process-tree sampling.

**Expected cost**: ~29 s per formal arm (4.5 s setup + 16.15 s training +
5.64 s inference + startup), ~62 s per pair, **~3.1 min for Case 12**;
c1-c11 ~3 min; **~6.2 min total Lite-A**. Inside the 6-10 min target and
below the 15 min threshold, so no new Cost Justification is required.

**Normal production Behavior Delta: none.**

### Probe output lifetime — FINDING 2 fixed `[x]`

The inference loop now releases each output before the next forward:

```text
forward -> synchronize -> hold while the parent samples -> parent confirms
        -> release the output -> only then the next forward
```

`del output` at the end of each iteration, plus an `outputs_released`
counter on `RealismEvidence` so the property is checkable from a persisted
artifact rather than only by rerunning.

**The release is unconditional** — it does not depend on the parent
confirming. The batches that leaked were precisely the ones the parent had
stopped watching, so making cleanup conditional on the parent's answer
would leave the exact case that concealed the defect still leaking.

**No production-equivalent CPU transfer was added.** Formal's decode
(`output.argmax(dim=1).detach().cpu()`) dispatches on the model's
output-type contract and the loss's target dtype, and reproducing it inside
the measurement worker would put a second copy of `process_batch`'s
dispatch logic where it could drift. Its transient is ~8 MiB at batch 25
against a ~3.4 GiB phase. Whether that omission is visible at all is what
the parity check measures rather than assumes; if it is, the decode is
added then and not speculatively.

**Tests** — `test_gpu_measurement_phases.py`. They fail when: an earlier
output survives into a later forward (checked at the START of each forward,
over weak references, so a strong reference in the test cannot mask a
missing release); fewer than the configured batches execute; the release
becomes conditional on the parent; `outputs_released` disagrees with the
batches executed; or training's repetition behaviour changes.

**Mutation proof**: removing `del output` — restoring the rebinding without
cleanup — fails `test_the_output_is_released_before_the_next_forward`.
Applied to a file backup with `__pycache__` cleared and a `count == 1`
assertion on the edit site, then restored and re-baselined at 1827 passing.

### Validation-only milestone tracing — implemented `[x]`

Approved to locate milestones 4-7. It may touch the formal inference path,
and does, under strict conditions: **disabled by default, unreachable
without an explicit validation environment variable, behaviour-preserving
when disabled, no LLM call, no production configuration change, and no
ordinary production CLI flag.**

**The channel.** `SIDERIUS_C2_INFERENCE_MILESTONE_TRACE`, whose value is a
Pydantic-validated JSON channel — an explicitly writable artifact path, the
device UUID, a run id, and an optional `max_traced_batches` — never a bare
boolean. With it absent, `tracer_from_environment` returns `None`: no
channel parsed, no file created, no driver query taken, and no tracer for
any call site to hold. **The absence of the tracer IS the disabled state**,
which is why there is no "enabled" flag anywhere to get wrong. Production
never sets it, and a test scans the production sources to keep that true.

**One memory policy, not two.** Every figure comes from
`gpu_accounting.sample` — the same primitive `gpu_measurement_sampler`
polls, the same ancestry-based ownership rule, the same refusal to read a
failed query as zero. No pynvml, no private `nvidia-smi`, no second
definition of "driver-visible".

**Milestones.** Six once-per-process (`process_start`, `after_imports`,
`after_cuda_init`, `after_model_construction`, `after_model_to_device`,
`after_checkpoint_load`, plus `before_exit`) and four per-batch
(`after_input_to_device`, `after_forward_output_resident`,
`after_output_to_cpu`, `after_output_cleanup`), each recording timestamp,
side, phase, milestone, batch index, candidate-owned PIDs and their
per-PID MiB, the process-tree total, allocator allocated/reserved,
`cuda_initialized`, `cuda_synchronized`, live input shape/dtype, model
dtype/mode, output residency/shape/dtype, GPU UUID, candidate identity,
inference batch size, run id and the exact Git SHA.

**`after_checkpoint_load` is an addition to the plan's ten**, deliberately.
The plan's milestone 4 reads "after model construction **or** checkpoint
loading", but formal inference does BOTH while the probe does neither —
folding them into one name would hide precisely the step the two paths do
not share. The probe never records it, and that absence is evidence.

**Milestone 7 placement is the load-bearing decision.**

```text
forward completes -> CUDA synchronize -> output STILL GPU-resident
  -> record -> only then argmax / .cpu() / release
```

Taken after the transfer it would describe a different state while looking
identical. It allocates nothing, extends no lifetime (`output` is live
there anyway, because the decode reads it), adds no forward, and changes no
batch count, model loading, output handling or cleanup semantics.

**Where the two sides are honestly not equivalent**, recorded rather than
smoothed over:

* `inference_single.py` imports torch at module scope, so `process_start`
  and `after_imports` are both taken at `main()` entry. Recording them
  earlier would need a statement above the imports (E402) and a first-party
  import ordered above the third-party ones (I001), and this repository does
  not disable lint rules to make code fit. Both sides agree on what the two
  milestones MEAN — process entry, torch available, CUDA not yet initialized
  — and milestones 1-3 are already closed by direct measurement, so nothing
  load-bearing rests here.
* CUDA context creation is lazy. On the probe it happens inside
  `resolve_device`'s `get_device_properties`; on the formal path at the
  first device allocation. Each record's `cuda_initialized` field states
  which is true rather than the milestone name implying it.
* The probe emits no `after_output_to_cpu` / `after_output_cleanup` and no
  `after_checkpoint_load`, because it performs none of them. Missing
  milestones are a first-class outcome the comparison reports.

**One behaviour-preserving refactor**, in both files and the same way:
`model_class(cfg).to(DEVICE)` split into two statements so a milestone can
sit between construction and transfer. `nn.Module.to()` moves parameters in
place and returns `self`, so both forms perform an identical sequence on an
identical object; a test asserts exactly one device transfer survives.

**Tests** — `tests/unit/core/test_gpu_milestone_trace.py` (44). They fail
when: the variable is absent and anything is written · a malformed or
unwritable channel does not raise `MilestoneTraceUnavailable` **before** any
measurement · a failed driver query is recorded as 0 MiB · a sampler
exception escapes instead of becoming a value · a milestone is recorded
twice or out of order · the per-batch bound is applied without recording it
· the default sampler is not `gpu_accounting.sample` · a rival telemetry
backend appears · milestone 7 is missing, is before the forward, is after
the `.cpu()` transfer, does not synchronize, or is not passed the live
output · the probe's milestone 7 leaves the observation hold · a
`trace.record()` argument becomes a call that could allocate · the record
retains the output tensor · `process_batch` returns different arrays or
runs a different number of forwards with the tracer attached · the worker
launcher starts curating `env=` and would drop the trace.

**Mutation proofs**, each applied to a file backup, with `__pycache__`
cleared, a `count == 1` assertion on the edit site, then restored and
re-baselined at 44 passing:

| mutation | tests that failed |
|---|---|
| delete milestone 7 from `process_batch` | 6 |
| move milestone 7 after the CPU transfer | 4 (incl. the runtime order guard raising `MilestoneTraceMisuse`) |
| swap the default sampler for a rival memory policy | 1 |

**No harness change was needed.** Neither launcher passes `env=` —
`gpu_measurement_runner.py:271` and `sandbox_executor.py:300` — so the
variable reaches both the probe worker and the formal inference subprocess
by inheritance. A test asserts that stays true.

### Cost justification — the minimal inference-only GPU audit (NOT YET RUN)

| | |
|---|---|
| **Acceptance property** | the first lifecycle milestone at which the probe and formal inference diverge, and by how much |
| **Why existing artifacts are insufficient** | every preserved artifact records phase *peaks*, not per-milestone occupancy. No artifact at any SHA contains a milestone series, so the first point of divergence cannot be read out of one. Milestones 1-3 ARE already closed and are not re-run. |
| **Minimum workload** | one corrected pre-phase inference measurement + one formal inference. **No training.** Fresh processes, milestone trace enabled, `max_traced_batches=2`. |
| **Expected wall time** | ~2-4 min total (probe ~3 s; formal inference ~16 s at the established timings; the remainder is process startup and CUDA init on each side) |
| **Expected GPU time** | < 30 s of actual device work |
| **Expected storage** | one NDJSON trace, ~20-30 records, < 100 KB, plus the existing immutable case artifacts |
| **Early-stop conditions** | stop if the trace is empty or missing milestone 7 on either side (infrastructure failure, not a result); stop if projected wall time exceeds 10 min; stop if the formal figure is not 3642 MiB, since the gap would no longer be the one under audit |
| **Evidence reused** | training probe/formal equivalence (1474 vs 1476 MiB) · training peak saturation at 5.88 s of 870.008 s · the three alternating probe/formal repeats · milestones 1-3 (0/0/596 both sides). **None of these is re-measured.** |

**Not executed.** The exact command, expected cost and artifact paths are
ready; the run itself awaits operator authorization.

### Documentation synchronization — C2

**Production behavior changed.** A formal attempt on a real device now runs
a bounded isolated GPU measurement before any formal GPU work and consumes
one typed disposition; a stop consumes the attempt and starts no GPU work.
Formal admission receives a real requirement instead of `policy_unavailable`.

| | |
|---|---|
| **Affected nodes** | `ml_hyperparameter_tune_agent` — its formal call path gained a phase |
| **Affected agents** | none — no agent-facing prompt, schema or decision surface changed |
| **Affected skills** | none *behaviourally* (see inspected-unchanged below) |
| **Affected CLI surfaces** | none in production (**no flag was added**); one validation-only surface, `scripts/c2_prephase_validation.py` |

**Files updated**

* `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md` — new
  *Pre-phase GPU measurement (V20 PR C2)* section: the call sequence, the two
  applicability rules, all seven dispositions and their PR B lanes, the O-7
  accounting, the resource cost, the deadline/soft-budget values, and the
  explicit statement that **there is no flag**. The round-loop list gained
  step 2b so the documented phase order matches execution order.
* this document — D-C2-11 and the corrected Gate packet.

**Files inspected and NOT changed, with the reason**

| File | Why unchanged |
|---|---|
| `agent/skills/training_skill/training_skill.md` | `execute_training`'s signature, inputs and behaviour are untouched; C2 runs *before* it and the harness calls it exactly as production does |
| `agent/skills/evaluate_vram_skill/evaluate_vram_skill.md` | `isolated_probe`'s only change is delegating three private helpers to `core.runtime_control.process_group`; bodies moved verbatim, names preserved, behaviour identical |
| `nodes/ml_hyperparameter_tune_agent.md` (top-level) | describes the node's I/O contract, which did not change — no new input, no new output field |
| `docs/running_chain_test.md` | documents launcher flags; no production flag was added or renamed |
| `docs/gates/gate_testing_standard.md` | C2's gates follow the existing standard rather than amending it |

**Command parsing evidence.** `--dry_run` executed against the real
environment. *Historical record of what was run at the time* — the
parameters below were the packet's then-current ones and were **superseded**
for Case 12 by the live-stability block (D-C2-20); the portion flags still
exist and still parse (`--formal_train_portion 0.01 --formal_eval_portion
0.01 --formal_seed 137`): `device_uuid_matches: true`,
`spec_constructs: true`, `candidate_registered: true`. Every flag in every
documented command block is checked against the harness's real `argparse`
actions by `test_c2_documentation_sync.py`.

**Structural documentation tests** — `tests/unit/scripts/test_c2_documentation_sync.py`
(22). They fail when: a documented CLI flag does not exist · the approved
gate parameters are not real flags · the renamed `--formal_trial_portion`
appears in active text · a validation-only flag appears in the production
node doc · the node doc omits any `PrephaseDisposition` that exists in code
· the node doc omits an O-7 statement · documented deadline/soft-budget
values diverge from the code constants.

**Remaining documentation gaps.** None known for C2. `docs/running_chain_test.md`
will need the Lite-A/Lite-B procedure once the gates have actually run —
tracked with the gate results, not written ahead of them.

### Documentation synchronization — validation-only milestone tracing

**Production behavior changed:** *no*, in the sense that matters — with the
environment variable absent (always, in production) the traced processes
create no file, take no driver query and hold no tracer, and
`process_batch` returns bit-identical arrays after the same number of
forwards. Three production **files** are touched, and one
behaviour-preserving refactor lands in two of them (the
construct/transfer split, proved to leave exactly one device transfer).
Admission authority, dispositions, O-7 accounting, retry, phase order,
timeout and signal semantics are all unchanged.

| | |
|---|---|
| **Affected skills** | none behaviourally — `inference_skill/wrapper.py` is untouched and invokes `inference_single.py` exactly as before |
| **Affected nodes** | `ml_hyperparameter_tune_agent` — its measurement worker is one of the two traceable processes |
| **Affected agents** | none — no prompt, schema or decision surface changed |
| **Affected CLI surfaces** | **none.** No production flag was added. The only control is the `SIDERIUS_C2_INFERENCE_MILESTONE_TRACE` environment variable, and it is validation infrastructure |

**Files updated**

* `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md` — new
  *Validation-only lifecycle trace* block in the pre-phase section: what a
  milestone records, the channel's JSON shape, that it is off unless
  explicitly switched on, that there is **no CLI flag**, that it does not
  alter admission authority, and that an unwritable path fails as
  infrastructure rather than as a measurement outcome.
* this document — the lifecycle audit record above, the implementation
  record, the mutation table and the cost justification.

**Files inspected but unchanged, with the reason**

**Complete inspection.** Every skill, node and agent `.md` in the
repository was enumerated and inspected, not sampled: the three skill docs
that exist (`evaluate_time_skill`, `evaluate_vram_skill`,
`training_skill`), all seven node/agent docs under `nodes/`, and every
`.md` naming `process_batch`, `model_class(`, `.to(DEVICE)`,
`load_state_dict` or `inference_single`.

| File | Why unchanged |
|---|---|
| `agent/skills/inference_skill/` (no `.md`) | the skill's `wrapper.py` and `skill_config.json` are untouched; it invokes `inference_single.py` with the same argv and the same behaviour. A new doc file is not minted for a change that does not reach the skill's surface |
| `agent/skills/training_skill/training_skill.md` | training is not traced and `execute_training` is untouched |
| `agent/skills/evaluate_vram_skill/evaluate_vram_skill.md` | PR A's probe is not involved in this trace |
| `agent/skills/evaluate_time_skill/evaluate_time_skill.md` | describes the time-estimate composition, not the GPU memory lifecycle; no timing term changed |
| `nodes/ml_hyperparameter_tune_agent.md` (top-level) | its `inference_single.py --mode agent` command block stays verbatim correct **because no CLI flag was added**, and the node's I/O contract gained no field. The environment channel is documented once, in the sub-node doc, rather than duplicated into an operator-facing command listing |
| `nodes/ml_code_validator_agent`, `ml_literature_review`, `ml_model_implementor`, `ml_model_proposal_agent`, `result_interpretation_agent`, `NODE_TEMPLATE` | none participates in the inference call path or in GPU admission |
| `docs/running_chain_test.md` | documents launcher flags; no production flag was added or renamed, and the trace is not an operator control |
| `docs/refine_inference_time_estimator.md` | names `process_batch` only as a timing component of `per_file_elapsed_ms`; the two added parameters are keyword-only, default `None`, and change no timing term |
| `docs/design/enable_loss_inventory.md` | records that `current_loss_name` was plumbed through `process_batch`; still true |
| `scripts/c2_prephase_validation.py` and its packet | needs **no** change: neither launcher passes `env=`, so the variable reaches both subprocesses by inheritance |
| `docs/gates/gate_testing_standard.md` | the audit follows the existing standard rather than amending it |

**Finding recorded, not fixed: `docs/optimize_inference_and_scoring.md`
carries stale line references.** Its Fix 3 entry cites the normal-mode
per-file loop at `inference_single.py:215-234` and the trial-mode loop at
`:151-205`. Both were **already wrong at `14290710`, before this change**:
at that commit line 151 is the argparse tail and line 215 is the end of
`process_batch`. The doc's substance — the `del` + `gc.collect()` pattern
and its measured 9.43 GB -> 5.68 GB effect — remains accurate, and this
change does not touch that pattern. Re-deriving which historical revision
the ranges were correct for is out of scope here; widening a milestone-trace
PR into a line-number sweep of a Phase 6.7 record is exactly the silent
scope growth the regression rule forbids. Tracked separately.

**Command parsing evidence.** No command changed, so there is nothing new
to parse. The existing `test_c2_documentation_sync.py` checks continue to
hold every documented harness flag against the harness's real `argparse`
actions, and `VALIDATION_ONLY_FLAGS` is unaffected because the trace adds no
flag. The environment variable's contract is enforced instead by
`test_gpu_milestone_trace.py`, which exercises the real `os.environ` path
end to end rather than only the injected one.

**Remaining documentation gaps.** The milestone comparison table itself,
which does not exist until the audit runs. `docs/running_chain_test.md`
still needs the Lite-A/Lite-B procedure once those gates have actually run —
tracked with the gate results, not written ahead of them.

**Static checking limitation, recorded rather than claimed.** `ruff check`
and `ruff format --check` pass locally on every touched file. **pyright
could not be run locally**: the vendored binary aborts under this host's
Node v10.19.0, which is below its minimum. CI is the only environment that
can run it, and no claim of local type validation is made here.

### Gate results — BOTH PASSED at `7302c467d81a575e3e35a8f81821eb5dbd63e451`

| gate | hardware | result | attempt |
|---|---|---|---|
| Gate 1 | — | **N/A** (no LLM-facing surface) | — |
| Gate 2 Lite-A | RTX 5090 `GPU-c30b6678-…f8b4-d378-af9681c6ceef` | **PASS** | 20 + 22 |
| Gate 2 Lite-B | H100 80GB HBM3 `GPU-8c96cde6-…6413-4a14-c9125500102d` | **PASS** | 01 |

#### The headline numbers, per machine

|  | RTX 5090 | H100 80GB |
|---|---|---|
| device total | 32,607 MiB | 81,079 MiB |
| training driver peak | 1476 MiB | **1496 MiB** |
| inference driver peak | 3434 MiB | **3384 MiB** |
| training allocator peak | 807 MiB | 808 MiB |
| inference allocator peak | 1612 MiB | 1557 MiB |
| **driver − allocator, inference** | **1822 MiB** | **1827 MiB** |

**The peaks differ between machines, and that is the design working.** No
requirement, duration, step count or cap travels between cards; each is
measured live. A Gate that reproduced the 5090's numbers on an H100 would
be reporting a constant, not a measurement.

The allocator under-reports by 627–1827 MiB. That gap is the whole reason
the authority is driver-visible, candidate-owned, ancestry-attributed
process-tree memory.

#### Lite-A — evidence assembled across two SHAs

| # | evidence | SHA |
|---|---|---|
| 1 | c1–c11 immutable artifacts | `7f8e9ffa` (attempt 20) |
| 2 | corrected replay of all three Case 12 pairs | `7302c467` |
| 3 | live one-pair Case 12 | `7302c467` (attempt 22) |

Reuse across SHAs was operator-approved after an **AST-hash comparison of
every function** between the two commits: the only changed units are
`run_formal_comparison`, `run_formal_execution` and the new
`summarize_formal_arm`, all Case 12 only. The isolated worker, process-tree
sampler, measurement runner, classifier, requirement authority, PR B
admission, O-7 disposition and every c1–c11 execution function are
byte-identical.

Case 12: **probe perturbation 0 MiB** across six arms — 1476 MiB training
and 3434 MiB inference with and without a preceding probe, spread zero.
Arms stopped on live stability at 518–569 completed steps against a
5000-step backstop and a 6000-step data ceiling.

Two sub-attempts, both preserved:

* **c5 sub1** — the worker was SIGTERM'd by the machine's
  `/usr/local/bin/vram_watchdog.py`, 64 MB over a 30,000 MB per-user quota,
  one allocation short of the natural OOM. `term_sent: false` proves the
  kill was external, and C2 refused to call it a CUDA OOM. sub2 won the
  race and produced `MEASURED_CUDA_OOM`. **This is a per-machine hazard: c5
  deliberately allocates ~30 GiB and therefore races any quota watchdog.
  Inspect the watchdog before running c5 on new hardware, and never label
  an externally terminated process as a measured OOM.**
* **c3 sub1** — an ineffective PATH injection. `/bin` is a symlink to
  `usr/bin` on merged-`/usr` systems, so `PATH=shim:/bin` left `nvidia-smi`
  reachable. sub2 used a shim directory containing only `git`.

#### Lite-B — target hardware

Artifacts at
`.gate_artifacts/C2_LITE_B/7302c467…/attempt-01/`, verified
`sha256sum -c SHA256SUMS` → **62/62 OK**, audited from the raw manifests
rather than the run's own summary.

Eight cases: c1, c2, c3, c4, c7, c9 executed; c10 and c16 derived from those
manifests per the approved packet. Every authoritative result carries the
H100 UUID; c1 delivered a real 1.461 GiB `measured` requirement to PR B
against a 72 GiB ceiling; c2 refused from the measured peak against the cap
(1496 MiB vs 512 MiB); c7 measured inference alone; c9 excluded a **2658 MiB**
controlled neighbour from a 1496 MiB candidate; O-7 held on every stop;
`live_registry_unchanged: true` on all twelve manifests; no orphans.

**c2's `pr_b_admission: null` is the designed short-circuit**, not a gap: an
over-cap measurement is refused by the classifier and never reaches PR B's
capacity gate. Identical on both machines.

Non-blocking H100 environment notes: `/dev/md0` was unavailable so the
temporary workspace used the local overlay filesystem; final evidence was
persisted under `/workspace`; the inherited `c2_lite_a…` artifact-name
prefix is cosmetic, since identity is carried by the embedded SHA, attempt
and case; no code, docs, Git history or PR state was changed on the H100.

#### Type-only carry-forward — Gate-tested SHA vs final CI head  `[x]` RESOLVED

| | SHA |
|---|---|
| Gate-tested (Lite-A + Lite-B) | `7302c467d81a575e3e35a8f81821eb5dbd63e451` |
| Final CI-tested head | `5dca28f9652ae003c4f2d3d229aedc03c1ccd730` |
| Merge commit on `master` | `40d17f69c2f4b74cb14e6624a9c72a5ef82d5dac` |

The first CI run on this branch found **44 pyright-strict errors**, all in
C2 files, none inherited (master was green at the merge-base `9533c65d`).
The operator authorized a **strictly type-only** fix so the Gate evidence
could carry rather than rerunning either machine.

| file | errors | root cause | fix |
|---|---|---|---|
| `formal_stability.py` | 33 | `common = dict(...)` unannotated, so its inferred value type joined an int peak, a float timestamp and `base`'s float elapsed time; `**common` offered `float` to every `int` field | the `dict[str, Any]` annotation `base` already carried |
| `gpu_measurement_data.py` | 11 | h5py types `__getitem__` as `Group \| Dataset \| Datatype`, so the chained subscript and the later `.shape` / slice / `.astype` / `.nbytes` were all rejected | `Any` walk + `cast`, mirroring `train_engine_sandbox._h5_dataset`; **no runtime fallback added, read semantics untouched** |
| `gpu_measurement_worker_main.py` | 1 | pyright **widens literal types** when inferring an attribute's declared type from an assignment, so `self.status` inferred `str \| None` despite the parameter being `WorkerStatus \| None` | declare the attribute; the runtime value is unchanged |

**Five non-comment production lines.** Behavioural equivalence was *proven*,
not asserted: against real TIDMAD data the pre-change h5py expression and
the new path produce bit-identical tensors, equal `file_sample_count`
(2,010,000,000), equal `bytes_read` and the same source file, and `cast`
was confirmed a runtime identity. Lite-A and Lite-B were **not** rerun.

**Two lessons worth more than the fix.**

1. **CI had never run on this branch**, so 44 type errors and a guardrail
   violation sat latent behind a locally-green suite.
2. **A locally-green suite is not a green CI.** After pyright passed, CI
   failed once more on a test that read `live_registry_before["sha256"]` --
   a key `live_registry_fingerprint` records only when the calibration root
   exists. It passed on a dev box with `~/.siderius` (27 files) and raised
   `KeyError` on a runner without one. The production function was right:
   it records `present: False` rather than fabricating a digest, exactly
   the shape the H100 manifests carry. The test now covers both worlds and
   the absent branch keeps a real claim -- *a missing tree must never carry
   a digest*.

**Running pyright locally**, since this was got wrong twice: the system
Node is v10.19.0 and too old, but pyright-python caches its own
**Node v26.2.0**, which reproduces CI exactly:

```bash
PATH=~/.cache/pyright-python/nodeenv/bin:$PATH ./.venv/bin/pyright
```

### C2 gate packets — the executable commands

Retained as the record of what was run. Both gates have now PASSED at
`7302c467d81a575e3e35a8f81821eb5dbd63e451`; the "NOT AUTHORIZED" labels
below are historical.

**The call site exists and is unconditional on a real GPU**, so both gates
drive the ordinary formal path -- there is no flag to turn on.

#### Gate 2 Lite-A — RTX 5090, mechanism only  (EXECUTED — PASSED, attempts 20 + 22)

*Establishes that the machinery is correct. Establishes NOTHING about an
H100 requirement.*

**Fixed for every case.** Verified live 2026-08-03.

```text
SHA          `git rev-parse HEAD` at authorization — record it, do not guess
             (a SHA written here can never be current: the commit that
              writes it changes the head)
cwd          /home/yuema137/SIDERIUS
python       ./.venv/bin/python          (never system python3 — it is 3.8)
GPU          index 0 · RTX 5090 · 32607 MiB
GPU UUID     GPU-c30b6678-ff2a-f8b4-d378-af9681c6ceef
driver       575.64 · CUDA 12.8 · torch 2.10.0+cu128
data_dir     /home/klz/Data/TIDMAD/                     (verified present)
workspace    /tmp/c2_lite_a/ws
artifacts    /tmp/c2_lite_a/artifacts
candidate    punet, paper-spec baseline
  model_config  {"segmentation_size": 40000}
  train_config  {"batch_size": 1, "optimizer_type": "adamw", "lr": 0.0005}
  loss_config   {"loss_type": "focal", "alpha": 0.5, "gamma": 2.0}
```

**Command shape.** Every case is one invocation of the same harness; only
the marked arguments change.

```bash
./.venv/bin/python scripts/c2_prephase_validation.py \
    --case <CASE> \
    --device_uuid GPU-c30b6678-ff2a-f8b4-d378-af9681c6ceef \
    --model_type punet \
    --model_config '{"segmentation_size": 40000}' \
    --train_config '{"batch_size": 1, "optimizer_type": "adamw", "lr": 0.0005}' \
    --loss_config  '{"loss_type": "focal", "alpha": 0.5, "gamma": 2.0}' \
    --data_dir /home/klz/Data/TIDMAD/ \
    --workspace /tmp/c2_lite_a/ws \
    --artifact_dir /tmp/c2_lite_a/artifacts \
    --ceiling_gib 24 --deadline_seconds 600 \
    --sampling_interval_seconds 0.25 \
    --training_steps 4 --inference_batches 3 \
    --gate_attempt <N>
```

`--gate_attempt` is required and forms part of the immutable artifact
identity `c2_lite_a<N>_<sha12>_<case>__sub<K>.json` (D-C2-15). For a
synthetic case induced by a shim, add `--injection_shim <path>` so the
manifest records its sha256 and content.

For `--case c12a` (and `c12b`), **training length is decided by live
stability on this machine** (D-C2-20), not by a step count, a duration or a
portion. `--train_config` pins `epochs: 1`. The data bound below is a
*ceiling on available work*, generous enough that the stop comes from the
peak settling rather than from the data running out — if an arm ends
because it exhausted its data, `stability.succeeded` is `false` and the
arm is `INCONCLUSIVE`.

```bash
    --train_config '{"batch_size": 1, "optimizer_type": "adamw", "lr": 0.0005, "epochs": 1}' \
    --formal_train_files 8 --formal_train_psd_per_file 3 \
    --formal_eval_files 8 --formal_eval_psd_per_file 2 \
    --formal_seed 137 \
    --formal_stable_steps 500 --formal_min_samples 3 \
    --formal_max_steps 5000 --formal_max_phase_seconds 120 \
    --prior_cases_wall_seconds <measured 1-11 wall> --max_total_wall_seconds 5400
```

**Inference is unchanged and already correct**: the machine's own
`inference_batch_for(model_type)`, a configured number of real batches, the
post-forward observation hold, and each output released before the next
forward. No inherited duration.

**`--formal_max_steps` and `--formal_max_phase_seconds` are SAFETY
BACKSTOPS, never success criteria.** Reaching either yields
`INCONCLUSIVE_MAX_STEPS` or `INCONCLUSIVE_DEADLINE` — the peak was still
moving when the measurement stopped, so no requirement is claimed. Stability
is evaluated **before** the backstops, so an arm that settles on its last
allowed step still passes rather than being failed for arriving late. Each
Gate sets its own caps for the card it runs on; **no cap, step count,
duration or measured requirement travels between machines.**

**The training ceiling is derived, not chosen.** It must be impossible for
the data to run out *before* the max-step backstop — otherwise the arm ends
in data exhaustion, which is `INCONCLUSIVE` for a reason unrelated to the
peak, and the backstop that exists to bound the run would never be the
thing that bounds it. From the verified geometry:

```text
completed training steps per PSD segment   250   (10,000,000 / 40,000, batch_size 1)
selected files                               8
formal_max_steps                          5000

ceil(5000 / (8 x 250)) = ceil(2.5) = 3 PSD segments per file
                                     -> 8 x 3 x 250 = 6000 available steps
```

**3 is the smallest integer that cannot exhaust first** (1 gives 2000
steps, 2 gives 4000 — both below the 5000 backstop). 6000 available steps
is a **ceiling on capacity, not a required workload**: live stability
remains the success criterion and a typical arm stops far earlier. An
earlier draft used 4 on judgment rather than derivation; it also worked,
but 8000 steps of capacity buys nothing the backstop does not already
bound.

Changing `--formal_max_steps` or `--formal_train_files` therefore requires
re-deriving this integer. A test asserts the documented triple satisfies
`files x psd_per_file x 250 >= formal_max_steps`.

*Withdrawn, 2026-08-04*: the previous packet read `--formal_train_files 8
--formal_train_psd_per_file 1`, described as "2000 training steps
(~16.15 s) and 160 inference batches (~5.64 s)". Those integers encoded one
5090's speed (8.0762 ms/step, 0.705 s/file), and 29 % of the inference
phase they came from was filesystem. They are **derivation evidence, never
portable Gate parameters**, and must not become H100 constants. Note that
the withdrawn value of 1 is also *arithmetically* unusable under the live
rule: 2000 available steps cannot reach a 5000-step backstop.

Case 12 runs pair 1, computes `6 x T_formal + 3 x T_probe` from its real
timings, and continues into pairs 2 and 3 only within the budget;
otherwise it stops with `STOPPED_BY_TIME_BOUND`. **The workload is never
increased during the Gate** — a shortfall is reported, not fixed by running
more.

**Every arm records separately**: data-preparation time · measured GPU-phase
time · completed steps · the step at the last peak increase · stable steps
since · readings since · the exact stop reason · the driver-visible peak ·
allocator diagnostics · the external environment series · current free
capacity.

**Execution order and per-case deltas.**

| # | Case | Argument delta | Expected outcome | Expected admission | O-7 attempt | est. wall |
|---|---|---|---|---|---|---|
| 1 | success | — | `COMPLETED_MEASUREMENT` | ALLOW | not consumed | ~90 s |
| 2 | above cap | `--ceiling_gib 0.5` | `MEASURED_PEAK_ABOVE_VRAM_CAP` | REFUSE | consumed | ~90 s |
| 3 | telemetry unavailable † | run with `PATH` lacking `nvidia-smi` | `INCONCLUSIVE_MEASUREMENT` | REFUSE | consumed | ~90 s |
| 4 | hard timeout | `--deadline_seconds 1` (was 3 — attempt 2 ran in 2.39 s) | `MEASURED_HARD_TIMEOUT` | REFUSE | consumed | ~5 s |
| 5 | measured CUDA OOM | `--train_config '{"batch_size": 1024, …}'` (D-C2-10) | `MEASURED_CUDA_OOM` | REFUSE | consumed | ~120 s |
| 6 | crash † | (harness injects `sys.exit(3)`) | `PROBE_INFRASTRUCTURE_FAILURE` | REFUSE | consumed | ~5 s |
| 7 | phase separation | `--case c7 --phase inference` | `COMPLETED_MEASUREMENT` | ALLOW | not consumed | ~90 s |
| 8 | parent+child residency | — (read from c1/c7 artifacts) | `max_concurrent_own_processes` recorded | n/a | n/a | 0 |
| 9 | ours/other split | second CUDA process held externally | `own_tree_mib` excludes it | n/a | n/a | ~90 s |
| 10 | allocator vs driver | — (read from c1 artifact) | driver ≥ allocator, gap recorded | n/a | n/a | 0 |
| 11 | sampling completeness | `--sampling_interval_seconds 120` | `INCONCLUSIVE_MEASUREMENT` | REFUSE | consumed | ~90 s |
| 12a | perturbation | `+` the live-stability block above (`--formal_train_files 8 --formal_train_psd_per_file 3 --formal_eval_files 8 --formal_eval_psd_per_file 2 --formal_seed 137 --formal_stable_steps 500 --formal_min_samples 3 --formal_max_steps 5000 --formal_max_phase_seconds 120`) | characterization — no expected value | n/a | n/a | 6F + 3P |
| 12b | representativeness | same invocation as 12a | characterization — no expected value | n/a | n/a | shares 12a's runs |

`F` = one bounded production formal execution, `P` = one prephase
measurement (~90 s). 12a runs **3 pairs x 2 arms = 6 formal executions plus
3 probes**; 12b reads the same artifacts, so it costs nothing extra.

† synthetic injection through an existing seam, labelled
`synthetic_injection: true` in the manifest. Neither can carry capacity
authority — neither yields `COMPLETED_MEASUREMENT`, so the authority
contract refuses independently of the label.

**Cases 1-11: ~11 min wall, ~9 bounded GPU executions** (< 8 GiB peak
each, except c5 which is expected to exhaust the card by design).

**Case 12 adds `6 x T_formal + ~4.5 min`.** `T_formal` is **not known in
advance and is not fixed by the packet** — the training arm ends when this
machine's driver-visible peak has settled (D-C2-20), so its length is a
property of the card under test. It is bounded above by
`--formal_max_phase_seconds 120` per training phase, which caps Case 12's
training contribution at `6 x 120 s = 12 min` in the worst case; the 5090
evidence (peak saturating at 5.883 s) suggests the real figure is far
below that, but **the projection uses the measured pair-1 timing, never an
assumed one**. Pair 1's real `T_formal` drives the budget checkpoint, as
it always has.

**The formula, stated before the number:**

```text
c12 cost = 6 x (formal training + formal inference) + 3 x prephase measurement
```

Six arms (3 pairs x 2), each now running **both** production phases — the
training-only estimate is superseded by D-C2-11. `T_formal` at a 1% slice is
not yet measured, so the total is deliberately left to be restated from the
first pair's observed wall time rather than guessed a second time.

**Cases 13-16 — EVIDENCE FROM EXACT-HEAD TEST, not a GPU run.** Named in
the harness's `TEST_EVIDENCE_CASES`, and a test resolves each citation
against the filesystem so it cannot rot.

| # | Evidence | Why no GPU run adds anything |
|---|---|---|
| 13 | `test_prephase_measurement_reachability.py::TestTheDispositionDrivesTheAttempt::test_each_stop_is_filed_under_its_lane` | asserts the record's lane and `counts_toward_attempt_budget` for all six stops; a GPU run exercises one |
| 14 | `test_prephase_admission.py::TestOSevenHoldsForEveryStop::test_the_frozen_accounting` | asserts all six O-7 properties across all six stops |
| 15 | `test_prephase_admission.py::TestOSevenHoldsForEveryStop::test_a_measured_oom_records_insufficiency_without_issuing_advice` | proves the fact is kept and the instruction withheld |
| 16 | `test_prephase_measurement_reachability.py::TestTheCallSiteExists::test_it_runs_before_training_starts` **plus** case 1's artifact | ordering is a source property; case 1 shows the real launch after ALLOW |

**Every real stop case still serializes its own O-7 state** — the manifest's
`o7` block records attempt consumption, completed round, blame, shrink,
same-attempt retry and formal launch for every case including the stops. So
13-15 are cited, not skipped.

**Pass criteria.** Each case produces its expected outcome AND disposition ·
case 1 admits with a driver-visible figure and `authoritative: true` ·
cases 2-6 and 11 stop with `may_launch_formal_phase: false` · case 7's
inference peak is recorded independently of case 1's training peak ·
case 10 shows driver ≥ allocator · every manifest carries
`live_registry_unchanged: true` · the three PR B refusal lanes stay
distinct (`test_refusal_lane_distinctness.py` green at the same SHA).

**Stop criteria.** Any write outside `/tmp/c2_lite_a` · any
`live_registry_unchanged: false` · any observed attempt-accounting change
beyond O-7 · total wall beyond 30 min · any case whose manifest reports
`git.dirty: true`.

**Cleanup.** `rm -rf /tmp/c2_lite_a/ws` after archiving; the artifact
directory is retained. The harness's calibration redirect lives under the
workspace and goes with it. No process outlives a case — the parent reaps
its worker's process group and records `orphans_remaining`.

**Retained artifacts**, per case, at
`/tmp/c2_lite_a/artifacts/c2_lite_<case>_manifest.json` (+ `.sha256`):
exact SHA and dirty state · full command and resolved config · hostname,
GPU model/UUID, driver, CUDA, torch · start/end timestamps · sampling
interval · **raw driver-visible samples** · allocator diagnostics ·
process-tree membership over time · phase boundaries · typed measurement
result · authority decision and refusal reason · PR B verdict · O-7
disposition and accounting · exit status · manifest hash.

**No LLM is possible.** Zero LLM tokens in the harness (asserted by
`test_it_makes_no_llm_call`); zero in the eight C2 modules (every
occurrence is a comment); and `test_no_llm_is_constructed_during_a_measurement`
poisons `LLMBridge.__init__` and runs a real measurement.

**No live registry is modified.** C2 references no registry at all — no
`CalibrationRegistry`, `runtime_calibration`, `SIDERIUS_CALIBRATION_DIR`,
`record_observation` or `observation_store` in any C2 module. The harness
additionally redirects `SIDERIUS_CALIBRATION_DIR` into the workspace before
anything runs (one env var governs BOTH the legacy v1 table and the v2
root) and fingerprints the live tree before and after.

**Static validation performed 2026-08-03, no GPU work:** command parses ·
`--dry_run` green against the real environment (`data_dir_present`,
`workspace_writable`, `artifact_dir_writable`, `spec_constructs`,
`candidate_registered`, `config_class_registered`, `device_uuid_matches`
all true) · worker module resolves (`usage:`, exit 2) · 31 harness tests
green.

#### Gate 2 Lite-B — target H100, production authority  (EXECUTED — PASSED, attempt 01)

*Repeats the production-critical subset on the hardware that will run it.*

```bash
git fetch origin && git checkout <EXACT_LITE_A_SHA>   # by hash, never by branch
git rev-parse HEAD    # must equal <EXACT_LITE_A_SHA>
nvidia-smi --query-gpu=index,uuid,name --format=csv,noheader   # record the H100 UUID
```

Then the same harness with `--device_uuid <H100 UUID>`, the H100's
`--data_dir`, `--workspace /tmp/c2_lite_b/ws`, `--artifact_dir
/tmp/c2_lite_b/artifacts`, and `--ceiling_gib` set from the H100's capacity.

**Cases repeated:** 1 (success + admission), 2 (above cap), 3 (unavailable),
4 (bounded timeout), 7 (phase separation), 9 (tree coverage), 10 (allocator
vs driver), 16 (formal launch only after ALLOW). Estimated **~10 min wall,
~6 bounded GPU executions**.

**Live stability is re-derived on the H100, never inherited.** If Case 12 is
added to Lite-B, its training arms use the same rule and the same flags with
**H100-local safety caps**:

```bash
    --formal_stable_steps 500 --formal_min_samples 3 \
    --formal_max_steps 5000 --formal_max_phase_seconds <H100 cap, set locally>
```

`--formal_stable_steps` and `--formal_min_samples` are portable **because
they are counts of real work, not durations** — a faster card simply reaches
them sooner, which is the entire reason the rule is expressed this way.
`--formal_max_phase_seconds` is **not** portable and must be chosen from an
H100 observation, never from the 5090's. Likewise `--formal_train_files` /
`--formal_train_psd_per_file` are a data ceiling, and if an H100 arm ends
`INCONCLUSIVE` because it exhausted its data before the peak settled, the
ceiling is raised **on the H100** and the arm rerun — the 5090's value is
not evidence about the H100's.

**Nothing measured on the 5090 is reused, and most of it cannot be.** A
requirement is refused unless `observed_device_uuid == request.device_uuid`,
so a 5090 figure cannot be assembled into a table on the H100 at all —
enforced by the authority contract, verified here end to end. Beyond that
contract, the following are **forbidden by protocol** and must be
re-established locally: wall-clock caps · final step counts · measured
GPU requirements · per-step or per-file unit times · any duration-derived
workload bound.

**Additionally required.** Formal admission reports a real requirement
rather than `policy_unavailable`; the recorded `observed_device_uuid` is
the H100's; every stop shows the O-7 accounting; every recorded arm carries
its own `stability` block naming the H100's own stop reason.

### Gate Behavior Delta — the consolidated statement

*Everything C2 changes about how a Gate behaves, in one place, so an
acceptance reader does not have to reassemble it from eighteen deviations.*

| # | What changed | Cases affected | Delta for a NORMAL production run |
|---|---|---|---|
| 1 | The presence of a foreign GPU process no longer contaminates a case (D-C2-19) | all | none — validation harness only |
| 2 | Environment is judged over the whole sample series, not two endpoint snapshots (D-C2-19) | all | none |
| 3 | A contaminated pair reruns as a sub-attempt; the Gate is not invalidated (D-C2-19) | c12a/b/char | none |
| 4 | c9 now *requires* its controlled neighbour rather than tolerating it (D-C2-19) | c9 | none |
| 5 | Formal training length comes from live peak stability, not a portion or a step count (D-C2-20) | c12a/b/char | none — no channel, no change |
| 6 | Backstops return `INCONCLUSIVE`; they are not passes (D-C2-20) | c12a/b/char | none |
| 7 | An incomplete watch cannot certify a peak even when the arithmetic says STABLE (D-C2-20) | c12a/b/char | none |
| 8 | Fixed 5090 constants (2000 steps / 160 batches / 15 s / 5 s) are **withdrawn** as acceptance criteria | c12a/b | none |
| 9 | External occupancy *drift* is no longer contamination; `environment_shift_observed` and `pair_comparable` are separate facts (D-C2-21) | c12a/b/char | none |
| 10 | Arms are summarized individually and compared; their sample series are never pooled (D-C2-21) | c12a/b/char | none |
| 11 | The 64 MiB absolute refusal threshold is removed and not replaced (D-C2-21) | all | none |
| 12 | `environment_samples` (repr strings) removed; `raw_samples` is the single machine-readable series (D-C2-21) | all | none |

**The single production-facing statement**: with
`SIDERIUS_C2_FORMAL_STABILITY` unset — which is every production run, and
which no CLI flag or config key can change — no file is opened, no step
event is written, no stop signal is read, and both training engines execute
the loop they executed before C2. Environment assessment and the stability
controller exist only inside `scripts/c2_prephase_validation.py`.

**No idle-GPU requirement exists anywhere in this Gate**, and no
still-GPU requirement either. Dynamic measurement exists so a candidate can
be measured on the card **as it actually is**; a Gate that only runs on a
quiet GPU validates a laboratory rather than production, and in practice the
GPU is sometimes busy. **Presence and ordinary occupancy oscillation are not
contamination — effect on the acceptance claim is the criterion.**

### Finding recorded, not fixed: `probe_production.py` omits fcnet's `loss_type`

`train_engine_sandbox` constructs fcnet as
`model_class(model_cfg, loss_type=loss_cfg.loss_type)`;
`probe_production.py:128` constructs every model as `model_class(cfg)`.
A candidate needing that argument fails to construct in the duration probe.
Classified as a **duration-probe limitation, not an admission defect** —
`probe_production` feeds C1's calibration path, not `measured_requirements`
— and left alone for the same reason D-C2-4 leaves its optimizer copy
alone. The C2 worker mirrors the trainer, with a test that fails if the
branch is dropped (M3).

---

## 17. Commit plan

Nine commits. Each is independently reviewable and does not carry unrelated
cleanup. `[ ]` = not done; `[x]` only after implementation **and** recorded
evidence.

> **Ladder note — which checkpoint creates PR B's requirement.**
>
> The first draft's ladder restored registry writing (C-C3) and promotion
> (C-C4) and then expected C-C6 to hand PR B a requirement. §3 shows that
> cannot work: those checkpoints promote **milliseconds**.
>
> The two tracks are now explicit:
>
> ```
> Track 1  time calibration      C-C1 -> C-C2 -> C-C3 -> C-C4 -> C-C5
>          consumer: time-budget decisions. Does NOT feed PR B.
>
> Track 2  GPU requirement       C-C1 -> C-C2 -> C-C5a -> C-C6
>          consumer: PR B's admission gate.
> ```
>
> **C-C5a is the checkpoint that creates the authoritative GPU requirement**
> — it is new in this revision, and it is the one that must exist before
> C-C6 has anything to deliver. C-C2's identity model and C-C5's
> applicability evaluator are shared by both tracks; nothing else is.
>
> **O-10 answered this (2026-08-03 UTC):** `observed_peak` is *not* the
> producer. It is telemetry and consistency evidence. C-C5a instead builds
> a dedicated isolated bounded **pre-phase** measurement — the only kind
> that can decide whether a phase should start.
>
> The two tracks are now two PRs (§15), because after O-10 they share no
> producer, no unit, no consumer and no authority — only the identity
> framework.
>
> If C-C5a's pre-phase probe cannot produce a trustworthy measurement for a
> given candidate, it produces **no requirement**, and O-7 governs: the
> attempt stops before the GPU phase, consumes an attempt, completes no
> round, blames nothing and advises no shrink. That is a designed outcome,
> not a failure path.


**All ten §8.C decisions were approved on 2026-08-03 UTC.** Each checkpoint
below names the decisions that govern it. Where a checkpoint's low-level
steps were previously withheld pending a decision, they are now to be
drafted **from the approved answer plus fresh code inspection** — not
invented, and not carried over from the first draft, whose assumptions
several answers overturned.

**Standing rule for every commit below.** Once this design and the §8.C
decisions are approved, Claude implements, tests, documents and commits each
bounded checkpoint **autonomously** on the PR C branch. Do not stop before
each commit; record the evidence in the commit message and the final PR
instead.

Pause only for: a verified new production defect; a material deviation from
the approved architecture; unresolved authority or policy behaviour; a
change to retry, LLM cost, resource authority or a production default; real
GPU/LLM execution; destructive operations; merge approval.

Inspect the relevant code before finalising each plan. If inspection reveals
ambiguity or a larger scope than assumed here, that is a deviation — stop
and ask rather than widening the commit.

---

### C-C1 — Populate the two identity fields production drops  `[C1]`

**1. Goal.** `model_family` and `software_stack` are dropped at two
production call sites (§2.5), so every registry record buckets under
`family=unknown` with a constant stack digest. Fixing this is a precondition
for any applicability rule: without it, every record is in one bucket.

**Bounded to known candidates.** A candidate whose family resolves gets a
real family and a real stack. A candidate whose family does not resolve
keeps today's behaviour untouched. The `unusable` state belongs to schema
v2 (C-C2, O-2) and must not be promised by a commit that changes no
schema.

Belongs here because it changes **no schema** — both fields already exist —
so it can land and be validated before the migration decision (O-1) is
made.

**2. Scope.**
- `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:947-957`
  (`ProbeRequest` construction) and `:978` (`build_registry_persist`).
- Possibly `core/runtime_control/probe_lifecycle.py:69` (the `"unknown"`
  default).
- The resolver for a real family value —
  `calibration_policy.classify_model_family` (`:259`) exists and has zero
  callers; whether it is the right resolver is **8.B**.

*Non-goals:* no change to `bucket_components`; no schema field added; no
change to what the probe measures; the `"unknown"` value must remain legal
for records that genuinely cannot be classified.

*Dependencies:* none. This is the first commit.

**3. Implementation plan.**
- [x] Read `classify_model_family` (`calibration_policy.py:259-273`): a
      non-empty `declared_family` is returned verbatim; `structural_features`
      is only the fallback. The tuner has `model_type` in scope at `:895`.
- [x] **8.B resolved:** `model_family` is the registered `model_type`, via
      `classify_model_family(declared_family=model_type)`. The time skill
      already keys its store this way (`evaluate_time_skill/wrapper.py:499`),
      so this makes the registry agree with the store rather than creating a
      third namespace (§2.9).
- [x] Passed the resolved family into `ProbeRequest`
      (`ml_hyperparameter_tune_agent.py:947-968`).
- [x] Resolved a real `software_stack` at the `build_registry_persist` call.
      **Discovery:** there was no shared producer — `bootstrap.py:464` built
      `{"torch": ..., "cuda": ...}` inline and the tuner passed `{}`.
      `capture_environment_provenance()` captures the same facts but under
      `torch_version`/`cuda_version`, and since `stack_identity` content-hashes
      the dict, reusing it would have forked the bucket away from the two
      records bootstrap already wrote. Extracted
      `provenance.capture_software_stack()` emitting bootstrap's exact shape;
      both call sites now use it. Verified byte-identical:
      `stack_identity` = `stack:cb380df61b90` before and after, vs the
      `stack:44136fa355b3` constant that 18 records share.
- [x] `probe_lifecycle.py:69`'s `"unknown"` default **left as-is** for C-C1.
      Making it required is a schema-shaped change that belongs with C-C2's
      v2 work; C-C1 changes no schema.

**4. Validation plan.**
- Unit: the resolved family reaches `CalibrationObservation.model_family`,
  driven through the **real** `ProbeRequest` → `probe_wiring` →
  `probe_observations` path, not a hand-built observation.
- Unit: a non-empty `software_stack` produces a different `stack_identity`
  than `{}` — i.e. the bucket actually forks.
- Negative: a candidate whose family genuinely cannot be classified keeps
  the **existing non-authoritative behaviour**. C-C1 changes no schema, so it
  cannot introduce the `unusable` state — that arrives with schema v2 in
  C-C2 under O-2. Asserting an unusable marker here would be a promise this
  commit's own scope forbids.
- Backward-compat: existing records keep their ids; this commit adds no
  field, so §2.7 does not apply. **Assert that explicitly.**
- No Gate / real-training test.

**5. Acceptance criteria.**
- [x] A probe-produced observation carries a family that is **not**
      `"unknown"` for a registered model type.
- [x] `bucket_key` for two different model families differs in exactly the
      family component and nothing else — asserted as a component-wise diff
      count of 1.
- [x] `stack_identity` for a populated stack differs from the constant
      `stack_identity({})` digest: `stack:cb380df61b90` vs
      `stack:44136fa355b3`.
- [x] All 20 existing records still load — `load_observation` raises on
      none of them. Verified against a **copy in a temporary tree**; the live
      tree's file hashes were compared before and after and are identical. The live per-user registry
      is read-only evidence for this work: no test, script or checkpoint may
      write to it, and O-1 preserves the old tree untouched.
- [x] Mutation proofs, each asserting a unique match and re-running the
      baseline after restore:

      | mutation | result |
      |---|---|
      | producer drops the family it was handed | 2 failures |
      | producer drops the stack it was handed | 2 failures |
      | helper regresses to `{}` (the pre-C-C1 state) | 1 failure |
      | helper renames its keys (forks from bootstrap) | 1 failure |

      The `{}` regression initially **passed**: on a machine with torch the
      assignments repopulate the dict either way, so the branch only bites
      where torch is absent. The test asserted on a hand-built dict rather
      than the helper's real torch-absent path — a test-local fiction. Fixed
      by driving the branch with `monkeypatch.setitem(sys.modules, "torch",
      None)`.

**6. Failure and edge cases.**
- Family unresolvable → unchanged non-authoritative behaviour, and the run
  continues. The explicit `unusable` namespace is C-C2's (O-2); C-C1 must
  not pre-empt it.
- Stack capture fails → record the gap explicitly; must not fabricate a
  stack, and must not fall back to `{}` silently, since `{}` is currently
  indistinguishable from "captured an empty stack".
- A model type with no registered family → same as unresolvable.

**7. Verification commands and evidence.**
- [ ] `pytest tests/unit/core/ -k "probe or calibration" -q`
- [ ] `pytest tests/unit/agent/tune_ml_hyperparam_agent/ -q`
- [ ] Mutation proofs recorded per §10, each asserting a unique match and
      re-running the baseline after restore.
- [ ] Record counts and wall time here after execution.

**8. Commit boundary.** Independently reviewable: two call-site changes plus
their tests. Carries no schema change, no new dimension, no reporting.

---

### C-C2 — Typed identity contract for a calibration record  `[C1] governed by O-1, O-2`

**1. Goal.** Add task identity, dataset/data-shape class and device-instance
identity to calibration identity (§2.6), so a record states what it
measured.

**2. Scope.** `core/runtime_control/registry_schemas.py`,
`calibration_policy.py:296-326` (`bucket_components`/`bucket_key`), and the
producers that must supply the new values.

*Non-goals:* no change to promotion thresholds; no merge of System A and
System B.

*Dependencies:* C-C1; and **O-1**, which decides whether this is a new
schema version in a new directory, a re-hash migration, or a partial hash.

**3. Implementation plan.** **Deliberately not written.** Every step depends
on O-1: option 1 means a v2 tree and a reader that handles both; option 2
means a migration script; option 3 changes `hash_payload` itself. Writing
steps now would commit to one before the operator chooses.
Split into three semantic commits: C-C2a models, C-C2b tree, C-C2c
quarantine.

- [x] **C-C2a** — `MeasurementIdentity` (exact match, incl.
      `measurement_kind`, `task_identity`, `data_shape_class`,
      `hardware_uuid`) and `ApplicabilityEnvelope` (bounded ranges). The two
      share **no field**, so an applicability verdict cannot be obtained by
      matching a key — the §8.A invariant made structural. 29 tests, 6
      mutation proofs. Phase vocabulary resolved to `RuntimePhase`: verified
      `io` is declared in `ObservationOperation` and produced nowhere, while
      `scoring`/`orchestration` are real phases v1 could not express.
      `gpu_reserved` deliberately not declared — no producer exists, and a
      kind nothing emits is how `cuda_peak_allocated_gb` became a dead field.
      **Deferred** until a real producer exists.
- [x] **C-C2b** — `REGISTRY_SCHEMA_VERSION` 1.0.0 → 2.0.0, and each major
      version gets its own tree. v1 keeps the historical
      `runtime_calibration` name so the existing tree is found where it has
      always been; v2 is the sibling `runtime_calibration_v2`.
      `legacy_registry_root()` exposes v1 for read-only inspection.
      A fail-closed guard refuses to open a tree whose manifest declares a
      different major — without it, a stale `SIDERIUS_CALIBRATION_DIR` would
      have v2 code append into the v1 tree, and `rebuild_index` would then
      commit a manifest silently omitting whichever half failed its hash
      check. Live v1 tree verified untouched: 26 files, digest
      `df0351b59a5bd0bd`; no v2 tree created (nothing writes yet).
      3 mutation proofs.
- [x] **C-C2c** — the explicit `unusable`/quarantine namespace under O-2.
      `QuarantineRecord` keeps the measurement verbatim with a required
      reason and the missing identity fields; the registry writes it to a
      separate `quarantine/` directory and a separate `quarantined_ids`
      manifest list. The isolation is **structural**: `iter_observations`
      walks `observation_ids`, which a quarantined id never enters, so
      "never authoritative" is a property rather than a rule each reader
      must remember. Auditing requires a different method by design.
      10 tests; 3 mutation proofs (id also appended to `observation_ids`;
      written into `observations/`; `iter_observations` widened to walk
      both) — 4, 5 and 2 failures respectively.
- [ ] Wiring the identity into the write path, with an **explicit**
      legacy-`ObservationOperation` → `RuntimePhase` mapping that fails
      closed on an unsupported value. No string casts, no silent
      reinterpretation of old records.

**4. Validation plan (shape known now, cases pending O-1).**
- Unit: two records identical except for task land in different buckets.
- Unit: two records identical except for GPU UUID land in different buckets
  — **a 5090 measurement must never be H100-authoritative** (frozen, 8.A).
- Unit: two records identical except for data-shape class land in different
  buckets.
- Backward-compat: whatever O-1 chooses, the 20 existing records must
  remain **readable and attributable**, not silently dropped by
  `rebuild_index`.
- Negative: a record missing a mandatory identity field cannot become
  authoritative (O-2).

**5. Acceptance criteria.**
- [ ] The synthetic second task from §8 answer 7 buckets separately from a
      TIDMAD record with identical workload numbers.
- [ ] `rebuild_index` reports zero unexpected rejections against the live
      registry.
- [ ] No new fail-open default is added to the §2.10 table.

**6. Failure and edge cases.** Old record lacking the new fields; task
identity unavailable at write time; UUID unavailable (PR B degrades to
`None` rather than raising — decide whether that may still be bucketed);
`rebuild_index` encountering a mixed-version tree.

**7. Verification commands and evidence.** To be written with the steps.

**8. Commit boundary.** Schema and identity only. No promotion, no
admission wiring.

---

### C-C3 — Make the registry write path reachable  `[C1] governed by O-3`

**1. Goal.** `record_observation` is reached only through a gate the happy
path cannot open (§2.3), which is why there are 20 records and 0 promotions.

**2. Scope.** `core/runtime_control/probe_wiring.py`,
`decision_policy.py:308-320`, `ml_hyperparameter_tune_agent.py:924-946`.
Also §2.8: `probe_runner_availability()` refuses without `TIDMAD_DATA_DIR`,
so on any other task the path is dead regardless of the trigger.

*Non-goals:* not changing what a probe measures; not changing
`RuntimeDecisionPolicy`'s authority matrix.

*Dependencies:* C-C1; **O-3** (what triggers promotion evaluation), and the
§2.8 dataset gate must be addressed or the fix is TIDMAD-only.

**3. Implementation plan.** **Not written** — O-3 determines whether the
trigger is a new decision branch, a scheduled evaluation, or a write-time
hook. Inspect `decide` and the `REQUEST_PROBE` branches before drafting.
Split: C-C3a the capability boundary, C-C3b the write path, C-C3c the O-3
trigger (kept separate from observation creation, per the operator
constraint).

- [x] **C-C3a** — `core/runtime_control/measurement_capability.py`:
      `ResolvedMeasurementCapability` + a generic `resolve_measurement_capability`.
      The task's dataset root arrives as an ARGUMENT; `dataset_root=None` is
      refused, not defaulted, because a default there would be the very task
      assumption being removed. A validator refuses
      `probe_available=False` without a reason — the old `(bool, str)` tuple
      allowed a silent False by convention. Identity (task, adapter,
      data-shape class) is required even when unavailable, so the verdict
      can supply a `MeasurementIdentity` later. 16 tests, 3 mutation proofs.
      Callers already hold what they must pass: the tuner has `data_dir` as
      a parameter of `_resolve_time_check_probe_request`; `launch_guard`
      takes an optional root from its caller (C-C3b).
- [x] **C-C3b** — `probe_runner_availability` now takes a resolved
      capability and imports no task module. The TIDMAD default lives in
      `execute_tools.data_paths.resolve_tidmad_measurement_capability` —
      the task-owned layer, where a default legitimately belongs. The tuner
      resolves it from the `data_dir` it already holds, so the capability
      describes the dataset the probe will actually use rather than a second
      independently resolved path. `launch_guard` threads an optional
      capability and fails closed without one.

      Unavailability now reaches the record: the tuner stamps
      `probe_capability_task` and `probe_capability_reason` into the
      breakdown instead of a bare `unavailable`.

      **Reachability gap found and closed.** Reverting the tuner to
      `probe_runner_availability()` — the exact silent-disable regression —
      left all 23 launch-guard tests green. Added
      `test_measurement_capability_reachability.py` (9 cases), which now
      fails on it. Mutation proofs: no-argument call → 2 failures; reason no
      longer recorded → 1; generic wiring re-imports the task constant → 1.

      **Deferred, filed:** `probe_production.py:137` still falls back to
      `TIDMAD_DATA_DIR` when no `data_dir` is supplied, and loads
      TIDMAD-shaped batches via `execute_tools.probe_data`. Making that
      generic needs a dataset-adapter abstraction, which is beyond C-C3b's
      bounded scope. `bootstrap.py:439` is an operator CLI for this task and
      is outside the generic decision path.
- [ ] **C-C3c** — the happy-path duration write, then O-3: idempotently
      evaluate only the affected bucket after a successful eligible write.
      Creation and trigger stay separate.

      **Architecture (operator, 2026-08-03 UTC):** System A stays the single
      source of truth for measured duration. System B must not perform or
      invent a second measurement; it receives a typed, deterministic
      *derivative* of the `RuntimeObservation` System A already writes.

      **HOOK CORRECTED BY AUDIT.** The anticipated seam was the shared
      `_append_runtime_observation`. Verified and rejected: its four
      production call sites are not four successful phases —

      | site | function | records |
      |---|---|---|
      | `:2499` | `_handle_in_subprocess_rejection` | a rejected attempt |
      | `:2525` | `_raise_if_evidence_channel_failure` | an infrastructure failure |
      | `:2551` | `_raise_if_wall_clock_timeout` | a wall-clock timeout |
      | `:4700` | `run()`, the E. COMMIT block | the **successful** attempt |

      Three of the four are failure paths. Deriving calibration at the
      shared seam would feed rejections, infrastructure failures and
      timeouts into throughput calibration, violating the D4 rule at
      `calibration_policy.py:279-285` — which explicitly anticipates
      "another producer" recording failure evidence as an observation.
      The derivation therefore hooks the **success call site only**, after
      `_emit_record`, where the record is already complete.

      Identity available there: `train_engine_sandbox.py:813-828` already
      populates `calibration_context` with precision, optimizer_type,
      model_family, param_count, seg_size, batch_size — and its
      `model_family` is `model_cfg.model_type`, the same namespace C-C1 chose
      for System B, so the two agree rather than fork. Task identity and
      data-shape class come from C-C3b's `ResolvedMeasurementCapability`;
      the stack from C-C1's `capture_software_stack`. Anything unavailable
      drives **quarantine, never a fabricated default**.

      Safety boundary: System A is written first and unchanged. A System B
      conversion or persistence failure is observable but must not alter the
      experiment result, attempt/round accounting, retry behaviour,
      scientific output or agent feedback — fail-open for the scientific
      workflow, fail-closed for calibration authority.

      - [x] **part 1** — the pure converter. Three results, not two:
            `DerivedDurationRecord` / `QuarantinedDerivation` /
            `NotDerivable`. The third was not anticipated by the design and
            is required: a rejected, watchdog-killed or non-steady attempt is
            not an incomplete identity that might later be repaired, and
            parking it in quarantine would leave failure evidence in a
            namespace meaning "salvageable". Reuses the existing
            `component_calibration_eligible` gate rather than defining a
            second notion of clean. 22 cases, 5 mutation proofs.
      - [x] **part 2** — persistence and idempotency.
            `CalibrationObservation` gains an optional `identity`
            (`MeasurementIdentity`); the derived producer always sets it and
            persistence refuses an eligible record without one, while the
            probe producer keeps working. Idempotency is content addressing,
            not a ledger: reprocessing one event yields the same id and
            dedups, so it cannot advance a promotion sample count twice.
            A registry failure returns `kind="failed"` with the reason
            instead of raising — System A is already durable, so a storage
            problem costs this run its calibration sample and nothing else.
            8 further cases, 4 mutation proofs.
      - [x] **part 3** — production wiring at the success seam.
            `_derive_calibration_from_observation` is a focused helper (not
            branching inside `run()`), called once, immediately after the
            System A append so the raw measurement is durable first.
            Identity comes from what is already in scope: `device_identity`
            (`:2883`), `time_data_dir` (`:2842`), the C-C3b capability and
            C-C1's `capture_software_stack`. A missing UUID yields
            `identity=None` and the derivation quarantines — no placeholder
            is ever substituted, since a fabricated UUID would produce an
            eligible record naming the wrong device.

            The helper is **total**: it returns for any input and prints the
            loss rather than raising, because the experiment result is
            already decided and persisted by the time it runs.

            14 guard tests. Mutation proofs: production hook deleted → 4
            failures; derivation moved into the shared append helper → 2;
            derivation reordered before the System A append → 1; placeholder
            UUID fabricated → 1.

            **Test defect found and fixed during validation.** A full core
            run left a real `~/.siderius/runtime_calibration_v2` tree behind:
            `test_the_helper_is_total` passes `{"timestamp": "t"}`, which
            PARSES as a valid `RuntimeObservation`, so the helper reached a
            real `CalibrationRegistry()` at the default root and created
            profiles there. No observations or quarantined records were
            written — the derivation correctly returned `NotDerivable` — but
            the tree existed. Fixed with an autouse fixture pointing
            `SIDERIUS_CALIBRATION_DIR` at `tmp_path`; re-verified that a full
            core run now creates nothing, and v1 stays at digest
            `df0351b59a5bd0bd`.
- [ ] Proceed autonomously unless inspection reveals a material deviation.

**4. Validation plan.**
- Reachability: a test that **fails when the production call site is
  removed** — the control absent from every dead seam in §2.2.
- Integration: a pseudo run produces at least one registry observation on
  the happy path, not only on a warm-up failure.
- Negative: a task without the TIDMAD dataset must not silently disable the
  path *without saying so*.

**5. Acceptance criteria.**
- [ ] A normal formal pseudo run leaves a new record in a **temporary
      validation registry** (`$SIDERIUS_CALIBRATION_DIR` pointed at a
      tmp_path), with the record explicitly marked synthetic /
      validation-only and **permanently ineligible for authoritative
      promotion**.
- [ ] The user's real per-user registry at `~/.siderius/runtime_calibration`
      is **byte-identical before and after** the pseudo run — asserted, not
      assumed. A pseudo run proves reachability only; an authoritative
      measurement must come from a real bounded measurement on the target
      device.
- [ ] Deleting the production call site fails a named reachability test.
- [ ] `probe_runner_availability` returning `False` is reported, not silent.

**6. Failure and edge cases.** No CUDA; no dataset; probe times out; probe
returns inconclusive (must not become allow or reject — invariant 4).

**7. Verification commands and evidence.** To be written with the steps.

**8. Commit boundary.** Reachability only. No promotion logic.

---

### C-C4 — Wire promotion evaluation and recording  `[C1] governed by O-4, O-5, O-9`

**1. Goal.** `evaluate_promotions` and `record_promotion` have zero
production callers (§2.2), so `bucket_status` can never return
`promoted_measurement` and `AUTHORITATIVE_PROVENANCE` is unsatisfiable.

**2. Scope.** `calibration_policy.py:365-505`,
`calibration_registry.py:204`, and whatever orchestration boundary C-C3
establishes.

*Non-goals:* not changing the consistency ratio or minimum counts without
the O-4 values, which are frozen at their current settings.

*Dependencies:* C-C2, C-C3.

**3. Implementation plan.**
- [x] Confirmed the `run_invariants` interaction by inspection **before**
      touching `CalibrationPolicy`: no policy edit was needed at all.
      `evaluate_bucket` already accepts `policy=DEFAULT_POLICY`, so promotion
      is wired without altering the model. `runtime_policy_identity` stays at
      `calibration_policy@1.0.0+b83994605c57`, with O-4 frozen at
      `provisional_min_observations=2`, `validated_min_observations=3`,
      `consistency_max_min_ratio=1.5`. 81 invariant/lock tests pass.
- [x] Implemented `evaluate_affected_bucket_after_write` in
      `calibration_derivation.py` (+114 lines) under the O-4 values, O-5
      (bucket key already encodes the concurrency class, so only same-class
      evidence can share a bucket) and O-9 (no wall-clock term anywhere in
      the evaluation).
- [x] Wired it at the tuner success seam,
      `ml_hyperparameter_tune_agent.py:2750`, guarded so **only an
      `eligible` write** triggers evaluation — a quarantined or failed write
      never promotes.

**Design note — idempotency is not free here, unlike observations.**
`CalibrationPromotion` content-addresses `derived_from_generation`, which
increments on every committed index write. Re-evaluating one *unchanged*
bucket at a later generation therefore produces a **different id** and would
write a second promotion for the same evidence, inflating the apparent
record. Verified directly (generation 5 vs 6 → different ids). Equivalence is
consequently checked on `(bucket_key, source_observation_ids, level)` — what
actually identifies "this promotion, from this evidence".

**4. Validation plan.** Executed: 1 obs → `not_promoted` with reason; 2
consistent → `promoted`/`provisional`; 3 consistent → `validated`; a 10×
outlier → `not_promoted`; re-evaluation → `already_promoted`.

**5. Acceptance criteria.**
- [x] A bucket with sufficient consistent observations reaches `validated`.
- [x] A bucket with inconsistent observations does not, and the reason is
      recorded on the outcome.
- [x] Zero promotions is now an *explainable* state rather than an absence —
      the refusal reason names the observation count and the threshold or
      ratio that blocked it. This is the specific defect the live v1 registry
      exhibited: 20 observations, 0 promotions, no recorded reason.

**6. Failure and edge cases.** Insufficient samples; inconsistent
observations; contended-only buckets; stack or hardware change mid-bucket.
Promotion never raises — a derived view failing must cost the bucket its
authority, never the run its result.

**7. Verification commands and evidence.**

```bash
.venv/bin/python -m pytest tests/unit/core/test_calibration_derivation.py \
    tests/unit/core/test_calibration_derivation_wiring.py -q     # 56 passed
```

*Mutation evidence.* Four mutations, each restored from a file backup with
`__pycache__` cleared and the baseline re-run:

| # | Mutation | Killed by |
|---|---|---|
| M2 | evaluate every bucket, not only the affected one | `test_only_the_affected_bucket_is_evaluated` |
| M3 | drop the dirty-observation screen | `test_a_dirty_observation_in_the_bucket_is_screened_out` |
| M4 | remove the production promotion call | `test_the_promotion_trigger_is_reachable_from_production` |
| M5 | let a quarantined write promote | `test_promotion_is_triggered_only_by_an_eligible_write` |

M2 and M3 initially **survived**: the tests only ever built one bucket and
only clean observations. Both tests were added in response. M4 is the
reachability guard — `evaluate_affected_bucket_after_write` was written,
fully tested and called from nowhere, the same shape as #156, #157 and #159.

**8. Commit boundary.** Promotion only. No applicability, no admission.

---

### C-C5 — split into C-C5a and C-C5b  `[C1] governed by O-6, O-8`

**Why the split (operator decision, 2026-08-02).** The C-C5 audit found that
the "production path" this checkpoint was written against **does not exist**.
System B has only *write* paths in production:

| production site | direction |
|---|---|
| `ml_hyperparameter_tune_agent.py:2714` (C-C3c/C-C4) | write |
| `probe_wiring.py:162` `_persist` | write |
| `scripts/runtime_replay/legacy_migration.py:65` | write (migration) |

`as_estimate` — the only function that converts a stored observation into an
estimate carrying authority — has **zero** production callers, as do
`applicability_for_request`, `downgrade_for_applicability` and
`ApplicabilityEnvelope`. Nothing in production has ever read a promoted
bucket back.

This is not a live production bug; it is an **interface that would grant
authority incorrectly the moment anyone wired it up**. Fixing an uncalled
function and declaring C1 closed would leave "writes and promotion work, but
production never reads" — so C-C5 becomes two bounded checkpoints: make the
seam intrinsically safe (C-C5a), then prove production actually reads it
(C-C5b).

---

### C-C5a — Make the authority-producing read seam intrinsically safe  `[C1]`

**1. Goal.** `as_estimate` must never return measured/promoted authority
merely because a matching bucket is validated.

**2. Scope.** A new `core/runtime_control/calibration_read.py` boundary and
the `as_estimate` seam. *Non-goals:* no consumer wiring (that is C-C5b).

**3. Implementation plan.**
- [x] Audited every repository caller before changing the signature: no
      production, script or migration callers; no `__all__` export contract;
      docs reference only the §3.3 cross-machine rule, which is preserved.
- [x] Added `CandidateRequest` (identity + bounded dimensions) and
      `AuthorityDecision`, plus `evaluate_candidate_authority` — a typed,
      independently testable boundary that never raises.
- [x] Wired it inside `as_estimate` so the measured-provenance return is
      reachable **only** from the granted branch. The check cannot be
      bypassed by a caller who forgets it, because there is no longer a
      lower-level method that returns measured authority without it.
- [x] Order enforced: identity match → validated bucket → applicability →
      otherwise downgrade.

**4. Validation plan / Layer-2 matrix.** Executed in
`tests/unit/core/test_calibration_read_authority.py` (21 tests):

| row | outcome |
|---|---|
| matching identity + in-range candidate | **granted**, `interpolation` |
| cross-task | refused |
| cross-device-uuid | refused |
| cross-phase | refused |
| cross-measurement-kind | refused |
| cross-family / cross-candidate-config / cross-data-shape / cross-stack | refused |
| candidate outside an observed range (3 rows) | refused, `unsupported_extrapolation` |
| dimension with no measured evidence | refused, `not_applicable` |
| **no candidate request** | refused (`NO_CANDIDATE`) |
| observation without identity | refused |
| bucket without an envelope | refused |
| unknown model family | refused |

A positive control is included so a matrix of refusals cannot pass by
refusing everything, and a companion assertion proves the identity rows are
in-range — otherwise each would pass for the wrong reason.

**5. Acceptance criteria.**
- [x] Every Layer-2 row produces its expected label.
- [x] A matching bucket with a non-applicable candidate is downgraded, not
      accepted.
- [x] Mutation: removing an applicability dimension fails a named row.

**6. Failure and edge cases.** All fail closed: absent candidate, absent
identity, absent envelope, unmeasured dimension, unknown family, empty
request.

**7. Verification commands and evidence.**

```bash
.venv/bin/python -m pytest tests/unit/core/ -q     # 1464 passed, 2 skipped
```

| # | Mutation | Killed by |
|---|---|---|
| M7 | remove the identity comparison | all **8** identity rows |
| M8 | remove the applicability call | all **5** range/fail-closed rows |
| M9 | grant authority without consulting the decision | reachability guard **+** `test_a_validated_local_bucket_alone_is_not_authority` |

*Stale-contract tests updated after classification*, not relaxed:
`test_local_validated_evidence_keeps_measured_provenance` and
`test_validated_bucket_restores_measured_authority_end_to_end` (unit) and two
lifecycle tests (integration) asserted `validated + local ⇒ measured` with no
candidate. Their C7/D4 subject is preserved; each now names the candidate, and
the old expectation is **inverted and locked** by
`test_a_validated_local_bucket_alone_is_not_authority`.

> **Finding for C-C5b.** The two write paths differ: the C-C3c derivation
> populates `MeasurementIdentity`, but `probe.py::probe_observations` does
> **not**. Probe-written records therefore can never be authoritative — the
> correct fail-closed outcome, but it means C-C5b must consume evidence from
> the derivation path, or the probe path must start populating identity.
> Asserted explicitly in the lifecycle test rather than left implicit.

**8. Commit boundary.** The read seam only. No consumer wiring.

---

### C-C5b — CANCELLED by operator decision (2026-08-02)

> **Historical duration calibration must not influence the production
> allow/reject time decision.**
>
> Runtime and GPU conditions are live. The production time decision must use
> the current measured speed of the concrete candidate on the current machine
> under current conditions. A stored duration describes a different moment,
> and letting it decide prices today's work with yesterday's clock.

**Historical duration in C1 is observability-only.** It is still collected,
identity-checked, quarantined, promoted as internally consistent history,
reported (C-C7) and available for offline analysis, trend reporting and drift
detection. It may **not** support ALLOW, cause REJECT, modify
`_gate_decision`, be passed into the production time gate, or change retry,
attempt/round accounting or execution behaviour.

**Within the v2 calibration subsystem, the current live measurement is the
sole production time-decision input.**

> **Scope correction, found by audit 2026-08-02 — read this before quoting the
> sentence above.** An earlier draft of this section said "current live
> measurement is *the* sole production time-decision input", full stop. That
> is **not true of the codebase as a whole**, and stating it unqualified would
> have made this document assert something the code does not do.
>
> A **pre-existing legacy v1** mechanism does let history scale the production
> estimate, and it is untouched by PR C:
>
> * write — after every successful run, `ml_hyperparameter_tune_agent.py`
>   (Phase F post-flight) feeds the observed-vs-predicted ratio through an
>   asymmetric EMA (`evaluate_time_skill/calibration.py::update_k`) into
>   `~/.siderius/time_calibration_<gpu>.json`;
> * read — `training_skill/estimator.py:282-283` loads that table and
>   multiplies the estimate by `k` (`total_ms = total_steps * ms_per_step * k
>   * SAFETY_MULTIPLIER`).
>
> So the accurate claim, and the one the guardrail tests actually assert, is:
> **the v2 `CalibrationObservation` registry — the system PR C builds — has no
> influence on any production decision.** The legacy per-GPU `k` predates PR C
> entirely.
>
> **RESOLVED 2026-08-03 — the operator extended the rule to the legacy
> mechanism, and `k` was removed inside C1 before merge.** The paragraph above
> describes the code as it stood for one day, and is kept because the sequence
> matters: the audit found the gap, the document stated it accurately rather
> than overclaiming, and the operator then decided. See the Behavior Delta in
> §16a-BD.
>
> **So the claim is now unqualified:** the current live measurement of the
> concrete candidate is the sole runtime evidence in the production time
> decision. Both history systems — legacy v1 and the v2 registry — are
> observability-only.

*Sequence of events, recorded honestly.* The C-C5b wiring was implemented,
tested and committed (`95c4539` production, `b920b22` tests, `0d32187` docs)
**before** this decision arrived. Published commits were not rewritten; the
consumption was removed forward. `agent/skills/evaluate_time_skill/wrapper.py`
is now **byte-identical** to its pre-C-C5b state (verified by empty diff
against `0d32187~3`), and `calibration_prelaunch.py` plus its tests are
deleted — the module existed only to feed the production verdict, so leaving
it importable would invite the cancelled wiring back.

*Negative guardrails* (`tests/unit/core/test_historical_duration_is_observability_only.py`,
9 tests). These assert an ABSENCE, which is the hardest property to keep:
nothing fails when someone adds the input back unless a test watches for it.

| guard | proves |
|---|---|
| `_gate_decision` signature | no historical/calibration parameter |
| `_gate_decision` body | never mentions historical calibration |
| `run_skill` call graph | no historical lookup reached |
| wrapper imports | no calibration read-path module |
| module absence | `calibration_prelaunch` is not importable |
| registry-invariance | same live measurement → identical verdict regardless of registry contents |

| **positive control** | a 1-minute vs 10000-minute projection still changes the verdict, so the guards cannot pass by the gate ignoring everything |
| GPU admission imports | no calibration module |
| GPU admission signature | no duration/historical parameter |

*Correction found by audit, 2026-08-02.* The registry-invariance test
originally constructed an **empty** registry under an unrelated `tmp_path`.
That proved nothing twice over: production never resolves to `tmp_path`, and
an empty registry holds no authority to ignore in the first place — the
assertion would have held even if the gate did consult history. It now
populates the registry **production would read** (the default root, pinned to
a temporary tree by the session isolation fixture) with three observations
promoted to `validated`, whose stored ~900 ms/step contradicts the live
projection, and asserts the fixture really did reach `validated` before
asserting invariance.

**Any future use of history in execution decisions requires a separate PR and
explicit operator approval.**

---

### C-C5b — Wire the safe read seam to the time-budget consumer  `[C1]`  *(superseded — see cancellation above)*

**1. Goal.** Prove a production time-budget decision actually reaches the safe
seam. Without this, C1 remains "writes and promotion complete, production
never reads".

**2. Scope.** The smallest existing time-budget decision boundary.
*Non-goals:* no new logic inside the giant `run()` method; no wiring into
`train_engine_sandbox.py`; no activation of the unused
`production_estimator_factory()`; no general estimator/C9 refactor.

**3. Verified consumer audit (read-only, 2026-08-02).**

```text
tuner run()  [parent process]
 :2998  device_identity_from_hardware(...)        → DeviceIdentity(uuid)
 :3012  sandbox = _sandbox_factory(..., device_identity=...)
 :3856  [Pre-flight 2/2] Wall-time gate
         └─ evaluate_time_skill.wrapper.run_skill(sandbox, **active_params)
             └─ :852  _gate_decision(...) → policy.decide(...)   ← THE DECISION
 later   training subprocess launch
          └─ train_engine_sandbox.py:813 set_calibration_context(...)  [WRITE]
             :829 decide_admission()
```

*Correction recorded:* `decide_admission()` is **not** a GPU/resource gate —
it sums `predicted_seconds` against `operator_budget_seconds`. It is a time
decision, but in-subprocess, so it is still the wrong seam.

*Why not the estimator.* No production code calls `estimator.estimate()` and
nothing in production constructs a `RuntimeEstimateRequest`; the only mention
is `estimator.py:216-227` explaining why it is bypassed. Filling in
`history_lookup` would attach the seam to a function nobody calls.

**Identity availability at the pre-flight gate** — all fields resolvable, no
broad plumbing needed:

| field | source |
|---|---|
| `model_family`, `batch_size`, `seg_size` | existing kwargs |
| `param_count` | `_count_params(...)`, which instantiates the real model |
| `optimizer_type` | already read at `wrapper.py:498` |
| `task_identity`, `data_shape_class` | `data_dir` → measurement capability |
| `runtime_stack_identity` | `capture_software_stack()` |
| **`hardware_uuid`** | **`sandbox.device_identity.uuid`** — already in scope |
| `precision`, `runtime_flags` | shared canonical context (below) |

**4. Foundation landed (two committed fixes).** Both are silent-never-match
defects: the reader would find nothing, raise nothing, and be
indistinguishable from an empty registry.

- `8f97251` — **one shared calibration context**
  (`core/runtime_control/calibration_context.py`). The engine and the
  pre-flight disagreed on the parameter count —
  `sum(... if p.requires_grad)` vs unfiltered — identical for a
  fully-trainable model, silently different for any model with a frozen
  layer. `trainable_param_count` and `model_precision` now serve both.
  `MeasurementIdentity` unchanged; parity proven by pinning the
  pre-refactor mapping and its hash, so no stored identity moved.
- `8606b47` — **envelope dimensions derived from recorded evidence**.
  Derived records carry `seg_size`, probe records carry `segment_length`,
  and `ApplicabilityEnvelope` defaulted to the latter — so a fixed reader
  vocabulary found no range for one producer and never matched.
  `_measured_dimensions` now follows the evidence;
  `DERIVED_WORKLOAD_DIMENSIONS` gives the writer's vocabulary one home.

**Shared-context decision.** Only values that are (a) semantically part of
the candidate configuration and (b) deterministically derivable **both**
before launch and inside the training loop may enter. `precision` qualifies
because the pre-flight already instantiates the real model; `runtime_flags`
qualify as loop constants. Anything realized only during execution is
evidence *about* a candidate, not part of its identity, and would make the
identity unknowable before launch.

**Landed.** `d901412` — `candidate_config_hash` promoted to the single public
helper in `calibration_context`; the private `_config_hash` duplicate in
`calibration_derivation` is **deleted**, with a structural test forbidding its
return (a reintroduced copy would pass every behavioural test while drifting
from the reader).

**C-C5b wiring landed.** `95c4539` (production), `b920b22` (tests). The loop
is closed:

```text
wrapper.run_skill                      [before subprocess launch]
  -> _prelaunch_calibration(sandbox, ...)
      -> lookup_applicable_duration(...)          v2 registry
          -> registry.as_estimate(..., request=)  C-C5a authority seam
  -> _gate_decision(historical_calibration=..., ...)
  -> time-budget verdict
... only then is training launched
```

**O-6 is structural, not conventional.** `decision.kind` is computed by
`policy.decide(...)` **before** the historical block runs, and nothing in that
block writes it. `historical_support_only` returns `may_support_allow` — there
is no value it can return that denies a candidate. A field named
`should_reject` would have made rejection expressible, and expressible
eventually becomes reachable.

> **Deviation from the plan, recorded deliberately.** Applicable under-budget
> history is read, surfaced (`historical_supports_allow`, provenance, reasons)
> and may support an allow interpretation — but it does **not flip an existing
> verdict**. Granting history verdict-changing power is a material authority
> change beyond "may support ALLOW", and prior-tier evidence is already
> `cannot_block` in the §7.4 matrix. Deferred pending an explicit operator
> decision; **not** implemented inside C1.

**Mutation evidence.**

| # | Mutation | Killed by |
|---|---|---|
| M10 | remove the production read call | `test_run_skill_calls_the_prelaunch_lookup` **and** `test_the_result_reaches_the_gate` |

M10 kills two guards, deliberately: calling the lookup and discarding its
result is the #159 shape, so reaching the lookup is not sufficient evidence.

**GPU isolation.** Three structural guards: `admission.py` imports no
calibration module; `evaluate_gpu_admission` exposes no
duration/estimate-shaped parameter; `calibration_prelaunch` neither imports
nor calls the admission path. Milliseconds cannot reach a mebibyte decision.

**Tests.** `test_calibration_prelaunch.py` — 25, including the positive
control (an applicable validated record IS consumed end-to-end through a real
registry), six cross-dimension refusals, cross-candidate-config, three
incomplete-identity refusals that must name the missing field, unusable
registry as refusal, empty registry says so. `tests/unit/agent` +
`tests/unit/core`: **4667 passed, 2 skipped**.

**5. Acceptance criteria.**
- [x] A production time-budget decision reaches the safe read seam (`95c4539`).
- [x] Applicable promoted duration evidence is actually consumed.
- [x] Inapplicable evidence is ignored/downgraded.
- [x] Deleting the production read call fails a reachability test (M10).
- [x] Duration evidence cannot affect GPU admission (3 structural guards).
- [x] Absent applicable calibration preserves current non-authoritative
      fallback behaviour.
- [ ] Retry, attempt/round accounting, scientific result and LLM calls
      unchanged.
- [x] O-6 preserved: applicable history may support ALLOW; it may never
      directly REJECT. Rejection requires a live measurement of the concrete
      candidate.
- [x] A structural guard proves the duration-calibration module is neither
      imported by nor passed into the GPU-admission path.

**6. Completion standard.** C-C5b is **not** complete when
`calibration_prelaunch.py` works and its unit tests pass. It is complete when
the real pre-launch time decision calls it and only applicable historical
duration evidence can influence that decision.

**8. Commit boundary.** Consumer wiring only. The lookup module is committed
**with** its production wiring, never before it.

---

### C-C5a — Isolated pre-phase GPU requirement measurement  `[C2] governed by O-10`

**1. Goal.** Create the quantity PR B's gate consumes, per O-10: a
**dedicated isolated bounded pre-phase measurement** of the concrete
candidate on the target GPU.

O-10 explicitly rules out promoting normal-phase
`GpuEvidenceBundle.observed_peak`, and the reason is decisive: a peak
sampled *during* a phase cannot decide whether that phase should start. It
is additionally a sampled lower bound and describes occupancy rather than
need, so promoting it would under-state the requirement — the failure
direction that causes an OOM. `observed_peak` stays as telemetry and as
consistency evidence against which a promoted requirement can be checked.

Belongs in its own commit because it is the **only** checkpoint that turns
a memory observation into promotable evidence. Merging it into C-C6 would
hide the step where a lower bound becomes a requirement — the single place
this PR can most easily under-state need.

**2. Scope.** A **new dedicated pre-phase measurement worker** — the
authoritative requirement producer. The identity/envelope/policy models from
C-C2, and the `gpu_requirement` `measurement_kind`. Persistence of
GPU-requirement observations alongside duration observations.

Roles, kept explicitly apart:

| Component | Role |
|---|---|
| dedicated pre-phase worker (**new**) | **produces the authoritative requirement**, before the phase starts |
| `GpuPhaseObserver` (`gpu_observer.py`) | normal-phase **telemetry**; may corroborate or contradict a promoted requirement (O-8); **never originates one** |
| `GpuAccountingSnapshot.own_tree_mib` | the candidate-owned driver-visible quantity both of them read |

*Non-goals:* not changing what `GpuPhaseObserver` samples; not changing PR
B's attribution; not changing `estimated_gb`'s status as a prior.

*Dependencies:* C-C1, C-C2, C-C5; O-10. **Implementation is not authorized
until the C2 producer audit (§15.2) is complete and approved.**

**3. Implementation plan.** To be drafted from O-10 plus fresh inspection.
The shape is fixed by the decision; the details are not yet written because
they depend on code not yet read at this level.
- [ ] Read `agent/skills/evaluate_vram_skill/isolated_probe.py` — PR A's
      isolated worker is the closest existing mechanism and may be the
      right host for this, rather than a new subprocess design.
- [ ] Read `gpu_accounting.sample`'s ours/other process-tree split; the
      measurement must be **candidate-owned**, not device total.
- [ ] Determine how sampling completeness is represented so an incomplete
      sample cannot silently become a requirement (O-7 governs the
      inconclusive case).
- [ ] Establish `measurement_kind` as an exact-match identity dimension so a
      duration bucket can never answer a memory query.
- [ ] Draft the remaining steps and bring them back before implementing.

**4. Validation plan.**
- Unit: a GPU-memory observation and a duration observation with otherwise
  identical identity land in **different** buckets (the 8.A cross-kind
  invariant).
- Unit: a peak measured under concurrency yields the candidate's share, not
  the raw device total.
- Negative: `valid_sample_count < 2` produces no promotable evidence.
- Negative: a duration bucket can never resolve to `requirement_mib`.

**5. Acceptance criteria.**
- [ ] `measurement_kind` is an exact-match identity dimension; a mutation
      removing it lets a millisecond bucket answer a memory query, and fails
      a named test.
- [ ] A promoted GPU-memory bucket exposes a value in MiB with provenance in
      `AUTHORITATIVE_PROVENANCE`.
- [ ] Under-statement is addressed explicitly per O-10, and the treatment is
      recorded on the record rather than applied silently.

**6. Failure and edge cases.** Single-sample phase; no observer bundle;
contended peak; first-ever configuration (cold start, D-B5); observer
present but device unavailable.

**7. Verification commands and evidence.** To be written with the steps.

**8. Commit boundary.** The measurement kind and its promotion only. No
admission wiring — that is C-C6.

---

### C-C6 — Supply PR B's admission gate  `[C2] governed by O-6, O-7, O-8`

**1. Goal.** `_phase_requirement` reads
`getattr(sandbox, "measured_requirements", None)`, which no production code
sets (§2.4), so formal admission always lands at `policy_unavailable`.

**2. Scope.** `core/sandbox_executor.py:467-500`, `admission.py:127`
(`AUTHORITATIVE_PROVENANCE`), `admission.py:165` (the unread
`measurement_source`), and the evidence-selection boundary per §9.

*Non-goals:* **no change to PR B's lane semantics, attribution vocabulary or
shrink authority.** No change to `enforcement` defaults — flipping
`observe_only` to `enforce` is a production-default change requiring
separate evidence and operator approval, and is **not** in this commit.

*Dependencies:* **C-C5a** (which creates the quantity this commit
delivers), C-C5; **O-6, O-7, O-8, O-10**.

**3. Implementation plan.**
- [ ] Implement the O-6 / O-7 / O-8 routing table above. The typed-boundary
      question is **frozen** by 8.A: PR B receives evidence through a typed
      production boundary, not the duck-typed `getattr`. A read no
      production code satisfies is how this gap survived PR B and its
      entire test suite.
- [ ] Proceed autonomously unless inspection reveals a material deviation —
      but only after the §15.2 producer audit is approved.
- [ ] Re-read `_phase_requirement` and `evaluate_gpu_admission`'s
      `requirement_provenance` handling before drafting.
- [ ] Resolve `measurement_source` (currently written, never read) or
      remove it.
- [ ] Draft remaining steps after the decisions land.

**4. Validation plan.**
- Unit: an applicable validated measurement produces a `requirement_mib`
  with provenance in `AUTHORITATIVE_PROVENANCE`.
- Unit: a **non**-applicable measurement does not.
- Reachability: a test failing if the executor bypasses the new boundary.
- Negative: inconclusive evidence produces neither allow nor reject.
- **Routing, per O-7** — the no-evidence path is *not* today's path:

  | State | Behaviour |
  |---|---|
  | cached applicable authoritative evidence | supply the typed requirement to PR B |
  | no cached evidence | request a **live pre-phase measurement** |
  | live measurement succeeds | supply the typed requirement to PR B |
  | live measurement inconclusive **or** unavailable | **stop the attempt before the GPU phase** (O-7) |

  The O-7 stop consumes an attempt, completes no round, carries no candidate
  blame and no shrink advice, and adds **no same-attempt retry loop** — only
  the existing outer attempt budget may produce another attempt.
- Parity, correctly scoped: what must be **unchanged** is PR B's attribution,
  its three refusal lanes, its shrink authority and the `observe_only`
  enforcement default. Today's *proceed-without-evidence* behaviour is
  **deliberately replaced** and must not be asserted as parity.

**5. Acceptance criteria.**
- [ ] Formal admission with applicable validated evidence no longer reports
      `policy_unavailable`.
- [ ] With no cached evidence, a live pre-phase measurement is requested —
      the attempt does **not** silently proceed as it does today.
- [ ] An inconclusive or unavailable probe stops the attempt before the GPU
      phase, with the O-7 accounting and no shrink advice.
- [ ] PR B's enforcement default is untouched; flipping `observe_only` to
      `enforce` remains a separate production-default change.
- [ ] `AUTHORITATIVE_PROVENANCE` is satisfiable by at least one real
      producer.
- [ ] No lane merge: the three refusal lanes still produce distinct
      statuses, budget accounting and shrink authority
      (`test_refusal_lane_distinctness.py` unchanged and green).

**6. Failure and edge cases.** Evidence applicable but stale; live evidence
contradicting calibration (O-8); probe unavailable (O-7); UUID missing.
None may fail open.

**7. Verification commands and evidence.** To be written with the steps.

**8. Commit boundary.** Evidence delivery only. No enforcement-default
change, no promotion logic.

---

### C-C7 — Calibration-state reporting and provenance  `[C1]`

**1. Goal.** No production reader of the registry exists, so the campaign
cannot state its own calibration state. Today an honest report would read
*20 observations, 0 promotions, 0 authoritative buckets* (§2.3).

**2. Scope.** Reporting surface, `CalibrationSummary`
(`registry_schemas.py:205`, zero non-test references), and the admission
record's provenance fields.

*Non-goals:* no dashboard work; no new persisted schema beyond what C-C2
established.

*Dependencies:* **C-C4 only.** C-C7 belongs to C1 and must **not** depend on
C-C6, which belongs to C2 — a C1 calibration report cannot be blocked on a
C2 checkpoint. Split accordingly:

| Report | PR | Content |
|---|---|---|
| calibration-state | **C1** (this commit) | collected / bucketed / unbucketed / quarantined / eligible / promoted / rejected, with reasons |
| admission-provenance | **C2** (with C-C6) | evidence source, tier, bucket identity, sample count, applicability decision, final authority, resolved policy source |

Report shape is an 8.B choice; the honesty rule (zero buckets is never
reported as active calibration) is frozen by 8.A and applies to both.

**3. Implementation plan.**
- [x] Resolve the report shape from the existing report surfaces (8.B) —
      landed as `core/runtime_control/calibration_state.py` (186 lines):
      `CalibrationStateReport` + `collect_calibration_state()`.
- [x] Inspect the existing report surfaces before choosing where this lands —
      `BootstrapReport.render()` was the surface already printing
      `observations : N recorded`, i.e. the exact number that misled for
      weeks. The state line is appended directly beneath it.
- [x] Wire it into `BootstrapReport.render()` (reachability test below).

**Authority is defined by buckets, never by record count.**
`buckets_authoritative` returns `buckets_validated` only —
`provisional` is a real state that is explicitly **not** authoritative, and
counting it is precisely how a report begins to overstate. `is_active` is
`readable and buckets_authoritative > 0`, so 20,000 observations with zero
validated buckets still reports `INACTIVE`, **with the reason attached**.

Counts are deliberately separate rather than one total, so an operator
asking *why* nothing is authoritative can see where evidence is being lost:
quarantined (incomplete identity), ineligible (failure provenance), or
eligible but below `provisional_min_observations=2` / outside
`consistency_max_min_ratio=1.5`.

**4. Validation plan.** `tests/unit/core/test_calibration_state.py` — 10
tests. Counts against a known fixture registry; refusal reasons name the
blocked bucket and its shortfall; unreadable ≠ empty; a provisional-only
report is not active.

**5. Acceptance criteria.**
- [x] The exact v1 shape — evidence collected, none promoted — reports
      `INACTIVE` with a reason
      (`test_observations_without_promotion_are_still_inactive`). Asserted
      against a fixture reproducing that shape rather than against the live
      tree, which is preserved evidence and is never opened by tests.
- [x] The report never describes calibration as active while zero
      authoritative buckets exist (`test_a_provisional_bucket_is_not_authoritative`).
- [ ] The seven admission-provenance fields are **C2's** acceptance
      criterion, asserted with C-C6, not here.

**6. Failure and edge cases.** Empty registry; registry unreadable; mixed
schema versions (per O-1); a bucket promoted then invalidated.

*Correction found by audit, 2026-08-02.* The first wiring built
`CalibrationRegistry(Path(self.registry_root))` **inside `render()`** and
passed the object in. `CalibrationRegistry.__init__` `mkdir`s six
subdirectories, so constructing one against a read-only or vanished parent
raises — placing the only raising step **outside** the guard
`collect_calibration_state` advertises, and letting a reporting failure
propagate into `render()`. That directly contradicts "reporting never raises
into or changes the scientific workflow".

Fixed by adding a `root=` parameter so construction happens **inside** the
guarded region; `render()` now passes the path, never a registry.

*Mutation proof.* Reverting `render()` to construct the registry itself makes
`test_bootstrap_render_survives_an_unusable_registry_root` fail with
`PermissionError: [Errno 13] ... /ro/runtime_calibration_v2` propagating out
of `render()`. Restored; baseline re-run green (19/19 for the two modules).
The collector-level test still passes under the mutation — correctly, since
it exercises the collector — which is why the **reachability** test at the
production caller is the one that catches this.

**7. Verification commands and evidence.**

```bash
.venv/bin/pytest tests/unit/core/test_calibration_state.py \
                 tests/unit/core/test_historical_duration_is_observability_only.py -q
# 19 passed
.venv/bin/pytest tests/unit/core/ -q     # 1500 passed, 2 skipped
```

**8. Commit boundary.** Reporting only. Reporting is read-only, never raises,
and carries no implication that historical data affects execution — see the
C-C5b cancellation above.

---

### C-C8 — Documentation sync  `[C1 and C2]`

**1. Goal.** Keep the operator's map current, per the node/skill doc-sync
rule.

**2. Scope.** This document (checkboxes, decision answers, evidence),
`docs/design/v20_priorities/README.md`, `v20_priorities.md` §20.5, and any
touched node/skill `.md`. Also the stale ladder row at
`v20_priorities.md:2139` (PR B "Conditional, likely yes").

*Dependencies:* all prior commits.

**3. Implementation plan.**
- [x] Update every C1 `[ ]` above to `[x]` with recorded evidence — §8.A
      frozen invariants (ten `[x]` with named tests, two marked `[C2]` rather
      than left ambiguous), §12.1 Layer-3 requirements, C-C7 §3/§5.
- [x] Quote each documented flag and default against the merged source —
      `docs/runtime_bootstrap.md` gained the `calibration:` line documented
      against `bootstrap.py::render`; O-4 values quoted from
      `DEFAULT_POLICY`; `SIDERIUS_CALIBRATION_DIR` semantics quoted from
      `calibration.py:50,57-62` and `default_registry_root()`.
- [x] Record which Layer-3 confirmation ran, on which device — §17b, run 4,
      RTX 5090 `GPU-c30b6678-…`, SHA `b06ef87`.

**4. Validation plan.** Documentation only; no tests. Verify by quoting
source, not memory.

**5. Acceptance criteria.**
- [x] No status line in the V20 folder contradicts the merged code —
      `v20_priorities/README.md` PR C row updated to "C1 implemented, in
      review" with the C-C5b cancellation; the C-C5b section header itself
      marked superseded rather than deleted.
- [x] Every follow-up is filed with its evidence — see the follow-up table
      in §16a: **FU-C-9** (legacy single-file mode crashes the time estimator
      on a `None` SampleSet) — the only one still open. **FU-C-10** (legacy
      v1 `k` in the estimate) and **FU-C-11** (Phase F writing the legacy
      table) are both **closed by implementation**, §16a-BD.

**6. Failure and edge cases.** n/a.

**7. Verification commands and evidence.** Full-suite sweep, ruff,
exact-head CI — recorded once at the end per §12.

**8. Commit boundary.** Docs only; last commit before the PR.

---

## 17a. C1 Layer-3 bounded real validation — pre-registered plan

Written **before** the run, per operator requirement. Operator authorised one
bounded fixed-candidate, no-LLM C1 run.

**What it confirms.** The **write → promotion → reporting** path end-to-end on
real hardware. Not a consumption path — C-C5b is cancelled, so there is no
production consumer of historical duration to confirm.

**Entry point.** `HyperparamTuningAgent(bridge_factory=...).run(...)` — the
real production entry point, containing the single production derivation seam
(`ml_hyperparameter_tune_agent.py:4822`). `sandbox_factory` is left at its
default, so training, inference and scoring are **real subprocesses**.

**How "no LLM" is achieved without faking the thing under test.** Only the
planner is substituted, through the sanctioned constructor DI seam
(`docs/pseudo_test_infra.md` §4A). A `FixedPlanBridge` returns the *same*
`ExperimentPlan` on every `plan()` call and a fixed string on `reflect()`.
Zero network calls. This is also what makes the run a *fixed candidate*: an
LLM planner varies the config each round, which would scatter observations
across buckets and never reach the promotion threshold.

**Configuration.**

| Item | Value |
|---|---|
| device | RTX 5090, `GPU-c30b6678-ff2a-f8b4-d378-af9681c6ceef` |
| model | `punet`, `segmentation_size=40000`, `batch_size=8` |
| train | `lr=5e-4`, `epochs=1`, `optimizer_type=adamw`, `device=cuda` |
| loss | `focal`, `alpha=0.5`, `gamma=2.0` |
| rounds | 3 formal (one per required observation) |
| data | `train_portion` / `eval_portion` bounded to a small snapshot |
| workspace | scratch directory, discarded after evidence capture |
| registry | `SIDERIUS_CALIBRATION_DIR` → **temporary v2 tree** |

**Expected wall time and resources.** Bounded by `--formal_time_budget_minutes`
and a small portion; target well under 30 min total, single GPU, no
concurrency.

**Pass criteria.**
1. Three successful attempts each derive one `CalibrationObservation` with
   `measurement_kind="duration"` and a complete `MeasurementIdentity`
   (including the real GPU UUID).
2. All three land in the **same** bucket — proving the fixed candidate hashes
   to one `candidate_config_hash` across rounds.
3. Promotion crosses the frozen O-4 thresholds in order: 1 → candidate only,
   2 → `provisional`, 3 → `validated`, with max/min ms-per-step ≤ 1.5.
4. `collect_calibration_state` reports `INACTIVE` before promotion and
   `ACTIVE` with ≥1 validated bucket after.
5. The live time verdict is **unchanged** by the populated registry.
6. The live v1 tree digest is still `c1065a8b612fb691…`.

**Stop criteria.** Stop and report rather than retry if: the run needs a real
LLM call; consistency ratio exceeds 1.5 (record it — that is a real finding
about measurement stability, not a failure to paper over); any write lands
outside the temporary registry; wall time materially exceeds the bound.

**Retained artifacts.** The temporary registry tree, the derived observation
and promotion records, the before/after calibration-state report lines, and
the v1 digest check. Recorded in §17b.

---

## 17b. C1 Layer-3 execution record

### Run 3 — 3 rounds on a SHARED GPU (superseded, but the findings stand)

Device: RTX 5090, `GPU-c30b6678-ff2a-f8b4-d378-af9681c6ceef`. Real training,
real inference, real scoring; `FixedPlanBridge`, zero LLM calls. Rounds 1 and
2 completed with real scores (`-0.0776`, `+0.8962`).

**Six observations, four buckets:**

| bucket | n | level | ms | ratio | identity | eligibility |
|---|---|---|---|---|---|---|
| `training \| single_candidate_idle` | 2 | **provisional** | 41.574, 48.095 | 1.157 | full, real GPU UUID, `cfg:c23fbeb88652` | clean |
| `inference \| single_candidate_idle` | 2 | **provisional** | 17.810, 24.604 | 1.381 | full, same `cfg` | clean |
| `training \| foreign_contended` | 1 | unvalidated | 40.785 | — | **absent** | `concurrency_identity='foreign_contended' is not clean` |
| `inference \| foreign_contended` | 1 | unvalidated | 6.826 | — | **absent** | same |

**What this actually confirms — more than a clean 3/3 would have.** The box is
shared, and a foreign process (`/home/wenyu/summer/.venv/bin/python`, 2.9 GiB)
was resident during part of the run. The system therefore exercised its
contamination paths on real hardware rather than in a fixture:

* contention **separates buckets** — the contended measurements did not land
  in, or pollute, the idle buckets (the §8 bucket-separation rule, live);
* contended observations are **ineligible** and can never be promoted;
* their identity is **absent, not fabricated** — `TestIdentityIsNotFabricated`
  is not a hypothetical;
* both clean buckets sit at exactly 2 → `provisional`, and C-C7 reports
  `INACTIVE` **with the D4 reason** while holding 6 observations. That is the
  precise failure mode this PR exists to remove: a registry that looks
  populated and is not authoritative, now saying so out loud.
* the same `candidate_config_hash` (`cfg:c23fbeb88652`) appears in every
  bucket across rounds, confirming the fixed candidate hashes stably and that
  the D-4 shared-identity fix holds end-to-end.

**Why it was stopped rather than finished.** Round 3 was promoted to a
**formal** round, which uses `formal_portion` / `formal_train_portion` —
left at their defaults (0.1 / 1.0) these are *not* bounded by the trial caps.
The estimate came out at **1801.9 min against a 25 min budget** and the
attempt OOMed. That is a harness scoping error, not a production defect: the
time gate correctly refused and requested a probe. Stopped under the §17a
stop criterion ("wall time materially exceeds the bound") rather than left to
grind through five attempts.

*Kept as evidence.* Run 3's registry is retained; it is the only artifact in
which the contention-exclusion path was exercised on live hardware.

### Registry-safety finding: one env var governs BOTH systems

`SIDERIUS_CALIBRATION_DIR` is read by both evidence systems:

* `evaluate_time_skill/calibration.py:50,57-62` — the **legacy v1** per-GPU
  `time_calibration_<gpu>.json` table;
* `calibration_registry.py::default_registry_root()` — the **v2** tree, as
  `$SIDERIUS_CALIBRATION_DIR/runtime_calibration_v2`.

Two consequences, both good, both previously unstated:

1. The session isolation fixture in `tests/conftest.py` pins that one
   variable and therefore protects **both** systems — the legacy table was
   never at risk from the suite either.
2. The Layer-3 harness isolates both for the same reason. Verified after the
   runs: `~/.siderius/time_calibration_nvidia_geforce_rtx_5090.json` still has
   its 2026-07-20 mtime, and no `time_calibration*` file was written into
   either temporary tree (the Phase F post-flight only fires on
   `real_dataset_warmup` evidence, and these rounds ran
   `static_uncalibrated`).

*Also note the shape of a mistake worth not repeating.* The variable is a
**base** directory, not the registry root — the v2 tree is a child of it.
Reporting against the base directory finds nothing and is indistinguishable
from "the writer never ran", which is precisely the silent never-match this PR
exists to remove. The first Layer-3 harness reproduced that bug in its own
reporting; fixed by resolving through `default_registry_root()`.

### Run 4 — bounded formal parameters, 5 rounds

`formal_portion=0.01`, `formal_train_portion=0.02`, `formal_eval_portion=0.01`
so a promoted formal round is bounded too, and 5 rounds so a
contention-contaminated observation can be **replaced** rather than a
threshold lowered.

**PASS.** Stopped after round 3 — every threshold was crossed and further
rounds would have consumed a shared GPU for no additional evidence.

#### Execution record

| Item | Value |
|---|---|
| Git SHA at validation | `b06ef87e0bda15d925765092ca4469d55bdb1bdd` |
| Harness | `layer3_c1.py` — `HyperparamTuningAgent(bridge_factory=FixedPlanBridge).run(...)`, default (real) sandbox |
| Command | `SIDERIUS_ROOT_FOR_HARNESS=<repo> LAYER3_SCRATCH=<scratch>/layer3_run4 .venv/bin/python layer3_c1.py` |
| LLM calls | **0** — planner substituted at the constructor DI seam; training, inference and scoring are real subprocesses |
| Device | RTX 5090, `GPU-c30b6678-ff2a-f8b4-d378-af9681c6ceef` (shared box; a foreign process was resident) |
| Candidate | `punet`, `seg=40000`, `batch=8`, `lr=5e-4`, `epochs=1`, `adamw`, focal(α=0.5, γ=2.0), `cuda` |
| Registry | `<scratch>/layer3_run4/registry_v2/runtime_calibration_v2` (temporary; 88 KB retained) |
| Workspace | `<scratch>/layer3_run4/workspace` |
| Expected / actual | ≪30 min budgeted; 3 rounds completed, real scores `-1.226`, `-0.285`, and round 3 |

#### Result — both buckets validated

```
calibration: ACTIVE — 2 validated bucket(s) from 6 eligible observation(s)
```

| bucket | n | level | ms/step | max/min | quarantined |
|---|---|---|---|---|---|
| `training \| optimizer_step \| single_candidate_idle` | 3 | **validated** | 48.419, 48.757, 49.028 | **1.013** | 0 |
| `inference \| inference_batch \| single_candidate_idle` | 3 | **validated** | 15.754, 15.943, 16.833 | **1.068** | 0 |

Every record carried a complete identity, from real hardware, identical across
rounds:

```
measurement_kind      duration
task_identity         tidmad_denoise
data_shape_class      psd10000000_seg200_files20
model_family          punet
candidate_config_hash cfg:c23fbeb88652
hardware_uuid         GPU-c30b6678-ff2a-f8b4-d378-af9681c6ceef
phase                 training / inference   (separate buckets, never merged)
```

#### Pass criteria — all six met

1. [x] Three successful attempts each derived a `duration` observation with a
       complete identity including the real GPU UUID.
2. [x] All three landed in the **same** bucket per phase — one
       `candidate_config_hash` (`cfg:c23fbeb88652`) across rounds, confirming
       the D-4 shared-identity fix end to end.
3. [x] The O-4 ladder crossed **in order, live**: 1 → candidate only, 2 →
       `provisional`, 3 → `validated`, both ratios far inside 1.5.
4. [x] `INACTIVE` before promotion (with the D4 reason, while already holding
       4 observations) → `ACTIVE` after.
5. [x] **The live verdict is unchanged by the registry.** Same
       `_gate_decision` inputs, run twice: against this ACTIVE registry (2
       validated buckets, 6 eligible observations) and against an empty one —
       **identical** `ALLOW` with `evidence_provenance=real_dataset_warmup`,
       the live measurement, never a calibration source. This is the operator
       decision demonstrated on genuinely authoritative stored evidence rather
       than on an empty tree.
6. [x] Live v1 tree byte-identical: `c1065a8b612fb691…` re-verified after the
       run; the legacy `k` table still carries its 2026-07-20 mtime and no
       `time_calibration*` file was written into either temporary tree.

**Phase separation, observed rather than asserted:** training ≈48.7 ms/step
and inference ≈16.2 ms/batch are ~3× apart and occupy separate buckets. The
frozen rule that training and inference never substitute for each other is not
a stylistic preference here — the numbers are simply different measurements.

---

## 17c. C1 final validation record

> **C1 COMPLETE — PR #161 green at exact head
> `3f5fa23238de19762f768bc5e89b446aa7218902`.**
> https://github.com/Galileo-Sandbox/SIDERIUS/pull/161 · CI run
> `30839502103` · `Lint + Type + Unit Tests: pass (8m12s)` · **not merged**.
>
> It took three CI runs, and both failures were things this machine
> structurally could not catch — pyright cannot execute here at all, and the
> local GPU made two tests pass for the wrong reason. Recorded because the
> pattern outlives this PR: on this repository "green locally" is a weaker
> claim than it sounds.

The table below was recorded at `5a5e7b5`, the PR head at open; the local
results are unchanged at the green head except for the added ordering test
(6389, not 6388).

| Check | Result |
|---|---|
| `pytest tests/unit -q` | **6388 passed, 2 skipped, 4 xfailed** (293s, exit 0) |
| `pytest tests/unit/core -q` | 1500 passed, 2 skipped |
| `ruff check .` | All checks passed |
| `ruff format --check .` | 667 files already formatted |
| **`pyright`** | **NOT RUN LOCALLY — cannot be.** Node on this host is v10.19.0; pyright's bundled JS fails to parse (`SyntaxError: Unexpected token =` in `vendor.js`). CI is the only environment that can run it. Recorded, not claimed. |
| live v1 registry | byte-identical, `c1065a8b612fb691…`, re-verified after every GPU run |
| legacy `k` table | untouched, mtime still 2026-07-20 |
| working tree | clean |
| Layer-3 | **PASS** — §17b |

**Mutation proofs retained in this PR**

| Mutation | Fails |
|---|---|
| revert `render()` to construct the registry itself | `test_bootstrap_render_survives_an_unusable_registry_root` — `PermissionError` escapes `render()` |
| reintroduce `_config_hash` in the write path | `test_the_derivation_does_not_define_its_own_hash` |
| delete the production derivation call | `test_the_derivation_is_called_in_production` / `test_it_is_called_from_run` |
| delete the promotion trigger call | `test_the_promotion_trigger_is_reachable_from_production` |
| move derivation into the shared append helper | `test_the_shared_append_helper_does_not_derive` |
| reintroduce a historical parameter on `_gate_decision` | `test_gate_decision_has_no_historical_parameter` |
| make the gate ignore its live input | `test_the_verdict_still_responds_to_the_live_measurement` (positive control) |

**On pyright specifically.** Per the repository rule that local success is not
evidence when a tool cannot run locally, nothing in this PR claims a passing
pyright run from this machine. The blocking check runs on the exact PR head in
CI, and that run — not this table — is the evidence.

**And it immediately earned its keep.** The first CI run on the PR head failed
on a blocking pyright error that had been latent since `f3ab878`:

```
calibration_policy.py:752:34 - error: Argument of type "str | None" cannot be
assigned to parameter "concurrency_identity" of type "ConcurrencyIdentity | None"
```

A set comprehension over a `Literal`-typed expression widens the element type
to `str`, so `regimes.pop()` could not populate the envelope's
`ConcurrencyIdentity` field. Fixed by **annotating the set**, not by loosening
the field or suppressing the rule — the Literal is the point: it is what stops
an arbitrary string becoming a concurrency class. (`2fed791`)

*Why nothing caught it earlier, worth knowing beyond this PR:* the workflow
triggers on `pull_request` only. A long-lived branch therefore accumulates
commits with **zero** CI coverage until a PR is opened — 34 commits, in this
case. Every "green" claim made on this branch before 2026-08-03 was a local
claim about a check the local machine could not run. That is a property of the
CI configuration, not of this PR, and is worth an operator decision separate
from C1.

**Second CI finding: two C1 tests silently required a GPU.** The next run
failed in `pytest`:

```
tests/unit/core/test_measurement_capability.py
  test_a_missing_dataset_root_is_refused_not_defaulted
    AssertionError: assert 'no dataset root' in ('no CUDA device is visible')
  test_a_nonexistent_root_names_the_path
    AssertionError: assert 'absent' in ('no CUDA device is visible')
```

`resolve_measurement_capability` checks the accelerator **before** the dataset
(`measurement_capability.py:132-137`), so on a GPU-less runner the dataset
branches those two tests exist to cover are **unreachable**. They passed only
because the developer box has a GPU — precisely the "local success is not
evidence of portability" failure the repository rules name, in tests C1 itself
added (`3927d06`).

*Fix, and why not the obvious one.* Skipping without CUDA would leave the
dataset policy untested in the one environment that gates merges — a green
suite proving less than it appears to, which is the same defect class in a new
costume. Instead a `cuda_present` fixture monkeypatches
`torch.cuda.is_available` so the dataset branches are reachable **everywhere**,
and a new test `test_the_accelerator_is_checked_before_the_dataset` pins the
ordering that made them machine-dependent in the first place.

*Verified against CI's actual condition, not assumed.* `CUDA_VISIBLE_DEVICES=""`
was confirmed to reproduce it exactly — `torch.cuda.is_available()` returns
`False` and the resolver emits the identical reason string CI reported — and
the whole unit suite was then re-run under it.

---

## 18. Expected artifacts

Per PR, since the two are reviewed separately.

**PR C1**
- A migration note recording how O-1 was carried out: the new tree, and
  proof the old tree's 20 records are untouched and still readable.
- Layer-2 matrix results for identity and applicability.
- One C1 Layer-3 confirmation: a real duration observation through
  promotion and applicability into the **calibration-state report**
  (corrected 2026-08-02 — the time-budget consumer was cancelled; see
  C-C5b and §11 Layer 3).
- A calibration-state report showing honest counts — against a read-only
  copy, 20 observations / 0 promotions / 0 authoritative buckets before any
  new evidence is collected.
- This document, checkpoints updated to `[x]` with recorded evidence.

**PR C2**
- The producer audit findings (§15.2) — required **before** implementation
  is authorized.
- One C2 Layer-3 confirmation on the target device: isolated pre-phase
  measurement through the typed requirement boundary into PR B's gate, with
  device identity and sampling completeness recorded.
- Evidence that an inconclusive probe stops the attempt under O-7 with no
  candidate blame and no shrink advice.
- An admission-provenance report carrying the seven fields.

**Both**
- Mutation proofs per merged family, each against real production source.
- Follow-ups FU-C-1..FU-C-8 filed with evidence.

---

## 30. Validity separation — the audited path and the frozen semantics (2026-08-05)

**Operator correction.** PR C's occupancy work (#176) implemented T0 at the
eligibility layer but left a presence-based refusal upstream, and defined
validity partly in terms of external *stability*. Both are wrong. Governing
mandate: `v20_prelaunch_completion_mandate.md` §2.4.

### 30.1 Audit — what production actually does today

Traced by reading the call path and by executing it (real-GPU Case B,
2026-08-05), not inferred from names.

**The refusal**, `core/runtime_control/bootstrap.py`:

```python
contended = window.classification not in ("single_candidate_idle",
                                          "pairwise_expected_peer")
...
remedy = ("Another process is using this GPU. The measurement would not "
          "describe an idle baseline — stop the other workload and re-run.")
if contended:
    return _finish(False)
```

Measured consequence — a stable, sole-occupant, 5104 MiB holder:

```text
bootstrap  ready: False
           contention window: foreign_contended (5 samples)
           "known foreign GPU process present (unregistered PIDs [2280629])"
```

`MeasurementValidity` was **never reached**. Three defects in one gate:

1. **presence decides readiness** — any unregistered PID refuses, regardless
   of stability or attribution;
2. **registration is privileged** — `pairwise_expected_peer` passes while an
   otherwise identical unregistered process is refused. Registration becomes
   a correctness requirement, which the mandate forbids;
3. **the remedy is dishonest** — it tells the operator to stop other
   workloads, i.e. that SIDERIUS requires an empty GPU.

**Producers of `foreign_contended`**: `calibration_policy.classify_contention_window`
(3 return sites — unregistered PID, peer-held memory over threshold, sustained
utilisation). **Consumers**: `bootstrap` readiness (above);
`estimate_types.contended` (2 sites) feeding `derive_decision_eligibility`;
`decision_policy` for the contended-measurement `REQUEST_PROBE` producer.

**The current `MeasurementValidity` is itself wrong** — mine, from #176:

```python
"valid_current_conditions" | "unstable_external_identity"
| "unattributed_occupancy_growth" | "sampling_incomplete"
```

`unstable_external_identity` makes a changing external PID set an invalidity
reason. Under the corrected semantics a changing PID set is an
**observation**.

**Correction (operator, 2026-08-06)**: do not read this as "only
`sampling_incomplete` survives". The vocabulary is not being narrowed to one
reason — it is being *re-grounded*. EVERY genuine measurement-integrity
failure remains a valid invalidity reason:

* candidate-owned process attribution failed;
* device identity missing or inconsistent;
* required samples missing or corrupted;
* probe lifecycle incomplete;
* telemetry cannot separate candidate demand;
* a required interpretation invariant does not hold.

What loses its standing as a **direct** invalidity reason is only:

* an external PID exists;
* an external PID is unregistered;
* the external PID set changed;
* external memory fluctuated;
* the external workload is bursty.

`unattributed_occupancy_growth` therefore survives *as an attribution
failure* — when growth means candidate demand can no longer be separated —
and not as a statement that a neighbour grew.

### 30.2 Frozen semantics — three independent questions

**(1) External activity — CONTEXT, never validity.** Recorded: present or
absent; registered PIDs; unregistered PIDs; whether the PID set changed;
external attributed-memory min/max/latest; a descriptive marker
(`absent` / `stable` / `variable` / `unknown`). Descriptive only.

**(2) Measurement validity — INTEGRITY only.** Valid when the device is known,
candidate-owned processes and descendants are attributable, samples are
complete and interpretable, candidate demand is separable from other demand,
the probe lifecycle completed, and interpretation invariants hold.

Invalid only for a **named integrity failure**: attribution unavailable;
process tree untrackable; device identity missing or inconsistent; samples
incomplete or corrupted; telemetry cannot separate candidate usage; probe
lifecycle incomplete; invariant failed.

**Never invalidity reasons**: an external process exists; it is unregistered;
its memory changes; the PID set changes; it is bursty; there are several.

Where external change genuinely destroys attribution, the reason is the
**attribution/telemetry failure**, never the external presence.

**(3) Admission — SEPARATE.** Candidate-attributed demand vs current available
resources vs configured margin, with external occupancy recorded alongside.
Both `valid + admit` and `valid + reject_insufficient_current_resources` are
expected. No hidden stability gate. No registration requirement.

**Registration is metadata.** Given identical measured facts and resources,
registered and unregistered external workloads must produce identical validity
and admission outcomes.

**Historical compatibility.** Existing `foreign_contended` records stay
readable; new records do not emit it as a blocking presence verdict; nothing
is reconstructed or upgraded.

### 30.3 Decision ledger

| | |
|---|---|
| current behaviour | presence refuses readiness before validity is computed; registration privileged; remedy demands an empty GPU |
| corrected behaviour | presence is observation; validity is integrity; admission is separate; registration is provenance |
| why the old behaviour is wrong | it asks "is anyone else on the GPU?" — the question T0 was adopted to stop asking — and makes SIDERIUS unusable on a shared device |
| alternative rejected | register the holder as an expected peer. Rejected: it produces a green result for a *different* property and leaves the real claim untested |
| alternative rejected | retire `classify_contention_window` entirely. Rejected: it still produces useful observations and is consumed elsewhere; the narrow fix is to stop it *deciding readiness* |
| compatibility | old vocabulary readable; new records use honest non-blocking terms; no historical upgrade |

### 30.4 Implementation record (2026-08-06)

| checkpoint | commit | what landed |
|---|---|---|
| A | `ac0afeed` | `ExternalActivityObservation` + `summarise_external_activity` — activity marker, registered/unregistered PID split, PID-set-change flag, external memory min/max/latest. Pure observation, no verdict. Unreadable telemetry reports `unknown`, never `absent` |
| B | `ac0afeed` | the presence gate removed from `bootstrap.py`; the window is still sampled and recorded with `decides_readiness: False` |
| C | `ac0afeed` | validity re-grounded to integrity: `candidate_attribution_failed`, `device_identity_unavailable`, `sampling_incomplete`, `probe_lifecycle_incomplete`, `measurement_invariant_failed`; retired reasons named in `RETIRED_PRESENCE_REASONS` |
| D | `8c888891` | admission separation asserted; scope narrowed (below) |
| E | this commit | bootstrap docstrings and the operator doc corrected |

**Scope narrowed, and the attempt recorded.** Widening the no-window fallback
so `foreign_contended` no longer withheld blocking authority changed behaviour
across five modules for paths carrying **no occupancy evidence at all**. It
was reverted. The fallback now reads "validity NOT ESTABLISHED", not "presence
invalidates", and every path that names its device — including the real
bootstrap/probe path after FU-C-1 — builds a window and is decided by
integrity.

**Mutation guards** (all caught): PID-set change invalidating again; presence
refusing readiness again; registration privileged in the summary; conservative
aggregates dropped.

**Re-grounded suites**, because they encoded the retired semantics:
`test_measurement_validity` (identity change now valid),
`test_c10_bootstrap` and `test_bootstrap_pseudo` (a busy GPU is recorded and
still measured). A `_Window` fake also needed `occupancy` — the fourth
instance of the injection-seam class; the fake was fixed rather than
production weakened.

**Not stale after review**: "idle baseline" in `campaign.py`,
`runtime_campaign.py`, `running_chain_test.md` and
`runtime_estimation_and_calibration.md` describes the C12 campaign's
*scientific* design — measure alone, then paired, to derive a contention
multiplier. That is a legitimate experimental requirement, not a readiness
gate, and was deliberately left unchanged.

### 30.5 Pre-freeze transport verification, and one honest residue

Run against the candidate head before freezing. Six properties verified by
execution; the seventh is a documented residue rather than a clean claim.

| # | property | result |
|---|---|---|
| 1 | a no-window path does not FABRICATE `VALID` in the persisted field | **OK** — `measurement_validity` stays `None`; only the local eligibility computation treats idle as valid, preserving legacy behaviour without writing a claim |
| 2 | registered and unregistered produce identical validity and aggregates | **OK** — labels differ (`registered_pids` vs `unregistered_pids`), `activity` and `external_mib_max` identical, same verdict |
| 3 | an attribution failure names attribution, never resources | **OK** — reason contains none of "insufficient / free memory / headroom / resources" |
| 4 | `ExternalActivityObservation` round-trips and is strict JSON | **OK** — reload equals the original; no `Infinity`/`NaN` |
| 5 | the observation is actually attached to the bootstrap step, from the window's REAL snapshots | **OK** — `external.model_dump(mode="json")` on the step; summarised from `window.occupancy.snapshots` |
| 6 | `decides_readiness: False` is a CONSTRAINT, not decoration | **OK** — the step's `ok=True` is literal, so presence cannot refuse; guarded by a test and by mutation 2 |
| 7 | `foreign_contended` is read-only for history | **RESIDUE — see below** |

**The residue.** `classify_contention_window` still *produces*
`foreign_contended` (3 return sites), and `estimate_types` still maps it into
`contended`, which feeds the no-window eligibility fallback. So on paths that
name **no device** — and therefore have no occupancy window — external
presence still influences blocking authority indirectly.

Where it does **not** apply: the bootstrap readiness gate (removed), and every
path that names its device, which builds a window and is decided by integrity.
That includes the real Case B bootstrap/probe path after FU-C-1.

**Why it is left.** Removing it means changing the eligibility rule for
measurements carrying no occupancy evidence at all. That was attempted and
reverted: it altered behaviour across five modules for paths where nothing had
been sampled, and granting blocking authority there would rest on no evidence.
The mandate's narrow-correction rule excludes that scope, and the operator's
instruction is explicit that a missing-evidence path must not fail OPEN merely
to retire old vocabulary.

**How to read the residue honestly**: on a no-window path the outcome is
"validity NOT ESTABLISHED", and `foreign_contended` is the legacy signal that
happens to carry it. The classification remains useful provenance. Retiring
the vocabulary entirely belongs to a later change that gives those paths real
occupancy evidence, not to this one.
