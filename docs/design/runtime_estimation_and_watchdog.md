# Design: Runtime Verification + Watchdog (`runtime_control`)

**Status**: rev 5 — the GOLDEN PLAN. Unifies the end-to-end, data-driven
formal runtime prediction plan (operator, RT2 detailed plan) with the
codebase audit and the operator's Revision-5 review feedback. Headline
decisions of rev 5:
1. **In-subprocess verification is the primary architecture** (§2.1):
   verification runs as a preamble INSIDE the sandboxed production
   subprocess — setup is measured exactly once, the materialized dataset
   continues into formal execution, and sandbox/process controls apply
   to verification.
2. **Component-wise total-runtime prediction** (§1): admission is decided
   on `setup + training + inference + scoring + orchestration`, never on
   a single phase.
3. **Prediction / Measurement / Actual are distinct concepts** (§2.3)
   and never conflated; prediction error = final prediction vs actual.
4. **Generic `RuntimePhaseVerifier` abstraction** (§2.4): one
   verification framework, phase-specific workload semantics.
5. **Observation store is the primary persistent artifact** (§6):
   append-only, component-first; calibration is a derived view.
6. **Explicit backward compatibility** (§7): legacy calibration data,
   wrapper breakdown fields, pseudo-test injection, additive record
   parsing, environment-scoped thresholds, hardware portability
   (H100 ↔ RTX 5090).

