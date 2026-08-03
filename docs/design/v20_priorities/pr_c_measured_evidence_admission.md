# Design: V20 PR C — Measured evidence and formal admission

- **Status**: **DESIGN — revision 3, awaiting final operator review.** The
  ten §8.C operator decisions are **APPROVED (2026-08-03)**; the document
  itself is not yet approved for implementation. No implementation has
  begun, and neither implementation branch has been created
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
documents were re-derived, not carried forward; §3 lists the ones that
changed.

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

| Kind | Producer | Unit | Phase | Persistence | Promotable? | Authority it may hold |
|---|---|---|---|---|---|---|
| **Runtime duration** | bounded probe → `probe_observations` (`probe.py:518`); warm-up → `evaluate_time_skill/wrapper.py` | ms per `optimizer_step` / `inference_batch` | training, inference | System B registry (content-addressed, per user); System A JSONL (per workspace) | yes — the existing `evaluate_bucket` path | time-budget decisions; **never** a GPU capacity verdict |
| **GPU allocated** | `GpuAccountingSnapshot` via `gpu_accounting.sample` | MiB | any phase | inside `GpuEvidenceBundle` → `ExperimentRecord.gpu_evidence` (`sandbox_executor.py:753`) | **no mechanism today** | occupancy evidence for PR B's attribution |
| **GPU reserved / driver-visible** | same snapshot, driver-visible column; the A6 finding is that these differ from allocated by ~1.8–2.0x | MiB | any phase | same | **no mechanism today** | the quantity a host quota actually counts |
| **GPU driver-visible requirement** | **does not exist as a measurement.** Nearest: `GpuEvidenceBundle.observed_peak` (`gpu_observer.py:84`) | MiB | per phase | `ExperimentRecord.gpu_evidence` | **no mechanism today** | this is what PR B needs |
| **Host memory** | `HostMemoryEvidence`, isolated pre-flight; `read_process_rss_bytes` | GiB / bytes | pre-flight, any phase | `IsolatedProbeResult`; `RuntimeObservation` | no | host-memory refusal only; **never** a VRAM verdict |

Separately, and not a measurement at all: `evaluate_vram_skill` produces
`estimated_gb` (`wrapper.py:660`) — a **prediction** from a structural probe.
V19 established it holds no rejection authority, and A6 measured it
under-reading driver-visible by 1.95x and 1.82x. It is a prior, not a
requirement.

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
- **Track 2 — GPU requirement.** Establish a bucketed, promotable
  GPU-memory measurement from `observed_peak`, with its own kind, unit and
  authority, that resolves to `requirement_mib`. Consumer: PR B's gate.

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
  source, if §8 O-1 chooses that).
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
  8.B, 8.B, 8.A) — subject to the 8.A rule that zero buckets is
  reported honestly.
- Which of the seven provenance fields each admission record carries and how
  they are typed (former 8.B) — the *set* is fixed by 8.A, the encoding is
  not.
- Whether `measurement_source` (`admission.py:165`, written and never read)
  is resolved or removed.
- Whether `probe_lifecycle.ProbeRequest.model_family` becomes required.

### 8.C Operator decisions — APPROVED 2026-08-03

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

### Layer 3 — bounded real confirmation

One small real path:

```
real candidate -> real observation -> real identity and provenance
-> promotion evaluated -> bucket validated or rejected with reason
-> applicability checked -> admission consumer receives the evidence
-> decision and authority persisted
```

Implementation and unit tests need no H100. **A measurement promoted as
H100-authoritative must be collected on the H100 itself; a 5090 measurement
must never become H100-authoritative** (8.A). Not run while drafting.

---

## 12. Stop conditions

Stop and report rather than proceeding if:

- the migration decision (O-1) would destroy or orphan existing evidence;
- a change would let any lane's refusal produce shrink advice;
- a change would alter retry behaviour, LLM call count, or cost;
- an applicability rule cannot be stated without a task-specific special
  case inside generic code;
- production is found to still admit formally on non-authoritative evidence
  in a way not described here.

## 13. Merge criteria

- All Layer-1 tests pass, each with a mutation proof against real production
  source;
- Layer-2 matrix complete, every row with an expected outcome;
- one bounded Layer-3 confirmation on the target hardware;
- no new fail-open default (the §2.10 table unchanged in length);
- `run()` gains no new responsibility;
- exact-head CI green, including the repository's configured blocking
  pyright check — currently `typeCheckingMode: "basic"`
  (`pyrightconfig.json:28`), despite the CI step being *named*
  "strict, blocking". PR C must not claim strict; see FU-C-1;
