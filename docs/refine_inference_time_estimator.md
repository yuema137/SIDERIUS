# Refine Inference Time Estimator

**Status**: design (2026-05-02). Not yet implemented.
**Author**: design discussion 2026-05-02 (prompted by V9 audit `reports/v9_20260502.md`).
**Motivation**: V9 audit §8 — time-gate over-estimation killed 9/12 completed iters with `skipped_time_risk` verdicts despite ample real budget. Root cause is a hand-calibrated constant (`_INFERENCE_VS_TRAINING_RATIO = 2.7`) used to derive inference ms/step from training ms/step. The constant was fit on N=2 V7 architectures and over-predicts badly for archs whose true ratio is below it.

---

## 1. Problem Statement

### 1.1 What happens today

Inference wall-time is estimated from training warmup output, scaled by a fixed constant:

```
# agent/skills/evaluate_time_skill/wrapper.py:455-458
inference_ms = measured_training_ms * _INFERENCE_VS_TRAINING_RATIO  # 2.7
```

`_INFERENCE_VS_TRAINING_RATIO = 2.7` lives in `agent/skills/inference_skill/estimator.py:80` and was calibrated 2026-04-30 from exactly two V7 archs (`fft_fused_cyclic_tcn` ratio=1.45, `gated_context_dualpath_tcn` ratio=2.72). The median is 2.7. The constant is documented as a "blunt" placeholder pending more datapoints.

### 1.2 V9 evidence (audit §8)

In `exploration_explore_novel_v9_0501` and `exploration_exploit_cnn_v9_0501`:

- 4 explore iters and 6 exploit iters completed; only **3/10** produced a formal score.
- The other 7 had `status="skipped_time_risk"` — the gate predicted formal-stage wall-time exceeded budget despite identical archs frequently finishing under budget when run.
- Best-score trajectory froze at 5.5763 (exploit) for the entire run because formal scores never made it into the score table.
- Estimator-emitted `inference_minutes` was consistently **3–5× the real measured inference time** when post-hoc compared against actual run logs.

### 1.3 Compounding bug — formal architecture mutates relative to trial

The formal-round override (`_apply_mode_override_chain` in `nodes/ml_hyperparameter_tune_agent.py:130-203`) currently inherits **only** `loss_cfg` and `train_cfg["lr"]` from the best trial winner. Critically, `model_cfg`, `epochs`, and `batch_size` are left to the planner's discretion.

**Consequence**: V9 audit §7 found the LLM emitting formal architectures with hyperparameters never tested in trial (e.g. `kernel_size=2` in formal vs 3 in both trials, `use_same_padding=False` in formal vs True). This makes any timing measurement taken during trial **inapplicable** to the formal round — the formal round is running a different model.

This is an architectural blocker for the rest of the work. Without it, even a perfect per-trial inference timing measurement would be irrelevant to the formal round it is supposed to gate.

---

## 2. Goals & Non-Goals

### Goals

- Replace the `× 2.7` constant with a **measured per-PSD-segment inference cost** captured during the trial round and reused by the formal round's time gate.
- Force the formal round's architecture to match the trial winner so the measurement is applicable.
- Surface, for audit: what fraction of files were treated as warmup, what aggregator ran, the raw per-file timings, the parent-measured process startup overhead.

### Non-Goals

- Do **not** retire `_INFERENCE_VS_TRAINING_RATIO`. Keep it as the fallback when no trial measurement exists (first iter, OOM-killed trial, CPU-only host).
- Do **not** change the VRAM gate, the training warmup, the scoring estimator, or the baseline-runner inference path (`--mode fix`).
- Do **not** introduce a per-arch ratio model. N=2 datapoints don't justify it; the measured marginal makes it unnecessary.
- Do **not** change the trial→formal config promotion contract beyond the `model_cfg`/`epochs`/`batch_size` inheritance — the broader refactor (Audit §7 follow-on work) is a separate effort.

---

## 3. Design

### 3.1 Architectural reality

Inference runs as a subprocess (`core/sandbox_executor.py::execute_inference` → `subprocess.run(["python", "execute_tools/inference_single.py", ...])`). Per-file timings must be captured **inside** the subprocess and surfaced to the parent via a sidecar JSON. Stdout parsing is fragile and would require touching the existing progress-bar / stderr capture branches.

### 3.2 Two distinct timings, separated

The total wall-time of an inference subprocess decomposes into:

```
subprocess_wall_ms = process_startup_ms + sum(per_file_elapsed_ms)
```

Where:
- `process_startup_ms`: paid **once per inference call** — Python import, CUDA context init, `torch.load(state_dict)`, h5py library init, plugin load. Roughly fixed.
- `per_file_elapsed_ms[i]`: scales with `len(eval_sample_set)` — h5py file read + reshape + `process_batch` loop + `create_abra_file` write.

**Only the per-file marginal scales with eval volume**. Trial uses `eval_portion=0.05` (~1 file); formal uses `eval_portion=1.0` (~20 files). Mixing the two would over-predict formal time by amortising a fixed cost over a tiny denominator.

### 3.3 Warmup discard — relative percentage

The first 1–2 files in any inference run are dominated by:
- CUDA context initialisation (cudaMalloc, cudnn autotune)
- Cold disk cache for the validation H5 (~3 GB read)
- Lazy CUDA-graph capture / kernel selection

