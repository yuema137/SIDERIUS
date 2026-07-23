# Design: Calibrated Runtime Estimation + Watchdog (`runtime_control`)

**Status**: Design for approval — NOT implemented. Motivated by the
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

A pre-execution skill (`calibrate_step_time`) that runs the ACTUAL
proposed configuration briefly, inside the same sandbox contract as
training:

1. Build the actual plugin model + optimizer + loss from the validated
   configs, on the actual device, production precision/path.
2. Data: a small in-RAM tensor batch replicated from one real PSD segment
   (representative dtype/shape; no full dataset load).
3. **20 untimed warm-up steps** (cudnn autotune, allocator, JIT settle) —
   first-step numbers are never used.
4. **Timed steps: adaptive** — keep stepping until ≥ 50 timed steps AND
   ≥ 1 s of timed wall, hard cap 60 s total; explicit
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

- **Deadline** = `min(operator_phase_budget × 2.0, predicted_phase_time ×
  3.0)`, floor 5 min. Rationale: the operator budget stays the contract
  (×2 slack absorbs estimator noise + contention), the calibrated
  estimate bounds pathological cases tighter when it is the smaller
  term. The exact constants are operator-tunable input fields; this
  formula ships as default only after the trial/formal-budget
  interaction tests in §6 pass.
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

## 5. Guardrails against pathological step counts (Phase 7)

Runtime/schema — not prompts (prompt disclosure added separately as §3
estimator-output rendering):

- `max_steps_per_attempt` on `HyperparamTuningInput` (default 150,000 —
  ≈1.8 h at the worst observed 44 ms/step): resolved-step-count above it
  → plan rejected pre-training with a structured `PhysicalRejection`
  (existing Phase-K machinery — reuse, don't invent), planner-visible.
- `min_formal_batch_size` (default 4) enforced at the formal plan
  boundary the same way.
- Operator override: explicit input field (`allow_extreme_steps=True`)
  — never a prompt instruction; recorded in run_config provenance.

## 6. Calibration store (Phase 8)

`core/server_configs/step_time_calibrations.json` (audited: this dir
already holds per-server configuration; `core/hardware_context` already
fingerprints the GPU — reuse its identity fields). Entry key:
`(gpu_name, torch_version_major, precision, optimizer_type,
model_family_fingerprint, log2_param_bucket, seg_size_bucket,
batch_size)`; value: median ms/step, MAD, n_steps_measured, timestamp,
host, driver. Lookup requires exact gpu_name + torch major match —
never silently cross-hardware. Entries are appended with provenance;
staleness: entries older than the recorded torch/driver combo are
ignored. Warm-ups write back automatically so repeated configurations
skip calibration.

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

**Recommendation: four FRESH workspaces; archive the halted ones.**
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