Core principle: **formal execution must be admitted using a complete,
current, measurement-backed prediction of TOTAL runtime from the actual
production environment.** No complete, valid runtime verification → no
formal execution. Static estimates and historical calibration provide
prior expectations only; they are never the final authority for formal
admission. Verification stays lightweight: short representative
measurements predicting long executions ("spend seconds to protect
against hours"), never a reproduction of the formal run.

Rev history: rev 4 — static demoted to formal-ineligible prior, adaptive
steady-state warm-up, store-as-prior, no incident-derived constants.
Rev 3 — component-wise error ledger, append-only observations, RT
evaluation contract. Rev 2 — framework-not-constants, prediction-accuracy
objective, audited calibration key, runtime-primary guardrails.

Motivated by the 2026-07-23 V18 incident: the static estimator priced a
480,000-step formal attempt at 2.00 ms/step (16 min train est, 61.1 min
total vs 120-min budget → passed) while reality was 44.3 ms/step → 5.9 h
training, with no runtime enforcement. Root-cause audit: session records
+ per-step profile (backward 44% / forward 22% / unpinned h2d 19% /
per-step `.item()` sync 10%; DataLoader 0.5%; I/O 0.7% of wall —
kernel-launch/sync-bound at tiny batch).

**Author**: session of 2026-07-23 (operator: Yue Ma)
**Baseline**: master `0291875`; RT1 landed as `788487f`. V18 Wave 1
intentionally halted; workspaces quarantined per `HALT_RECORD.md`.

## 0. Implementation progress

*This document is a living implementation document: specification AND
authoritative roadmap. Tick stages here as they land; per-commit detail
lives in §11; evidence lives in §12.*

**Tick discipline (rev 5.2)**: a stage is ticked `[x]` only after its
implementation commits exist — the sequence is design approval →
implementation commits → checkpoint → stage approval → tick. Until the
commits land, the tracker line carries an explicit interim status
(e.g. "stop-and-show approved; commits pending"). §12 log entries
distinguish the same three events: design approval, stop-and-show
review, committed implementation (with hashes).

```
Runtime-Control Implementation

[x] RT1     — step resolver + static-prior demotion (788487f)
[x] Rev 5   — golden-plan design unification (this document)
[x] RT2-A   — runtime data model + workload contracts (a93963d, a4e4a52)
[x] RT2-B   — in-subprocess setup measurement (746c592, 8646751)
[x] RT2-C   — generic adaptive phase verification (training) (d1b3c1e, 061bc27)
[x] RT2-D   — inference verification (734592b, 2ad6222)
[x] RT2-E   — scoring + orchestration accounting (0cca7bf; contribution-based policy per operator decision)
[x] RT2-F   — observation store + historical priors (9a6f0a0; built before RT2-E — no dependency on its decision)
[x] RT2-G   — formal admission wiring + pseudo integration (c5ec268)
[x] RT3     — trigger policy + provenance fields (3dba462)
[x] RT4     — runtime watchdog (60c654f)
[ ] RT5     — guardrails
[ ] RT6     — chain/CLI/docs wiring
[ ] Gate 1  — real LLM + pseudo training
[ ] Gate 2  — operator-approved real training (incl. pathological case)
```

**Per-commit checkpoint philosophy (rev 5.1)**: every commit ends with a
LIGHTWEIGHT verification checkpoint (unit tests, small integration
tests, synthetic timing sequences, tiny representative datasets,
deterministic examples) — `implement → small checkpoint → review → next
commit`, never `implement many commits → large validation`. Long-running
experiments and full formal campaigns belong exclusively to the final
Gates. Each commit in §11 documents what its checkpoint verifies, how,
and the expected outcome.

## 1. Core runtime model and exact workload resolution

### 1.1 Component-wise runtime model

The prediction is component-wise, never one opaque number:

```
T_total = T_setup + T_train + T_inference + T_scoring + T_orchestration

T_train     = N_train_steps     × measured_train_step_time
T_inference = N_inference_units × measured_inference_unit_time  (+ setup + output write)
T_scoring   = N_scoring_units   × measured_scoring_unit_time    (or defensible bound)
```

Units differ by phase and must mirror the actual production
implementation: training = optimizer steps; inference = batches /
segments / PSDs / files / output blocks (audited against
`inference_single.py`); scoring = files / predictions / score-vector
elements (audited against `score_vector`). Every prediction exposes its
decomposition (`setup_seconds, training_seconds, inference_seconds,
scoring_seconds, orchestration_seconds, total_seconds`). The total is
DERIVED from the components.

The static formula survives only as an uncalibrated PRIOR
(`source = static_uncalibrated`, `formal_execution_eligible = false`),
used for exactly: (1) a lightweight preliminary risk screen, (2)
deciding whether verification itself is safe to execute, (3) explicitly
allowed non-formal paths. It contains no incident-derived constants —
per-step overhead is environment-specific and is only ever MEASURED.

### 1.2 Exact workload resolution (before any measurement)

Before verification begins, the ACTUAL formal workload is resolved:
DataScope files; selected PSDs per file; formal/train/inference/eval
portions; batch size; segment size; epochs; `drop_last`; training
samples, batches, and optimizer steps; inference inputs and batches;
scoring units. The resolved workload is persisted in the
runtime-verification record so the prediction is independently
reproducible:

```yaml
resolved_workload:
  files: [4, 5, 6, 7, 8, 9]
  selected_psd_count: 120
  segment_size: 1250
  segments_per_psd: 8000
  train_samples: 960000
  train_batch_size: 2
  train_steps: 480000
  inference_units: ...
  scoring_units: ...
```

No phase may estimate workload with a formula that diverges from
production execution semantics.

- **Training resolver (RT1, landed)**: `_total_train_steps` mirrors the
  trainer exactly — per-file `max(1, round(portion × len(scope_segments)))`
  subsample (`execute_tools/train_engine_sandbox.py:300-304`), then
  `floor(total_samples / batch_size) × epochs` (`drop_last=True`).
  *RT1 finding*: the old global-`ceil` product undercounted
  many-small-file scopes by up to `1/portion×` (20 files × 1 PSD at
  portion 0.1: old predicted 2 PSDs, trainer runs 20). The incident's
  480,000 count was already exact.
- **Inference and scoring resolvers (RT2-A)**: equivalent resolvers are
  audited or introduced with the same exact-match-vs-production test
  pattern.
- **Task-genericity**: resolvers necessarily encode dataset semantics
  (PSDs, portion floors, `drop_last`). They stay COLOCATED with the
  production engine/dataset code under `execute_tools/`; the generic
  verification framework (§2.4) consumes resolved-workload objects and
  never duplicates task-specific formulas. Porting SIDERIUS to a new
  task means implementing new resolvers, not touching the framework.

## 2. Runtime verification (the verification system)

**Framing: this is a VERIFICATION system, not a calibration module.**
We already have a prediction (static prior, historical observations,
previous runs on this hardware); verification checks whether reality
agrees with it. Agreement → finish quickly; disagreement → continue
measuring, use the live result, update the observations, flag the prior.

### 2.1 In-subprocess verification — the chosen architecture (rev 5)

Audit finding: today's warm-up runs in the TUNER process while formal
training runs in a sandboxed subprocess. That measures a different
execution than the one that runs (different process/allocator/CUDA
state), materializes the dataset twice, perturbs the page cache that the
formal run then observes, and leaves verification outside the sandbox
memory limits. This violates "measure the execution that is actually
going to run." The chosen architecture:

```
sandboxed production subprocess
    → construct the actual dataset          (setup measured ONCE, for real)
    → initialize actual model + loss + optimizer
    → adaptive runtime verification (§2.4-§2.5)
    → component-wise total prediction
    → admit: continue directly into formal execution (no double load)
      or reject: abort with structured provenance
```

The pre-launch side retains only the cheap screening layer: static
prior + historical prior + VRAM screening + warm-up-safety screening.
The in-subprocess measured verification is the sole authority for
formal admission.

**Cost of rejection is explicit**: a rejected proposal pays real setup
(~1-2 min) plus seconds of verification — acceptable (minutes to prevent
hours), and recorded so the strategy's cost-effectiveness is analyzable:

```yaml
admission:
  decision: rejected
  stage: post_setup_runtime_verification
  setup_cost_seconds: ...
  verification_cost_seconds: ...
  avoided_predicted_runtime_seconds: ...
```

If any phase is ever forced into a separate verification subprocess, it
must NOT silently equate its setup with formal setup: measure a
representative per-file subset, extrapolate by bytes/units, record the
extrapolation method, apply conservative uncertainty, and later record
the actual formal setup so the discrepancy enters the error ledger.

### 2.2 Setup measurement (data discovery + dataset construction)

Measures all work before steady-state training: file discovery, HDF5
open, slice selection, decompression, NumPy conversion, concatenation,
dataset/index construction, DataLoader init, initial host allocation,
non-steady-state h2d setup — via the REAL production dataset path (the
in-subprocess preamble makes this the actual formal setup). Synthetic
tools (dd/cp/fio) are supplementary diagnostics only, never the
authority.

Each observation records storage/environment provenance: dataset root,
path digest, filesystem type + mount point, storage class and options
when detectable, file count, expected raw bytes, bytes read from
process counters, measured duration, effective throughput, host memory
before/after, already-in-memory flag, page-cache state, active chain
count, host CPU / GPU load. No ambiguous labels ("network_state=good") —
measure the outcome, preserve the evidence.

**Cold/warm-cache semantics are explicit**: `cold_first_access` |
`warm_page_cache` | `already_materialized` | `unknown`. A warm-cache
measurement is never presented as a cold-start prediction; if cache
state cannot be established reliably, mark `unknown`.

### 2.3 Prediction / Measurement / Actual — a CORE architectural principle

Three fundamentally different objects, distinct types in the data model
(rev 5.1: this separation is foundational, not a schema convention):

- **Prediction**: produced BEFORE execution; combines prior knowledge
  and verification evidence; used for admission decisions.
- **Measurement**: representative observations collected during runtime
  verification (e.g. `{steady_state_step_ms: 42.1, measured_steps: 18,
  stabilization_steps: 7}`); evidence used to refine the prediction;
  never the final runtime.
- **Actual**: the duration of the complete production phase after
  admission; used to evaluate prediction quality.

Flow: `historical prior → verification measurements → runtime
prediction → formal execution → actual runtime → prediction error`.
Prediction error ALWAYS compares prediction vs actual — never
measurement vs actual.

### 2.4 Generic `RuntimePhaseVerifier` abstraction

One framework, phase-specific semantics. Conceptual interface:

```
resolve_workload() → prepare() → reach_steady_state() → measure()
→ predict() → record() → finalize_actual()
```

The common framework owns: provenance; Prediction/Measurement/Actual
separation; confidence; admission eligibility; observation writing;
historical-prior comparison; error-ledger updates. Phase
implementations own: exact workload units; production execution
semantics; steady-state behavior; resource preparation; output handling.

| Phase | Unit | Stabilization | Measurement |
|---|---|---|---|
| Training | optimizer step | repeated training steps | steady-state step time |
| Inference | batch / segment / PSD / file | repeated inference units | compute + postprocessing + output cost |
| Scoring | file / prediction block | often unnecessary | representative or fully bounded |

Training and inference use the SAME verification pipeline (resolve →
prior → prepare → steady state → measure → predict → record) — the V18
investigation showed inference can independently consume hours, so a
training-only verification cannot certify total formal runtime. Future
phases (data processing, simulation, analysis, report generation…) join
the same framework without estimator redesign.

### 2.5 Training verification (Phase B)

Uses the actual plugin/model, architecture parameters, loss, optimizer,
precision, batch size, segment size, device, representative real data,
and the production forward/backward/optimizer code path — a simplified
proxy is not sufficient for formal admission.

**B1 — stabilization (adaptive)**: first steps are never representative
(CUDA context init, cuBLAS/cuDNN autotune, kernel compilation,
memory-pool growth, cache warming, DataLoader startup, GPU clock ramp).
Run until a steady-state criterion is satisfied OR a step/wall budget is
reached OR an early pathological condition is detected. The criterion is
configurable and tested (rolling-median stability implemented in RT2a;
CoV, window agreement, robust slope are acceptable alternatives).
Steady state is DETECTED, never assumed after a fixed count.

**RT2a empirical findings (H100, real registry model, locked in unit
tests)**: (a) a leading transient absorbed by the robust median (step 0
at 2307 ms vs 28 ms plateau, 82x) must be TRIMMED from the steady
region; (b) a run can start FAST (boosted clocks + cached kernels,
~8 ms/step), satisfy the stability criterion, then drift up to the true
plateau (~29 ms) — trusting the first declaration would underpredict
~3x, so the detector RE-ARMS on post-declaration drift and re-declares
at the new plateau. Consequence: early exit is only permitted after the
declaration survives phase-B2 verification or agrees with a store
prior — never on B1 stability alone.

**B2 — measurement**: timed steady-state steps only; explicit
`torch.cuda.synchronize()` around timed blocks; individual step timings
preserved; robust central estimate (median) + variability (MAD,
trimmed mean, P50/P90); stabilization/measured step counts and total
verification duration reported.

**Lightweight adaptive stopping**: stop when minimum observations AND
minimum timed duration AND timing stability are reached; hard caps on
verification wall time, steps, memory, data volume. For very slow steps
a few observations suffice — one pathologically slow step terminates
verification early and REJECTS the proposal rather than completing a
fixed sample.

**Historical prior comparison** — outcomes: `verified_match` (early
exit permitted) | `verified_drift` (keep measuring within budget, use
live result, flag prior per §6 policy) | `new_configuration` |
`insufficient_stability` | `verification_failed`. Historical data never
exempts formal execution from live verification.

### 2.6 Inference verification (Phase C)

Audit the actual inference path; define its natural unit. Measure with
the actual (initialized) model path, batch size, input shape, precision,
device, output-writing behavior, real representative data, production
inference code. Prediction = resolved units × measured steady-state
unit time + inference setup + output serialization/write time.
Separately account: model/device init, input loading, h2d, forward,
postprocessing, output materialization, file writing, flush/close — if
output writing is substantial it is not hidden inside compute time.
Early calls are excluded until steady state, as with training.

### 2.7 Scoring and orchestration (Phases D + E)

Scoring is audited, not assumed negligible: units, files read, FFT /
numerical kernels, CPU vs GPU, aggregation, serialization, subprocess
startup. Classify as `measured` | `historically_calibrated` (per-host
scoring throughput in `core/server_configs/{hostname}.py` qualifies) |
`bounded_negligible` — the last only with evidence that the
conservative upper bound is operationally insignificant. Expose compute
and I/O components where meaningful.

Orchestration overhead (subprocess creation, env init, plugin import,
serialization, checkpoint/manifest writes, teardown, inter-stage
transitions) is measured or conservatively bounded, explicit rather
than absorbed. A fixed historical orchestration estimate is acceptable
only if environment-scoped, provenance-recorded, drift-monitored, and
not hiding an expensive unknown phase.

### 2.8 Structured runtime-verification result

One structured result consumed by downstream systems (watchdog,
proposal validator, planner). Canonical shape (schema may evolve;
equivalent information must remain available):

```yaml
runtime_verification:
  status: verified
  formal_execution_eligible: true
  source: live_end_to_end_verification
  resolved_workload: {train_steps: 480000, inference_units: 120, scoring_units: 6}
  components:
    setup:         {predicted_seconds: 150,   source: measured_real_dataset_setup,  confidence: medium}
    training:      {predicted_seconds: 21264, unit_count: 480000, measured_unit_ms: 44.3,
                    source: measured_steady_state, confidence: high}
    inference:     {predicted_seconds: 7200,  source: measured_representative_inference, confidence: medium}
    scoring:       {predicted_seconds: 180,   source: measured_representative_scoring,   confidence: medium}
    orchestration: {predicted_seconds: 60,    source: historical_observation,            confidence: low}
  total: {predicted_seconds: 28854, safety_adjusted_seconds: ..., operator_budget_seconds: ..., decision: reject}
  verification: {steady_state_reached: true, stabilization_steps: ..., measured_steps: ...,
                 total_verification_seconds: ..., historical_prior_available: true, prior_agreement: drift}
  provenance: {gpu:, driver:, cuda:, torch:, dataset_root:, filesystem:, active_workloads:, timestamp:}
```

**Prediction-source vocabulary (rev 5 — widened)**: structured (not
free-form), broad enough for phase-specific evidence, extensible
without redesign: `static_uncalibrated`, `legacy_calibration_prior`,
`historical_observation_prior`, `real_dataset_setup`,
`real_training_verification`, `real_inference_verification`,
`measured_representative_scoring`, `historical_orchestration`,
`bounded_negligible`, plus a derived-total source. (RT2a's provisional
narrow `PredictionSource` Literal is widened in RT2-A before it lands.)

**Total-eligibility semantics (rev 5.2 clarification)**: eligibility of
the TOTAL is component-derived, never source-string-based. Two distinct
cases:

- A **component** prediction from any prior/derived source
  (`static_uncalibrated`, `legacy_calibration_prior`,
  `historical_observation_prior`, `historical_orchestration`,
  `bounded_negligible`, `derived_total`) can never carry
  `formal_execution_eligible=True` — schema-rejected.
- The **derived total** is a different kind of object (`TotalRecord`):
  it carries no source and no eligibility flag of its own. It is valid
  only when derived from a complete component prediction set
  (`observation_totals_from_components` raises otherwise, and
  `RuntimeObservation` rejects a total that is not the exact component
  sum). Its formal eligibility is COMPUTED from its components: the
  total is formally eligible iff every required component prediction is
  individually measurement-backed, verified, and eligible
  (`record_is_formal_verified` implements this fail-closed for
  persisted records). A total built entirely from verified components
  is therefore eligible even though it is "derived"; a total containing
  any prior-backed component is not.

Deferred-decision status:

1. **Minor-phase sources — RESOLVED at RT2-E (operator decision
   2026-07-23, contribution-based policy)**: verification strategy is
   determined by runtime CONTRIBUTION, never phase names. Live-verified
   phases carry measurement-backed predictions; evidence-backed
   historical estimates (`historical_observation_prior`,
   `historical_orchestration`, `legacy_calibration_prior`,
   `bounded_negligible`) are admissible into a formally eligible total
   while their combined share stays below the configurable
   `historical_phase_share_limit` (provisional default 0.10); exceeding
   it AUTOMATICALLY escalates those phases to live verification. The
   individual-eligibility schema invariant is unchanged — historical
   predictions are never individually eligible; their participation is
   total-level only (`core/runtime_control/total_assembly.py`).
2. **Required-phase completeness (decide at RT2-G)**: the schema layer
   is phase-extensible and does not know which phases a given run
   requires; `assemble_total` takes the required set from its caller.
   The admission wiring (RT2-G) must define the required-phase set per
   execution class and enforce §3's "incomplete component prediction is
   never sufficient" against it.

### 2.9 Confidence and uncertainty

Every component carries: estimate source, confidence, uncertainty or
safety margin, formal eligibility. Confidence derives from EVIDENCE
(live vs static; timing stability; observation count; workload
representativeness; environment match; historical prediction error;
cache-state certainty; current concurrency) — not arbitrary labels.
Component uncertainties combine conservatively; independent-Gaussian
assumptions require justification. A simple conservative aggregation is
acceptable initially, provided its logic is explicit and testable.

### 2.10 Prediction-accuracy contract (rev 2, retained)

- **Acceptance criterion**: `|log(actual / predicted)| ≤ log(F)` for at
  least P% of production attempts (provisional F=1.5, P=90;
  configurable, revised from data).
- **Error ledger**: every completed (or watchdog-killed) attempt
  persists component-wise predicted-vs-actual (setup, training,
  inference, scoring, orchestration, total) — evaluated BOTH
  component-wise and end-to-end, so training accuracy cannot hide
  inference drift. The ledger evaluates calibration quality, drives
  safety-factor revision, and triggers prior invalidation (§6).
- **Fallback, split by execution class**: **formal — NO fallback**
  (failed/unstable/incomplete verification → the attempt does not run:
  `skipped_time_risk`, structured reason). **Non-formal** — most
  conservative available estimate (max of static prior and store
  values, elevated safety factor), never the optimistic one.

### 2.11 Failure modes (fail closed for formal)

Explicitly handled, each with a structured reason (logs, planner
feedback, attempt records, later analysis): dataset unavailable; setup
timeout; HDF5/read failure; warm-up OOM (`skipped_oom_risk`); model
construction failure; no steady state; unstable timing; pathological
unit time (`skipped_time_risk`, reason `calibration_step_too_slow`);
inference/scoring verification failure; environment mismatch;
insufficient representative data; subprocess crash; store corruption
(fails safely — never silently yields a formal-eligible estimate). For
formal execution every unresolved verification failure fails closed; no
silent static substitution. Existing status vocabulary is reused; no
new statuses.

### 2.12 Verification performance budget

"Spend seconds to protect against hours." The budget is adaptive and
component-aware: normal cases complete quickly; expensive checks
terminate early once sufficient evidence exists; correctness is not
sacrificed for an arbitrary tiny fixed duration. Stop conditions
balance minimum evidence, stability, representativeness, and a hard
cap. The final report includes actual verification overhead as a
percentage of predicted formal runtime.

## 3. Admission policy

Formal admission is based on the complete, safety-adjusted TOTAL
prediction:

```
resolve exact formal workload
→ cheap static + VRAM screening (pre-launch)
→ load historical priors
→ launch sandboxed production subprocess
→ measure actual setup
→ live phase verification (training, inference; scoring measured/bounded)
→ component-wise total prediction
→ safety-adjusted total vs operator budget
→ reject (clean exit, structured provenance)  |  continue into formal execution
```

NEVER sufficient for formal admission: a training-only estimate; a
static estimate; a historical store hit without current verification;
an optimizer-step count; prompt guidance; incomplete component
prediction; missing live verification. Step-count and batch-size
guardrails (§5) remain defense-in-depth only — the primary criterion is
total predicted runtime.

**Rejection attempt-accounting (rev 5.2, operator decision)**: two
rejection classes with different budget semantics. *Static pre-flight
rejections* (schema validation, VRAM screen, static time screen)
consume essentially no execution resources and keep the current
behavior — they do NOT consume an attempt. *In-subprocess runtime-
verification rejections* have already paid for sandbox launch, real
dataset construction, model/CUDA initialization, and setup time — they
COUNT AS ONE ATTEMPT, so the planner cannot repeatedly submit
pathological proposals at near-zero search-budget cost. The tuner-side
bookkeeping wiring lands at RT2-G.

**Unified stop reporting (rev 5.2, operator decision)**: a
verification rejection and a watchdog termination produce the SAME
`RuntimeObservation` structure — identical schema, provenance,
prediction, measurement, partial actuals, cleanup, and planner
feedback; they differ only in `admission.decision` / `admission.stage`
("rejected" @ verification) vs `watchdog_status` + `final_status`
("terminated" @ the phase the watchdog fired in). RT4 must reuse the
RT2-B session/event-log machinery rather than introducing a parallel
report shape.

Non-formal paths (trial/smoke) keep the existing screening behavior:

| Condition (non-formal) | Action |
|---|---|
| Store hit (exact key §6a) and n_steps ≤ 50k and trial round | reuse stored ms/step (source=`store`) |
| Novel plugin / unseen family fingerprint | warm-up required |
| batch_size < 4 or > 512; seg_size < 2500 or > 40000 | warm-up required |
| n_steps > 50,000 | warm-up required |
| static vs store estimates disagree > 3× | warm-up required |

## 4. Runtime watchdog (Phase 6)

Wraps every training and inference subprocess (scoring is in-process
parallel workers — phase 2 of watchdog work; start with the two
subprocess phases that caused the incident).

- **Deadline framework (rev 2 — constants are NOT part of the
  protocol)**:

  ```
  deadline = min( operator_hard_budget,
                  calibrated_estimate × safety_factor )
  ```

  `safety_factor` is a configurable input field (schema-level, recorded
  in run_config provenance), NOT a hardcoded constant. It ships with a
  deliberately conservative provisional default and is expected to be
  revised as the prediction-error ledger (§2.10) accumulates calibration
  data — the framework must remain stable across any future change to
  the numeric value. A configurable floor prevents degenerate deadlines
  for near-zero estimates. The trial/formal-budget interaction is
  audited by the §8 tests before any default is finalized.
- **Component deadlines (rev 5 interface)**: RT2 provides component
  predictions and phase start/end times so the watchdog can eventually
  enforce phase-specific deadlines (training exceeding its verified
  training envelope is terminated without waiting for the full attempt
  deadline) with structured timeout provenance. RT2 provides the
  interfaces; full watchdog lands in RT4.
- Mechanism: subprocesses already run via `core/sandbox_executor`; launch
  in their own process group (`start_new_session=True`), watchdog
  `killpg` TERM → 10 s → KILL on deadline; verify no surviving pids and
  (for training/inference) that no CUDA context lingers.
- Partial outputs: the killed attempt's partial checkpoint/denoised files
  are deleted by the executor (paths are known from the attempt config),
  mirroring `--cleanup_denoised` semantics.
- **Status audit (existing vocabulary)**: `skipped_time_risk` = pre-flight
  prediction skip (no compute spent) — reusing it for a mid-run kill
  would conflate semantics. The existing `attempt_failure` record_type
  already carries `failure_stage` / `failure_type` /
  `counts_toward_attempt_budget` and feeds planner memory. **Decision:
  a watchdog kill records an `attempt_failure` with
  `failure_type="wall_clock_timeout"`, `failure_stage`= training|
  inference, plus `{elapsed_s, deadline_s, estimate_source}`** — no new
  status value; timeout is thereby distinguished from OOM
  (`skipped_oom_risk`), schema failures, collapse
  (`failed_mode_collapse`), and generic errors, and the planner sees the
  timeout with its config in memory. Workflow policy: timeout counts
  toward the attempt budget; the round continues to its next attempt
  (existing brake machinery unchanged).

## 5. Guardrails (Phase 7) — runtime estimate is PRIMARY (rev 2)

Runtime/schema — not prompts (prompt disclosure added separately as
estimator-output rendering):

- **Primary criterion: predicted runtime.** A plan whose verified
  predicted TOTAL time exceeds the operator budget is rejected
  (structured `PhysicalRejection` via the existing Phase-K machinery,
  planner-visible). 100k cheap steps may pass; 80k expensive steps must
  fail — the decision is time, not count.
- **Secondary sanity checks** (demoted, rev 2): `max_steps_per_attempt`
  (provisional default 150k) catches degenerate counts even when the
  estimator claims they are cheap (defense-in-depth against estimator
  bugs); `min_formal_batch_size` (provisional default 4) encodes the
  known launch-overhead pathology directly. Both configurable.
- Operator override: explicit input field (`allow_extreme_steps=True`)
  — never a prompt instruction; recorded in run_config provenance.
- **Environment-scoped absolute thresholds (rev 5)**: absolute limits
  (max verification wall time; max individual unit time before early
  abort — the provisional "single step > 5 s → pathological" rule; max
  setup time; initial safety factor; orchestration prior; store
  location) are NOT universal protocol constants — a legitimate large
  model on a slower device (e.g. the RTX 5090) may exceed them while
  fitting the operator budget. They live in scoped configuration
  (`core/server_configs/{hostname}.py` or an equivalent runtime-policy
  surface), are recorded in each observation, and are distinguishable
  from scientific task parameters. Defense-in-depth only; the primary
  admission criterion remains predicted total runtime vs operator
  budget.

## 6. Observation store — the primary persistent artifact (rev 5)

**Raw observations are the source of truth; calibration is a derived
view.** Pipeline: `append-only observations → eligibility filtering →
aggregation / calibration model → historical prior`. Benefits: full
provenance, reproducibility, calibration algorithms improvable without
losing history, clearer drift analysis, safe schema migration.

### 6.1 Component-first observation schema

Observations are organized around runtime components, with total
derived — a total-only ledger could hide compensating errors across
phases:

```yaml
runtime_observation:
  timestamp: ...        # + chain_id, attempt_id, phase identifiers
  hardware: ...         # gpu, driver, cuda; host
  software: ...         # torch, runtime_flags
  workload: ...         # resolved workload (§1.2)
  historical_prior: ...
  setup:         {prediction:, measurement:, actual:, error:}
  training:      {prediction:, measurement:, actual:, error:}
  inference:     {prediction:, measurement:, actual:, error:}
  scoring:       {prediction:, measurement:, actual:, error:}
  orchestration: {prediction:, measurement:, actual:, error:}
  total:         {prediction:, actual:, error:}
  verification_measurement: ...   # raw step timings, steady-state history
  admission_decision: ...         # + rejection stage, avoided runtime (§2.1)
  watchdog_status: ...
  final_status: ...
  calibration_eligible: ...
```

### 6.2 Observation lifecycle

Progressive, per attempt: **before subprocess** — proposal, resolved
workload, static + historical priors, environment identity,
runtime-policy config. **During setup/verification** — setup
measurements, stabilization history, phase measurements, updated
predictions, confidence, admission decision. **During formal
execution** — phase start/end times, watchdog state. **After
completion/termination** — actual phase runtimes, total actual,
component-wise prediction errors, final status, calibration
eligibility. The global store receives an immutable finalized record
(or immutable event sequence); partially written shared records must
never appear complete.

**RT2-B realization (rev 5.2)**: `RuntimeVerificationSession`
(`core/runtime_control/session.py`) implements this lifecycle as an
event log: the observation is created when in-subprocess setup BEGINS
and the sidecar is atomically rewritten (`tmp` + `os.replace`) at every
stage transition — `setup_started → setup_complete →
admitted | rejected → completed` — so a crash at any point leaves the
last completed stage's evidence (setup timing, environment/storage
provenance, partial state) on disk rather than nothing.