These are **also** one-shot costs, but they leak into the first per-file timing rather than the parent-side wall-time. We discard a percentage of leading files rather than a hardcoded count, so the rule scales with the trial's eval size:

```python
n_warmup = min(max(1, round(n_files * 0.20)), n_files - 1)
```

| n_files | n_warmup | n_timed |
|--------:|---------:|--------:|
| 1       | —        | (return None — fallback to constant) |
| 2       | 1        | 1       |
| 5       | 1        | 4       |
| 10      | 2        | 8       |
| 20      | 4        | 16      |

The aggregator returns `None` when fewer than 2 files exist, so the fallback path (`× 2.7`) is preserved for tiny trials.

### 3.4 Sidecar path — collision-safe

`self.dirs["configs"]` resolves to `{workspace}/configs/{run_name}/`. The chain runner uses iteration-keyed `run_name` (e.g. `iter_001_explore`), so the dir is already iteration-scoped. Adding `{exp_id}` to the filename makes it experiment-scoped within an iteration:

```
{workspace}/configs/{run_name}/inference_timing_{exp_id}.json
```

Collision-safe across both axes.

### 3.5 Aggregation — median of per-PSD-segment cost

For each timed file, normalise to per-PSD-segment cost:

```
per_psd_seg_ms[i] = elapsed_ms[i] / max(n_psd_segs[i], 1)
```

Then take the median. Median (not mean) for the same robustness reasons as training warmup — one rogue file (kernel re-tune from unusual segment-count rounding) shouldn't poison the estimate.

The estimator converts back to per-step cost downstream:

```
ml_per_psd = PSD_SEGMENT_LENGTH // seg_size
inference_ms_per_step = per_psd_seg_ms * ml_per_psd / inf_batch
```

### 3.6 Estimator hint path

`evaluate_time_skill::run_skill` accepts a new optional kwarg `inference_per_psd_seg_ms_hint`. When present and `> 0`, the estimator uses the conversion above and tags the result `inference_ms_source = "trial_inference_warmup"`. When absent, it falls back to the existing `× 2.7` derivation tagged `"training_warmup_×2.7_fallback"`.

The tuner reads the most recent successful trial round's measurement from `memory_history` (current iteration only — a measurement from a different iter is for a different arch under the model_cfg-inheritance rule) and passes it as the hint.

### 3.7 model_cfg inheritance — prerequisite

`_apply_mode_override_chain` is extended to copy `model_cfg`, `train_cfg["epochs"]`, and `train_cfg["batch_size"]` from the best trial winner alongside the existing `loss_cfg` + `lr` inheritance. The docstring is updated to reflect that the formal round is now defined as "longer training of the trial winner with full eval", not "planner's choice with a couple of inherited hyperparams".

---

## 4. Detailed Plan

Edits in dependency order. Each step is independently reviewable.

### Step 0 — model_cfg inheritance fix (BLOCKING prerequisite)

**File**: `nodes/ml_hyperparameter_tune_agent.py` (lines 130-203)

Extend the inheritance branch in `_apply_mode_override_chain`:

```python
# Replace lines 181-184:
plan.loss_cfg = dict(winner_loss)
plan.train_cfg["lr"] = winner_lr

# With:
plan.loss_cfg = dict(winner_loss)
plan.train_cfg["lr"] = winner_lr
plan.model_cfg = dict(winner["params"]["model_config"])
plan.train_cfg["epochs"] = winner["params"]["train_config"]["epochs"]
plan.train_cfg["batch_size"] = winner["params"]["train_config"]["batch_size"]
```

Update docstring around line 156–160 to drop the *"LLM may legitimately scale those for the formal pass"* clause and note that formal = "longer training of the trial winner with full eval; LLM-emitted formal model_cfg/epochs/batch_size are overridden". Update the `[FORMAL OVERRIDE]` print to name the inherited model_type + key dimensions.

### Step 1 — emit per-file timings inside `inference_single.py`

**File**: `execute_tools/inference_single.py` (trial-mode loop at line 174-236)

Before the loop:
```python
per_file_timings_ms: list[dict] = []
```

Wrap the body of the loop:
```python
for file_index_str, psd_segment_indices in sorted(sample_set.items()):
    t_file_start = time.perf_counter()
    # ... existing body (h5py open through gc.collect()) ...
    elapsed_ms = (time.perf_counter() - t_file_start) * 1000.0
    per_file_timings_ms.append({
        "file_index": file_index,
        "n_psd_segs": len(psd_segment_indices),
        "elapsed_ms": elapsed_ms,
    })
```

After the loop:
```python
if args.timing_out_json:
    with open(args.timing_out_json, "w") as f:
        json.dump(per_file_timings_ms, f)
```

### Step 2 — add `--timing_out_json` flag

**File**: `execute_tools/inference_single.py` (`get_parser()`, line 34-55)

```python
parser.add_argument("--timing_out_json", type=str, default=None,
                    help="If set, write per-file inference timings to this JSON path. "
                         "Trial-mode only; ignored in --mode fix.")
```

`import time` if not already top-level.

### Step 3 — plumb sidecar path + capture parent wall-time

**File**: `core/sandbox_executor.py::execute_inference` (line 548)

