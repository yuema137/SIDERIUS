# Design: Calibrated Runtime Estimation + Watchdog (`runtime_control`)

**Status**: rev 4 — RT1 operator review incorporated: **fully data-driven
runtime estimation for formal execution**. No hardcoded per-step overhead
constants anywhere (environment-specific: hardware, GPU, CUDA/driver/torch
versions, model implementation, batch/seg regime, optimizer, precision,
concurrency, sync behaviour — a value measured from one incident on one
machine must not enter the estimator). The static formula is demoted to a
preliminary risk screen (`source = static_uncalibrated`,
`formal_execution_eligible = false`); for formal execution the final
runtime prediction comes exclusively from an adaptive warm-up measurement
of the actual configuration: **no successful warm-up measurement → no
formal execution** (no silent static fallback). Warm-up detects steady
state adaptively (first steps are NOT representative: CUDA context init,
cuBLAS/cuDNN autotune, kernel compilation, memory-pool init, cache
warming, DataLoader startup, clock ramp) and stays lightweight (seconds).
The calibration store becomes PRIOR knowledge that lets warm-up terminate
quickly on agreement — never the final answer. Rev 3 (second operator
review): component-wise error ledger; append-only raw-observation store
with derived calibrations; RT evaluation contract. Implementation
approved per the RT series. Motivated by the
2026-07-23 V18 incident: the static estimator priced a 480,000-step
formal attempt at 2.00 ms/step (16 min train est, 61.1 min total vs
120-min budget → passed) while reality was 44.3 ms/step → 5.9 h training,
with no runtime enforcement. Root-cause audit: session records +
per-step profile (backward 44% / forward 22% / unpinned h2d 19% /
per-step `.item()` sync 10%; DataLoader 0.5%; I/O 0.7% of wall —
kernel-launch/sync-bound at tiny batch).
**Author**: session of 2026-07-23 (operator: Yue Ma)
**Baseline**: master `0291875`. V18 Wave 1 intentionally halted; workspaces
quarantined per `HALT_RECORD.md` in each.

## 1. Estimator architecture (Phase 3)

Formal-execution runtime prediction (rev 4 — fully data-driven):

```
training_estimate = setup_load_time
                  + n_steps × measured_steady_state_step_time   (warm-up, §2)
total_estimate    = training_estimate + inference_estimate + scoring_estimate

no successful warm-up measurement → no formal execution
```

The static formula survives only as an uncalibrated PRIOR
(`source = static_uncalibrated`, `formal_execution_eligible = false`),
used for three things exactly: (1) a lightweight preliminary risk screen,
(2) deciding whether performing a warm-up is itself safe, (3) explicitly
allowed non-formal paths. It contains no incident-derived constants —
per-step overhead is environment-specific and is only ever MEASURED.

- **`n_steps` resolver (exact, pure)**: mirrors the trainer's realized
  step math exactly: per-file `max(1, round(portion × len(scope_segments)))`
  subsample (`TIDMADEpochDataset.__init__`,
  `execute_tools/train_engine_sandbox.py:300-304`), then
  `floor(total_samples / batch_size) × epochs` (`drop_last=True`
  semantics). Unit-tested against an independent re-derivation of the
  loader math — the incident's count (portion 1.0) was already correct
  (480,000); the failure was pricing, not counting. *RT1 finding*: for
  partial portions the OLD resolver applied the portion as a global
  product with `ceil`, but the trainer's per-file `max(1, ·)` floor
  keeps at least one PSD per file — many-small-file scopes were
  undercounted by up to `1/portion×` (e.g. 20 files × 1 PSD at
  portion 0.1: old predicted 2 PSDs, trainer runs 20).
- **`measured_steady_state_step_time`**: from the adaptive warm-up (§2)
  of the ACTUAL configuration. It inherently captures what no
  decomposition of constants can: kernel-launch floor, h2d of a batch,
  `.item()` sync, Python loop, and the compute term, on the actual
  environment. (Rev 4 drops the earlier `fixed_step_overhead +
  compute_term` decomposition for prediction — the split survives only
  as diagnostic vocabulary in the error ledger.)
