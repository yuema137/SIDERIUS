# M8 — Complete Gate Coverage and Output-Diversity Metrics — Execution Plan

- **Status**: **implementation landed (§3.1-§3.5); pending user review + merge**
- **Scope**: **generic** (framework: coverage + schema extension + new blocking check) + **task-specific** (thresholds calibrated to TIDMAD)
- **Owner**: TBD
- **Created**: 2026-07-16
- **Last Updated**: 2026-07-16 (implementation session)
- **Parent design**: [`docs/design/collapse_detection_framework_generic.md`](./collapse_detection_framework_generic.md), [`docs/design/tidmad_collapse_advice_and_forensics.md`](./tidmad_collapse_advice_and_forensics.md)
- **Tracks**: issue #118 (see Task 7), [`v17_priorities.md`](./v17_priorities.md) MUST-fix **M8**
- **Supersedes**: **M1** (file-vector byte-identity dedup, `#108`, DROPPED) and **M4** (phantom-score-table lookup, `#109`, DROPPED)

## 1. Purpose

M8 delivers **complete gate coverage** (every round is gated, no exceptions) and adds **output-diversity blocking + recording checks** as the primary collapse defense for V17. It replaces the drift-sensitive numeric-matching approach of M1/M4 with mechanism-level detection.

### 1.1 Empirical motivation

Two experiments on 2026-07-16 established the empirical basis for this replacement:

1. **6.3556-mechanism investigation** (`scripts/investigate_6_3556_mechanism.py`, log `/tmp/6_3556_investigation.log`). Demonstrated that the existing `noise <= 1e-10` guard in `get_snr` catches only the strict-constant phantom family (rate=0.0). Any output with ≥ 0.01 % non-constant samples escapes the guard while still being fully collapsed by any other measure.
2. **Pearson feasibility experiment** (`scripts/investigate_pearson_feasibility.py`, log `/tmp/pearson_feasibility.log`). Compared five cases against 20 TIDMAD validation files:
   - Real learning (FCNet paper reproduction, files 10-14): `unique_int8` = 127-128, `output_std` = 7.35 mV
   - Agent tuning-best (round 7, `agent_012`, wavenet, HG passed by accident): `unique_int8` = 2, `output_std` = 0.008 mV
   - Paper-spec baseline (collapsed): `unique_int8` = 9-15, `output_std` = 0.08-0.19 mV
   - Synthetic collapse K=0/K=-1 rate=0.001: `unique_int8` = 5, `output_std` = 0.014 mV

   **Separation ratio**: FCNet real-learning is 10× to 60× above the worst collapse case on `unique_int8`, and 40× to 1000× above on `output_std`. Both metrics are file-independent — no "files 0-3 special case" required.

3. **Root cause of the agent_012 escape** (diagnostic investigation, 2026-07-16): the framework was intact; `output_diversity` check with threshold 50 would have caught agent_012's `unique_int8=2`. The gate was **not configured to fire at round 7**. `configs/health_checks.yaml` had gates only at `after_round: 1, 3, 5, 10`; rounds 2, 4, 6, 7, 8, 9 were completely ungated.

### 1.2 Why M8 replaces M1 and M4

- **M1 (file-vector dedup)** defends by matching **specific byte-identical hashes** across rounds. If a phantom shifts by one LSB in one segment, its hash changes and the defense fails. It also requires two rounds to accumulate before the first defense fires.
- **M4 (phantom-score-table lookup)** defends by matching **specific numeric scalar values** (5.5763, 6.3556, etc.). Any new phantom that produces a novel scalar slips through. Table maintenance is manual.
- **M8** defends by measuring the **mechanism** — the diversity and amplitude of the denoised output distribution — which every collapse variant fails by orders of magnitude. Coverage is complete on the very first round.

## 2. Preconditions

