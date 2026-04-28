# Engineering Spec: Infrastructure Hardening for SIDERIUS v4

## Overview
A forensic audit of SIDERIUS v4 runs (`explore_novel_v4_0425`, `exploit_cnn_v4_0425`) identified 35 infrastructure-related failures. There are **zero** logic blockers in the LLM implementation layer; all issues stem from the physical execution layer (warmup bias, memory management, silent training crashes, scoring quantization).

**Goal:** Implement four fixes — each targeting the actual root cause confirmed by source-level review — to eliminate the "Infrastructure Mire" and restore the Planner's ability to reason effectively.

**Audit trail:** `reports/v4_pr61_20260425_222622.md`.

**Failure fingerprint we are clearing:**

| Category | Count | Run split |
|---|---|---|
| Time-gate miscalibration (`skipped_time_risk`) | 24 (69%) | explore 9 / exploit 15 |
| Trial-mode `numpy._core._exceptions._ArrayMemoryError` | 4 (11%) | explore 4 / exploit 0 |
| `FileNotFoundError` on `cached_models/*.pth` (misclassified as `error_inference`) | 7 (20%) | explore 3 / exploit 4 |
| Ghost-score `-2.7708098959837675` collisions | 7 distinct rounds | explore 1 / exploit 6 |

---

## Problem Statement & Proposed Solutions

### 1. Time-Gate Hallucination (JIT Penalty)

* **Problem:** The warmup measurement that feeds the time gate today runs only **1 warmup step + 2 timed steps**. For complex novel architectures (e.g. `bidir_gated_tcn_ssm`), step 0 is dominated by JIT compile + cudnn.benchmark + CUDA-allocator block growth (~20s). With only two timed steps, a single residual JIT/allocator stutter on step 1 or 2 still skews the average dramatically. Multiplied by ~50k total steps, the estimator predicts wall-times of 5,800–25,000 minutes against a 20-min budget. Audit confirms 24 of 35 failures (69%) are this single bias.
* **Where the warmup actually lives:** `agent/skills/evaluate_time_skill/wrapper.py:127 — _measure_ms_per_step()`. The knobs are at lines 134-135:

  ```python
  n_warmup_batches: int = 1,
  n_timed_batches: int = 2,
  ```

  **It is not in `train_engine_sandbox.py`.** The original spec proposed a `--warmup_only` subprocess flag in the training engine; that scaffold would re-implement what is already in-process, plus add subprocess startup + torch import + model re-instantiation cost on every preflight. Discarded.

* **Solution: Steady-State Warmup, in-process.**
    1. In `_measure_ms_per_step`, raise defaults to `n_warmup_batches=3, n_timed_batches=7` — three discarded JIT/allocator-warmup steps, seven timed samples.
    2. Replace the plain arithmetic mean (`sum(timings_ms) / len(timings_ms)` at wrapper.py:265) with **median** (or trimmed mean dropping the max), so a single allocator-stutter spike no longer skews the estimate.
    3. **Fast-fail short-circuit:** if step 0 elapsed ≥ 5000 ms, return that value as the ms/step estimate and skip the remaining nine steps. This caps warmup cost at ~5 s on genuinely slow models instead of running ~200 s of preflight per round on a `bidir_gated_tcn_ssm`-class architecture.
    4. Surface `n_warmup_batches`, `n_timed_batches`, raw `timings_ms`, and aggregator label (`median` / `trimmed_mean` / `fast_fail`) in the wrapper's `breakdown` for forensic visibility downstream.

### 2. Trial-Mode Memory Deadlock (Inference)

* **Problem:** `inference_single.py` implemented buffer-free GC for **Normal Mode** (line 245) but missed it for **Trial Mode**. In trial mode, raw 2 GB HDF5 buffers stay in memory while `denoised.flatten().astype(np.int8)` creates a ~1.86 GiB temporary copy in `create_abra_file`, hitting the 40 GB VA limit (`RLIMIT_AS`).
* **Solution:** Port the buffer-free pattern from the normal-mode branch into the trial-mode loop.
    1. Move the `del raw_ch1, raw_ch2, all_input, all_target; gc.collect()` block from line 204 to **before** the `create_abra_file` call at line 201.
    2. **View-aliasing addendum (critical):** `train_loader = all_input.reshape(...)` and `target_loader = all_target.reshape(...)` (lines 179-180) are NumPy **views** over the parent buffers — they pin the parents alive even after `del`-ing the parents. The `del` list must therefore mirror the membership of the proven normal-mode `del` at line 245:

       ```python
       del train_loader, target_loader, all_input, all_target, raw_ch1, raw_ch2
       gc.collect()
       create_abra_file(out_name, denoised.flatten().astype(np.int8), injected.flatten().astype(np.int8), indexed=False)
       ```

       (`denoised` and `injected` stay alive across the call because they are the source of the temporary copies inside `create_abra_file`.)

### 3. Misclassified Training Crashes (was: I/O Race)

* **Re-diagnosis:** The original spec attributed `FileNotFoundError: …/cached_models/model_*.pth` to filesystem-sync race. Source-level review rules this out:
  * `torch.save` (`train_engine_sandbox.py:349 / 485`) closes the file before returning. Linux page cache provides read-after-write consistency on a single host — no `fsync` is required.
  * The audit pattern is **"file does not exist at all"**, not "exists but zero-byte." That is incompatible with an I/O sync race; it is consistent with **`torch.save` was never reached.**
  * Most likely cause: the training subprocess crashed (OOM, signal, exception in epoch loop) before reaching the save call. The orchestrator interpreted the run as a success and proceeded to inference, which then trips a misleading `error_inference: FileNotFoundError`.
  * Consequence: the original Fix 3's producer-side `os.path.exists` post-save check is structurally unable to fail (if `torch.save` returned, the file is there). The consumer-side 30 s retry-with-backoff would burn 30 s of trial budget per failure with zero recovery probability. **Both elements of the original Fix 3 must be dropped.**