After the existing model_cfg path setup (around line 568-569):
```python
timing_out = os.path.abspath(
    os.path.join(self.dirs["configs"], f"inference_timing_{exp_id}.json")
)
```

Append to `cmd` (line 578):
```python
cmd.extend(["--timing_out_json", timing_out])
```

Wrap the `subprocess.run` call (line 594) with parent-side timing:
```python
import time as _time  # if not already imported
t_subprocess_start = _time.perf_counter()
result = subprocess.run(cmd, ...)  # existing
subprocess_wall_ms = (_time.perf_counter() - t_subprocess_start) * 1000.0
```

After success (line 605), parse the sidecar and compute the startup overhead:
```python
per_file_timings_ms = []
process_startup_ms = None
if os.path.exists(timing_out):
    try:
        with open(timing_out) as f:
            per_file_timings_ms = json.load(f)
        sum_per_file = sum(t["elapsed_ms"] for t in per_file_timings_ms)
        process_startup_ms = max(0.0, subprocess_wall_ms - sum_per_file)
    except Exception as exc:
        print(f"[execute_inference] sidecar parse failed: {exc}")

return {
    "status": "success",
    "message": "Inference finished.",
    "per_file_timings_ms": per_file_timings_ms,
    "process_startup_ms": process_startup_ms,
    "subprocess_wall_ms": subprocess_wall_ms,
}
```

### Step 4 — aggregator helper in `evaluate_time_skill/wrapper.py`

**File**: `agent/skills/evaluate_time_skill/wrapper.py` (next to `_aggregate_warmup_timings`, line 96-151)

```python
def _aggregate_inference_file_timings(
    per_file_timings_ms: list[dict],
    warmup_fraction: float = 0.20,
) -> tuple[float | None, dict]:
    """Drop a leading fraction of files (CUDA context, cold disk cache),
    return median per-PSD-segment ms over the remainder.

    Returns ``(per_psd_seg_ms_or_None, breakdown_dict)``. Mirrors the
    breakdown shape of ``_aggregate_warmup_timings`` so downstream record-
    writing is symmetric.
    """
    n_files = len(per_file_timings_ms)
    breakdown = {
        "aggregator": None,
        "n_warmup_files": 0,
        "n_timed_files": 0,
        "warmup_fraction": warmup_fraction,
        "timings_ms": list(per_file_timings_ms),
    }
    if n_files < 2:
        return None, breakdown

    n_warmup = min(max(1, round(n_files * warmup_fraction)), n_files - 1)
    timed = per_file_timings_ms[n_warmup:]
    if not timed:
        return None, breakdown

    per_psd_seg_ms = [
        t["elapsed_ms"] / max(t.get("n_psd_segs", 1), 1) for t in timed
    ]
    if not per_psd_seg_ms or all(v <= 0 for v in per_psd_seg_ms):
        return None, breakdown

    breakdown["aggregator"] = "median"
    breakdown["n_warmup_files"] = n_warmup
    breakdown["n_timed_files"] = len(timed)
    return statistics.median(per_psd_seg_ms), breakdown
```

### Step 5 — persist measurement in tuner memory

**File**: `nodes/ml_hyperparameter_tune_agent.py` (success-path memory write, around line 1503; also the `final_record["memory"]` site near line 1962)

After running the inference skill and (in the success path) capturing its result, call the aggregator and write into the round's memory:

```python
# Pseudo — exact location depends on the existing record-assembly code:
inf_result = inf_status  # the dict returned by execute_inference
per_file = inf_result.get("per_file_timings_ms", [])
per_psd_seg_ms, inf_breakdown = _aggregate_inference_file_timings(per_file)

memory["inference_per_psd_seg_ms_measured"] = per_psd_seg_ms
memory["inference_warmup_aggregator"]      = inf_breakdown["aggregator"]
memory["inference_n_timed_files"]          = inf_breakdown["n_timed_files"]
memory["inference_warmup_fraction"]        = inf_breakdown["warmup_fraction"]
memory["inference_process_startup_ms"]     = inf_result.get("process_startup_ms")
```

The aggregator is imported from `agent.skills.evaluate_time_skill.wrapper` at the top of the module.

### Step 6 — estimator prefers measurement when hint is present

**File**: `agent/skills/evaluate_time_skill/wrapper.py` (line 455-464)

Replace the current `inference_ms` derivation:

```python
# REMOVE:
inference_ms = (
    measured * _inference_est._INFERENCE_VS_TRAINING_RATIO
    if (measured is not None and measured > 0)
    else None
)

# REPLACE WITH:
inference_per_psd_seg_ms_hint = kwargs.get("inference_per_psd_seg_ms_hint")
inf_batch = _inference_est.inference_batch_for(model_type)
ml_per_psd = PSD_SEGMENT_LENGTH // seg_size

if inference_per_psd_seg_ms_hint is not None and inference_per_psd_seg_ms_hint > 0:
    inference_ms = inference_per_psd_seg_ms_hint * ml_per_psd / max(inf_batch, 1)
    inference_ms_source = "trial_inference_warmup"
elif measured is not None and measured > 0:
    inference_ms = measured * _inference_est._INFERENCE_VS_TRAINING_RATIO
    inference_ms_source = "training_warmup_x2.7_fallback"
else:
    inference_ms = None
    inference_ms_source = "static_formula"
```

