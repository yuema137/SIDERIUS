# Design: V20 PR C — Measured evidence and formal admission

- **Status**: **DESIGN DRAFT — awaiting operator review.** No implementation
  has begun and none is authorized until this document is approved
  (`v20_priorities.md` §20.1). When approved, implementation starts on a
  fresh branch cut from the then-current `master`.
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

It is **not** "wire calibration into admission". The calibration machinery
exists and is almost entirely unreachable; the identity it would key on is
incomplete; and the persistence format cannot accept new identity fields
without invalidating every record already written. Those three problems are
the work.

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

## 3. Corrections to earlier assumptions

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

## 4. Scope

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

## 5. Out of scope

- Changing PR B's lane semantics, attribution vocabulary, or shrink
  authority.
- Raising any memory ceiling.
- The legacy k-table's own behaviour (only its registration as a legacy
  source, if §7 D-C3 chooses that).
- Repository-wide test pruning.
- HealthGate formal policy (PR D) and campaign-scoped control (PR E).
- FU-B-18 (`_MAX_REASONING_RETRIES`).

---

## 6. High-level evidence and authority invariants

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
   proceed."** §2.8 is the existing list; PR C adds nothing to it.

### 6.1 Three categories that must not collapse

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

## 7. Open operator decisions

None of these may be settled by quietly coding a convenient default.

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

## 8. Genericization impact and in-passing refactor

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

## 9. Responsibility-oriented decomposition and orchestration impact

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

### 9.1 The three existing hooks, in order of preference

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

### 9.2 Caveat on the existing extractions

Per CLAUDE.md — *"a helper that still reads and mutates arbitrary outer
state is not a completed decomposition"* — several PR-B-era helpers are
**parameter-passing extractions, not typed boundaries**:
`_handle_admission_refusal` takes 11 arguments, `_check_and_record_guardrail_skip`
15, `_build_skip_record` 13, `_build_resource_admission_record` 12. They do
not mutate outer state, which is the important half. But the nine-field
identity block (`exp_id`, `model_type`, `file_index`, `record_params`,
`expert_advice_str`, `hypothesis`, `round_index`, `attempt_in_round`) is
re-threaded by hand at every call site and is not itself a typed object.

**There is no `AttemptContext` model.** Introducing one is the smallest
bounded decomposition that would make PR C's new boundaries cheap to call
and is the recommended first checkpoint — but it touches many call sites and
must be proven behaviour-preserving before any new logic rides on it.

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

## 10. Validation design

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
must never become H100-authoritative** (D-C16). Not run while drafting.

---

## 11. Stop conditions

Stop and report rather than proceeding if:

- the migration decision (D-C3) would destroy or orphan existing evidence;
- a change would let any lane's refusal produce shrink advice;
- a change would alter retry behaviour, LLM call count, or cost;
- an applicability rule cannot be stated without a task-specific special
  case inside generic code;
- production is found to still admit formally on non-authoritative evidence
  in a way not described here.

## 12. Merge criteria

- All Layer-1 tests pass, each with a mutation proof against real production
  source;
- Layer-2 matrix complete, every row with an expected outcome;
- one bounded Layer-3 confirmation on the target hardware;
- no new fail-open default (§2.8 unchanged in length);
- `run()` gains no new responsibility;
- exact-head CI green including strict pyright;
- every operator decision in §7 answered in this document before
  implementation.

## 13. Deferred

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

## 14. Commit plan

Eight commits. Each is independently reviewable and does not carry unrelated
cleanup. `[ ]` = not done; `[x]` only after implementation **and** recorded
evidence.

**Three commits are BLOCKED on operator decisions and are deliberately left
without low-level steps** — writing them now would mean inventing the very
details the decision determines. They are marked `BLOCKED` with the decision
that unblocks them.

**Standing rule for every commit below:** before committing, stop and show
the exact diff summary, staged file list, test results, and any deviation
from this design. Inspect the relevant code before finalising each plan; if
inspection reveals ambiguity or a larger scope than assumed here, stop and
ask rather than widening the commit.

---

### C-C1 — Populate the two identity fields production drops

**1. Goal.** `model_family` and `software_stack` are dropped at two
production call sites (§2.5), so every registry record buckets under
`family=unknown` with a constant stack digest. Fixing this is a precondition
for any applicability rule: without it, every record is in one bucket.

Belongs here because it changes **no schema** — both fields already exist —
so it can land and be validated before the migration decision (D-C3) is
made.

**2. Scope.**
- `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:947-957`
  (`ProbeRequest` construction) and `:978` (`build_registry_persist`).