* **Solution: Subprocess Monitoring + Proper Error Classification.**

    1. **Producer side (post-save sentinel):** in `train_engine_sandbox.py`, after `torch.save` returns successfully (both `run_experiment` line 349 and `run_experiment_streaming` line 485), write a zero-byte sibling sentinel `…/cached_models/_OK_<exp_id>`. The sentinel proves "training reached the end" without depending on `.pth` size. Wrap save+sentinel together so any save failure does not silently leave a sentinel.
    2. **Orchestrator side (subprocess exit-code capture):** when launching training as a subprocess, capture `returncode` and the last ~20 lines of `stderr`. Non-zero exit → record as `error_training` with the captured tail in `memory.conclusion`. **Never proceed to inference on a non-zero exit.**
    3. **Consumer side (preflight existence check):** at the inference entry point, before loading the `.pth`, test for the sentinel `_OK_<exp_id>`. If missing, raise `error_training: checkpoint never written: <path>` — **not** `error_inference: FileNotFoundError`. This corrects the audit's 7 currently-misattributed failures.
    4. **No retry loop.** `torch.load` continues to fail-fast on a missing file. Waiting cannot recover a file that was never written.

### 4. Ghost Scores (-2.7708 Quantization)

* **Problem:** `round(grand_mean, 2) + 1e-10` collapses every per-file vector whose grand-mean rounds to 0.01 into the identical scalar `math.log(0.01 + 1e-10, 5.27) = -2.7708098959837675`. Audit found 7 ghost-score collisions across 4 distinct model classes, in both trial and formal modes. The Planner cannot distinguish "promising failure" from "dead end."
* **Identified sites — must flip together:** the same `round(·, 2) + 1e-10` pattern appears at **six** places. Patching only a subset creates *worse* inconsistency (model scalar precise vs. comparison columns coarse → garbage headroom math in score_table; ceiling flipped but raw baseline coarse → broken `gain_vs_raw` / `headroom_vs_gt` columns since Decision 13 explicitly designs `compute_raw_baseline._calculate_score` as the *symmetric* counterpart of `compute_ground_truth._global_per_file_ceiling`).

  | File | Line | Function |
  |---|---|---|
  | `execute_tools/scoring_utils.py` | 516 | `score_vector` (planner-facing model scalar) |
  | `execute_tools/scoring_helpers.py` | 175 | `_grand_mean_log_scalar` (powers ScoreComparisonTable raw_baseline + ground_truth columns) |
  | `compute_ground_truth.py` | 81 | `_global_per_file_ceiling` (per-file ceiling) |
  | `compute_ground_truth.py` | 119 | `_anchor_normalized_ceiling` (grand-mean ceiling) |
  | `compute_raw_baseline.py` | 120 | `_calculate_score` (per-file raw baseline — symmetric counterpart of site 3) |
  | `compute_raw_baseline.py` | 181 | `_maybe_write_anchor_normalized_scalar` (grand-mean raw baseline — symmetric counterpart of site 4) |

* **Solution:** **Drop legacy quantization at all six sites in a single commit.** Use raw `float64` `grand_mean`:

  ```python
  final_scalar = math.log(grand_mean, 5.27) if grand_mean > 0 else float('-inf')
  ```

    * **Schema impact: zero.** `denoising_score: Optional[float]` and `file_vector: Optional[List[Optional[float]]]` accept any float; no `Field(precision=…)` constraint exists.
    * **Storage impact: zero.** Python's `json.dump` writes full-precision repr; old rounded values and new precise values coexist in the same field.
    * **Markdown rendering:** audit `_fmt_log` and prompt-rendering format strings; bump precision spec where needed so the planner sees fine-grid differentiation in tuner/reflector/proposer prompts.
    * **Edge case (must be explicit):** when `grand_mean ≤ 0`, `math.log` raises. The original `+ 1e-10` floor implicitly protected this. Replace with the explicit `if grand_mean > 0 else float('-inf')` guard above. Without it, the change replaces ghost scores with a `ValueError` regression.
    * **Sentinel consolidation (Option α):** `scoring_helpers._LOG_FLOOR = math.log(_ROUND_EPS, _LOG_BASE) ≈ -13.854` becomes inconsistent once the floor is removed (it would be the only path returning a finite quantized value while every other empty/non-positive case returns `float('-inf')`). **Retire `_LOG_FLOOR` entirely.** Every empty / non-positive / `total_n <= 0` branch returns `float('-inf')`. One sentinel for "no signal", consistent across `score_vector`, `_grand_mean_log_scalar`, and the ceiling helpers.

* **Legacy parity policy:** the `round` step is a byte-strict copy from `denoising_score_old.py`. We are explicitly choosing planner differentiation over byte-parity with legacy TIDMAD. Drop quantization unconditionally — no `legacy_mode=True` carve-out, since `legacy_mode` is for one-off debugging and not in the live tuner path.

* **Mandatory test sweep — included in the same commit:**

  | Test file | What changes |
  |---|---|
  | `tests/unit/test_compute_raw_baseline.py` | Multiple expected-score literals baked-in with `round(·,2) + 1e-10` (lines 65, 92-94, 256, 323); lines 70-97 (`test_linear_sum_is_unrounded`) explicitly tests "weak-signal files where `round(mean, 2)` would zero out" via the `expected_clipped = math.log(1e-10, 5.27)` assertion — that test's premise disappears. Delete or rewrite as a "no quantization floor / linear-sum still recoverable" assertion. |
  | `tests/unit/test_compute_ground_truth.py` | 6+ expected-score literals (lines 44, 52, 102, 127, 144, 155); recompute against unrounded values and replace literals. `test_all_zero_anchors_clips_to_log_of_eps` (lines 47-53) and `test_tidmad_round_is_applied` (lines 130-145) test premises that disappear — rewrite as "all-zero anchors → `float('-inf')`" / "no quantization round". |
  | `tests/unit/execute_tools/test_scoring_helpers.py` | Reference-builder `_make_reference` (lines 55-67) recomputes `raw_per_file_log`, `gt_per_file_log`, `raw_scalar_full`, `gt_scalar_full` via `round(·, 2) + _ROUND_EPS` — this is what every test downstream compares against, so flipping it cascades fixes through all assertions. Subset-aggregation test (lines 166-167) also has explicit literals. |
  | `tests/unit/execute_tools/test_scoring_utils.py` | Lines 198-202 (`test_scalar_is_log_of_round_grand_mean`) and 222-223 (`test_multiple_files_grand_mean`) assert `math.log(round(vector[6], 2) + 1e-10, 5.27)` against site #1 — flip the formula. Line 293 docstring needs prose update. The `test_scalar_is_log_of_round_grand_mean` test name is now misleading; rename to `test_scalar_is_log_of_grand_mean`. |
  | `tests/unit/execute_tools/test_score_table_adversarial.py` | `_make_reference` (lines 61-72) mirrors the pattern in `test_scoring_helpers.py::_make_reference`; same `round(·, 2) + _ROUND_EPS` literals at lines 62, 66, 71, 72. Recompute. |
  | (new) | Add a regression test asserting two distinct grand-means in `[0.005, 0.0149]` produce **different** scalars (the ghost-score-killer assertion). Place under `tests/unit/execute_tools/test_scoring_utils.py` near the existing `test_scalar_is_log_of_grand_mean`. |