Surface `inference_ms_source` in the returned `breakdown` dict so audit logs distinguish.

### Step 6.5 — 10% slack rule when measurement is precise

**File**: `agent/skills/evaluate_time_skill/wrapper.py` (around the `feasible = total_min <= budget_min` line, ~line 499)

When the inference path used the trial-warmup measurement (`inference_ms_source == "trial_inference_warmup"`), the gate's skip verdict is **softened**: configs whose total estimated wall-time is within 10% over budget are forced to run rather than skipped.

```python
# Replace the binary feasibility check with a measurement-aware version:
SLACK_FRACTION_WHEN_MEASURED = 0.10
effective_budget = budget_min
slack_applied = False
if inference_ms_source == "trial_inference_warmup":
    effective_budget = budget_min * (1.0 + SLACK_FRACTION_WHEN_MEASURED)
    slack_applied = True
feasible = total_min <= effective_budget
```

Surface `slack_applied`, `effective_budget_minutes`, and `inference_ms_source` in the returned breakdown so the tuner records distinguish a "barely-passed-with-slack" verdict from an "easily under budget" one. The verdict string mentions the slack when active.

**Rationale**: a measured estimate is precise to ±10% in practice (median over n>=4 post-warmup files); rejecting a config whose estimate lands at 102% of budget is throwing away signal. The constant-fallback path keeps the strict `<=` check because its uncertainty band is much wider.

**Test**: `test_inference_hint_path.py` — when hint is present and `total_min` is within `(budget_min, budget_min * 1.10]`, `feasible` is True and `slack_applied` is True. When hint is present and `total_min > budget_min * 1.10`, `feasible` is False. When hint is absent (training-fallback or static path), the strict check applies regardless.

### Step 7 — tuner passes the hint

**File**: `nodes/ml_hyperparameter_tune_agent.py`

Add a helper next to `_best_trial_winner` (line 119):

```python
def _latest_trial_inference_marginal(memory_history: list) -> Optional[float]:
    """Return the most recent successful trial round's measured per-PSD-segment
    inference cost in ms, or None if no qualifying record exists.

    Looks within the *current iteration's* memory history only — measurements
    from earlier iters are for different arches under the model_cfg-inheritance
    rule and must not be reused.
    """
    for r in reversed(memory_history):
        if (r.get("status") == "success"
                and (r.get("memory") or {}).get("time_mode") == "trial"):
            v = (r.get("memory") or {}).get("inference_per_psd_seg_ms_measured")
            if v is not None and v > 0:
                return float(v)
    return None
```

At the `evaluate_time_skill` invocation site (line 1461-1467):

```python
inference_hint = _latest_trial_inference_marginal(round_memory_history)
time_check = _run_skill(
    "evaluate_time_skill",
    sandbox,
    **active_params,
    time_budget_minutes=chosen_time_budget,
    data_dir=time_data_dir,
    inference_per_psd_seg_ms_hint=inference_hint,
)
```

`round_memory_history` is the existing in-iter record list the function already builds; verify variable name in code.

### Step 8 — schema additions

**File**: `agent/schemas/hyperparam_tuning.py` (or wherever `ExperimentMemory` is defined — verify before editing)

Add to the round-record memory schema:
```python
inference_per_psd_seg_ms_measured: Optional[float] = None
inference_warmup_aggregator: Optional[Literal["median"]] = None
inference_n_timed_files: Optional[int] = None
inference_warmup_fraction: Optional[float] = None
inference_process_startup_ms: Optional[float] = None
inference_ms_source: Optional[str] = None  # set on every gate verdict
```

All optional so existing records remain valid.

---

## 5. Commit Plan

Four sequential commits. Each commit ships a self-contained slice and leaves the system in a working state.

### Commit A — model_cfg inheritance fix (Step 0)

**Scope**: `_apply_mode_override_chain` extension + docstring update + unit test.

**Why first**: every subsequent measurement is meaningless if the formal round runs a different architecture than the trial it inherits from. This is the architectural prerequisite.

**Test**: extend or create `tests/unit/agent/tune_ml_hyperparam_agent/test_apply_mode_override_chain.py` with a case where the trial winner uses `kernel_size=3, use_same_padding=True` and the formal `plan.model_cfg` (as proposed by the LLM) uses `kernel_size=2, use_same_padding=False`. Assert post-override `plan.model_cfg["kernel_size"] == 3` and `plan.model_cfg["use_same_padding"] is True`. Also assert `epochs` and `batch_size` were inherited.

**Independently revertible**: yes. Doesn't touch any timing code.

### Commit B — sidecar emit + parent-side capture (Steps 1, 2, 3)

**Scope**: per-file timings written to JSON inside the subprocess; parent reads + computes startup overhead. Returned dict gains 3 new keys, but no caller reads them yet.

**Why second**: instrumentation only. Zero behaviour change. Lets us collect audit data even if Commit C/D have to be reverted.

**Test**: new `tests/unit/execute_tools/test_inference_timing_emit.py` invokes `inference_single.py` end-to-end via subprocess on a tiny synthetic h5 dataset with `--timing_out_json`. Assert sidecar contains one entry per file in `sample_set`, all with positive `elapsed_ms` and matching `n_psd_segs`.