### 6.3 Concurrent writes (rev 5)

Multiple chains run per host; interleaved appends to one shared file
can corrupt evidence. Initial design: **one append-only JSONL file per
chain/process** (e.g. `runtime_observations/v18r_loss_04_09.jsonl`),
merged at read time. Equivalent-guarantee alternatives (flock'd atomic
appends, SQLite, transactional storage) acceptable. The design must
prove concurrent chains cannot corrupt calibration evidence; store
corruption fails safely and never silently produces a formal-eligible
estimate.

### 6.4 Legacy calibration compatibility (rev 5)

The existing calibration tables and warmup-ratio machinery
(`agent/skills/evaluate_time_skill/calibration.py`,
`core/server_configs/step_time_calibrations.json`) are EXTENDED, not
orphaned: legacy data remains loadable as a historical prior source
through an adapter (or lazy translation into prior objects / migration
into observations with explicit provenance), tagged
`prior_source: legacy_calibration_prior`,
`provenance_quality: historical`,
`formal_execution_eligible_without_live_verification: false`. Old files
are never silently mutated or required to be rewritten; legacy priors
never bypass live verification.

### 6a. Key audit (rev 2 — every factor justified)

Included: `gpu_name`, `torch_version_major`, `precision`,
`optimizer_type`, `model_family_fingerprint`, `log2_param_bucket`,
`seg_size_bucket`, `batch_size` (all demonstrably move per-step time),
plus `phase ∈ {training, inference}` — inference calibrates per-psd-seg
with its own table, never sharing training entries.