- Possibly `core/runtime_control/probe_lifecycle.py:69` (the `"unknown"`
  default).
- The resolver for a real family value —
  `calibration_policy.classify_model_family` (`:259`) exists and has zero
  callers; whether it is the right resolver is **D-C2**.

*Non-goals:* no change to `bucket_components`; no schema field added; no
change to what the probe measures; the `"unknown"` value must remain legal
for records that genuinely cannot be classified.

*Dependencies:* none. This is the first commit.

**3. Implementation plan.**
- [ ] Read `classify_model_family` and confirm what `structural_features` it
      requires and whether the tuner has them at `:947`.
- [ ] Decide (D-C2) whether `model_family` is the classified family or the
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
- Negative: a candidate whose family genuinely cannot be classified still
  produces a valid record, marked unusable rather than silently
  `"unknown"`-bucketed (subject to D-C1).
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
      none of them.
- [ ] Mutation: reverting either call site to its current form fails at
      least one new test.

**6. Failure and edge cases.**
- Family unresolvable → explicit unusable marker, **not** `"unknown"`
  silently entering a shared bucket (D-C1). Must not stop the run.
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

### C-C2 — Typed identity contract for a calibration record  `BLOCKED: D-C3`

**1. Goal.** Add task identity, dataset/data-shape class and device-instance
identity to calibration identity (§2.6), so a record states what it
measured.

**2. Scope.** `core/runtime_control/registry_schemas.py`,
`calibration_policy.py:296-326` (`bucket_components`/`bucket_key`), and the
producers that must supply the new values.

*Non-goals:* no change to promotion thresholds; no merge of System A and
System B.

*Dependencies:* C-C1; and **D-C3**, which decides whether this is a new
schema version in a new directory, a re-hash migration, or a partial hash.

**3. Implementation plan.** **Deliberately not written.** Every step depends
on D-C3: option 1 means a v2 tree and a reader that handles both; option 2
means a migration script; option 3 changes `hash_payload` itself. Writing
steps now would commit to one before the operator chooses.
- [ ] Operator answers D-C3 (and D-C4, D-C5).
- [ ] Re-inspect `hash_payload`/`content_id` and the manifest reader before
      writing the steps.
- [ ] Draft the steps and bring them back for review.

**4. Validation plan (shape known now, cases pending D-C3).**
- Unit: two records identical except for task land in different buckets.
- Unit: two records identical except for GPU UUID land in different buckets
  — **a 5090 measurement must never be H100-authoritative** (D-C16).
- Unit: two records identical except for data-shape class land in different
  buckets.
- Backward-compat: whatever D-C3 chooses, the 20 existing records must
  remain **readable and attributable**, not silently dropped by
  `rebuild_index`.
- Negative: a record missing a mandatory identity field cannot become
  authoritative (D-C1).

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

### C-C3 — Make the registry write path reachable  `BLOCKED: D-C6`

**1. Goal.** `record_observation` is reached only through a gate the happy
path cannot open (§2.3), which is why there are 20 records and 0 promotions.

**2. Scope.** `core/runtime_control/probe_wiring.py`,
`decision_policy.py:308-320`, `ml_hyperparameter_tune_agent.py:924-946`.
Also §2.8: `probe_runner_availability()` refuses without `TIDMAD_DATA_DIR`,
so on any other task the path is dead regardless of the trigger.

*Non-goals:* not changing what a probe measures; not changing
`RuntimeDecisionPolicy`'s authority matrix.

*Dependencies:* C-C1; **D-C6** (what triggers promotion evaluation), and the
§2.8 dataset gate must be addressed or the fix is TIDMAD-only.

**3. Implementation plan.** **Not written** — D-C6 determines whether the
trigger is a new decision branch, a scheduled evaluation, or a write-time
hook. Inspect `decide` and the `REQUEST_PROBE` branches before drafting.
- [ ] Operator answers D-C6.
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
- [ ] A normal formal pseudo run leaves a new record in the registry.
- [ ] Deleting the production call site fails a named reachability test.
- [ ] `probe_runner_availability` returning `False` is reported, not silent.

**6. Failure and edge cases.** No CUDA; no dataset; probe times out; probe
returns inconclusive (must not become allow or reject — invariant 4).

**7. Verification commands and evidence.** To be written with the steps.

**8. Commit boundary.** Reachability only. No promotion logic.

---

### C-C4 — Wire promotion evaluation and recording  `BLOCKED: D-C7, D-C8`

**1. Goal.** `evaluate_promotions` and `record_promotion` have zero
production callers (§2.2), so `bucket_status` can never return
`promoted_measurement` and `AUTHORITATIVE_PROVENANCE` is unsatisfiable.