- every operator decision in §8.C answered in this document before
  implementation.

## 14. Deferred

- Unifying `operation` and `RuntimePhase` vocabularies.
- Merging System A and System B.
- Registering the legacy k-table as a legacy source.
- `_ROLE_DEFAULT_RSS_GB` keyed by task phase name (FU-B-6).
- The dead seams listed in §2.2 that PR C does not revive — each should be
  either wired or removed, not left as apparent coverage.
- **FU-C-1**: `pyrightconfig.json` says `basic` while the CI step is named
  `strict` (§9). Repository-wide effect; needs its own decision.
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

---

## 15. Implementation splits into two PRs

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

Merge criteria, in addition to §14: a normal formal run leaves a duration
observation in the **new** tree; a bucket reaches `validated` only under the
O-4 values; the report tells the truth about an uncalibrated system; the old
tree is untouched and still readable.

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

Merge criteria, in addition to §14: an applicable pre-phase measurement
produces `requirement_mib` with provenance in `AUTHORITATIVE_PROVENANCE`; an
inconclusive probe stops the attempt per O-7 with no candidate blame and no
shrink advice; **PR B's three refusal lanes remain distinct**
(`test_refusal_lane_distinctness.py` unchanged and green); with no
authoritative evidence, behaviour is byte-identical to today.

**Explicit non-goal:** C2 changes no enforcement default. Flipping
`observe_only` to `enforce` is a production-default change needing its own
evidence and approval.

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

## 16. Commit plan

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
> **O-10 answered this (2026-08-03):** `observed_peak` is *not* the
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


**All ten §8.C decisions were approved on 2026-08-03.** Each checkpoint
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
- [ ] Read `classify_model_family` and confirm what `structural_features` it
      requires and whether the tuner has them at `:947`.
- [ ] Decide (8.B) whether `model_family` is the classified family or the
      registered `model_type`; the two producers currently disagree (§2.9).
- [ ] Pass the resolved family into `ProbeRequest` at `:947-957`.
- [ ] Resolve a real `software_stack` at `:978` instead of `{}` — source it
      from the existing provenance capture rather than re-deriving.
- [ ] Decide whether `probe_lifecycle.py:69`'s `"unknown"` default should
      become required; a required field turns a silent mis-bucket into a
      loud construction error.

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
- [ ] A probe-produced observation carries a family that is **not**
      `"unknown"` for a registered model type.
- [ ] `bucket_key` for two different model families differs in exactly the
      family component and nothing else.
- [ ] `stack_identity` for a populated stack differs from the constant
      `stack_identity({})` digest observed today.
- [ ] All 20 existing records still load — `load_observation` raises on
      none of them. Verified against a **copy in a temporary tree**, never
      against `~/.siderius/runtime_calibration`. The live per-user registry
      is read-only evidence for this work: no test, script or checkpoint may
      write to it, and O-1 preserves the old tree untouched.
- [ ] Mutation: reverting either call site to its current form fails at
      least one new test.

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
- [ ] Operator answers O-1 (and the 8.B config-identity choice).
- [ ] Re-inspect `hash_payload`/`content_id` and the manifest reader before
      writing the steps.
- [ ] Draft the steps and bring them back for review.

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
- [ ] Operator answers O-3.
- [ ] Re-inspect `decision_policy.decide` and `probe_runner_availability`.
- [ ] Draft the steps and bring them back for review.

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
the operator setting them (O-4, O-4).

*Dependencies:* C-C2, C-C3.

**3. Implementation plan.** **Not written.** The thresholds are operator
policy; `CalibrationPolicy`'s identity hash covers every field, so changing
one trips `runtime_policy_identity` and invalidates every existing workspace
lock. That interaction must be settled before steps are drafted.
- [ ] Operator answers O-4, O-5, O-9.
- [ ] Confirm the `run_invariants` interaction above by inspection.
- [ ] Draft the steps and bring them back for review.

**4. Validation plan.** Promotion reached in production; rejected promotions
reported with reasons; contended evidence handled per O-5; expiry per O-9;
repeated samples where promotion depends on statistical consistency.

**5. Acceptance criteria.**
- [ ] A bucket with sufficient consistent observations reaches `validated`.
- [ ] A bucket with inconsistent observations does not, and the reason is
      recorded.
- [ ] The calibration-state report shows non-zero promotions where they
      exist — today it would honestly show zero.

**6. Failure and edge cases.** Insufficient samples; inconsistent
observations; contended-only buckets; stack or hardware change mid-bucket.

**7. Verification commands and evidence.** To be written with the steps.