- [ ] PR #114 merged (three design docs `active`) — **DONE** (`e1244ea`)
- [ ] `execute_tools/health_checks/` package on master (PR #101) — **DONE** (`a595fcc`)
- [ ] Framework runner supports multi-gate composition per round — **VERIFIED** (2026-07-16 investigation): `get_gates_for_position` returns a list, `evaluate_gate` runs each, `resolve_action` picks max severity; recording gates (`on_pass=continue`, `on_fail=continue`) never override blocking gates because `CONTINUE=0` loses every max-severity comparison.
- [ ] Understand the `_gate_results_to_score_meta` behaviour (`nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:511`): a `passed=False` check flags `is_degenerate=True` even when the resolved action is `CONTINUE`. **All recording-only checks in M8 MUST return `passed=True` on numeric completion** and use `HealthCheckResult.metrics` to carry the measurement — never fail to indicate "value below some soft threshold".
- [ ] Baseline test count captured before starting M8 work (for Gate G4 comparison):
  ```bash
  python -m pytest tests/unit/execute_tools/health_checks/ tests/unit/agent/tune_ml_hyperparam_agent/ --collect-only -q 2>&1 | tail -3
  ```

## 3. Execution checklist

### 3.1 Fix diagnostic-summary semantics (P0 — deferred to follow-up PR)

**Status: NOT applied on this branch.** `scripts/build_diagnostic_summary.py` lives on branch `feat/parallel-session-fixes-and-improvements` (PR #117) and is not yet on master. The three-state fix will land as a follow-up commit on PR #117, or as a separate follow-up PR once #117 merges.

- [ ] Update `scripts/build_diagnostic_summary.py`: change the binary `failed if failure_reason else passed` inference to three-state `passed / failed / not_run`. The `not_run` case is `no gate was registered for this round` — determinable via `execute_tools.health_checks.runner.get_gates_for_position(round_index)`.
- [ ] Unit test: fabricate a round record with `failure_reason=None` and no registered gate → assert `healthgate_result == "not_run"`.
- [ ] Unit test: fabricate a round record with `failure_reason=None` and at least one registered gate → assert `healthgate_result == "passed"`.
- [ ] Unit test: `failure_reason="..."` → `"failed"`.

### 3.2 Schema extension for coverage — `after_round: every` + Caveat A semantic fix (P0)

- [x] Extend `execute_tools/health_checks/config.py` `GateConfig.after_round` to `int | Literal["every"] | list[int]` with a `field_validator` and a `matches_round(round_index)` helper.
- [x] Extend `execute_tools/health_checks/runner.py` `get_gates_for_position` to delegate to `GateConfig.matches_round`.
- [x] Preserve strict-int backwards compatibility for existing configs (verified: `test_int_gate_unchanged_backwards_compat` in `tests/unit/execute_tools/health_checks/test_after_round_schema.py`).
- [x] Add `BLOCKING_ACTIONS: frozenset[GateAction]` to `execute_tools/health_checks/schemas.py`.
- [x] Apply Caveat A semantic fix in `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py::_gate_results_to_score_meta`: `is_degenerate` reflects only failed gates whose `action` is in `BLOCKING_ACTIONS`; `failure_reason` still concatenates ALL failed gates for observability.
- [x] Unit tests (`tests/unit/execute_tools/health_checks/test_after_round_schema.py`):
  - `after_round: every` matches rounds 1, 5, 10, 100 ✓
  - `after_round: 5` still matches only round 5 (regression guard) ✓
  - `after_round: 0` raises validation ✓
  - `after_round: "sometimes"` raises Pydantic validation ✓
  - `after_round: [3, 7, 11]` matches only listed rounds ✓
- [x] Semantic-fix tests (`tests/unit/agent/tune_ml_hyperparam_agent/test_gate_integration.py::TestGateResultsToScoreMeta`):
  - Recording gate (action=CONTINUE) that failed does NOT set `is_degenerate` ✓
  - Blocking failure + recording failure → `is_degenerate=True`, reason concatenates both ✓
  - Recording failure with empty reason → clean pass-through (no ghost reason) ✓

### 3.3 Implement `output_std` blocking check (P0)

- [x] Created `execute_tools/health_checks/output_std.py` implementing `OutputStdCheck` — mirrors `OutputDiversityCheck` structure; default threshold `min_std_mv: 1.0`.
- [x] Registered in `execute_tools/health_checks/__init__.py`.
- [x] Unit tests (`tests/unit/execute_tools/health_checks/test_output_std.py`, 6 cases): FCNet-like passes; collapse-like fails; boundary fails; missing path → not applicable; missing file → OSError surfaced; custom threshold via config.

### 3.4 Implement three recording-only checks (P1 — unblocks Gate G3)

- [x] Decision A (target_path_fn context extension): **YES** — added `HealthCheckContext.target_path_fn` and `get_target_path()`. Test at `tests/unit/execute_tools/health_checks/test_context_target_path.py`.
- [x] Decision B (metrics schema): **JSON strings** — checks serialise per-file dicts into a `*_json` metric entry. Schema unchanged.
- [x] Decision C (peek helper): **YES** — added `peek_int8_at_channel(path, channel, peek_samples)`; existing `peek_int8_at_path` is now a thin wrapper. Tests at `tests/unit/execute_tools/health_checks/test_peek.py::TestPeekInt8AtChannel` (5 cases).
- [x] ~~Created `execute_tools/health_checks/pearson_correlation.py`~~ — **REPLACED 2026-07-16** by `pearson_dispersion.py` per full-file scan findings ([`reports/health_metrics_scan.md`](../../reports/health_metrics_scan.md) §6.3, [`paper_and_collapse_reference_baselines.md`](./paper_and_collapse_reference_baselines.md) §6.3). Per-file pearson is noise-limited on files 0-9; per-file value is uninformative. `pearson_dispersion` = stdev(per-file pearsons) provides a 24× discrimination between real learning and paper-spec collapse, exposed as a single scalar.
- [x] Created `execute_tools/health_checks/spectral_peak_ratio.py`. Imports `find_peak` from `execute_tools/scoring_utils.py`; same peak-finder as production scoring.
- [x] Created `execute_tools/health_checks/per_file_output_std.py`. Per-file std distribution.
- [x] Registered all three in `execute_tools/health_checks/__init__.py`.
- [x] Unit tests (16 cases across the 3 checks): happy path, all-I/O failure, partial I/O, `passed=True` on numeric completion, `not applicable` fallbacks.
- [x] Wired `target_path_fn=lambda i: os.path.join(TIDMAD_DATA_DIR, f"abra_validation_{i:04d}.h5")` at the tuner boundary in `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` (line ~2270).

### 3.5 Update `configs/health_checks.yaml` (P0 — after 3.2 and 3.3 land)

- [x] Applied the drafted YAML: 6 gates, all `after_round: every`. 3 blocking (`output_diversity_blocking` threshold **25** (revised from 30 per empirical scan — see Appendix A), `output_std_blocking` threshold 1.0 mV, `amplitude_collapse_blocking` threshold 0.95) + 3 recording (`pearson_dispersion_recording` (replaces per-file `pearson_correlation_recording` per empirical scan), `spectral_peak_ratio_recording`, `per_file_output_std_recording`).
- [x] Updated `test_default_path_loads_shipped_config` and `test_shipped_config_all_rounds` to assert the new YAML shape.
- [x] Validation Gate G1 real-run reproduction landed at `tests/integration/health_checks/test_gate_coverage_round_7.py` — 3 tests pass; agent_012 fingerprint invalidates at round 7 (fixes the escape).

**Peek strategy superseded by M9** — the M8 checks used single-file `min(denoised_paths)` peek. Post-M9 the three blocking checks use multi-file peek at `[3, 10, 17]` with `any_pass` aggregation. See [`m9_multi_file_peek_execution_plan.md`](./m9_multi_file_peek_execution_plan.md). Backward compat: empty `peek_file_indices` falls back to single-file peek, so tests / stubs from the M8 era keep working.

### 3.6 Framework-level sanity check (P1 — may defer to post-V17)

- [ ] At tuner startup, warn if any round in `[1, max_rounds]` has no blocking gate registered. Prevents the agent_012-class regression if a future YAML edit forgets a round.
- [ ] Not strictly required for V17 given the `after_round: every` coverage from §3.2 + §3.5.

## 4. Validation gates

### Gate G1 — After §3.1 + §3.2 + §3.5 (config + summary fix)

Reproduce the agent_012 case (or synthesise: build a denoised HDF5 with 99.99 % constant int8 = -65). Assert against the resulting record:

- [ ] `gate_action == "invalidate_round"`
- [ ] `denoising_score` is not counted toward `best_valid_result`
- [ ] `failure_reason` cites `output_diversity` (or `output_std`) and quotes the actual value
- [ ] `diagnostic_summary.json`'s `healthgate_result` is `"failed"` — not `"passed"` and not `"not_run"`

**Anti-hallucination**: quote both `failure_reason` and `healthgate_result` verbatim from the JSON.

### Gate G2 — After §3.3 (`output_std` check landed)

Point the check at the FCNet paper-reproduction files at `/home/klz/Data/SIDEREIS_DATA/tidmad_reproduction/fcnet/official_10_15/inference/` for files 10-14. Assert:

- [ ] All 5 files pass `output_std >= 1.0 mV` (measured 7.35 mV; wide margin)
- [ ] No false positive on genuine real-learning output

### Gate G3 — After §3.4 (recording checks landed)

Run one tuner round end-to-end with the new YAML. Assert:

- [ ] Every round record contains `check_results` entries for `pearson_dispersion`, `spectral_peak_ratio`, `per_file_output_std`, each with `passed=True` and non-empty metrics
- [ ] `gate_action` is unchanged by recording-check outcomes when blocking checks pass
- [ ] JSON-serialised per-file dicts round-trip cleanly through the record

### Gate G4 — Full regression

```bash
python -m pytest tests/unit/execute_tools/health_checks/ tests/unit/agent/tune_ml_hyperparam_agent/ -v
```

Expected: all pass. Diff against pre-M8 baseline count = `+N passed` where `N` matches the number of new tests added.

### Gate G5 — Real-run validation

Re-run the diagnostic wavenet chain with the new YAML. Assert:

- [ ] Any round producing `unique_int8 ≤ 25` OR `output_std < 1.0 mV` is invalidated with a specific failure_reason
- [ ] Recording gates populate per-file metrics in every round's record
- [ ] `best_valid_result` (when set) has `unique_int8 > 25` AND `output_std >= 1.0 mV` — i.e. the promotion criterion inherits the collapse defense

**Anti-hallucination**: quote verbatim the `failure_reason` string, one full recording-gate metric dump, and the final accepted `denoising_score` from at least one round.

## 5. Definition of Done

- [ ] All checklist items in §3.1-3.5 marked complete (§3.6 optional / may defer)
- [ ] All 5 validation gates pass with recorded evidence
- [ ] PR opened, CI green, merged to master
- [ ] Issue **#118** closed with reference to the merge commit SHA
- [ ] Issues **#108** and **#109** closed with a link to this plan and to the merge PR
- [ ] [`docs/design/tidmad_collapse_advice_and_forensics.md`](./tidmad_collapse_advice_and_forensics.md) updated with new threshold rationale and empirical FCNet vs collapse separation
- [ ] [`docs/design/v17_priorities.md`](./v17_priorities.md) updated: M1 → DROPPED, M4 → DROPPED, M8 → COMPLETE
- [ ] [`docs/README.md`](../README.md) index rows updated

## 6. Open questions / risks

- **Q1 (context extension)**: `HealthCheckContext.target_path_fn` — decision needed before §3.4 body implementation. Recommendation: add it (parallel to `denoised_filename_fn`) so the pearson check does not couple to `TIDMAD_DATA_DIR` at import time.
- **Q2 (metrics schema)**: nested dicts vs JSON-serialised strings inside `HealthCheckResult.metrics`. Recommendation: JSON-serialise; keeps existing schema stable, downstream consumers can `json.loads` on demand.
- **Q3 (peak-finder import boundary)**: `find_peak` is defined in `execute_tools/scoring_utils.py`. Importing a scoring-module helper into a health-check module crosses a module boundary. Options: (a) import as-is (fine for a pure helper), (b) copy the 3-line function into `_peek.py`. Recommendation: (a) — the function is stable and shared use is intentional.
- **Q4 (peek memory budget)**: pearson uses 1M-sample peek per file × 20 files × 2 channels = ~40 MB. Fine on any modern node; document the ceiling if `peek_samples` is user-configurable.
- **Q5 (interaction with `_merge_score_validity_failure`)**: The existing tuner-side helper already forces `is_degenerate=True` when the scorer returns None or non-finite. Confirm this still fires correctly when a blocking gate's `invalidate_round` action prevents downstream code from producing a scalar. Expected: yes (they compose orthogonally); verify in Gate G1.
- **Risk: false-positive on genuine borderline learning**. Thresholds are calibrated against the FCNet paper reproduction (see [`paper_and_collapse_reference_baselines.md`](./paper_and_collapse_reference_baselines.md) §6). FCNet's minimum `unique_int8` = 52 on file 3; threshold 25 gives 2.08× margin. If V17 introduces a different architecture that legitimately produces `unique_int8` in [15, 25) or `output_std` in [0.5, 1.0) mV, it would be blocked. Mitigation: recording-only checks give diagnostic data to justify future threshold tuning without rebuilding the framework.

## 7. Related docs

- **Parent design**: [`docs/design/collapse_detection_framework_generic.md`](./collapse_detection_framework_generic.md), [`docs/design/tidmad_collapse_advice_and_forensics.md`](./tidmad_collapse_advice_and_forensics.md)
- **Framework rev-6 architecture**: [`docs/design/pluggable_health_checks.md`](./pluggable_health_checks.md)
- **Priorities**: [`docs/design/v17_priorities.md`](./v17_priorities.md) MUST-fix **M8**
- **Empirical calibration**: [`paper_and_collapse_reference_baselines.md`](./paper_and_collapse_reference_baselines.md) — three-way (FCNet / paper-spec baseline / agent_012) per-file reference data and threshold justifications
- **Sibling execution plan**: [`m7_loss_implementor_contract_execution_plan.md`](./m7_loss_implementor_contract_execution_plan.md) (independent; unblocks Gate G5 real-run without workarounds)
- **Superseded plans**: M1 and M4 execution plans were deleted alongside this doc's creation (DROPPED per §1.2)
- **Post-V17**: [`analysis_tool_framework_generic_FUTURE.md`](./analysis_tool_framework_generic_FUTURE.md) (deferred pluggable Analysis Tool Framework)

## Appendix A — Empirical threshold calibration

See [`docs/design/paper_and_collapse_reference_baselines.md`](./paper_and_collapse_reference_baselines.md) and [`reports/health_metrics_scan.md`](../../reports/health_metrics_scan.md) for the full 20-file three-way scan (FCNet / paper-spec baseline / agent_012).

Key numbers used to set M8 thresholds:

| Metric | FCNet floor | Baseline ceiling | agent_012 | M8 threshold | FCNet safety | Baseline rejection |
|--------|-------------|------------------|-----------|--------------|--------------|--------------------|
| `unique_int8` | 52 | 15 | 2 | **25** | 2.08× | 40% |
| `std_mv` | 2.01 | 0.192 | 0.008 | **1.0 mV** | 2.01× | 5.21× |
| `mode_fraction` | 0.059 (max) | 0.994 (min) | 0.9999 | **0.95** | 16× below | 1.05× above |
| `pearson_dispersion` (stdev) | 0.048 (real) | 0.002 (collapse) | 0.007 (agent_012, n=8) | (recording, no threshold) | — | 24× separation |

Peek strategy: single-file `min(denoised_paths)` empirically sufficient — FCNet holds `unique_int8` ≥ 52 on every file including the low-signal band (files 0-3). Strategy C (triplet peek with `[3, 10, 17]` + any-pass aggregation) documented as a future option in the reference doc §6.4, not adopted for V17.

Rationale for `unique_int8: 25` (vs earlier `30`): user's 2026-07-16 decision — wider FCNet safety margin (2.08× strict 2×) protects against V17 models with lower quality than FCNet at only a 40%-of-headroom cost against baseline rejection. See [`paper_and_collapse_reference_baselines.md`](./paper_and_collapse_reference_baselines.md) §6.1 for the trade-off table.