**2. Scope.** `calibration_policy.py:365-505`,
`calibration_registry.py:204`, and whatever orchestration boundary C-C3
establishes.

*Non-goals:* not changing the consistency ratio or minimum counts without
the operator setting them (D-C7, D-C8).

*Dependencies:* C-C2, C-C3.

**3. Implementation plan.** **Not written.** The thresholds are operator
policy; `CalibrationPolicy`'s identity hash covers every field, so changing
one trips `runtime_policy_identity` and invalidates every existing workspace
lock. That interaction must be settled before steps are drafted.
- [ ] Operator answers D-C7, D-C8, D-C9, D-C10, D-C11.
- [ ] Confirm the `run_invariants` interaction above by inspection.
- [ ] Draft the steps and bring them back for review.

**4. Validation plan.** Promotion reached in production; rejected promotions
reported with reasons; contended evidence handled per D-C9; expiry per
D-C10; repeated samples where promotion depends on statistical consistency.

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

### C-C5 — Applicability evaluator on the production path

**1. Goal.** `applicability_for_request` and `downgrade_for_applicability`
have zero callers. Invariant 3 requires that a bucket match is **not**
applicability.

**2. Scope.** `calibration_policy.py:583-660`, plus a focused applicability
boundary per §9.

*Non-goals:* not making a bucket match sufficient; not merging phases.

*Dependencies:* C-C2, C-C4; **D-C12..D-C19**.

**3. Implementation plan.**
- [ ] Operator answers D-C12..D-C19.
- [ ] Re-read `classify_applicability` and confirm its fail-closed
      behaviour at `:612-616` still holds under the new dimensions.
- [ ] Extract the applicability evaluator as a typed boundary with a
      reachability test (§9).
- [ ] Draft remaining steps after the decisions land.

**4. Validation plan.** The full Layer-2 matrix (§10) — every row, with an
expected outcome. Training-vs-inference substitution must fail
(D-C18/D-C19). Cross-UUID reuse must fail (D-C16). Cross-task must fail
(D-C17).

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

### C-C6 — Supply PR B's admission gate  `DECISION: D-C27`

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

*Dependencies:* C-C5; **D-C20..D-C27**.

**3. Implementation plan.**
- [ ] Operator answers D-C20..D-C27, in particular D-C27: supply
      `measured_requirements` as-is, or replace the duck-typed `getattr`
      with a typed boundary. *Recommendation: the typed boundary* — a
      duck-typed read no production code satisfies is how this gap survived
      PR B and its whole test suite.
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
contradicting calibration (D-C25); probe unavailable (D-C24); UUID missing.
None may fail open.

**7. Verification commands and evidence.** To be written with the steps.

**8. Commit boundary.** Evidence delivery only. No enforcement-default
change, no promotion logic.

---

### C-C7 — Calibration-state reporting and provenance

**1. Goal.** No production reader of the registry exists, so the campaign
cannot state its own calibration state. Today an honest report would read
*20 observations, 0 promotions, 0 authoritative buckets* (§2.3).

**2. Scope.** Reporting surface, `CalibrationSummary`
(`registry_schemas.py:205`, zero non-test references), and the admission
record's provenance fields.

*Non-goals:* no dashboard work; no new persisted schema beyond what C-C2
established.

*Dependencies:* C-C4, C-C6; **D-C28..D-C31**.

**3. Implementation plan.**
- [ ] Operator answers D-C28..D-C31.
- [ ] Inspect the existing report surfaces before choosing where this lands.
- [ ] Draft the steps.

**4. Validation plan.** Counts are correct against a known fixture registry;
rejection reasons are represented; every admission record carries the seven
fields of D-C30; the report cannot claim calibration is active when zero
authoritative buckets exist (D-C31).

**5. Acceptance criteria.**
- [ ] Against the current live registry the report reads 20 / 0 / 0 — i.e.
      it tells the truth about an uncalibrated system.
- [ ] Every admission record identifies evidence source, tier, bucket
      identity, sample count, applicability decision, final authority and
      resolved policy source.

**6. Failure and edge cases.** Empty registry; registry unreadable; mixed
schema versions (per D-C3); a bucket promoted then invalidated.

**7. Verification commands and evidence.** To be written with the steps.

**8. Commit boundary.** Reporting only.

---

### C-C8 — Documentation sync

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

## 15. Expected artifacts

- This document, updated with operator answers to §7.
- A migration note recording the D-C3 decision and what happened to the 20
  existing records.
- Layer-2 matrix results.
- One Layer-3 confirmation record with device identity.
- A calibration-state report (D-C28/D-C31) showing honest counts.