Evaluated and EXCLUDED, with rationale (each becomes an inclusion the
moment the production trainer starts varying it — a reserved
`runtime_flags` dict field in every entry records the state at
measurement time so future divergence is detectable):
- **DataLoader workers**: production trainer is fixed `num_workers=0`;
  not a plan variable. Recorded in `runtime_flags`, excluded from key.
- **pin_memory / non_blocking**: not used by the trainer; recorded,
  excluded. (If the loop-hygiene optimization ever lands, this flips
  the flag and invalidates old entries automatically.)
- **Gradient accumulation**: no accumulation path exists in the loop;
  excluded; the `n_steps` resolver would change first if it appeared.
- **torch.compile / CUDA Graphs**: not used anywhere in the trainer;
  recorded as flags, excluded from key.
- **Scoring**: CPU-parallel in-process; per-host throughput config
  qualifies as `historically_calibrated` (§2.7).

### 6b. Prior lifecycle: invalidation & refresh (rev 2)

Every derived prior records full provenance (`gpu_name, driver, cuda,
torch, host, timestamp, runtime_flags, source_run`). A prior is INVALID
and ignored when any of:
1. gpu_name / precision / phase key mismatch (never cross-applied);
2. torch major, CUDA, or driver version differs from the entry's;
3. `runtime_flags` at lookup differ from the entry's;
4. **drift**: the error ledger (§2.10) shows the key violating the
   acceptance criterion on N consecutive attempts (provisional N=3) →
   prior evicted, next attempt runs full verification without early
   exit;
5. **age**: entries older than a configurable max age (provisional 90
   days) require refresh on next use — reused only with the elevated
   safety factor until refreshed.
Refresh = the next verification writes new observations; superseded
derived values keep a `superseded_by` pointer (auditability). Raw
observations are NEVER deleted or overwritten.

### 6c. Calibration eligibility (rev 2 + rev 5)

Only clean, representative observations update calibration: successful,
watchdog-untouched, free of OOM/schema/runtime failure, stable
measurements, known environment provenance, representative of the
predicted phase, based on actual production execution. Explicitly
excluded: watchdog-killed attempts, pathological/rejected
configurations, and the **archived pre-fix V18 Wave-1 workspaces** —
provenance + drift evidence + incident analysis only, never calibration
values. Failed/pathological observations remain visible in the ledger
as evidence but are excluded from the normal calibration aggregate.

## 7. Compatibility and portability requirements (rev 5)

1. **Wrapper breakdown fields**: existing consumers read
   `breakdown.source` / `breakdown.gpu_name` (tuner Phase-F EMA trigger,
   `ml_hyperparameter_tune_agent.py`). RT2 EXTENDS this contract —
   component fields are additive; legacy consumers keep functioning
   until deliberately migrated. `formal_execution_eligible` stays
   fail-closed: missing eligibility metadata is never interpreted as
   eligible.
2. **Pseudo-test injection**: once formal execution requires
   verification, pseudo integration tests need a deterministic
   injection point analogous to the existing sandbox stubs — able to
   provide verified/rejected results and to simulate no-steady-state,
   setup failure, OOM, timeout, inference-dominated prediction, scoring
   failure, and unavailable priors. Production code is not weakened for
   tests; the verification interface is injectable at the correct
   boundary.
3. **Additive record parsing**: attempt records gain
   runtime-verification structures as additive-OPTIONAL fields. Legacy
   records (including the halted V18 workspaces) continue to load; old
   records are never rewritten automatically; absence of verification
   metadata is represented explicitly and never treated as verified
   (same legacy-aware pattern as `validate_stamped_invariants`).
4. **Hardware portability (H100 ↔ RTX 5090 and beyond)**: no
   absolute-time protocol constants (§5); store keys are per-GPU (§6a);
   a hardware switch yields `new_configuration` (verification runs
   without a prior — degraded convenience, not failure); verification
   OOM on smaller VRAM fails closed via existing paths; per-host
   scoped configuration provides the environment-specific values.
5. **Task portability**: resolvers colocated with production engines
   (§1.2); the generic framework (§2.4) is task-agnostic.

## 8. Validation plan before V18 restart

Unit: resolver exact-match vs production for training (RT1, landed),
inference, and scoring — per-file portion floors, drop_last, small-file
edges, multiple epochs, DataScope variations. Dataset setup: real
constructor timing wrapper, bytes/file-count provenance, setup failure,
cold/warm labels, no accidental double materialization where reuse is
supported. Steady state: deterministic synthetic sequences — slow
startup, persistent drift, high jitter, no steady state, one
pathological step, early convergence against a prior (RT2a, landed).
CUDA timing: explicit sync around timed blocks; async work not
undercounted; CPU fallback correct; mocked CUDA fails safely. Training
verification: actual plugin path, loss and optimizer, prediction from
measured steps, pathological rejection, prior agreement/disagreement.
Inference: correct unit, steady-state timing, output-writing cost,
inference-dominated rejection. Scoring: measurable path,
bounded-negligible classification, failure, scorer-dominated rejection.
Admission: total within budget; training-within/total-over; missing
inference verification; static-only; store-hit-without-verification;
incomplete provenance; formal fail-closed. Observation store:
append-only, schema validation, no silent overwrite, environment
provenance, actual-runtime completion, component error ledger,
eligibility filtering. Watchdog: process-group kill leaves zero
orphans; partial-artifact cleanup; `attempt_failure/wall_clock_timeout`
record shape + planner-memory rendering. Pseudo integration: tuner loop
with stubbed verification (verified / rejected / pathological paths).

**Gate 1** (real LLM + pseudo training) after implementation.
**Gate 2** (operator-approved, real training): (a) a normal config
completes; (b) the incident config (batch=2, seg=1250, formal 4-9) is
REJECTED at in-subprocess verification — or, with guardrails
force-disabled, killed by the watchdog — with end-to-end wall time
provably < ~15 min.

## 9. Restart strategy (Phase 10)

**FIXED operator decision (2026-07-23, not subject to re-evaluation):
four FRESH workspaces; the halted ones are archived provenance.**
Rationale: (a) the estimator/watchdog change alters which attempts run —
mixing pre-fix and post-fix iterations in one workspace makes timing,
token, and exploration-dynamics analyses bimodal, and the
run-invariants lock does not (and should not) pin estimator semantics;
(b) the 04_09 chains' iteration-1 evidence is dominated by
collapse/pathology that consumed round budgets — a clean cold start
post-fix re-derives it in hours; (c) the 10_14 iteration-1 results
remain fully quotable from the archived workspaces (completed manifests
preserved). Archive = leave in place with `HALT_RECORD.md` +
quarantine dirs (or `mv` under `SIDERIUS_DATA/_archive_v18_wave1_prefix/`
at operator preference). Scientific validity of the archived scores is
unaffected (scoring semantics unchanged); they are simply a separate,
labeled campaign. **Do not restart V18 during RT2.**

## 10. RT-series evaluation contract (rev 5 — four questions)

Every RT stop-and-show answers FOUR independent questions:
1. **Correctness** — does the implementation match production execution
   semantics (tests, negative cases, provenance shapes)?
2. **Prediction quality** — does it improve component-wise AND total
   runtime prediction versus the previous system? Evidence:
   predicted-vs-actual on representative configurations, including the
   archived incident configuration (old system: 61.1 min predicted /
   ~8 h actual — the benchmark to beat and report).
3. **Portability** — does it behave correctly across GPUs, hosts,
   storage locations, and current system conditions?
4. **Compatibility** — does it preserve existing records, tests,
   wrappers, and prior infrastructure without silently changing
   unrelated behavior?

A stage does not advance merely because tests pass — it must provide
evidence that the runtime prediction or its supporting measurement is
meaningful. The RT2 final stop-and-show additionally includes at least
three worked prediction examples (ordinary cheap formal config; the
480,000-step incident; an inference- or setup-dominated config), each
with component predictions, total, decision, verification cost,
confidence, and provenance, plus verification-overhead measurements.

## 11. Detailed commit plan (rev 5.1)

Each commit is ONE logical architectural change with a documented
lightweight checkpoint (§0). RT2-A through RT2-G may land as one PR if
reviewable; implementation follows this dependency order with one
stop-and-show per stage. If the existing architecture conflicts with a
requirement: stop, audit the conflict, and report it before redesigning
unrelated infrastructure.

### RT1 ✅ (landed `788487f`)

Trainer-mirroring step-count resolver; static demoted to
`static_uncalibrated` prior with `formal_execution_eligible=false`
interface. No new constants. Evidence in §12.

### RT2-A — complete runtime data model + workload contracts

- **Objective**: establish the FULL runtime data model that every later
  stage builds on — not only resolvers.
- **Scope**: `RuntimePhaseVerifier` abstraction (lifecycle §2.4);
  Prediction / Measurement / Actual objects (§2.3); component-first
  observation schema (§6.1); widened prediction-source vocabulary
  (§2.8); phase identifiers; exact inference + scoring workload
  resolvers; wrapper-interface compatibility (§7.1). No verification
  loop yet, no store writes.
- **Affected modules**: new `core/runtime_control/` package (phases,
  sources, prediction/measurement/actual/error records, observation
  schema, verifier ABC; RT2a's `runtime_prediction.py` and
  `steady_state.py` move here as framework components); resolvers
  colocated with production engines under `execute_tools/`
  (`workload_resolvers.py`).
- **Expected interfaces**: `RuntimePhase`; `PredictionSource`;
  `RuntimePrediction` (admission invariant schema-enforced);
  `PhaseMeasurement`; `PredictionError` (log-ratio, contract check);
  `PhaseComponentRecord {prediction, measurement, actual, error}`;
  `RuntimeObservation` (component-first, derived total);
  `RuntimePhaseVerifier` (abstract lifecycle + assembly driver);
  `resolve_inference_workload()` / `resolve_scoring_workload()`.