- **static prior**: the existing FLOP-proxy (`max(params × seg × bs ×
  3e-9, 2.0)` — pre-existing Phase 6.8 constants, unchanged) retained
  solely for the three prior/screen roles above; never formal-eligible.
- **`setup_load_time`**: bytes_to_read ÷ calibrated effective decode rate
  (measured 16–21 MB/s on this host; seconds-to-minutes, minor).
- **`inference_estimate`**: keep the measured `ms/psd_seg` hint pathway,
  but a missing/uncalibrated hint (novel arch) may no longer produce a
  PASS verdict on formal rounds — it forces warm-up (§3) or applies the
  uncalibrated safety factor (§2) — the incident's "UNCALIBRATED …
  best-effort" pass is abolished for formal.
- Concurrency: estimates carry a documented no-contention assumption; the
  watchdog (§4), not the estimator, owns enforcement under contention.

## 2. Warm-up calibration (Phase 4)

**Objective (rev 2): accurately predict the TOTAL runtime of the
proposed execution.** Measuring ms/step is the mechanism, not the goal;
every implementation detail below serves prediction accuracy and may be
tuned without changing the contract.

### 2a. Prediction-accuracy contract

- **Acceptance criterion**: for production attempts, the predicted total
  phase time must satisfy `|log(actual / predicted)| ≤ log(F)` for at
  least P% of attempts, with provisional targets `F = 1.5, P = 90`
  (configurable; to be revised from data — same principle as §4's
  safety factor).
- **Evaluation loop**: every completed (or watchdog-killed) attempt
  persists the **prediction-error ledger** on its record and aggregated
  per run — **component-wise, not only totals (rev 3)**:
  `{training: {predicted_s, actual_s}, inference: {predicted_s,
  actual_s}, scoring: {predicted_s, actual_s}, total: {predicted_s,
  actual_s}, estimate_source}`. Rationale: totals can mask a drifting
  component (accurate training + slowly degrading inference can still
  sum to "acceptable"); per-component history localizes exactly where
  prediction quality degrades without requiring separate estimators
  up front.
  This ledger is the feedback signal that (a) evaluates calibration
  quality continuously, (b) drives safety-factor revision, and (c)
  triggers store invalidation on drift (§6).
- **Calibration success** = a warm-up whose measured step time is stable
  (jitter within the configured bound) AND whose resulting prediction,
  once actuals exist for that key, meets the acceptance criterion.
- **Fallback (rev 4 — split by execution class)**:
  - **Formal**: NO fallback. A failed/unstable warm-up, or a key whose
    ledger shows repeated criterion violations, means the formal
    attempt does not run (`skipped_time_risk`, reason
    `warmup_unavailable`). There is no silent fall-through to an
    uncalibrated static estimate — that fall-through IS the incident's
    mechanism.
  - **Non-formal (trial/smoke, explicitly allowed paths)**: the MOST
    CONSERVATIVE available estimate (max of static prior and store
    values, elevated safety factor) — never the optimistic one.

### 2b. Mechanism (implementation choices serving §2a — tunable)

A pre-execution skill (`calibrate_step_time`) that runs the ACTUAL
proposed configuration briefly, inside the same sandbox contract as
training:

1. **Measure the real execution**: build the actual plugin model +
   optimizer + loss from the validated configs, actual batch size /
   segment size / precision, on the actual GPU, through the production
   training code path. The goal is not to benchmark an approximation
   but to measure the execution that is actually about to run.
2. Data: a small in-RAM tensor batch replicated from one real PSD segment
   (representative dtype/shape; no full dataset load).
3. **Phase 1 — untimed, adaptive steady-state detection (rev 4)**: the
   first steps are NEVER representative (CUDA context init, cuBLAS/cuDNN
   autotune, kernel compilation, memory-pool init, cache warming,
   DataLoader startup, GPU clock ramp). Run untimed until step time is
   demonstrably stable OR a maximum warm-up budget is reached — no fixed
   "N untimed steps" constant. The stability criterion is an
   implementation choice serving §2a (rolling-median stability,
   coefficient of variation, relative change over the latest window, or
   another robust convergence metric); the REQUIREMENT is that steady
   state is detected, not assumed after a fixed count.
