# Design: V20 PR C — Measured evidence and formal admission

- **Status**: **DESIGN — revision 4.**
  - Umbrella architecture and the ten §8.C operator decisions:
    **APPROVED 2026-08-03 UTC**.
  - **PR C1 design: READY FOR IMPLEMENTATION** on approval, from a fresh
    branch off current `master`.
  - **PR C2 implementation: NOT AUTHORIZED.** C2 must first complete and
    have approved the read-only producer audit in §15.2 — the pre-phase
    GPU measurement is the most safety-critical measurement in the system,
    and its architecture must not be decided while writing it.
  - No implementation has begun; neither branch exists
    (`v20_priorities.md` §20.1).
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

- [ ] `model_family = "unknown"` is **never** authoritative. It is a
      bucketing failure, not a family.
- [ ] A matching bucket is **not** applicability. It identifies a candidate
      set that must then be checked.
- [ ] Cross-**task** reuse fails.
- [ ] Cross-**data-shape-class** reuse fails.
- [ ] Cross-**GPU-UUID** reuse fails. A 5090 measurement is never
      H100-authoritative.
- [ ] Cross-**phase** reuse fails; training and inference never substitute
      for each other (PR B measured them 1.8x apart).
- [ ] Cross-**measurement-kind** reuse fails (§3). A promoted millisecond is
      never a memory requirement.
- [ ] Missing identity **never** fails open into "safe to proceed".
- [ ] Zero authoritative buckets is **never** reported as active
      calibration.
- [ ] PR B receives evidence through a **typed production boundary**, not
      the unfulfilled duck-typed `getattr(sandbox, "measured_requirements")`.
      That read is how the gap survived PR B and its whole test suite.
- [ ] Static estimates remain priors; historical evidence alone is not a
      final gate; an inconclusive measurement becomes neither allow nor
      reject.
- [ ] PR B's three refusal lanes keep distinct statuses, budget accounting
      and shrink authority.

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
  -> time-budget consumer
  -> calibration-state report
```

Requirements:

- [ ] a **temporary v2 registry**; the live v1 tree is read-only evidence
      and is never written to or rebuilt;
- [ ] the same candidate and configuration repeated enough times to cross
      the frozen O-4 threshold (`validated_min_observations = 3`, with
      `consistency_max_min_ratio = 1.5`);
- [ ] every identity dimension recorded: task, data-shape class, phase,
      model family, GPU UUID, runtime stack, measurement kind;
- [ ] a mismatching task, GPU UUID, phase or measurement kind is **rejected**
      — the frozen §8.A isolation rules, proven on real records rather than
      constructed ones;
- [ ] the report says calibration is **inactive** while zero authoritative
      buckets exist.

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

**Current live measurement is the sole production time-decision input.**

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
- [ ] Update every `[ ]` above to `[x]` with recorded evidence.
- [ ] Quote each documented flag and default against the merged source.
- [ ] Record which Layer-3 confirmation ran, on which device.

**4. Validation plan.** Documentation only; no tests. Verify by quoting
source, not memory.

**5. Acceptance criteria.**
- [ ] No status line in the V20 folder contradicts the merged code.
- [ ] Every follow-up (FU-C-1..FU-C-8) is filed with its evidence.

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