- **Expected tests**: schema validation matrix (P/M/A separation,
  admission invariant, derived-total consistency, source vocabulary);
  resolver exact-match vs production semantics (inference engine,
  scorer) incl. DataScope variations; verifier-lifecycle contract with
  a deterministic stub phase; legacy-record parsing (absence of
  verification metadata explicit, never "verified").
- **Dependencies**: RT1 (training resolver, eligibility field).
- **Checkpoint**: unit suite green; ruff + pyright clean; resolver
  derivations shown against production code line references; no
  behavior change to any existing path (existing suites untouched).

### RT2-B — in-subprocess setup measurement

- **Objective**: move verification into the sandboxed production
  subprocess; measure real setup exactly once (§2.1, §2.2).
- **Scope**: verification preamble in the training entry
  (`execute_tools/train_engine_sandbox.py` path); setup timing +
  storage/environment provenance capture; materialized-dataset reuse;
  clean structured rejection before formal training.
- **Affected modules**: `execute_tools/train_engine_sandbox.py`,
  `core/sandbox_executor.py` (result plumbing), `core/runtime_control/`
  (setup measurement record).
- **Expected interfaces**: subprocess emits a
  `runtime_verification` block (schema from RT2-A) on both admit and
  reject paths; rejection exit is distinguishable from crash.
- **Expected tests**: tiny-dataset subprocess round-trip (setup
  measured, provenance populated, cache-state labeled); rejection path
  exits cleanly with structured provenance; no double materialization
  (dataset constructed once — assert via instrumentation); sandbox
  memory limits apply to the preamble.
- **Dependencies**: RT2-A schemas.
- **Checkpoint**: small integration test with a tiny representative
  dataset (seconds); provenance record shown; RSS-limit behavior
  demonstrated.

### RT2-C — generic adaptive phase verification (training first)

- **Objective**: the `RuntimePhaseVerifier` driver — stabilization
  (`reach_steady_state`), representative measurement, prior comparison,
  structured prediction with confidence.
- **Scope**: framework driver + training-phase implementation inside
  the RT2-B preamble; early-exit policy (§2.5: only after phase-B2
  survival or prior agreement); pathological early reject; adaptive
  stopping with environment-scoped caps (§5).
- **Affected modules**: `core/runtime_control/` (driver), training
  preamble; `core/server_configs/` (scoped thresholds).
- **Expected interfaces**: `verify_phase(verifier) → PhaseComponentRecord`;
  prior-comparison outcomes (`verified_match | verified_drift |
  new_configuration | insufficient_stability | verification_failed`).
- **Expected tests**: synthetic timing sequences (slow startup, drift,
  jitter, no steady state, pathological step, early convergence vs
  prior); real training micro-verification on a tiny config (seconds);
  verification-overhead reporting.
- **Dependencies**: RT2-A model, RT2-B preamble, RT2a detector.
- **Checkpoint**: synthetic-sequence suite + one real micro-verification
  run with overhead percentage shown. No formal campaigns.

### RT2-D — inference verification

- **Objective**: apply the identical framework to the production
  inference path (§2.6).
- **Scope**: inference-phase `RuntimePhaseVerifier` (natural unit from
  the RT2-A resolver; setup, compute, postprocessing, output-write
  accounting; steady-state exclusion of early calls).
- **Affected modules**: inference engine preamble/instrumentation,
  `core/runtime_control/`.
- **Expected tests**: unit-time measurement on a tiny scope; output-write
  cost separated from compute; inference-dominated prediction example.
- **Dependencies**: RT2-A, RT2-C framework.
- **Checkpoint**: tiny-scope inference verification (seconds) showing
  component split + an inference-dominated worked example.

### RT2-E — scoring + orchestration accounting

- **Objective**: complete the component model (§2.7) and the
  component-wise total with conservative uncertainty aggregation
  (§2.9).
- **Scope**: scoring measurement or defensible bound
  (`measured | historically_calibrated | bounded_negligible` with
  evidence); orchestration prior (environment-scoped, provenance-
  recorded); total assembly + safety adjustment.
- **Affected modules**: `core/runtime_control/`, scoring skill audit,
  `core/server_configs/`.
- **Expected tests**: classification evidence tests; total = derived
  from components; aggregation logic explicit + tested; normal and
  scoring/setup-dominated worked examples with admission decisions.
- **Dependencies**: RT2-A…D.
- **Checkpoint**: three worked component-prediction examples (unit-level,
  deterministic inputs) incl. decisions.

### RT2-F — observation store + historical priors

- **Objective**: append-only component-first persistence (§6) and
  priors derived from observations.
- **Scope**: per-chain JSONL store, merged reads (§6.3); progressive
  observation lifecycle (§6.2); legacy calibration adapter (§6.4);
  derived prior lookup + eligibility filtering (§6c) + invalidation
  (§6b).
- **Affected modules**: `core/runtime_control/observation_store.py`;
  `agent/skills/evaluate_time_skill/calibration.py` (adapter, extended
  not orphaned).
- **Expected tests**: append-only (no silent overwrite), schema
  validation, concurrent-writer safety (multi-process append test),
  legacy-table adapter parses existing files unmodified, prior
  derivation + eligibility filtering + drift invalidation.
- **Dependencies**: RT2-A schema; RT2-C/D/E produce observations.
- **Checkpoint**: raw observation examples + derived-prior round-trip +
  concurrent-append test output.

### RT2-G — formal admission wiring + pseudo integration

- **Objective**: fail-closed formal enforcement end-to-end (§3) without
  breaking any existing test surface.
- **Scope**: tuner/workflow wiring of the admission decision; pseudo
  injection point (§7.2); additive attempt-record fields (§7.3);
  planner-facing structured failures; full component-prediction
  propagation.
- **Affected modules**:
  `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py`,
  workflow/protocol touchpoints, `tests/pseudo_data/` stubs.
- **Expected tests**: static-only formal rejection;
  prior-without-verification rejection; verified admission; verified
  over-budget rejection; legacy-record compatibility; pseudo-full-loop
  suite green with stubbed verification.
- **Dependencies**: all prior RT2 stages.
- **Checkpoint**: full unit + pseudo-integration suites green
  (`-m "not real_run"`); the five admission scenarios demonstrated.

### RT3 — trigger policy + estimator-output provenance fields

Non-formal screening policy (§3 table) + planner-visible provenance
rendering. Checkpoint: policy matrix unit tests.

### RT4 — runtime watchdog

Process-group launch, deadline kill (incl. §4 component-deadline
interface), `attempt_failure/wall_clock_timeout`, partial-artifact
cleanup. Checkpoint: orphan-free kill-tree test, record-shape tests.

### RT5 — guardrails

`max_steps_per_attempt`, `min_formal_batch_size`, operator override
field, environment-scoped threshold config (§5). Checkpoint: rejection
record unit tests, config provenance shown.

### RT6 — chain/CLI/docs wiring + design-doc lock-step

CLI flags, chain scripts, README/docs sync. Checkpoint: chain pseudo
smoke + shell-parity tests.

### Gates

**Gate 1** (real LLM + pseudo training) after RT6. **Gate 2**
(operator-approved, real training) per §8 — the ONLY stage where
large-scale validation happens.

## 12. Implementation log

### RT1 — trainer-mirroring step resolver + static-prior demotion ✅ 2026-07-23 (rev 4)

An earlier RT1 draft introduced a provisional hardcoded
`_FIXED_STEP_OVERHEAD_MS = 15.0`; the operator review rejected it
(per-step overhead is environment-specific and must only ever be
measured) and set the rev-4 contract above. The constant was removed;
the static formula keeps its pre-existing Phase 6.8 form
(`max(flop, 2.0)`) unchanged and is demoted to a formal-ineligible
prior. RT1 as landed (`788487f`):

- [x] `_total_train_steps` rewritten as a trainer-mirroring resolver
  (`agent/skills/training_skill/estimator.py`): per-file
  `max(1, round(portion × n))` + `drop_last` floor, replacing the global
  `ceil(n_psd × ml × portion / bs)` product. Found and fixed a real
  undercount: many-small-file scopes were under-predicted by up to
  `1/portion×` (see §1.2 resolver note). Incident count (portion 1.0)
  unchanged at exactly 480,000. This is a correctness bug fix, not
  merely an estimation improvement.
- [x] Static path demoted (RT2 interface): `ms_source` renamed
  `static_formula_phase_b` → `static_uncalibrated`; breakdown gains
  `formal_execution_eligible` (`false` for static, `true` only for
  `real_dataset_warmup`), propagated through
  `evaluate_time_skill/wrapper.py`'s flat breakdown. Enforcement
  (no-verification → no-formal) lands in RT2-G; RT1 provides the field.
  No new constants introduced.
- [x] New tests
  (`tests/unit/agent/tune_ml_hyperparam_agent/test_rt1_step_resolver.py`,
  6 passed): resolver-vs-loader exact-match grid (seg × bs × portion ×
  epochs, independent re-derivation of the loader math), `max(1,·)`-floor
  case, incident step count exact, static-prior formal-ineligible,
  warm-up formal-eligible, incident measured-step-time (44.3 ms) →
  461 min ≫ 120-min budget (what mandatory verification catches).
- [x] Consciously updated stale pins: source string in
  `test_estimator.py` / `test_warmup_activation.py` /
  `test_evaluate_time_skill.py` (constants tests restored verbatim —
  the Phase 6.8 pins are valid again); `test_proposer_preflight.py`
  portion-ratio test corrected (the old "exact 1/5" expectation never
  matched the trainer's `max(1,·)` floor; now bounds 0.2–0.5 with the
  mirrored-math derivation inline). Stale `6e-10` docstrings fixed
  (`estimator.py`, `evaluate_time_skill/wrapper.py`).
- Test evidence: 89 passed across the six touched suites; full targeted
  dirs (tune_ml_hyperparam_agent + training_skill + utils) green; ruff
  check + format clean; pyright 0 errors.
- Prediction quality (§10) on the archived incident config
  (141,280 params, seg 1250, bs 2, 120 PSD, 480,000 steps; actual
  training ≈ 5.9 h at 44.3 ms/step): RT1 deliberately does NOT improve
  the static number — it makes the static number inadmissible for
  formal execution. Old system: 2.00 ms/step → 20.8 min → PASSED the
  120-min budget (the incident). RT1: same static prior but
  `formal_execution_eligible = false`; with the measured 44.3 ms/step a
  verification would supply, the same config prices at 461 min →
  REJECTED. The prediction-quality gain arrives with RT2's measurement;
  RT1 closes the door on unmeasured formal admission.

### RT2a — adaptive steady-state detection + RuntimePrediction contract ✅ built 2026-07-23 (uncommitted; carries into RT2-A/RT2-C)