**Independently revertible**: yes. The new flag is opt-in; baseline runner doesn't pass it.

### Commit C — aggregator + memory persistence (Steps 4, 5, 8)

**Scope**: new `_aggregate_inference_file_timings` helper, schema fields on `ExperimentMemory`, tuner writes measurement into round memory.

**Why third**: still no estimator change. Memory now carries the measurement, audit trail is complete, but the gate keeps using the `× 2.7` constant.

**Test**:
- `tests/unit/agent/evaluate_time_skill/test_inference_aggregator.py` — pure-function tests of the aggregator. Cases: empty list → None, 1 file → None, 2 files → drops 1, 5 files → drops 1 medians 4, 10 files → drops 2 medians 8, all-zero elapsed → None, mixed n_psd_segs → correct per-PSD normalisation, fractional rounding → matches the formula.
- Extend tuner unit test to assert the new memory keys appear on success records.

**Independently revertible**: yes. Schema fields are all `Optional[T] = None` so prior records remain valid.

### Commit D — estimator hint path + 10% slack + tuner plumbing (Steps 6, 6.5, 7)

**Scope**: estimator prefers the measurement when present; 10% slack on the feasibility check applies only when the measurement path was used; tuner passes the hint. The gate now uses measured data on every formal round following a successful trial, and leans toward "trying" rather than "skipping" when the estimate lands within 10% over budget.

**Why last**: this is the only behaviour change. Easy revert if it mis-calibrates.

**Test**:
- `tests/unit/agent/evaluate_time_skill/test_inference_hint_path.py` — monkeypatch `_inference_est.estimate_wall_time_seconds`; verify that when `inference_per_psd_seg_ms_hint` is passed, the resulting `inference_ms` matches `hint × ml_per_psd / inf_batch` and `breakdown.inference_ms_source == "trial_inference_warmup"`. Also: when hint is absent but training warmup measured, falls back to `× 2.7` with source `"training_warmup_x2.7_fallback"`. When both absent, source `"static_formula"`.
- Same test file: 10% slack rule. When hint present and `total_min ∈ (budget_min, budget_min × 1.10]`, `feasible=True` and `slack_applied=True`. When hint present and `total_min > budget_min × 1.10`, `feasible=False`. When hint absent, strict `<=` regardless of how close to budget.
- Integration test (dual-mode): extend an existing chain smoke test to assert that on a formal round following a successful trial, the formal record's memory has `inference_ms_source == "trial_inference_warmup"`.

**Independently revertible**: yes. Reverting leaves Commits A/B/C in place; the gate falls back to the constant; audit trail still populated.

---

## 6. Per-Step Checklists

### Commit A — model_cfg inheritance fix

- [x] Read current `_apply_mode_override_chain` implementation (`nodes/ml_hyperparameter_tune_agent.py:130-203`)
- [x] Read `_best_trial_winner` to confirm the winner record shape (lines ~110-127)
- [x] Confirm `winner["params"]["model_config"]` and `winner["params"]["train_config"]` keys exist by grepping the record-write site (`record_params` at line 1243-1250 — confirmed `model_config`, `train_config`, `loss_config` all present)
- [x] Edit lines 181-184: add `model_cfg`, `epochs`, `batch_size` inheritance
- [x] Update docstring (lines ~156-160): drop the "LLM may legitimately scale" clause, add new contract referencing V9 §7 + commits B–D dependency
- [x] Update `[FORMAL OVERRIDE]` print to name the inherited model dimensions (loss_type, lr, epochs, batch_size, model_cfg_keys)
- [x] Located existing test file `tests/unit/agent/tune_ml_hyperparam_agent/test_force_formal_round.py` (existing inheritance coverage); extended in place rather than creating a new file
- [x] Updated fixture `_make_trial_record` to include `model_config` (kernel_size=3, use_same_padding=True defaults) so winner records carry the new field
- [x] Added test `test_force_formal_inherits_full_winner_config`: trial winner with `kernel_size=3` overrides planner's `kernel_size=2`; epochs + batch_size also inherited
- [x] Added test `test_force_formal_model_cfg_inheritance_isolated_from_winner`: defensive copy verified
- [x] Updated existing tests: `test_inheritance_logs_winner_identity` (new print fields), `test_strategy_llm_propose_keeps_planner_choices` (expanded to assert model_cfg + epochs + batch_size preserved under llm_propose escape hatch)
- [x] Replaced `test_force_formal_inherits_loss_and_lr_from_best_trial` with broader `test_force_formal_inherits_full_winner_config` (covers loss + lr + epochs + batch_size + model_cfg)
- [x] `winner is None` path unchanged — existing tests `test_no_trial_winner_falls_back_to_planner_with_warning` and `test_inheritance_default_memory_history_none` still green
- [x] Ran `tests/unit/agent/tune_ml_hyperparam_agent/test_force_formal_round.py` — 29/29 green (added 2 new, all existing still pass)
- [x] Ran broader `tests/unit/agent/tune_ml_hyperparam_agent/ + workflows/test_model_exploration.py + protocols/test_ml_model_valid_to_ml_model_tune.py` — initial run 537/540 green; 3 failures investigated below
- [x] Investigated `test_trial_mode_round_picks_trial_budget` — root cause: the test fixture's `FAKE_PLAN_RESPONSE` (`test_tuning_agent.py:120-127`) puts `batch_size` in `model_config`, not `train_config`, so the saved trial winner record had no `batch_size` key, and my strict `winner_train["batch_size"]` raised `KeyError`. Fixed by making `epochs` and `batch_size` inheritance defensive (`.get()` — keep planner's value when winner record omits the key); `lr` remains required. Added regression test `test_force_formal_inheritance_resilient_to_missing_train_keys`. Re-run: 44/44 green across both `test_force_formal_round.py` and `TestTimeBudgetGate`.
- [x] Verified the other two failures are pre-existing on the branch HEAD (re-ran them with `git stash` of my changes — same `SAFETY_MULTIPLIER == 1.3 vs 2.0` failures; unrelated to Commit A)
- [x] Show diff to user
- [x] Commit (bundled with this design doc — see commit message in git log)