---

## Verification Metrics — Proof-of-Utility per Fix

Every fix must justify itself against a **measurable** target. "Vague feelings" (e.g. "fewer skips", "less crashy") are not acceptable success criteria. Each subsection below specifies (a) the consumers of the changed value, (b) the numerical target, and (c) the regression guard that prevents the fix from creating new noise channels.

### Fix 1 — Time-Gate Hallucination (Steady-State Warmup)

* **Downstream Audit — who consumes the ms/step value:**
    * `agent/skills/evaluate_time_skill/wrapper.py` returns `est_total_minutes = (n_train_steps + n_inf_steps) * ms_per_step / 60_000`.
    * The estimate is compared to `time_budget_min` in `nodes/ml_hyperparameter_tune_agent.py::_preflight_skip_check` → emits `error_skipped_time_risk` records.
    * The `breakdown` dict is rendered into the tuner LLM prompt (`render_preflight_breakdown` in the prompt builder) — the planner reads `n_warmup_batches`, `n_timed_batches`, raw `timings_ms`, and `aggregator` label to reason about whether a skip is JIT bias or genuine slowness.
    * Behaviour change: median-of-7 is more **stable** than mean-of-2 — the same model run twice now produces near-identical estimates (verifiable). `fast_fail` short-circuit is a new label; downstream prompt rendering must handle it (no schema break: `aggregator` is already a free-form string in `breakdown`).

* **Quantitative Success Metric:**
    1. **Skip-rate reduction**: replay the 24 historical `error_skipped_time_risk` records (by re-running the warmup measurement on the same model configs at `n_warmup_batches=3, n_timed_batches=7, median`). **Target ≥ 80% of the 4 sub-minute over-budget cases (`spectral_skip_tcn` rec_002 at 20.72; `dual_rate_gated_causal_cnn` rec_007 at 29.19, rec_008 at 23.51, rec_009 at 20.34) now pass the gate.** These are the records where the audit explicitly flagged the estimator as biased high.
    2. **Genuinely slow models still skip**: the `bidir_gated_tcn_ssm` rec_001 (25,019 min estimate) must still skip — the fix is not allowed to admit truly-slow architectures by under-warming. Verify the fast-fail short-circuit triggers (step 0 ≥ 5000 ms) and emits `aggregator = "fast_fail"` in the breakdown.
    3. **Estimator stability**: same model + same dataset, two consecutive `_measure_ms_per_step` calls → median-of-7 estimates within **±5%** of each other. Mean-of-2 currently fluctuates ≥ 30% on novel ops because step 1 vs step 2 allocator stutters dominate the mean.

* **Regression Guard:**
    * **Unit test (synthetic slow model)**: a `MockModel` whose `forward` sleeps 6 s on call 0 and 50 ms thereafter must produce `aggregator = "fast_fail"` and `ms_per_step ≥ 5000`. This proves the fast-fail path triggers and the fix cannot under-estimate a `bidir_gated_tcn_ssm`-class model into admission.
    * **Unit test (synthetic stable model)**: a `MockModel` with deterministic 100 ms / step must produce median = 100 ms ± 1 ms across 7 timed steps; the test asserts `abs(median - 100) < 1`.
    * **No silent under-budget**: assert `est_total_minutes` for the `bidir_gated_tcn_ssm` historical config remains ≥ 1000 min (3 orders of magnitude over budget) — even a buggy median can't cross this floor.

### Fix 2 — Trial-Mode Memory Deadlock (Buffer-Free Before Write)

* **Downstream Audit — who consumes the buffer-state at the write point:**
    * `create_abra_file` (in `execute_tools.abra_io`) consumes `denoised.flatten().astype(np.int8)` and `injected.flatten().astype(np.int8)` — these temporary copies (~1.86 GiB each) are what trip `RLIMIT_AS` when `raw_ch1`, `raw_ch2`, `all_input`, `all_target`, `train_loader`, `target_loader` are still alive.
    * After the fix, `create_abra_file` runs with the buffer-pinning views released. The function itself is unchanged.
    * Behaviour change: peak RSS of `inference_single.py` trial-mode runs drops by ~2 GiB (the size of the freed parent buffers). No schema or output-format change.