Built before the rev-5 restructure; carries forward as follows: the
steady-state detector becomes the RT2-C stabilization engine; the
`RuntimePrediction` schema becomes an RT2-A component leaf with its
`PredictionSource` Literal widened per §2.8 BEFORE first commit.

- [x] `agent/skills/evaluate_time_skill/steady_state.py`: pure,
  torch-free online detector (`SteadyStateDetector.observe(ms)`) +
  offline wrapper. Criterion: rolling-median stability (window=8
  medians, 4 consecutive within 10% relative spread — tunable
  `SteadyStateConfig`, no fixed "N untimed steps" constants; budget
  `max_steps` bounds detection, not extension). Post-detection:
  leading-transient trim + drift re-arm (both added in response to
  real H100 traces, below).
- [x] `agent/skills/evaluate_time_skill/runtime_prediction.py`:
  structured `RuntimePrediction` (predicted_seconds, source,
  confidence, steady_state, verification, measurement + prior
  provenance). The admission invariant is SCHEMA-ENFORCED: a
  `formal_execution_eligible=True` instance cannot be constructed
  unless the prediction is measurement-backed, verified, and
  steady-state with provenance present.
- [x] Unit tests (20 passed,
  `tests/unit/agent/tune_ml_hyperparam_agent/test_rt2a_steady_state.py`):
  ramp-then-plateau, flat-start earliest detection, monotonic ramp
  never declared, jitter tolerance both sides, budget semantics,
  online≡offline, leading-spike trim, drift re-arm/re-declare,
  admission-invariant matrix.
- Measurement evidence (H100, real wavenet 302,784 params via
  MODEL_REGISTRY, incident-shaped config seg=1250 bs=2, focal loss,
  Adam, production per-step `.item()` sync; 160 steps, 4-7 s wall):
  - Cold run: step 0 = 2307 ms (82x plateau), steps 1+ ≈ 27-28 ms →
    detector: steady median 28.13 ms, MAD 0.29 ms; naive
    mean(first 10) = 255 ms would over-predict 9.1x. The robust median
    absorbed the spike, leaving it INSIDE the region → leading-trim
    added (spike now excluded).
  - Warm run: step 0 ≈ 500 ms, steps 1-9 ≈ 8 ms (boosted clocks +
    cached kernels — FASTER than sustained), drifting up to ≈29 ms.
    Original detector declared steady at the 8 ms level (would
    underpredict ~3x) → drift re-arm added; final region median
    28.58 ms, MAD 0.12 ms at the true plateau.
  - Both failure shapes are now unit-locked with traces modeled on
    these measurements.

### RT2-A — complete runtime data model + workload contracts