4. **Phase 2 — timed measurement of steady-state steps only**; explicit
   `torch.cuda.synchronize()` before and after the timed region (block
   timing, so intra-step async is irrelevant). With a store prior (§6)
   available: if the measurement agrees with the prior, terminate
   quickly (verification, not re-benchmarking); if it disagrees
   significantly, keep measuring, use the measurement, and flag the
   prior for invalidation (§6b).
5. Statistic: **median** ms/step; report MAD; if max_step > 10× median
   flag jitter in the output.
6. **Safety factor**: predicted = median × n_steps × **1.5**; use **2.0**
   when any of: novel architecture, jitter flag, extrapolation outside
   the calibrated key region.
7. Abort rules: any single step > 5 s → classify configuration
   pathological → verdict FAIL (skip attempt, `skipped_time_risk`,
   reason `calibration_step_too_slow`). Warm-up OOM → existing
   `skipped_oom_risk` path. Warm-up crash → `skipped_schema_violation` /
   attempt-failure path (existing vocabulary; no new statuses needed
   here). **Lightweight contract**: expected cost a few seconds (steady
   state typically arrives within tens of steps); hard cap ≤ ~90 s worst
   case per attempt, charged before training launch — negligible against
   the hours-long execution it protects.

## 3. When warm-up runs (Phase 5)

| Condition | Action |
|---|---|
| Calibration-store hit (exact key §7) and n_steps ≤ 50k and trial round | reuse stored ms/step (source=`store`) |
| Novel plugin / unseen family fingerprint | warm-up required |
| batch_size < 4 or > 512; seg_size < 2500 or > 40000 | warm-up required |
| n_steps > 50,000 | warm-up required |
| static vs store estimates disagree > 3× | warm-up required |
| **formal round — unconditionally (rev 4)** | warm-up required. A store hit does NOT exempt formal: it becomes the PRIOR that lets the warm-up terminate quickly on agreement (§2b step 4). Formal is where hours die. |

Estimator output records (persisted on the record, planner-visible):
`estimate_source` (`static_uncalibrated`|`store`|`warmup`),
`formal_execution_eligible: bool` (true only for warm-up-backed
estimates), static prior, measured ms/step + n timed steps, predicted
train/inference/total minutes, safety factor, `calibrated: bool`.

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
  revised as the prediction-error ledger (§2b) accumulates calibration
  data — the framework must remain stable across any future change to
  the numeric value. A configurable floor prevents degenerate deadlines
  for near-zero estimates. The trial/formal-budget interaction is
  audited by the §7 tests before any default is finalized.
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

Runtime/schema — not prompts (prompt disclosure added separately as §3
estimator-output rendering):

- **Primary criterion: predicted runtime.** A plan whose calibrated
  predicted phase time exceeds the operator budget is rejected at
  pre-flight (structured `PhysicalRejection` via the existing Phase-K
  machinery, planner-visible). 100k cheap steps may pass; 80k expensive
  steps must fail — the decision is time, not count.
- **Secondary sanity checks** (demoted, rev 2): `max_steps_per_attempt`
  (provisional default 150k) catches degenerate counts even when the
  estimator claims they are cheap (defense-in-depth against estimator
  bugs); `min_formal_batch_size` (provisional default 4) encodes the
  known launch-overhead pathology directly. Both configurable.
- Operator override: explicit input field (`allow_extreme_steps=True`)
  — never a prompt instruction; recorded in run_config provenance.

## 6. Calibration store (Phase 8)

**Role (rev 4): prior knowledge, not the final answer.** The store never
replaces the warm-up on formal paths — it supplies the expected step
time that the adaptive warm-up verifies against (agreement → terminate
quickly; significant disagreement → keep measuring, use the
measurement, flag the stored value for invalidation). Pipeline:
`historical calibration → expected step time → adaptive warm-up →
measured step time → comparison → final runtime prediction`.

`core/server_configs/step_time_calibrations.json` (audited: this dir
already holds per-server configuration; `core/hardware_context` already
fingerprints the GPU — reuse its identity fields).

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
  excluded. (If the §Part-5 loop-hygiene optimization ever lands, this
  flips the flag and invalidates old entries automatically.)