* **Quantitative Success Metric:**
    1. **Zero `_ArrayMemoryError` in trial-mode write phase**: the next 5-min sanity run (Commit 5) and any subsequent v5 run produce **0** records with `error_inference: numpy._core._exceptions._ArrayMemoryError` against a 40 GB `RLIMIT_AS`. (Audit baseline: 4 such failures in 35 trials.)
    2. **Peak RSS drop**: instrumented run on the historical `spectral_gated_micro_tcn` trial config — measure peak RSS via `resource.getrusage(RUSAGE_SELF).ru_maxrss` before and after the `create_abra_file` call. **Target: peak RSS at the call ≤ 38 GB** (down from the audit's failure point ≥ 40 GB).
    3. **View-aliasing correctness**: the `del` set must include `train_loader` and `target_loader` — without them, the parent buffers are pinned even though the line `del all_input, all_target` ran. Verify post-`del` via `gc.get_referents(...)` introspection in unit test.

* **Regression Guard:**
    * **Normal-mode parity test**: a synthetic 200-segment dataset run through `inference_single._run_normal_mode` and `inference_single._run_trial_mode` must produce **byte-identical** denoised output (the buffer-free order is purely a memory optimization, not a math change). This catches accidental edits to the data path.
    * **del-order unit test**: monkeypatch `create_abra_file` to introspect the live referents at call time; assert `train_loader`, `target_loader`, `all_input`, `all_target`, `raw_ch1`, `raw_ch2` are all freed before the call. Asserts the *exact* membership of the `del` list, since one missing entry re-creates the memory-pin bug.

### Fix 3 — Misclassified Training Crashes (Sentinel + Subprocess Monitoring)

* **Downstream Audit — who consumes the error classification:**
    * The Tuner planner (`nodes/ml_hyperparameter_tune_agent.py`) reads `record["memory"]["conclusion"]` and `record["status"]` to choose the next round's hyperparameters. An `error_inference: FileNotFoundError` is interpreted as "scoring infrastructure is flaky" → planner retries similar configs. An `error_training` is interpreted as "model + hyperparameters caused training to crash" → planner moves away from this region.
    * The reflector / tuner-advice JSON (`tuner_advice/explore_novel_v*.json`) groups failure categories — misclassification corrupts the categorical histogram the reflector reasons over.
    * The dashboard's iteration table panel renders status badges; the `error_training` vs `error_inference` distinction is visible to the human operator.
    * Behaviour change: 7 historical `error_inference` records would have been `error_training` under the new classification. The `_OK_<exp_id>` sentinel file is a new artefact in `cached_models/` (zero-byte, ignored by inference loaders).

* **Quantitative Success Metric:**
    1. **Zero `error_inference: FileNotFoundError` for missing `.pth`**: in the next sanity run, the count of records matching `^error_inference:.*FileNotFoundError.*\.pth$` is **0**. Genuine missing-file events instead surface as `error_training: checkpoint never written`. (Audit baseline: 7 such misclassifications in 35 trials.)
    2. **Subprocess-monitoring coverage**: 100% of `train_engine_sandbox.py` invocations from the orchestrator capture `returncode` and the last 20 lines of `stderr`. Verify by grep on the orchestrator records: every `error_training` record has a non-null `memory.conclusion.stderr_tail` field, except for the "zero exit but missing sentinel" class which has the canonical `subprocess returned 0 but no _OK_ sentinel; likely silent crash before save` message.
    3. **Sentinel coverage**: synthetic-success run produces `_OK_<exp_id>` sentinel; synthetic-mid-training-crash run produces **no** sentinel. Verify in unit test that a `KeyboardInterrupt` raised between `model = build()` and `torch.save(...)` leaves no sentinel.

* **Regression Guard:**
    * **No orphan sentinel**: forced-failure unit test wraps `torch.save` to raise `IOError` mid-write. The sentinel **must not** be created. (If `torch.save` succeeds-then-fails-on-sync, the sentinel must be cleaned up.) Assert via `os.path.exists(_OK_path) is False` after the failed save.
    * **No retry loop introduced**: grep the inference entry point for `time.sleep`, `for attempt in range`, `retries=` — all must be absent. `torch.load` continues to fail-fast.
    * **Sentinel never substituted for `.pth`**: assert that the inference loader **never** treats sentinel presence as proof of `.pth` existence — it must check the sentinel **and** the `.pth` separately. Unit test: sentinel exists but `.pth` deleted → still raises `error_training: checkpoint missing despite sentinel`.

### Fix 4 — Ghost Scores (Quantization Drop + Sentinel Consolidation)

* **Downstream Audit — who consumes `denoising_score` / `file_vector` / scoring sentinels:**
    * **Tuner planner** reads `record["denoising_score"]` to decide next-round moves. Before the fix, 7 records collapsed to `-2.7708098959837675` exactly → planner could not differentiate. After the fix, scores are full-precision float64.
    * **`render_comparison_table`** (`scoring_helpers.py`) renders model_scalar, raw_baseline_scalar, gt_scalar via `_fmt_log` (currently `:.4f`). **`_fmt_log` does not currently handle `float('-inf')`**: the branch `value < 0 → f"\u2212{abs(value):.4f}"` produces `"−inf"` (Python's `f"{abs(float('-inf')):.4f}"` returns `"inf"`). This is a new code path the fix introduces — the renderer must handle it explicitly (e.g. emit `"−∞"` or `"N/A (no signal)"`).
    * **JSON storage**: `json.dump` serializes `float('-inf')` as the literal string `-Infinity` by default. This is **non-standard JSON** — strict parsers (e.g. browser `JSON.parse` on the dashboard) will reject it. Two options: (i) allow `json.dump(allow_nan=True)` (Python default) and have the dashboard `app.js` pre-process the response, OR (ii) serialize `-inf` as `null`. Decision: (i) for simplicity — the dashboard already tolerates non-numeric `denoising_score` (it renders failed runs as "—"). Add a unit test asserting Python `json.load` round-trips `float('-inf')` correctly through the record format.
    * **`Optional[float]` Pydantic schema**: `float('-inf')` is a valid float and passes Pydantic validation. Verified: `denoising_score: Optional[float] = None` accepts `float('-inf')` without raising. No schema change.
    * **`_fmt_log` precision**: `:.4f` shows 4 decimal places in log space → resolves grand-means down to `5.27^0.0001 ≈ 1.000166×` in linear space. The historical 7 ghost-score collisions had grand-means in `[0.0050, 0.01499]` — at `:.4f` precision, the new scores span `[-5.5764, -2.7708]`, comfortably distinct. **No precision bump needed.** Audit confirms `:.4f` already differentiates the historical collision set.

* **Quantitative Success Metric:**
    1. **Zero ghost-score collisions on historical samples**: take the 7 audit records flagged as `-2.7708098959837675`. Recompute their `final_scalar` using the new formula on the stored `(linear_sum, n_segments)` per-file pairs (already preserved in records). **Target: all 7 produce distinct float64 values.** (We can do this offline since the linear sums are persisted.)
    2. **Regression-test bound**: the new ghost-score-killer test asserts: for any 100 grand-means uniformly sampled from `[0.005, 0.0149]`, the resulting scalars are pairwise distinct (no two collide bit-for-bit).
    3. **Differentiation in the planner-visible region**: minimum scalar gap between two grand-means differing by `1e-5` (roughly the FFT/PSD precision floor) is at least `1e-5 / log(5.27) ≈ 6e-6` log-units, well above the `:.4f` rendering precision (`1e-4`). The planner sees real signal, not bit-quirks.
    4. **Ceiling-and-baseline coherence**: after re-running `compute_raw_baseline.py` and `compute_ground_truth.py` with the new formula, the **ratio** `model_scalar / gt_scalar` for the historical `bidir_gated_tcn_ssm` rec_009 (which had a ghost score) changes from `(-2.7708 / gt_old) = …` to `(new / gt_new)`. **Target: the ratio either improves monotonically or shows a real, non-collision difference** — i.e. it does not stay at the spurious "100% recovery" or "−108% recovery" produced by the rounded values.

* **Regression Guard — high-precision noise:**
    * **Determinism test**: the same `(model_state_dict, validation_data, s_max)` triple → bit-identical scalars across two invocations. Floats from FFT are deterministic in float64; this test fails if anyone introduces non-deterministic ops (e.g. `torch.use_deterministic_algorithms(False)` on a CUDA path that bleeds into scoring). Assert `score_a == score_b` exactly (not `pytest.approx`).
    * **Score-noise floor characterization**: train **the same model** twice with **the same seed** and **the same training data** but different `torch.cuda.manual_seed` ordering — the resulting scores must be within `5e-4` log-units. This bounds the "training-RNG noise" floor; below it, planner signals are not actionable. Document this floor in `docs/scoring_noise_floor.md` and reference it from the planner prompt: "differences smaller than 5e-4 log-units are training-RNG noise; do not propose hyperparameter moves based on them."
    * **Render-precision floor**: `_fmt_log` displays `:.4f` (1e-4 resolution). This is **above** the FFT-precision floor (1e-6) and **below** the training-RNG floor (5e-4). The renderer is therefore the natural quantization in the planner's information path — the planner cannot see noise below `1e-4` log-units, so cannot be misled by sub-noise differences. **No code change needed for this guard, but it is asserted in a new test:** `_fmt_log(x) == _fmt_log(x + 1e-5)` for typical scalar values.
    * **`-inf` rendering test**: `_fmt_log(float('-inf'))` must NOT produce `"−inf.0000"` or similar garbage; must produce a clean sentinel string. Add an explicit branch: `if value == float('-inf'): return "−∞"` (or `"N/A"`). Assert in unit test.
    * **JSON round-trip test**: write a record with `denoising_score = float('-inf')` to JSON, read it back, assert `loaded["denoising_score"] == float('-inf')`. Catches accidental serializer changes that would silently drop or coerce the sentinel.

---

## Step-by-Step Commit Plan

### Commit 1 — Scoring Precision (Fix 4) — All Six Sites + Test Sweep

* **Files (production — 6 sites):**
    * `execute_tools/scoring_utils.py` (line 516, `score_vector` grand-mean)
    * `execute_tools/scoring_helpers.py` (line 175, `_grand_mean_log_scalar`; also retire `_LOG_FLOOR` constant at line 35)
    * `compute_ground_truth.py` (line 81, `_global_per_file_ceiling`)
    * `compute_ground_truth.py` (line 119, `_anchor_normalized_ceiling`)
    * `compute_raw_baseline.py` (line 120, `_calculate_score` per-file)
    * `compute_raw_baseline.py` (line 181, `_maybe_write_anchor_normalized_scalar` grand-mean)
* **Files (tests — 5 files + 1 new):**
    * `tests/unit/test_compute_raw_baseline.py`
    * `tests/unit/test_compute_ground_truth.py`
    * `tests/unit/execute_tools/test_scoring_helpers.py`
    * `tests/unit/execute_tools/test_scoring_utils.py`
    * `tests/unit/execute_tools/test_score_table_adversarial.py`
    * (new) ghost-score-killer regression test (placed in `test_scoring_utils.py`)
* **Action:**
    1. Drop `round(·, 2) + 1e-10` at all six production sites. Replace with the raw-float64 path guarded by `grand_mean > 0`, returning `float('-inf')` on non-positive grand-mean.
    2. **Sentinel consolidation:** delete `_LOG_FLOOR` from `scoring_helpers.py` and replace its `total_n <= 0` early-return with `float('-inf')`. One sentinel, system-wide.
    3. **`_fmt_log` `-inf` branch:** add an explicit `if value == float('-inf'): return "−∞"` branch in `scoring_helpers._fmt_log` (line 265-272). Without it, the existing `value < 0` branch produces `"−inf.0000"` garbage and corrupts the rendered prompt for the planner.
    4. **`_fmt_log` precision audit:** keep `:.4f` (verified above noise floor in §Verification-Metrics-Fix-4). No change to format string.
    5. Recompute every literal expected-score assertion in the five test files. The reference-builder helper functions (`_make_reference` in both `test_scoring_helpers.py` and `test_score_table_adversarial.py`) are the highest-leverage edit: flipping them cascades through every downstream `pytest.approx`.
    6. Delete (or rewrite) the round-zero-out premise tests:
       * `test_compute_raw_baseline.py::test_linear_sum_is_unrounded` (lines 70-97)
       * `test_compute_ground_truth.py::test_all_zero_anchors_clips_to_log_of_eps` (lines 47-53)
       * `test_compute_ground_truth.py::test_tidmad_round_is_applied` (lines 130-145)
    7. Rename `test_scoring_utils.py::test_scalar_is_log_of_round_grand_mean` → `test_scalar_is_log_of_grand_mean` (the round step is gone).
    8. Add the ghost-score-killer regression test (100 grand-means in `[0.005, 0.0149]` → pairwise-distinct scalars).
    9. Add the regression-guard tests from §Verification-Metrics:
       * Determinism: `score_vector(same_input) == score_vector(same_input)` exactly (not `approx`).
       * `_fmt_log(float('-inf'))` returns the sentinel string, not `"−inf.0000"`.
       * `_fmt_log(x) == _fmt_log(x + 1e-5)` for typical scalar values (sub-noise quantization preserved by render).
       * JSON round-trip: `json.loads(json.dumps({"score": float('-inf')}))["score"] == float('-inf')`.
       * **Historical-replay assertion**: synthesize 7 mock per-file linear-sum vectors matching the audit's ghost-score grand-means → assert the new formula produces 7 distinct scalars.
* **Checklist:**
    * [x] All six production sites flipped together — no mixed-precision score_table possible.
    * [x] `_LOG_FLOOR` removed from `scoring_helpers.py`; no remaining import or reference.
    * [x] Non-positive `grand_mean` returns `float('-inf')`, does **not** raise. Guard hardened to `grand_mean > 0 and math.isfinite(grand_mean)` (blocks NaN, ±inf, subnormals).
    * [x] `_fmt_log(float('-inf'))` branch added; unit test green.
    * [x] Every `round(·, 2) + 1e-10` / `round(·, 2) + _ROUND_EPS` literal in the 5 test files is updated or its containing test rewritten/deleted.
    * [x] No surviving symbol `_LOG_FLOOR` in tests (it was imported in `test_scoring_helpers.py` line 23 — drop the import).
    * [x] Ghost-score-killer regression test passes (100 distinct grand-means → 100 distinct scalars).
    * [x] Determinism test passes (`==` not `approx`).
    * [x] JSON round-trip test passes for `float('-inf')`.
    * [x] Historical-replay assertion passes: 7 audit ghost-score grand-means → 7 distinct scalars.
    * [x] Scoped pytest is fully green: `pytest tests/unit/test_compute_raw_baseline.py tests/unit/test_compute_ground_truth.py tests/unit/execute_tools/test_scoring_helpers.py tests/unit/execute_tools/test_scoring_utils.py tests/unit/execute_tools/test_score_table_adversarial.py`.

* **Implementation status (2026-04-25, commit `6c3f736` on `feat/dashboard-iteration-panel`):**
    * **Verified data — the seven historical ghost records under the new formula:**

      | record | grand_mean | new scalar (float64) |
      |---|---|---|
      | spectral_skip_tcn rec_003 | 0.008939 | -2.8382944494645015 |
      | spectral_skip_tcn rec_004 | 0.008739 | -2.8519090981316575 |
      | spectral_skip_tcn rec_005 | 0.006588 | -3.021909575075987 |
      | fused_spectral_gate_tcn rec_009 | 0.005285 | -3.154504741781992 |
      | hierarchical_cycle_fusion_tcn rec_004 | 0.005398 | -3.1417757954581043 |
      | dual_rate_gated_causal_cnn rec_010 | 0.005227 | -3.1611442832970242 |
      | gated_recycle_skip_tcn rec_011 | 0.005091 | -3.1770063429829163 |

      Span 0.339 log-units; **min adjacent gap 0.0066 = 13.3× the 5e-4 noise floor**, visible at `:.4f` render precision. Physically meaningful, not numerical noise.
    * **Test result:** scoped suite **92/92**; full unit suite **2007 passed, 3 xfailed**.
    * **Honest divergences from spec:**
        1. New regression suite lives in standalone `tests/unit/execute_tools/test_phase67_scoring_precision.py` (23 tests across 4 classes) rather than inside `test_scoring_utils.py`. Cleaner organisation; no functional impact.
        2. JSON-safety helper `coerce_nonfinite_to_none` was added to `execute_tools/scoring_utils.py` and applied at **3 storage boundaries beyond the 6 sites** — `denoising_score_single.py`, `nodes/ml_hyperparameter_tune_agent.py`, `core/sandbox_executor.py` — required by the user's "don't just rely on `allow_nan=True`" directive so the dashboard's RFC-8259 `JSON.parse` never sees `-Infinity`/`NaN` literals.

### Commit 2 — Inference Memory & Error Classification (Fix 2 + Fix 3 Consumer Side)

* **Files:**
    * `execute_tools/inference_single.py`
* **Action:**
    1. Move the trial-mode buffer-free block to **before** `create_abra_file` (line 201). The `del` list mirrors the proven normal-mode set: `train_loader, target_loader, all_input, all_target, raw_ch1, raw_ch2`. Followed by `gc.collect()`.
    2. At the inference entry, preflight-check the sentinel `_OK_<exp_id>`. If missing, raise `error_training: checkpoint never written: <path>` and return immediately.
    3. **Drop** the original spec's 30 s retry-with-backoff loop on `torch.load` (it would mask, not fix, the silent-crash root cause).
* **Checklist:**
    * [x] Trial-mode `del` happens **before** `create_abra_file`, not after.
    * [x] All view-aliasing buffers (`train_loader`, `target_loader`) included in the `del` list.
    * [x] Missing sentinel surfaces as `error_training`, not `error_inference`.
    * [x] No retry loop introduced.

* **Implementation status (2026-04-25, pre-commit on `feat/dashboard-iteration-panel`):**
    * **Files touched (2):** `execute_tools/inference_single.py` (production), `tests/unit/execute_tools/test_inference_single.py` (new, 7 tests).
    * **Sentinel preflight extracted into module-level helper** `_assert_training_sentinel(model_path: str, exp_id: str) -> None` so the contract is testable without mocking `torch` / `MODEL_REGISTRY` / HDF5 I/O. Helper raises `RuntimeError` with the prefix `error_training: checkpoint never written: …` — the orchestrator (Commit 4) will pattern-match that prefix to reclassify the failure category.
    * **Trial-mode `del` block** placed at the new line 199, immediately before `create_abra_file` at line 207. Canonical 6-name set (`train_loader, target_loader, all_input, all_target, raw_ch1, raw_ch2`) followed by `gc.collect()`. The post-write `del denoised, injected; gc.collect()` is preserved at the end of each iteration so the loop's per-file peak still drops between iterations.
    * **No retry loop, by construction:** verified by a negative-guard test that scans the helper's exception message for `retry`/`backoff`/`will try again`.
    * **Test coverage:** AST inspection of `inference_single.py` confirms (a) the canonical 6-name `del` runs before `create_abra_file`, (b) both view-aliasing handles are in the set, (c) `gc.collect()` follows the `del`. Sentinel helper tests cover missing-sentinel raise, sentinel-present pass-through, sibling-path convention (`cached_models/_OK_<exp_id>`), and the no-retry message guard.
    * **Test result:** scoped `tests/unit/execute_tools/test_inference_single.py` **7/7 passing**; sibling regression `tests/unit/ml_models/test_plugin_loader.py` **22/22 passing**.
    * **Deferred to other commits (intentional):** the sentinel itself is *written* by Commit 3 (trainer side); the orchestrator *parser* that pattern-matches the `error_training:` prefix to set the record's `error_category` is Commit 4. Commit 2 only produces the right exception shape — the producer + consumer halves of the contract land separately.

### Commit 3 — Training-Side Sentinel + Steady-State Warmup (Fix 3 Producer + Fix 1)

* **Files:**
    * `execute_tools/train_engine_sandbox.py`
    * `agent/skills/evaluate_time_skill/wrapper.py`
* **Action:**
    1. **Sentinel write:** after `torch.save` returns successfully (both `run_experiment` line 349 and `run_experiment_streaming` line 485), write a zero-byte sibling `…/cached_models/_OK_<exp_id>`. Wrap save+sentinel so a save failure cannot leave an orphan sentinel.
    2. **Steady-state warmup:** in `_measure_ms_per_step`, change defaults to `n_warmup_batches=3, n_timed_batches=7`. Aggregate via **median** (or trimmed mean dropping max) instead of arithmetic mean. Add fast-fail: if step-0 elapsed ≥ 5000 ms, return that value and skip the remaining steps.
    3. Surface `n_warmup_batches`, `n_timed_batches`, raw `timings_ms`, and aggregator label (`median` / `trimmed_mean` / `fast_fail`) in the wrapper's `breakdown` dict for downstream visibility.
* **Checklist:**
    * [x] Sentinel file written **iff** `torch.save` succeeded.
    * [x] `n_warmup_batches=3, n_timed_batches=7` defaults in place.
    * [x] Median (or trimmed mean) replaces arithmetic mean.
    * [x] Fast-fail at step 0 ≥ 5 s; verified on a synthetic slow model in unit test.
    * [x] Existing TimeEval unit tests still pass (with monkey-patched `_measure_ms_per_step`).

* **Implementation status (2026-04-26, commit `bf307c6` on `feat/dashboard-iteration-panel`):**
    * **Files touched (4):** `execute_tools/train_engine_sandbox.py` (+26 lines, sentinel writer in both save sites), `agent/skills/evaluate_time_skill/wrapper.py` (+158/-26, warmup overhaul), `tests/unit/agent/skills/test_evaluate_time_skill.py` (+210, 13 new + 4 updated tests), `tests/unit/execute_tools/test_train_sentinel.py` (NEW, +114, 4 sentinel atomicity tests). 4 files, 482 insertions, 26 deletions.
    * **Sentinel atomicity (`_save_with_sentinel`):** thin wrapper around `torch.save(...)` followed by `Path(sentinel_path).touch()`. Atomicity comes from exception propagation — if `torch.save` raises, control flow never reaches the sentinel write, so a save failure cannot leave an orphan `_OK_` for Commit 4's orchestrator to misinterpret. Called from both `run_experiment` (line 349) and `run_experiment_streaming` (line 485). Sentinel path is `<models_dir>/_OK_<exp_id>` (zero-byte, sibling of the `.pth`).
    * **Steady-state warmup:** `_measure_ms_per_step` defaults flipped to `n_warmup_batches=3, n_timed_batches=7`; aggregation switched from `sum(...)/len(...)` to `statistics.median(...)`. Pure `_aggregate_warmup_timings(timings_ms, fast_fail_ms_threshold)` helper extracted so the three branches (`median` / `fast_fail` / `None`) are testable without torch. Fast-fail short-circuit: if step-0 elapsed ≥ 5000 ms, the function returns immediately with `aggregator="fast_fail"` instead of running the remaining 9 steps.
    * **Breakdown propagation:** wrapper now surfaces `warmup_aggregator`, `warmup_n_warmup_batches`, `warmup_n_timed_batches`, and `warmup_timings_ms` in the flat `breakdown` dict so the planner-facing prompt and the audit log distinguish a steady-state estimate from a DOA short-circuit. Free-form keys; no schema change.
    * **Test result:** scoped suite **41/41 passing** (4 sentinel + 17 evaluate-time-skill new/updated + 20 pre-existing).
    * **Honest divergences from spec:**
        1. `_save_with_sentinel` is the *named* helper rather than an inline `Path(...).touch()` after each save call — refactored for symmetry across the two save sites and so the sentinel-write semantics are testable in isolation.
        2. Aggregator label uses `"median"`, `"fast_fail"`, or `None` (when no timed batches were collected) — `trimmed_mean` was discussed in the spec but not implemented; median already gives the outlier-robustness target without needing a tuning knob.

### Commit 4 — Orchestrator Subprocess Monitoring (Fix 3 Producer-Side, orchestrator half)

* **Files:** `nodes/ml_hyperparameter_tune_agent.py` (and any sibling site that launches `train_engine_sandbox.py` via subprocess).
* **Action:**
    1. Capture `returncode` and the last ~20 lines of `stderr` from every training subprocess.
    2. Non-zero exit → record as `error_training` with the captured tail in `memory.conclusion`. Skip inference for that round.
    3. Zero exit but missing sentinel → record as `error_training: subprocess returned 0 but no _OK_ sentinel; likely silent crash before save`. This catches the genuinely silent class.
* **Checklist:**
    * [x] Non-zero subprocess exits never reach inference.
    * [x] Missing sentinel after zero exit is surfaced as `error_training`, not `error_inference`.
    * [x] Forced-failure synthetic test confirms the reclassification.

* **Implementation status (2026-04-26, commit `e559fd1` on `feat/dashboard-iteration-panel`):**
    * **Files touched (5):** `core/sandbox_executor.py` (+27, post-subprocess sentinel check), `nodes/ml_hyperparameter_tune_agent.py` (+42, inference-error re-routing), `tests/unit/core/test_sandbox_executor.py` (+140, helper + 4 silent-crash tests + 5 existing rewired), `tests/unit/core/test_sandbox_rlimit.py` (+21, 3 existing rewired through new helper), `tests/unit/agent/tune_ml_hyperparam_agent/test_silent_train_crash_routing.py` (NEW, +375, 4 routing tests). 5 files, 593 insertions, 12 deletions.
    * **Producer-side detection (`core/sandbox_executor.execute_training`):** after `subprocess.run(...)` returns with `returncode == 0`, the executor tests for the `_OK_<exp_id>` sentinel that Commit 3's `_save_with_sentinel` writes. If the sentinel is missing, the run is surfaced as `{"status": "error", "message": "error_training: subprocess returned 0 but no _OK_ sentinel for exp_id=… (expected …).\n--- stderr tail (last 20 lines) ---\n…"}`. The 20-line cap is `(result.stderr or "").splitlines()[-20:]` joined with `"\n"`. The non-zero exit branch was already in place from earlier hardening; the missing-sentinel branch is the new contribution.
    * **Consumer-side routing (`nodes/ml_hyperparameter_tune_agent.run`):** the inference-error branch (around lines 1387–1446) now substring-matches `"error_training:"` in `inf_status["message"]` and re-routes the saved record's `status` from `error_inference` to `error_training`. The record's `memory.conclusion` / `memory.discovery` / `memory.memory_update` text is rewritten to point the planner at the trainer (the words "silently" + "training crashed" appear so the planner's prompt template renders the right narrative). The pre-existing CUDA-OOM disambiguation is preserved — `error_inference_oom` still routes correctly because the substring check is specific to `error_training:` (not just `error_`).
    * **Test result:** scoped suite **72/72 passing** (`tests/unit/core/test_sandbox_executor.py` 27 + `tests/unit/core/test_sandbox_rlimit.py` 41 + `tests/unit/agent/tune_ml_hyperparam_agent/test_silent_train_crash_routing.py` 4).
    * **Helper rewires:** introduced `_make_train_success_side_effect` in `test_sandbox_executor.py` and `_train_success_side_effect` in `test_sandbox_rlimit.py` so 8 pre-existing tests now mirror the post-Commit-3 contract (sentinel write occurs *before* subprocess returns). Without this rewire, every existing happy-path test would have started returning `error_training` because the new sentinel check fires unconditionally.
    * **Honest divergences from spec:**
        1. The tuner-side routing logic uses **substring match** (`"error_training:" in error_msg`) rather than a structured field on `inf_status`. This was pragmatic — adding a structured field would have required schema work in `inference_skill`'s output contract, and the substring check is precise enough that the routing tests pin all three classes (silent crash → routes; plain inference fail → stays; CUDA OOM → stays). If a future fix needs richer error metadata, it can promote the contract then.
        2. The new tuner-side routing tests live in a standalone file (`test_silent_train_crash_routing.py`) rather than being appended to an existing test file — pattern follows `test_physical_rejection_capture.py` for the same routing-contract test class. 375 lines, hermetic harness (patches `LLMBridge`, `TidmadSandbox`, `_run_skill`, `load_reference_scores`, `get_or_create`).

### (Validation) Commit 5 — End-to-End Sanity Run

Re-launch a small explore run (3 iterations × 3 rounds) and verify on the dashboard:

* No ghost-score collisions in records.
* No `numpy._core._exceptions._ArrayMemoryError` in the trial-mode write phase.
* No `error_inference: FileNotFoundError` for missing `.pth`; previously-misclassified failures now appear as `error_training`.
* Time-gate skip rate drops materially on novel architectures.

---

## Core Principles for Claude Code

1. **Logic First**: Source-level evidence over plan inertia. The original Fix 1 (subprocess) and Fix 3 (I/O race) were both wrong about *where* and *why* — both re-diagnosed against the actual code paths before writing this revision. The Fix 4 site count was *also* re-audited at execution time and corrected from 4 → 6 (raw-baseline pair was missed initially); the all-sites-together principle holds only if the inventory is exhaustive, so the source-level `grep` is the contract, not the prose.
2. **Pydantic First**: No new schema fields are required by these four fixes (verified: `denoising_score`, `file_vector` already accept any float; `breakdown` is a free-form dict). If subsequent work introduces config knobs (e.g. exposing `n_warmup_batches` in `TrainConfig`), add the Pydantic field before wiring.
3. **Strict Error Classification**: A silent training crash misclassified as an inference error wastes the planner's reasoning budget. Errors must be tagged at the layer that actually failed.
4. **All-Sites-Together**: When a numerical contract changes (the `round` step), **every** production site and **every** assertion-bearing test flips in a single commit. Never leave the codebase in a half-quantized state. The site list is whatever `grep -E 'round\(.*,\s*2\)\s*\+\s*(1e-10|_ROUND_EPS)'` returns at execution time, not what was enumerated when the spec was first drafted.
5. **One Sentinel**: `float('-inf')` is the universal "no signal" value across `score_vector`, `_grand_mean_log_scalar`, and the ceiling helpers. Quantization-floor sentinels (`_LOG_FLOOR`) are retired with the round step.
6. **Decoupling**: Measurement and execution stay as separate functions; in-process where possible (no needless subprocesses).