- **Design approval**: rev 5 / 5.1 (PR #134 lineage), 2026-07-23.
- **Stop-and-show review**: presented and APPROVED 2026-07-23, with two
  review comments addressed pre-commit: (1) total-eligibility semantics
  clarified in §2.8 (component-derived, not source-string-based;
  verified already schema-enforced — see the rev 5.2 clarification and
  its two deferred decisions for RT2-E/RT2-G); (2) tracker tick
  discipline adopted (§0 rev 5.2) — RT2-A ticked only after its
  implementation commits exist.
- **Committed implementation**: ✅ 2026-07-23 — `e473e07` (design rev
  5/5.1/5.2), `a93963d` (core framework + steady-state detector + RT2a/
  model suites), `a4e4a52` (workload resolvers + estimator delegation).
  Final checkpoint: full unit tree 4063 passed / 1 pre-existing
  environment skip / 3 xfailed (includes the guardrail suites; one
  comment rewrapped in `steady_state.py` so the H100 provenance marker
  and literal share a line — production logic untouched); ruff check +
  format clean; pyright 0 errors.

- [x] New `core/runtime_control/` package (task-agnostic framework):
  `phases.py` (`RuntimePhase`, `RUNTIME_PHASES`); `workload.py`
  (`ResolvedPhaseWorkload` — generic phase/unit/unit_count/detail
  object the framework consumes); `records.py` (the P/M/A data model:
  widened `PredictionSource` + `MEASUREMENT_BACKED_SOURCES`,
  `RuntimePrediction` with the schema-enforced admission invariant now
  keyed on measurement-backed sources, `PhaseMeasurement`,
  `PredictionError` (log-ratio + `within_contract(F)` for §2.10),
  `PhaseComponentRecord` {workload, prediction, measurement, actual,
  error} with cross-field validation forcing error = THIS record's
  prediction vs actual, `TotalRecord`, `AdmissionRecord` (§2.1 cost
  model), `RuntimeObservation` (component-first §6.1; validator rejects
  totals not derived from components),
  `observation_totals_from_components` (raises on incomplete component
  predictions — §3 ineligible), legacy helpers
  `extract_runtime_observation` / `record_is_formal_verified`
  (fail-closed §7.3)); `verifier.py` (`RuntimePhaseVerifier` ABC with
  the §2.4 lifecycle + deterministic `run_verification()` assembly
  driver + `finalize_actual`); `steady_state.py` (RT2a detector moved
  in from `evaluate_time_skill`).
- [x] `execute_tools/workload_resolvers.py` (task-specific, colocated
  §1.2): `resolve_training_workload` (authoritative trainer mirror —
  `estimator._total_train_steps` now DELEGATES here, single resolver),
  `resolve_inference_workload` (mirrors `inference_single.py`
  sample_set mode: per-file `dim1 = n_psd × (10M // seg)`,
  `ceil(dim1/bs)` batches via `range(0, dim1, bs)`, `output_bytes` =
  2 int8 channels × n_psd × 10M for §2.6 output pricing),
  `resolve_scoring_workload` (unit = PSD segment, `num_workers`
  parallelism recorded), `resolve_formal_workloads` (train scope vs
  eval scope).
- [x] Tests (53 passed across the four RT suites):
  `tests/unit/core/test_runtime_control_model.py` — vocabulary matrix
  (every measurement-backed source formal-eligible; every prior source
  rejected), P/M/A separation (error never computed from measurement;
  foreign error rejected), symmetric contract check, derived-total
  consistency + incomplete-components rejection, admission cost-model
  round-trip, legacy-record matrix (absence explicit, malformed
  fail-closed, static-backed admission not verified), verifier
  lifecycle order + record assembly + `finalize_actual`;
  `tests/unit/execute_tools/test_workload_resolvers.py` — training
  grid exact-match vs independent trainer re-derivation + incident
  480,000 + estimator-delegation identity; inference grid exact-match
  vs `range(0, dim1, bs)` re-derivation + partial-batch ceil +
  output-byte exposure; scoring unit/worker semantics; formal-workload
  scope separation. RT2a suite (20) and RT1 suite (6) updated to the
  moved/widened model and green.
- [x] Wrapper compatibility (§7.1): no wrapper behavior change in
  RT2-A — RT1's `breakdown.source` / `formal_execution_eligible`
  fields untouched; `"real_dataset_warmup"` retained in the widened
  vocabulary as a measurement-backed source.
- Checkpoint (§0): 1437 passed / 1 pre-existing environment skip
  (`test_scoring_helpers.py:674`, Path-A reference data absent —
  verified present without RT2-A changes) across core + execute_tools
  + tune_ml_hyperparam_agent + training_skill + utils; ruff check +
  format clean; pyright 0 errors. No behavior change to any existing
  path (estimator delegation is math-identical, verified by the RT1
  suite).

### RT2-B — architectural audit 🔍 2026-07-23 (read-only; stop-and-show pending review)

Pre-implementation audit of the execution lifecycle (no code modified).
Durable findings, verified against source:

- **Lifecycle** (proposal → formal training): tuner process —
  `brain.plan` → `ExperimentPlan.with_defaults` (:1836) → overrides
  (:1841/:1846) → trial/formal mode decision (:1888-1893) →
  `TrialConfig` (:1929) → `active_params` (:2019) → VRAM preflight
  (:2062) → time preflight `evaluate_time_skill` (:2277, runs the
  CURRENT warm-up IN THE TUNER PROCESS — the §2.1 audit finding) →
  feasibility gate / formal bypass / `skipped_time_risk` reject
  (:2299-2389) → `training_skill` (:2394, parent wall-times it
  :2393-2395) → `sandbox.execute_training`
  (`core/sandbox_executor.py:528`) → `subprocess.run` (:602, RLIMIT_AS
  40 GiB :610) → `train_engine_sandbox.main` (:599) → streaming path
  `run_experiment_streaming` (:459): model→device FIRST CUDA touch
  (:508/:510) → criterion (:513) → optimizer (:516-523) → epoch loop
  (:529): per-epoch `TIDMADEpochDataset` (:537) + `DataLoader` (:544)
  → batch loop (:547) = formal training.
- **Dataset ownership**: streaming mode constructs the epoch dataset
  INSIDE the epoch loop (:537) and destroys it per epoch (:568);
  it re-reads HDF5 every epoch even under `freeze_subsample=True`.
  Construct-once → verify → reuse → formal is achievable WITHOUT
  redesign by making verification the first production steps of
  epoch 0 on the same dataset object. Multi-epoch caveat: with
  `epochs > 1` the per-epoch dataset reconstruction cost recurs and
  must enter the prediction (epoch-0 setup measurement × epochs);
  moot under the paper-spec `--max_epochs 1`.
- **Model ownership**: model/criterion/optimizer built once before the
  epoch loop (:503-523); NO LR scheduler exists anywhere in the
  trainer; CUDA context lives for the process lifetime. All naturally
  survive verification; nothing needs reconstruction on admit.
- **Timing instrumentation**: the trainer has NONE (`time` not even
  imported) — only tqdm. Inference already has per-file
  `perf_counter` timing + a sidecar
  (`inference_timing_{exp_id}.json`, `core/sandbox_executor.py:
  728-731/:807-814`) — the plumbing precedent for RT2-B.
- **Result plumbing (proposed)**: subprocess assembles the RT2-A
  `RuntimeObservation` and writes a
  `runtime_verification_{exp_id}.json` sidecar (mirror of the
  inference sidecar); `execute_training` reads it back and attaches
  it under `RUNTIME_VERIFICATION_RECORD_KEY`; the tuner stamps it
  into attempt records (success `final_record` next to the existing
  time-context block ~:3068-3139; mirrored on skip/error records).
  `StubSandbox` mirrors the new keys for pseudo-mode.
- **Rejection path (proposed)**: reject → write sidecar with
  `admission.decision="rejected"` (+ §2.1 cost fields) → standard
  cleanup (`del model/optimizer/criterion`, `empty_cache`, `gc`) →
  exit 0 WITHOUT `.pth`/`_OK_` sentinel. HAZARD identified:
  exit-0-without-sentinel is today classified as a silent training
  crash (`core/sandbox_executor.py:633-642`) — the executor must
  check the sidecar's admission decision BEFORE the sentinel check
  and return a structured rejection status instead.
- **Overhead**: admitted runs ≈ <1 s added (timing wraps + provenance
  + sidecar; verification steps ARE production steps of epoch 0);
  rejected runs pay real setup (~1-2 min at incident scale, scales
  with scope) + seconds of verification — the explicit §2.1 cost.
- **Open decisions flagged for review** (rule-6): (1) rejected-attempt
  bookkeeping — pre-flight `skipped_time_risk` today does `continue`
  without consuming a round; should an in-subprocess rejection (which
  costs real setup minutes) follow the same bookkeeping or count
  differently? (2) RT2-B scope — instrument the streaming path only
  (the formal-admission path); legacy single-file `run_experiment`
  stays untouched.
- **Audit review outcome (2026-07-23)**: architecture APPROVED with
  five refinements — verification is literally the first production
  steps of formal execution (zero reinitialization after admission);
  in-subprocess rejection CONSUMES an attempt while static pre-flight
  rejections stay free (recorded in §3); streaming-path-only scope
  confirmed; `RuntimeObservation` begins at setup as an event log
  (recorded in §6.2); rejection and watchdog termination share one
  observation structure differing only in decision/stage (recorded in
  §3, binds RT4).

### RT2-B — in-subprocess setup measurement

- **Design approval**: rev 5 §2.1/§2.2 + architectural-audit approval
  with five refinements, 2026-07-23 (entry above).
- **Stop-and-show review**: superseded by the operator autonomy grant
  (2026-07-23): proceed continuously through the RT series incl.
  commits; stop only for destructive actions, unanswerable questions,
  or Gate launches. Stop-and-show content posted as progress reports.
- **Committed implementation**: ✅ 2026-07-23 — `746c592` (core:
  provenance + session event log + observation storage field),
  `8646751` (wiring: trainer preamble + executor sidecar plumbing).
- **Checkpoint**: RT2-B suites 39 passed (session, provenance,
  streaming preamble incl. tiny-dataset admitted/rejected round-trips,
  executor plumbing); full unit tree 4102 passed / 1 pre-existing
  environment skip / 3 xfailed (run before the operator's
  targeted-tests-only policy landed; subsequent stages run targeted
  suites, full suites again only before the Gates); ruff check + format
  clean; pyright 0 errors (venv interpreter).
- **Overhead (measured at tiny scale)**: admitted-path session overhead
  is timing wraps + provenance reads + a handful of sidecar writes —
  sub-second; rejected-path cost = real setup + teardown, recorded in
  the observation's §2.1 cost fields. Representative-scale numbers land
  with RT2-C's micro-verification checkpoint.

Built:

- [x] `core/runtime_control/provenance.py` — §2.2 provenance capture:
  environment snapshot (host, platform, Python/torch/CUDA, GPU name —
  all read from the live environment, none hardcoded), storage identity
  (dataset root, file count, on-disk bytes, filesystem type via
  `/proc/mounts` longest-prefix), process counters (`/proc/self/io`
  `read_bytes`, `VmRSS`), and MEASURED cold/warm cache classification
  (storage-layer read bytes vs expected bytes; anything unmeasurable →
  explicit `"unknown"`, never fabricated).
- [x] `core/runtime_control/session.py` — `RuntimeControlPolicy`
  (Pydantic; RT2-B carries `operator_budget_seconds` only) +
  `RuntimeVerificationSession` (§6.2 event log, atomic sidecar writes,
  stage vocabulary `setup_started/setup_complete/admitted/rejected/
  completed`). Setup component: measurement-backed
  (`real_dataset_setup`, formal-eligible, prediction ≡ measurement so
  error = 0 by construction §2.2). Admission (RT2-B): reject exactly
  when measured setup ALONE exceeds the operator budget (conservative
  §3 lower bound — the total can only be larger); otherwise admitted
  with explicit "training verification pending (RT2-C)" / "record-only"
  reason and the §2.1 cost fields. `RuntimeObservation` gains the
  additive `storage` field (§2.2 provenance home).
- [x] `execute_tools/train_engine_sandbox.py` — streaming path ONLY:
  new argv `--runtime_observation_out` / `--runtime_policy_json`;
  session created at `main()` entry (setup window covers config load →
  epoch-0 dataset + DataLoader ready; process import cost is
  orchestration, RT2-E); the post-setup boundary sits INSIDE the
  epoch-0 iteration after the existing unchanged dataset/loader
  construction — admitted execution falls straight through into the
  same batch loop with the same dataset/model/optimizer/criterion/CUDA
  context (no reinitialization of any kind); rejection does the
  standard cleanup and returns `None` (no `.pth`, no `_OK_` sentinel,
  no results JSON, exit 0). Training workload recorded from the
  MATERIALIZED epoch-0 loader (`len(loader) × epochs` — production
  ground truth; resolver cross-check is RT2-C/G ledger material);
  training ACTUAL spans admission → last step (includes epoch ≥ 1
  dataset reconstructions, the audit caveat). Legacy `run_experiment`
  untouched.
- [x] `core/sandbox_executor.py` — `execute_training(runtime_policy=)`
  (validated via `RuntimeControlPolicy` BEFORE launch); stale sidecar
  removed pre-launch; sidecar read back after exit with the REJECTION
  CHECK BEFORE the silent-crash sentinel check (the audit hazard);
  rejection returns `status="rejected_time_risk"` + the observation;
  success/silent-crash/subprocess-error dicts all carry
  `runtime_verification` (partial evidence from crashed runs preserved
  — §6.2); missing/malformed sidecar degrades to `None` (exact legacy
  behavior). `StubSandbox` mirrors the signature with explicit
  `runtime_verification=None` (pseudo parity, §7.3 fail-closed shape).
- [x] Tests (39 across four suites): `test_runtime_session.py` (policy
  validation, event-log staging with schema validity at EVERY stage,
  admission matrix incl. reject-on-budget + admission-before-setup
  raise, atomic-write + never-raise contracts);
  `test_runtime_provenance.py` (explicit-degradation, cache
  classification); `test_rt2b_streaming_preamble.py` (tiny synthetic
  1-segment HDF5 + minimal CPU wavenet, seconds: admitted path with
  instrumented SINGLE dataset construction + sentinel + finalized
  observation with actuals; rejected path with clean exit, no
  model/sentinel, retained setup evidence; `runtime_session=None`
  pre-RT2-B parity; `main()` argv wiring incl. rejection skipping the
  results JSON); `test_sandbox_executor_rt2b.py` (fake-subprocess
  plumbing: clean rejection NOT misclassified as silent crash, cost
  model surfaced, observation attached on success, legacy no-sidecar
  parity, stale-sidecar removal, crash surfacing partial observation,
  malformed-sidecar degradation, policy validation/forwarding with
  invalid-policy fail-before-launch, stub parity).

### RT2-C — generic adaptive phase verification (training first) ✅ 2026-07-23

- **Design approval**: rev 5 §2.5/§2.11/§2.12 + §5; operator autonomy
  grant in force (progress reports instead of stop-and-show waits).
- **Committed implementation**: ✅ 2026-07-23 — `d1b3c1e` (adaptive
  driver + session admission generalization), `061bc27` (epoch-0 loop
  instrumentation + micro-verification).
- **Checkpoint** (targeted per the operator's test-scope policy):
  RT2-C suites 28 (synthetic-trace matrix) + 7 (session verification)
  + 4 (trainer integration) new tests; affected dirs
  (`tests/unit/core` + `tests/unit/execute_tools`) 821 passed / 1
  pre-existing skip; ruff + format clean; pyright 0 errors. Real
  micro-verification (tiny CPU wavenet, 30 steps): steady
  97.5 ms/step from 3 steady steps; verification cost 0.66 s;
  predicted 2.92 s vs actual 3.18 s → ratio 1.088, inside the §2.10
  F=1.5 contract; cache state measured `warm_page_cache`; overhead
  2.9% at toy scale with 0 wasted work (verified steps ARE the first
  production training steps).

Built:

- [x] `core/runtime_control/adaptive.py`: incremental
  `AdaptiveUnitVerification` (production loop owns execution; driver
  consumes per-unit durations) — RT2a detector with re-arm; §2.5
  stopping rule (declaration must survive `min_timed_steps` steady
  observations AND `min_timed_ms` steady measurement; slow units
  verify from few observations); pathological units (relative factor +
  §5 absolute environment-scoped threshold), never applied to warm-up
  transients; prior comparison `verified_match` (exit at minimums) /
  `verified_drift` (sticky; extends measurement ×`drift_extra_factor`)
  / `new_configuration`; failed verification → measurement evidence,
  NO prediction (§2.11). `AdaptiveVerificationConfig` = every
  cap/tolerance, reached via `RuntimeControlPolicy.verification`.
- [x] Session: `RuntimeControlPolicy` gains `safety_factor` +
  `verification`; `start_phase_verification` /
  `complete_phase_verification` (evidence recorded regardless of
  outcome); `decide_admission(stage)` generalized to the KNOWN-COST
  lower-bound rule (Σ present component predictions × safety vs
  budget; fail-closed on verification failures with a budget in
  force; record-only without); admission carries real
  `verification_cost_seconds`. Later decisions supersede earlier
  (stage recorded).
- [x] Trainer: epoch-0 loop instrumented (explicit
  `torch.cuda.synchronize` around timed steps on CUDA; zero
  instrumentation after the verdict); mid-epoch rejection with
  standard cleanup; loader-exhausted resolution via `finalize()`
  (single epoch → record-only, work already done); per-epoch dataset
  reconstruction as an EXPLICIT additive prediction term
  ((epochs−1) × measured epoch-0 construction seconds).
- **Scope note (§11 deviation, documented)**: environment-scoped
  thresholds flow through `RuntimeControlPolicy` (the §5 "equivalent
  runtime-policy surface"), not `core/server_configs/` —
  `ServerConfig` is a measured-constants registry, and per-host
  policy overrides belong to the §5 guardrail wiring (RT5).

### RT2-D — inference verification ✅ 2026-07-23

- **Committed implementation**: ✅ 2026-07-23 — `734592b` (session
  resume + phase-workload recording), `2ad6222` (inference-engine
  instrumentation + executor plumbing).
- **Checkpoint** (targeted): 12 new session-level tests (resume matrix
  + the §11 inference-dominated worked example: training 300 s
  admitted, inference 7200 s vs 3600 s budget REJECTED at
  `post_inference_verification`) + 3 in-process tiny-scope engine
  round-trips + 5 executor plumbing tests; affected dirs 834 passed /
  1 pre-existing skip; ruff + format clean; pyright 0 errors.

Built:

- [x] `session.resume_or_start` (§6.1): one observation per ATTEMPT —
  the inference subprocess CONTINUES the training subprocess's sidecar
  (components/storage/admission restored; file read BEFORE the
  constructor's initial write so it cannot be clobbered; setup window
  never restarted on resume). `record_phase_workload` generalizes
  workload recording to any phase.
- [x] `inference_single.py` trial mode: inference setup (config load,
  model construction, weight load, device transfer) measured as the
  §2.6 setup term; resolver workload recorded
  (`resolve_inference_workload`, the colocated RT2-A authority);
  per-batch steady-state verification with explicit CUDA sync (early
  calls excluded; timing stops at the verdict); output-write cost
  timed per file, extrapolated per PSD segment, priced SEPARATELY
  from compute; prediction = batches × steady batch time + setup +
  write term; phase actual + error at exit. No admission enforcement
  in the inference subprocess — mid-inference overruns are RT4
  watchdog business.
- [x] Executor: `execute_inference(runtime_policy=)`; the per-attempt
  sidecar forwarded and NEVER deleted here (it carries the training
  components); updated observation attached to success and error
  results; `StubSandbox` parity.

### RT2-F — observation store + historical priors ✅ 2026-07-23

*Sequenced before RT2-E deliberately: RT2-E owns the deferred
minor-phase-sources operator decision (§2.8), while the store has no
dependency on it.*

- **Committed implementation**: ✅ 2026-07-23 — `9a6f0a0`.
- **Checkpoint** (targeted): 26 new tests incl. a 4-process
  concurrent-append test (100/100 records visible, none torn);
  affected dirs (`core` + `execute_tools` + calibration suite) 889
  passed / 1 pre-existing skip; ruff + format clean; pyright 0 errors.

Built:

- [x] `core/runtime_control/observation_store.py`: per-writer JSONL
  append-only store (§6.3 — one file per chain, merged validated
  reads, malformed lines fail safe, no update/delete surface); §6a
  calibration key (log2 param bucket; seg_size kept EXACT — documented
  choice: operator-chosen discrete values, bucketing would alias
  meaningfully different sizes); §6c eligibility filter; realized
  unit time (actual ÷ unit_count) preferred over the verification-
  window median; §6b lookup invalidation (env mismatch never
  cross-applied; drift eviction at N consecutive §2.10 violations;
  age staleness usable only with elevated safety). `PriorPolicy`
  carries the provisional F=1.5 / N=3 / 90-day parameters.
- [x] `RuntimeObservation.calibration_context` (additive §6a field);
  trainer records it at the post-setup boundary (precision from the
  live parameter dtype, optimizer, family, param count, seg/batch,
  literal `runtime_flags` of the current loop); session
  `set_calibration_context` + resume propagation.
- [x] §6.4 legacy adapter: `calibration.to_legacy_prior_entries`
  (extended, not orphaned) — read-only view of existing per-GPU
  tables as `legacy_calibration_prior` evidence; files never mutated;
  never bypasses live verification.
- **Deferred to RT2-G**: production wiring — who appends finalized
  observations (executor post-attempt) and where verifiers consume
  `lookup_prior` (the `prior_expected_unit_ms` argument is already
  plumbed through `start_phase_verification`).

### RT2-E — scoring + orchestration accounting ✅ 2026-07-23

- **Operator decision implemented**: contribution-based policy
  (Option A strengthened) — see the §2.8 resolution note. Verification
  strategy by runtime contribution, never phase names; evidence-backed
  historical estimates admissible under the configurable
  `historical_phase_share_limit` (provisional 0.10) with AUTOMATIC
  escalation above it.
- **Committed implementation**: ✅ 2026-07-23 — `0cca7bf`.
- **Checkpoint** (targeted): 17 new tests incl. the three §11 worked
  examples — (1) normal run: 3% historical share, eligible,
  safety-adjusted 150 min within 180 min budget → admit; (2)
  scoring-dominated: 75% share → automatic escalation, ineligible
  regardless of budget; (3) incident shape: all-live complete,
  eligible, 28,854 s ≫ 7,200 s budget → reject. Affected dirs 872
  passed / 1 pre-existing skip; ruff + format clean; pyright 0 errors.

Built:

- [x] `core/runtime_control/total_assembly.py`: source-based
  classification (`live_verified | historical_estimate |
  inadmissible`); `assemble_total` (completeness vs the caller's
  required set §3, inadmissible-source rejection, share limit +
  largest-first escalation list, §2.9 conservative aggregation: exact
  sum × safety factor, min component confidence);
  `evidence_backed_prediction` (individually never eligible — RT2-A
  invariant untouched); `observation_formal_eligible` +
  `record_is_formal_verified` under the recorded policy limit
  (fail-closed fallback).
- [x] Policy: `historical_phase_share_limit` on
  `RuntimeControlPolicy`; `session.assess_total(required_phases)`
  stores the derived `TotalRecord` on the observation (§6.1 exact-sum
  guard).
- [x] Scoring (§2.7 `historically_calibrated`):
  `scoring_prediction_from_server_config` — ServerConfig's measured
  `per_psd_segment_seconds` (ligroup: 2.21 s) × resolver unit count ÷
  workers, linear-speedup assumption recorded in the evidence.
  Orchestration uses the same `evidence_backed_prediction` constructor
  with `historical_orchestration` (env-scoped, provenance-recorded);
  live orchestration actuals accrue via the store once RT2-G wires
  appends.

### RT2-G — formal admission wiring + pseudo integration ✅ 2026-07-23

- **Committed implementation**: ✅ 2026-07-23 — `c5ec268`.
- **Checkpoint** (targeted, per the operator's test-scope policy — the
  §11 full-suite requirement moves to the pre-Gate sweep): 5 hermetic
  tuner-wiring tests + 3 store-prior tests; tuner suite 637 passed;
  core + execute_tools 875 passed / 1 pre-existing skip; ruff + format
  clean; pyright 0 errors (rejection-record construction extracted to
  keep `run()` under the analyzer's complexity ceiling).

Built:

- [x] Tuner policy wiring: formal rounds enforce the operator budget
  (seconds) — the in-subprocess measured verification is the sole
  formal authority (§2.1/§3), the pre-flight time gate stays as the
  cheap screen; trial rounds run RECORD-ONLY (observations + priors
  accrue, zero behavior change). Policy carries the store root.
- [x] Rejection routing + ATTEMPT ACCOUNTING (operator decision):
  `rejected_time_risk` → `skipped_time_risk` record (§2.11 vocabulary)
  with `memory.verification_stage="in_subprocess"`, §2.1 cost-model
  discovery text, attached observation — and the attempt is CONSUMED
  (real setup was paid), unlike pre-flight skips.
- [x] §7.3 additive record field: success records carry
  `runtime_verification` (inference-side block preferred — it resumed
  the training observation; explicit `None` otherwise). Finalized and
  rejected observations appended to
  `{workspace}/runtime_observations/` (best-effort, §6.3 fail-safe).
- [x] Prior consumption: `session.lookup_phase_prior` (context + §6b
  env checks; only `valid` lookups yield priors) consumed by the
  trainer at `start_phase_verification` — §2.5 early exit on
  `verified_match`, never a verification substitute. Skill wrappers
  forward `runtime_policy`.
- **Admission scenarios (§11) evidence map**: static-only formal →
  in-subprocess verification failure fails closed
  (`test_failed_verification_fails_closed_with_budget`); prior without
  verification → priors only feed `start_phase_verification`, never
  predictions (structural + `test_prior_enables_verified_match_early_
  exit`); verified admission + verified over-budget → RT2-C session
  tests + worked example 3; legacy records →
  `TestRecordVerifiedUnderContributionPolicy` + RT2-A §7.3 matrix;
  tuner-level routing → the RT2-G harness suite.

### RT3 — trigger policy + estimator-output provenance ✅ 2026-07-23

- **Committed implementation**: ✅ 2026-07-23 — `3dba462`.
- **Checkpoint** (targeted): 15 new tests (full §3 policy matrix incl.
  boundary values and the exact 3.0x ratio; wrapper store-reuse /
  fall-through wiring pinned against the real static prior); tuner dir
  652 passed; ruff + format clean; pyright 0 errors.

Built:

- [x] `evaluate_time_skill/trigger_policy.py`: the §3 non-formal table
  as a pure decision function (valid exact-§6a-key store hit + steps ≤
  50k + batch ∈ [4,512] + seg ∈ [2500,40000] + static-store agreement
  ≤ 3x → reuse; every violated row an accumulated reason; provisional
  thresholds overridable). Formal rounds never consult it.
- [x] Wrapper wiring: store-reuse decision before warm-up; reuse skips
  the warm-up and stamps `source="store"` +
  `formal_execution_eligible=False` (a historical prior is never
  live-verified); store problems degrade to warm-up (the policy can
  only skip work, never fabricate). Planner-visible breakdown
  provenance: `store_reuse` / `store_lookup_status` / `store_key` /
  `store_policy_reasons`; success records surface
  `memory.training_ms_source` + `time_store_reuse`.
- [x] Tuner passes `allow_store_reuse=plan.is_trial` + the store root
  to the time gate.

### RT4 — runtime watchdog ✅ 2026-07-23

- **Committed implementation**: ✅ 2026-07-23 — `60c654f`.
- **Checkpoint** (targeted): 13 new tests — orphan-free kill-tree
  (children of children die; TERM-trapping child escalated to KILL
  with zero survivors), §4 deadline-formula matrix incl. MID-FLIGHT
  tightening from a real live sidecar and the configurable floor,
  executor kill handling (partial-artifact cleanup, provenance
  triplet, disabled → plain-run parity), tuner
  `attempt_failure/wall_clock_timeout` record shape + store append.
  Affected suites 896 passed / 1 pre-existing skip; ruff + format
  clean; pyright 0 errors. Rejection/watchdog unified reporting (§3
  rev 5.2) holds: both paths carry the same `RuntimeObservation`.
- **Realization notes**: the §4 component-deadline interface is
  realized by reading the attempt's LIVE observation sidecar (RT2
  event log) from the parent — the deadline tightens the moment the
  in-subprocess verification lands predictions, without any new
  channel. `WatchdogConfig` (enabled/grace/poll/floor) lives on
  `RuntimeControlPolicy` — disabled by default, so RT4 is zero
  behavior change until the chain enables it (RT6/Gate 2). Found and
  fixed en route: the attempt-failure path persisted `model_dump()`,
  silently dropping extra keys — validation remains the gate, the raw
  dict persists (matches every other record path). Scoring-phase
  watchdog remains §4 "phase 2" (in-process workers — out of RT4
  scope by design).