- **Gradient accumulation**: no accumulation path exists in the loop;
  excluded; `n_steps` resolver would change first if it appeared.
- **torch.compile / CUDA Graphs**: not used anywhere in the trainer;
  recorded as flags, excluded from key.
- **Scoring**: CPU-parallel in-process; out of calibration-store scope
  (conservative static estimate retained).

### 6b. Lifecycle: invalidation & refresh (rev 2)

Every entry records full provenance (`gpu_name, driver, cuda, torch,
host, timestamp, runtime_flags, source_run`). An entry is INVALID and
ignored when any of:
1. gpu_name / precision / phase key mismatch (never cross-applied);
2. torch major, CUDA, or driver version differs from the entry's;
3. `runtime_flags` at lookup differ from the entry's;
4. **drift**: the prediction-error ledger (§2a) shows the key violating
   the acceptance criterion on N consecutive attempts (provisional
   N=3) → entry evicted, next attempt forces re-warm-up;
5. **age**: entries older than a configurable max age (provisional 90
   days) require refresh on next use — reused only with the elevated
   safety factor until refreshed.
Refresh = the forced warm-up writes a new entry; old entries are kept
append-only with a `superseded_by` pointer (auditability).

### 6b-bis. Raw observations, derived calibrations (rev 3)

The store is an **append-only observation log**, not a table of current
values. Each row preserves the raw evidence:
`{timestamp, gpu_name, driver, cuda, torch, host, runtime_flags,
config_key_fields, phase, warmup_ms_per_step (if any), predicted_s,
actual_s, prediction_error, accepted: bool, watchdog_involved: bool,
source_run}`. Calibrated values used by the estimator are DERIVED from
eligible rows at lookup time (`raw observations → calibration model →
runtime prediction`), never stored as the only artifact. Benefits:
calibration evolution is fully traceable, regressions and drift are
diagnosable retrospectively, and future calibration algorithms can
re-derive from history without information loss. (Ineligible rows —
§6c — remain in the log flagged `accepted=false` for drift analysis.)

### 6c. Eligibility — which runs may feed calibration (rev 2)

Calibration entries may be written ONLY from: (a) dedicated warm-up
runs, and (b) completed production attempts that finished
`success`/`failed_mode_collapse` WITHOUT watchdog intervention and with
plausible per-step timing (within jitter bounds of their own warm-up).
Explicitly excluded: watchdog-killed attempts, pathological/rejected
configurations, and the **archived pre-fix V18 Wave-1 workspaces** —
those remain debugging/reporting provenance only. Ledger rows from
excluded runs still count for DRIFT DETECTION (they are evidence of
misprediction) but never as calibration values.

## 7. Validation plan before V18 restart (Phase 9)

Unit: step-count resolver vs `TIDMADEpochDataset.__len__` (property
cases incl. drop_last edge); static-fallback pricing; warm-up on a
deterministic 1k-param model (CPU + CUDA), sync-correctness (timed block
between synchronize calls; assert monotonic clock deltas ≥ known sleep
injected into a stub model); watchdog: process-group kill leaves zero
orphans (spawn a child-of-child sleeper; assert tree dead), partial
artifact cleanup, `attempt_failure/wall_clock_timeout` record shape +
planner-memory rendering; guardrail rejection records. Pseudo
integration: tuner loop with a stub-calibration that flags pathological
→ attempt skipped, run continues. **Gate 1** (real LLM + pseudo
training) after implementation. **Gate 2** (operator-approved, real
training): (a) a normal config completes; (b) the incident config
(batch=2, seg=1250, formal 4-9) is REJECTED at calibrated pre-flight —
or, with guardrails force-disabled, killed by the watchdog — with
end-to-end wall time provably < ~15 min.

## 8. Restart strategy (Phase 10)

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
labeled campaign.

## 9. RT-series evaluation contract (rev 3)

Every RT stop-and-show answers TWO independent questions:
1. **Correctness** — does the implementation behave as designed
   (tests, negative cases, provenance shapes)?