**8. Commit boundary.** Promotion only. No applicability, no admission.

---

### C-C5 — Applicability evaluator on the production path  `[C1] governed by O-6, O-8`

**1. Goal.** `applicability_for_request` and `downgrade_for_applicability`
have zero callers. Invariant 3 requires that a bucket match is **not**
applicability.

**2. Scope.** `calibration_policy.py:583-660`, plus a focused applicability
boundary per §9.

*Non-goals:* not making a bucket match sufficient; not merging phases.

*Dependencies:* C-C2, C-C4. The reuse rules are **frozen** by 8.A, not
open; only their encoding is an 8.B choice.

**3. Implementation plan.**
- [ ] Confirm the 8.A reuse invariants are all expressible in the
      identity/envelope split; if one is not, that is a design deviation.
- [ ] Re-read `classify_applicability` and confirm its fail-closed
      behaviour at `:612-616` still holds under the new dimensions.
- [ ] Extract the applicability evaluator as a typed boundary with a
      reachability test (§9).
- [ ] Draft remaining steps after the decisions land.

**4. Validation plan.** The full Layer-2 matrix (§10) — every row, with an
expected outcome. Training-vs-inference substitution must fail
(frozen, 8.A). Cross-UUID reuse must fail. Cross-task must fail. Cross-kind
must fail (§3).

**5. Acceptance criteria.**
- [ ] Every Layer-2 row produces its expected label.
- [ ] A matching bucket with a non-applicable candidate is downgraded, not
      accepted.
- [ ] Mutation: removing any single applicability dimension fails a named
      row.

**6. Failure and edge cases.** No measured range for a dimension (already
fails closed — preserve); candidate at a range boundary; missing family;
inconclusive probe.

**7. Verification commands and evidence.** To be written with the steps.

**8. Commit boundary.** Applicability only.

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

**2. Scope.** `core/runtime_control/gpu_observer.py` (read only, as the
producer), the identity/envelope/policy models from C-C2, and a new
`measurement_kind` value. Persistence of GPU-memory observations alongside
duration observations.

*Non-goals:* not changing what `GpuPhaseObserver` samples; not changing PR
B's attribution; not changing `estimated_gb`'s status as a prior.

*Dependencies:* C-C1, C-C2, C-C5; **O-10**.

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
- [ ] Operator answers O-6, O-7, O-8. The typed-boundary question is
      **frozen** by 8.A: PR B receives evidence through a typed production
      boundary, not the duck-typed `getattr`. A read no production code
      satisfies is how this gap survived PR B and its entire test suite.
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
- Parity: with no authoritative evidence, behaviour is **unchanged** from
  today — `policy_unavailable`, `would_refuse` under `observe_only`.

**5. Acceptance criteria.**
- [ ] Formal admission with applicable validated evidence no longer reports
      `policy_unavailable`.
- [ ] With no evidence, the recorded outcome is byte-identical to today's.
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

*Dependencies:* C-C4, C-C6. Report shape is an 8.B choice; the honesty
rule (zero buckets is never 'active') is frozen by 8.A.

**3. Implementation plan.**
- [ ] Resolve the report shape from the existing report surfaces (8.B).
- [ ] Inspect the existing report surfaces before choosing where this lands.
- [ ] Draft the steps.

**4. Validation plan.** Counts are correct against a known fixture registry;
rejection reasons are represented; every admission record carries the seven
fields of 8.B; the report cannot claim calibration is active when zero
authoritative buckets exist (8.A).

**5. Acceptance criteria.**
- [ ] Against the current live registry the report reads 20 / 0 / 0 — i.e.
      it tells the truth about an uncalibrated system.
- [ ] Every admission record identifies evidence source, tier, bucket
      identity, sample count, applicability decision, final authority and
      resolved policy source.

**6. Failure and edge cases.** Empty registry; registry unreadable; mixed
schema versions (per O-1); a bucket promoted then invalidated.

**7. Verification commands and evidence.** To be written with the steps.

**8. Commit boundary.** Reporting only.

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
- [ ] Every follow-up (FU-C-1..FU-C-5) is filed with its evidence.

**6. Failure and edge cases.** n/a.

**7. Verification commands and evidence.** Full-suite sweep, ruff,
exact-head CI — recorded once at the end per §12.

**8. Commit boundary.** Docs only; last commit before the PR.

---

## 17. Expected artifacts

- This document, updated with operator answers to §7.
- A migration note recording the O-1 decision and what happened to the 20
  existing records.
- Layer-2 matrix results.
- One Layer-3 confirmation record with device identity.
- A calibration-state report (8.B/8.A) showing honest counts.