### Commit B — sidecar emit + parent capture

- [x] Read `execute_tools/inference_single.py` trial-mode loop (lines 174-236)
- [x] Add `import time` at top (was not present; added on line 10)
- [x] Initialise `per_file_timings_ms: list[dict] = []` before the loop
- [x] Wrap loop body with `t_file_start = time.perf_counter()` / `elapsed_ms = ...` (start placed AFTER `if not os.path.exists(fpath): continue` so skipped files don't pollute the median; end placed AFTER the second `del denoised, injected; gc.collect()` so the AST adjacency tests for the canonical 6-name del block still pass)
- [x] Append `{"file_index", "n_psd_segs", "elapsed_ms"}` per iteration
- [x] Add `--timing_out_json` to `get_parser()` (line 34-55)
- [x] After loop: write JSON if flag set
- [x] Read `core/sandbox_executor.py::execute_inference` (line 548)
- [x] Compute `timing_out` path using `self.dirs["configs"]` + `exp_id`
- [x] Append `--timing_out_json` to `cmd` — **only when `sample_set is not None`** (trial mode), so baseline / single-file mode keeps a clean cmd and never writes a stray sidecar
- [x] Wrap `subprocess.run` with parent-side `t_subprocess_start` / `subprocess_wall_ms`
- [x] After success: parse sidecar, compute `process_startup_ms = max(0, wall - sum)`
- [x] Extend return dict with `per_file_timings_ms`, `process_startup_ms`, `subprocess_wall_ms`
- [x] Failure path (`CalledProcessError`) extended to return the same new keys with empty/`None` values, so consumers can read the dict uniformly without `KeyError` on OOM/error
- [x] Tests landed in two existing files instead of a new `test_inference_timing_emit.py` (lighter split, per discussion 2026-05-02 — avoids spinning up real torch + h5py in unit tests, aligns with `feedback_unit_tests_are_flow_only`):
  - `tests/unit/execute_tools/test_inference_single.py` — new `TestTimingFlagAndInstrumentation` class, 4 AST tests:
    - `test_timing_out_json_flag_registered` — `get_parser` exposes `--timing_out_json`
    - `test_trial_loop_brackets_each_iteration_with_perf_counter` — ≥2 `time.perf_counter()` calls inside the trial loop (start + end)
    - `test_per_file_timings_list_appended` — append payload contains `file_index`, `n_psd_segs`, `elapsed_ms`
    - `test_sidecar_written_when_flag_set` — `if args.timing_out_json: ... json.dump(per_file_timings_ms, ...)` block exists in `main()`
  - `tests/unit/core/test_sandbox_executor.py` — new `TestExecuteInferenceTimingSidecar` class, 5 mock-subprocess tests:
    - `test_trial_mode_appends_timing_flag` — `--timing_out_json {path}` is in cmd when sample_set given
    - `test_normal_mode_omits_timing_flag` — flag absent in baseline / single-file mode
    - `test_success_returns_per_file_timings_and_decomposed_wall` — sidecar parsed back, return dict carries the 3 new keys, `process_startup_ms = max(0, wall − sum)`
    - `test_success_with_missing_sidecar_returns_empty_timings` — graceful no-sidecar path → empty list + None startup
    - `test_failure_path_returns_uniform_keys` — `CalledProcessError` returns the new keys with empty/None
- [x] Run new tests + existing tests in `tests/unit/execute_tools/test_inference_single.py` and `tests/unit/core/test_sandbox_executor.py` — **47/47 green** (38 existing + 9 new); no regressions to the canonical-del AST tests
- [x] Broader sanity: `test_tuning_agent.py + test_sandbox_rlimit.py` — 101/101 green (caller paths still happy with the new return-dict shape)
- [x] Show diff to user
- [x] Commit (this commit — see git log)

### Commit C — aggregator + memory persistence + schema

- [x] Read `agent/skills/evaluate_time_skill/wrapper.py` aggregator helper region (line 96-151)
- [x] Added `_aggregate_inference_file_timings(per_file_timings_ms, warmup_fraction=0.20)` immediately after `_aggregate_warmup_timings`. Defensive `.get()` on the dict consumption so legacy/partial sidecars don't crash. Smoke-tested: empty → None; 1 file → None; 5 files with elapsed [10..14] / 2 PSD-segs each → drops 1, medians [5.5, 6.0, 6.5, 7.0] = 6.25; all-zero → None.
- [x] Return shape matches `_aggregate_warmup_timings`: `(value_or_None, breakdown_dict)` where breakdown carries `aggregator` ('median' or None), `n_warmup_files`, `n_timed_files`, `warmup_fraction`, `timings_ms`.
- [x] Read `agent/schemas/hyperparam_tuning.py` `ExperimentMemory` definition (lines 106-188; 6 new fields inserted between `inference_batch_uncalibrated` and the Phase L `round_index` block)
- [x] Added 6 new optional fields (`inference_per_psd_seg_ms_measured: Optional[float]`, `inference_warmup_aggregator: Optional[Literal["median"]]`, `inference_n_timed_files: Optional[int]`, `inference_warmup_fraction: Optional[float]`, `inference_process_startup_ms: Optional[float]`, `inference_ms_source: Optional[str]`). Smoke-validated round-trip — defaults are all `None`; populating with the expected values validates cleanly.
- [x] Located the success-path memory-write site in `nodes/ml_hyperparameter_tune_agent.py` — the only `final_record` assignment is at line 1942, with the per-key memory writes flowing into it (`final_record["memory"][...]` between lines 1991–2054). The design doc's two separate bullets ("success-path memory-write site ~line 1554" and "`final_record['memory']` site ~line 1962") refer to the same location; only one edit was needed.
- [x] Added the import `from agent.skills.evaluate_time_skill.wrapper import _aggregate_inference_file_timings` at the top of the module (line 52).
- [x] Inserted the aggregator call + 5 memory key writes immediately after the existing `inference_batch_uncalibrated` block (line 2020+). Reads from `inf_status.get("per_file_timings_ms", []) or []` (defensive — empty list on legacy / failed-trial / non-trial rounds), passes through the aggregator, and writes `inference_per_psd_seg_ms_measured`, `inference_warmup_aggregator`, `inference_n_timed_files`, `inference_warmup_fraction`, `inference_process_startup_ms`. Inline comment explains the fall-through contract: an absent sidecar yields `None`/`0`/default-fraction, which the schema accepts.
- [x] Created `tests/unit/agent/tune_ml_hyperparam_agent/test_inference_aggregator.py` — landed in the existing per-agent dir (CLAUDE.md convention) instead of the design-doc-stipulated `tests/unit/agent/evaluate_time_skill/` (that dir doesn't exist; sibling files like `test_evaluate_time_skill.py` already live in `tune_ml_hyperparam_agent/`)
- [x] Tests: 20 cases across 5 classes — `TestFallbackBranches` (empty / 1-file / all-zero / negative), `TestWarmupDiscard` (2 / 5 / 10 / 20-file discard math, clamp-below-n-files, zero-fraction floor), `TestPerPsdSegNormalisation` (mixed seg counts normalise to identical median, outlier robustness, n_psd_segs=0 floor), `TestDefensiveConsumption` (missing keys, input-list independence), `TestBreakdownShape` (required keys, fraction echoed, aggregator label). **20/20 green** in 0.07s.
- [x] Extended `test_tuning_agent.py` with new `TestInferenceTimingPersistedToMemory` class — 2 tests asserting the wiring contract end-to-end through `agent.run()`:
  - `test_populated_timings_aggregate_into_memory` — feeds 5-file inference result with `process_startup_ms=1234.5` and per-PSD-seg cost = 10 ms each; asserts memory carries `inference_per_psd_seg_ms_measured == 10.0`, `inference_warmup_aggregator == "median"`, `n_timed_files == 4`, `warmup_fraction == 0.20`, `process_startup_ms == 1234.5`.
  - `test_legacy_inference_result_writes_safe_defaults` — feeds bare `{"status": "success", "results": {}}` (no timings, mirrors pre-Commit-B records and OOM-killed trials); asserts all 5 keys are present with safe defaults: value/aggregator/startup are `None`, `n_timed_files == 0`, `warmup_fraction == 0.20` (the aggregator returns the default fraction in its breakdown even when it returns `None`).
- [x] Ran aggregator + schema + new memory-persistence tests together — **159/159 green** in 5.26s.
- [x] Ran `tests/unit/agent/tune_ml_hyperparam_agent/test_tuning_agent.py` (the file housing the new `TestInferenceTimingPersistedToMemory` class) end-to-end — **66/66 green** in 190.98s. No regression to the rest of the file from the new test class. (The legacy `tests/unit/agent/evaluate_time_skill/` dir doesn't exist on this branch — coverage for the aggregator lives in the per-agent dir per CLAUDE.md.)
- [x] Schema test suite confirmation: `tests/unit/agent/tune_ml_hyperparam_agent/test_hyperparam_schemas.py` runs green inside the 159-test sweep above. `ExperimentMemory.model_validate({})` round-trips fine; populating with all six new fields validates cleanly. No back-compat regressions.
- [ ] Show diff to user
- [ ] Commit

### Commit D — estimator hint path + 10% slack + tuner plumbing

- [ ] Read `evaluate_time_skill/wrapper.py::run_skill` (line 378-557), focus on lines 455-464
- [ ] Replace `inference_ms` derivation with 3-branch hint/training-fallback/static logic
- [ ] Compute `inf_batch` and `ml_per_psd` correctly (import `inference_batch_for`, `PSD_SEGMENT_LENGTH`)
- [ ] Surface `inference_ms_source` in returned `breakdown` dict
- [ ] Add 10% slack rule (Step 6.5): `effective_budget = budget × 1.10` if `inference_ms_source == "trial_inference_warmup"`, else `effective_budget = budget`; surface `slack_applied` and `effective_budget_minutes` in breakdown
- [ ] Update verdict string to mention slack when active
- [ ] Read `nodes/ml_hyperparameter_tune_agent.py` `_best_trial_winner` region (line 110-127)
- [ ] Add `_latest_trial_inference_marginal(memory_history) -> Optional[float]` helper
- [ ] Locate `evaluate_time_skill` invocation (line 1461-1467)
- [ ] Compute `inference_hint = _latest_trial_inference_marginal(round_memory_history)` (verify variable name)
- [ ] Pass `inference_per_psd_seg_ms_hint=inference_hint` kwarg
- [ ] Verify the time_record / success_record memory write also stores `inference_ms_source` from `time_check["breakdown"]`
- [ ] Create `tests/unit/agent/evaluate_time_skill/test_inference_hint_path.py`
- [ ] Test: hint present → `source == "trial_inference_warmup"`, value matches formula
- [ ] Test: hint absent + training measured → `source == "training_warmup_x2.7_fallback"`
- [ ] Test: both absent → `source == "static_formula"`
- [ ] Extend a dual-mode integration test to assert formal record's `inference_ms_source == "trial_inference_warmup"` after a successful trial
- [ ] Run full `tests/unit/agent/` — green
- [ ] Run targeted dual-mode integration test — green
- [ ] Show diff to user
- [ ] Commit

---

## 7. Risks & Edge Cases

1. **Trial OOMs before any sidecar write**. Subprocess gets killed (RSS limit hit), no JSON exists, parent's `os.path.exists(timing_out)` is False, return dict has `per_file_timings_ms=[]`. Aggregator returns `None`, hint helper finds no qualifying record, gate falls back to `× 2.7`. **Verified safe by the `if hint and >0` guard at the only branching point.**

2. **First iteration of a chain**. No prior round in `memory_history`, hint helper returns `None`, gate falls back. Correct behaviour — no measurement to inherit yet.

3. **Trial round 1 succeeds, trial round 2 fails (OOM), formal round 3 fires**. `_latest_trial_inference_marginal` walks `reversed(memory_history)`, skips the failed round (status filter), picks up round 1's measurement. Correct.

4. **Chain iteration boundary**. Helper restricts lookup to current iteration's history (the `round_memory_history` variable already tracks this). A measurement from iter_001 is for a different arch than iter_002's plan. Documented in the helper's docstring.

5. **Spectral TCN over-correction**. The 2.7 constant was set by the spectral TCN ratio (2.72). If a future spectral arch has measured ratio < 2.7, the new path will under-predict relative to the constant. Acceptable risk: under-prediction shows up as actual run time exceeding budget, which the runner already handles by killing the round; the next iter sees the wall-time in the memory history and the planner adapts. **No safety multiplier added to the inference path** — the existing training-side `SAFETY_MULTIPLIER = 2.0` covers the dominant phase, and stacking another multiplier on inference would re-introduce the original over-prediction problem.

6. **First file's elapsed_ms includes process startup leak**. The 20% warmup discard absorbs this at the file granularity. The parent-side `process_startup_ms` is reported separately for audit but not used by the gate. Documented in the aggregator's docstring.

7. **Schema-validation breakage on existing records**. All new fields are `Optional[T] = None`. Existing records (no new fields) validate fine. Verified by running the schema unit suite in Commit C's checklist.

8. **Subprocess clock skew**. `time.perf_counter()` is monotonic and per-process; values aren't comparable across processes. The aggregator only consumes deltas computed inside the subprocess (sidecar) or inside the parent (`subprocess_wall_ms`); never mixes the two raw clocks.

---

## 8. Out of Scope

- Retiring `_INFERENCE_VS_TRAINING_RATIO`. Stays as the fallback.
- Calibrating per-arch ratios. Measurement makes it unnecessary.
- Touching the VRAM gate, training warmup, or scoring estimator.
- Touching `--mode fix` (baseline runner). The new flag is opt-in; baseline doesn't pass it.
- Broader trial→formal config promotion refactor (Audit §7 follow-on). Step 0 covers only the model_cfg/epochs/batch_size inheritance needed to make the timing measurements applicable.
- Cross-iteration measurement reuse. Different iters run different arches under the new inheritance rule, so reuse would be unsafe. Helper restricts to current iter only.

---

## 9. Expected Outcome

In the next V9-class run after Commit D lands:

- `inference_ms_source` in formal-round records distinguishes measured-path (`"trial_inference_warmup"`) from fallback paths.
- `skipped_time_risk` rate on formal rounds drops from ~70% (V9 baseline) to <30%.
- Best-score trajectory unfreezes because more formal scores reach the score table.
- Audit log shows `process_startup_ms` typically 5-30 s (CUDA init + model load + h5py) and `inference_per_psd_seg_ms_measured` typically 50-500 ms across architectures — orders of magnitude apart, confirming the separation was correct.