2. **Prediction quality** — does it measurably improve runtime
   prediction versus the previous system? Evidence: predicted-vs-actual
   comparisons on representative configurations, including the archived
   incident configuration (old system: 61.1 min predicted / ~8 h
   actual; the new system's prediction for the same config is the
   benchmark to beat and report).
Final validation must demonstrate BOTH that pathological runs are
prevented AND that prediction error on normal configurations has
significantly improved.

## 10. Proposed commit breakdown (RT series — approved direction)

| Commit | Content |
|---|---|
| RT1 | Trainer-mirroring step-count resolver; static demoted to `static_uncalibrated` prior with `formal_execution_eligible=false` interface (+ tests). No new constants. |
| RT2 | `calibrate_step_time` adaptive warm-up skill (steady-state detection, store-as-prior verification) + calibration store — becomes the sole producer of formal-eligible runtime estimates (+ tests) |
| RT3 | Trigger policy + estimator-output provenance fields (+ tests) |
| RT4 | Watchdog: process-group launch, deadline kill, `wall_clock_timeout` attempt-failure, partial-artifact cleanup (+ tests) |
| RT5 | Guardrails: `max_steps_per_attempt`, `min_formal_batch_size`, override field (+ tests) |
| RT6 | Chain/CLI/docs wiring + pseudo integration + design-doc lock-step |
| — | Gate 1, then operator-approved Gate 2 (incl. pathological case) |

## 11. Implementation log

### RT1 — trainer-mirroring step resolver + static-prior demotion ✅ 2026-07-23 (rev 4)

An earlier RT1 draft introduced a provisional hardcoded
`_FIXED_STEP_OVERHEAD_MS = 15.0`; the operator review rejected it
(per-step overhead is environment-specific and must only ever be
measured) and set the rev-4 contract above. The constant was removed;
the static formula keeps its pre-existing Phase 6.8 form
(`max(flop, 2.0)`) unchanged and is demoted to a formal-ineligible
prior. RT1 as landed:

- [x] `_total_train_steps` rewritten as a trainer-mirroring resolver
  (`agent/skills/training_skill/estimator.py`): per-file
  `max(1, round(portion × n))` + `drop_last` floor, replacing the global
  `ceil(n_psd × ml × portion / bs)` product. Found and fixed a real
  undercount: many-small-file scopes were under-predicted by up to
  `1/portion×` (see §1 resolver note). Incident count (portion 1.0)
  unchanged at exactly 480,000. This is a correctness bug fix, not
  merely an estimation improvement.
- [x] Static path demoted (RT2 interface): `ms_source` renamed
  `static_formula_phase_b` → `static_uncalibrated`; breakdown gains
  `formal_execution_eligible` (`false` for static, `true` only for
  `real_dataset_warmup`), propagated through
  `evaluate_time_skill/wrapper.py`'s flat breakdown. Enforcement
  (no-warm-up → no-formal) lands in RT2/RT3; RT1 provides the field.
  No new constants introduced.
- [x] New tests
  (`tests/unit/agent/tune_ml_hyperparam_agent/test_rt1_step_resolver.py`,
  6 passed): resolver-vs-loader exact-match grid (seg × bs × portion ×
  epochs, independent re-derivation of the loader math), `max(1,·)`-floor
  case, incident step count exact, static-prior formal-ineligible,
  warm-up formal-eligible, incident measured-step-time (44.3 ms) →
  461 min ≫ 120-min budget (what mandatory warm-up catches).
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
- Prediction quality (§9) on the archived incident config
  (141,280 params, seg 1250, bs 2, 120 PSD, 480,000 steps; actual
  training ≈ 5.9 h at 44.3 ms/step): RT1 deliberately does NOT improve
  the static number — it makes the static number inadmissible for
  formal execution. Old system: 2.00 ms/step → 20.8 min → PASSED the
  120-min budget (the incident). RT1: same static prior but
  `formal_execution_eligible = false`; with the measured 44.3 ms/step a
  warm-up would supply, the same config prices at 461 min → REJECTED.
  The prediction-quality gain arrives with RT2's measurement; RT1
  closes the door on unmeasured formal admission.
