# Design: Calibrated Runtime Estimation + Watchdog (`runtime_control`)

**Status**: rev 2 — operator review of 2026-07-23 incorporated (framework-not-constants watchdog, prediction-accuracy objective + error ledger, audited calibration key, runtime-primary guardrails, store lifecycle, calibration eligibility, fixed fresh-restart decision). Approved direction; implementation may begin per the RT series. Motivated by the
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

Two-layer estimate, replacing the pure-FLOP formula:

```
training_estimate = setup_load_time
                  + n_steps × ( fixed_step_overhead + compute_term )
total_estimate    = training_estimate + inference_estimate + scoring_estimate
```

- **`n_steps` resolver (exact, pure)**: `floor(n_PSD × (10M / seg_size)
  × per_epoch_fraction / batch_size) × epochs`, computed from the SAME
  resolved sample-set math the trainer uses (`drop_last=True`
  semantics). Unit-tested against `TIDMADEpochDataset.__len__` — this
  quantity was already correct in the incident (the estimator printed
  480,000); the failure was pricing, not counting.
- **`fixed_step_overhead`**: per-(GPU, precision, torch-version) constant
  measured by warm-up/calibration (§2), never hardcoded from one
  incident. Covers kernel-launch floor, h2d of a batch, `.item()` sync,
  Python loop.
- **`compute_term`**: the existing FLOP-proxy (`params × seg × bs ×
  k_gpu`) retained for the large-batch regime where it dominates.
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
  persists `{predicted_s, actual_s, estimate_source}` — the
  **prediction-error ledger** — on its record and aggregated per run.
  This ledger is the feedback signal that (a) evaluates calibration
  quality continuously, (b) drives safety-factor revision, and (c)
  triggers store invalidation on drift (§6).
- **Calibration success** = a warm-up whose measured step time is stable
  (jitter within the configured bound) AND whose resulting prediction,
  once actuals exist for that key, meets the acceptance criterion.
- **Fallback**: if warm-up fails, is unstable, or its key's ledger shows
  repeated criterion violations, the estimator falls back to the MOST
  CONSERVATIVE available estimate (max of static and store values, with
  the elevated safety factor) — never to the optimistic one.

### 2b. Mechanism (implementation choices serving §2a — tunable)

A pre-execution skill (`calibrate_step_time`) that runs the ACTUAL
proposed configuration briefly, inside the same sandbox contract as
training:

1. Build the actual plugin model + optimizer + loss from the validated
   configs, on the actual device, production precision/path.
2. Data: a small in-RAM tensor batch replicated from one real PSD segment
   (representative dtype/shape; no full dataset load).
3. **Untimed warm-up steps** (provisional default 20 — cudnn autotune,
   allocator, JIT settle); first-step numbers are never used.
4. **Timed steps: adaptive** (provisional: until ≥ 50 timed steps AND
   ≥ 1 s of timed wall, hard cap 60 s total) — all counts tunable in
   service of the §2a criterion; explicit
   `torch.cuda.synchronize()` before and after the timed region (and the
   region is timed as a block, so intra-step async is irrelevant).
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
   here). Calibration cost budget: ≤ ~90 s worst case per attempt,
   charged before training launch.

## 3. When warm-up runs (Phase 5)

| Condition | Action |
|---|---|
| Calibration-store hit (exact key §7) and n_steps ≤ 50k and trial round | reuse stored ms/step (source=`store`) |
| Novel plugin / unseen family fingerprint | warm-up required |
| batch_size < 4 or > 512; seg_size < 2500 or > 40000 | warm-up required |
| n_steps > 50,000 | warm-up required |
| static vs store estimates disagree > 3× | warm-up required |
| formal round without exact store hit | warm-up required (formal is where hours die) |

Estimator output records (persisted on the record, planner-visible):
`estimate_source` (static|store|warmup), static est, measured ms/step +
n timed steps, predicted train/inference/total minutes, safety factor,
`calibrated: bool`.

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

## 9. Proposed commit breakdown (RT series — pending approval)

| Commit | Content |
|---|---|
| RT1 | Step-count resolver + fixed-overhead static term (+ tests) |
| RT2 | `calibrate_step_time` warm-up skill + calibration store (+ tests) |
| RT3 | Trigger policy + estimator-output provenance fields (+ tests) |
| RT4 | Watchdog: process-group launch, deadline kill, `wall_clock_timeout` attempt-failure, partial-artifact cleanup (+ tests) |
| RT5 | Guardrails: `max_steps_per_attempt`, `min_formal_batch_size`, override field (+ tests) |
| RT6 | Chain/CLI/docs wiring + pseudo integration + design-doc lock-step |
| — | Gate 1, then operator-approved Gate 2 (incl. pathological case) |
