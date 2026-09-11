# M9 — Multi-File Peek (Strategy C) — Execution Plan

- **Status**: **implementation landed (§5.1-§5.7) — pending local pre-push verification (Milestone 4) and CI**
- **Scope**: **generic** (framework: shared peek helper + aggregation modes) + **task-specific** (which peek_file_indices + which aggregation for TIDMAD)
- **Owner**: TBD
- **Created**: 2026-07-16
- **Last Updated**: 2026-07-16
- **Parent design**: [`docs/design/collapse_detection_framework_generic.md`](./collapse_detection_framework_generic.md), [`docs/design/paper_and_collapse_reference_baselines.md`](./paper_and_collapse_reference_baselines.md)
- **Tracks**: to-be-opened issue #M9, [`v17_priorities.md`](./v17_priorities.md) (add M9 row after issue opens)
- **Follows**: **M8** ([`m8_gate_coverage_and_diversity_metrics_execution_plan.md`](./m8_gate_coverage_and_diversity_metrics_execution_plan.md))

## 1. Purpose

Refactor the three blocking health checks (`output_diversity`, `output_std`, `amplitude_collapse`) to consume a shared multi-file peek helper. Adopt Strategy C — peek at a **configurable list of files** rather than a single min-key file — with **YAML-configurable aggregation** (`any_pass`, `all_pass`, `max`, `min`, `mean`, `median`). Provides defense-in-depth against future partial-collapse cases; backward-compatible with single-file peek via YAML defaults.

## 2. Empirical motivation

The M8 full-file scan ([experiment report](https://github.com/Galileo-Sandbox/siderius-exp/blob/e9e5063b/reports/health_metrics_scan.md) + [`paper_and_collapse_reference_baselines.md`](./paper_and_collapse_reference_baselines.md)) established that **single-file peek is sufficient for FCNet** — FCNet's `unique_int8` floor is 52 across all 20 files, well above M8's threshold of 25. But two future scenarios motivate Strategy C:

1. **Partial-collapse** — a V17 model with real learning on high-signal files (10-19) but collapsed output on low-signal files (0-3). Single-file peek with `min(denoised_paths)` would peek file 0 and reject the whole run, discarding the useful high-signal-file learning.
2. **Weaker-than-FCNet models** — V17 architectures may legitimately produce lower diversity than FCNet on low-signal files (files 0-3 have narrowest FCNet margin). A single-file peek keyed to file 3 (52 uniq) sits close to the M8 threshold of 25; a triplet peek spanning frequency bands provides a more robust verdict.

## 3. Preconditions

- [x] **M8 landed** (commits `042d50a` → `0efb320` on PR #116). Provides: `pearson_dispersion`, `after_round: every` schema, Caveat A semantic fix, six-gate YAML.
- [x] **Q2-audit complete**: no framework-internal or script consumers of the current top-level metric keys (`unique_count`, `file_index`, `output_std_mv`, `mode_fraction`); 16 test assertions are the only downstream consumers, all safe to update alongside the refactor. **No dual-write compat required.**
- [ ] Baseline test count captured before starting M9 (for Gate G4 comparison):
  ```bash
  python -m pytest tests/unit/execute_tools/health_checks/ tests/unit/agent/tune_ml_hyperparam_agent/ tests/integration/health_checks/ --collect-only -q 2>&1 | tail -3
  ```

## 4. Design

### 4.1 New module — `execute_tools/health_checks/_multi_file_peek.py`

```python
from typing import Callable, Literal
from pydantic import BaseModel

AggregationMode = Literal["any_pass", "all_pass", "max", "min", "mean", "median"]


class PerFilePeekResult(BaseModel):
    """One file's contribution to a multi-file peek."""
    file_index: int
    metric_value: float | int | None   # None when I/O failed
    passed: bool                        # I/O failure → False
    io_error: str | None = None


class MultiFilePeekOutcome(BaseModel):
    """Aggregated verdict + per-file breakdown for record observability."""
    passed: bool                        # aggregated verdict
    aggregation: AggregationMode
    per_file: list[PerFilePeekResult]
    n_files_attempted: int
    n_files_io_failed: int
    reason: str = ""                    # populated on pass=False


def peek_and_aggregate(
    ctx: HealthCheckContext,
    peek_file_indices: list[int],
    metric_fn: Callable[[np.ndarray], float | int],
    predicate: Callable[[float | int], bool],
    aggregation: AggregationMode,
    peek_samples: int,
    channel: str = "channel0001",
) -> MultiFilePeekOutcome:
    """Peek each file, compute per-file metric, apply predicate, aggregate."""
```

### 4.2 Aggregation semantics

| Mode | Verdict | Chosen because |
|------|---------|----------------|
| `any_pass` | `passed=True` if at least one file's per-file `passed=True` | Chosen default. Real learning may dip on any single file; "at least one file cleared" is credible evidence. |
| `all_pass` | `passed=True` iff every file's per-file `passed=True` | Strictest — catches partial-collapse where some files healthy and some collapsed. |
| `max` | Apply predicate to `max(per_file_metric)` | Aggregate then threshold — "at least one file crossed the bar" for numeric predicates. |
| `min` | Apply predicate to `min(per_file_metric)` | Equivalent to `all_pass` for monotone predicates. |
| `mean` | Apply predicate to `mean(per_file_metric)` | Central tendency. |
| `median` | Apply predicate to `median(per_file_metric)` | Outlier-robust central tendency. |

### 4.3 Ambiguity resolution

1. **Empty `peek_file_indices` (backward compat)**: helper falls back to `[min(ctx.denoised_paths.keys())]` (or `[0]` if `denoised_paths` empty). Matches the pre-M9 single-file semantic exactly — every existing YAML entry keeps working unchanged.

2. **I/O failure on a subset of `peek_file_indices`**:
   - `any_pass`: I/O-failed files are dropped from the population. If at least one succeeds AND passes, gate passes. If ALL fail I/O, `passed=False`.
   - `all_pass`: I/O failure counts as fail (strictest — "if we can't verify, we can't clear").
   - `max` / `min` / `mean` / `median`: I/O-failed files dropped from the aggregate. If all fail, `passed=False`.
   - Common contract: `MultiFilePeekOutcome.per_file` always includes I/O-failed entries with `io_error` populated, so record has full observability regardless of aggregation.

3. **`peek_file_indices` contains an index not in `denoised_paths`**: use `ctx.get_denoised_path(i)` — which already falls back to `denoised_filename_fn`. If neither resolves, populate `io_error="no path resolved for file_index=N"`.

### 4.4 Interaction with `choose_peek_file_index`

**Keep as legacy wrapper.** Add deprecation note to its docstring:
```python
def choose_peek_file_index(ctx: HealthCheckContext) -> int:
    """DEPRECATED (M9): use peek_and_aggregate with empty peek_file_indices
    for the same single-file semantic. Kept for backward compatibility
    with any external callers not yet migrated."""
```
No deletion — defer to a P1 follow-up. 3 existing tests in `test_peek.py::TestChoosePeekFileIndex` keep working.

### 4.5 Aggregation defaults per check (per user's Q3 decision)

| Check | Default aggregation | Notes |
|-------|---------------------|-------|
| `output_diversity` | `any_pass` | Uniform default. |
| `output_std` | `any_pass` | Uniform default. |
| `amplitude_collapse` | `any_pass` | **Note**: `all_pass` semantics would arguably be stricter and more collapse-sensitive (any file with >95% single-value dominance is a collapse signal). Empirical validation deferred to post-V17 — see §8 Q1. |

### 4.6 Peek indices per check (per user's Q4 decision)

**Same triplet `[3, 10, 17]` for all three blocking checks.** Rationale (from `paper_and_collapse_reference_baselines.md` §6.4):
- File **3**: low-freq band, narrowest FCNet margin (52 uniq) — safety-margin test point
- File **10**: mid-high band, first high-signal file (127 uniq) — mid-band exemplar
- File **17**: high-freq band, strong FCNet (143 uniq) — high-signal exemplar

Uniform across checks for symmetry and predictability. Per-check divergence deferred until empirical evidence warrants.

## 5. Execution checklist

### 5.0 Q2-audit ✅ COMPLETE (this session)

Downstream consumer audit: 0 framework-internal, 16 test assertions (all safe to update inline), 0 script consumers. No dual-write compat required.

### 5.1 Create helper module — ✅ DONE (Milestone 1)

- [x] Created `execute_tools/health_checks/_multi_file_peek.py` (**287 lines**):
  - `AggregationMode` `Literal` type ✓
  - `PerFilePeekResult` Pydantic model ✓
  - `MultiFilePeekOutcome` Pydantic model ✓
  - `peek_and_aggregate()` function per §4.1 ✓
  - Bonus: dedup in `_resolve_indices` for typo-safety
- [x] Created `tests/unit/execute_tools/health_checks/test_multi_file_peek.py` (**382 lines, 23 test cases**, all pass):
  - Backward-compat (3 cases): empty fallback, not-applicable, filename_fn present but missing file
  - `any_pass` (5): all pass, one passes, none pass, one OK + 2 I/O, all I/O fail
  - `all_pass` (3): all pass, two pass one fail, I/O counts as fail
  - Numeric aggregations (6): `max` / `min` / `mean` / `median` — pass and fail cases + all-I/O-fail
  - Edge cases (4): index not in denoised_paths, deduplication, unknown aggregation, constant channel
  - Outcome shape (2): per_file populated on failure, Pydantic round-trip

### 5.2 Refactor three blocking checks — ✅ DONE (Milestone 2)

- [x] `execute_tools/health_checks/output_diversity.py` (117 → 92 lines): `metric_fn = int(np.unique(arr).size)`, `predicate = m > min_unique`. `_DEFAULT_MIN_UNIQUE` intentionally kept at 5 for backward compat (YAML overrides to 25).
- [x] `execute_tools/health_checks/output_std.py` (105 → 93 lines): `metric_fn = std * MV_PER_LSB`, `predicate = m >= min_std_mv`.
- [x] `execute_tools/health_checks/amplitude_collapse.py` (155 → 118 lines): `metric_fn = max(bincount)/n`, `predicate = m <= threshold` (dual of the pre-M9 "fail when m > threshold" — equality passes per design §9.2). Semantic note: `dominant_class` metric dropped (diagnostic-only, no consumer).
- [x] `execute_tools/health_checks/_peek.py`: `choose_peek_file_index` docstring updated to deprecation note.

### 5.3 Update existing check tests — ✅ DONE (Milestone 2)

Actual migration count: **22 assertions across 4 test files** (plan estimated 16; extras were `dominant_fraction` / peek-error / reason-substring assertions the plan's grep didn't catch). Plus 1 integration-test substring update.

- [x] `tests/unit/execute_tools/health_checks/test_output_diversity_check.py` — **10 assertions migrated** (5 mechanical `unique_count`/`file_index` → per_file_json extractions; 4 semantic peek-error rewrites; `threshold` untouched thanks to class-default revert to 5).
- [x] `tests/unit/execute_tools/health_checks/test_amplitude_collapse_check.py` — **10 assertions migrated** (7 `dominant_fraction`/`file_index` → per_file_json; 2 `dominant_class` semantically dropped; 2 semantic peek-error rewrites). Also removed the `"-1" in reason` assertion since `dominant_class` no longer appears in the reason string.
- [x] `tests/unit/execute_tools/health_checks/test_output_std.py` — **5 assertions migrated + 1 test renamed** (`test_at_exact_threshold_fails` → `test_below_threshold_fails` since original comment was misleading; test still exercises "threshold above measured → fail").
- [x] `tests/unit/execute_tools/health_checks/test_schemas.py` — **no change** (line 184's `unique_count` is an arbitrary Pydantic round-trip key, not tied to the check output shape).
- [x] `tests/integration/health_checks/test_gate_coverage_round_7.py` — **1 substring assertion updated** (M9 reason format changed from `"N unique int8 values"` to `"aggregation=... failed — per-file: file_N=metric"`).

**Test suite delta**: pre-M9 baseline 713 → post-Milestone-2 736 pass (net +23 from the new `test_multi_file_peek.py` cases, minus semantic consolidation).

### 5.4 New `HealthCheckResult.metrics` shape (documented once, applied to all three checks)

```python
metrics = {
    "aggregated_passed":   bool,            # was the aggregated verdict pass?
    "aggregation":         str,             # "any_pass" | ...
    "n_files_attempted":   int,             # len(peek_file_indices) after fallback
    "n_files_io_failed":   int,             # subset with io_error != None
    "peek_file_indices":   str,             # JSON-serialised list[int] — for record observability
    "per_file_json":       str,             # JSON-serialised list[PerFilePeekResult.model_dump()]
    "threshold":           int | float,     # per-check threshold value that was applied
    # No top-level unique_count / file_index / output_std_mv / mode_fraction
    # anymore — per Q2-audit, no consumer depends on them.
}
```

### 5.5 Update `configs/health_checks.yaml` — ✅ DONE (Milestone 3)

- [x] Added `peek_file_indices: [3, 10, 17]` and `aggregation: any_pass` to the config block of each of the three blocking gates (`output_diversity_blocking`, `output_std_blocking`, `amplitude_collapse_blocking`).
- [x] Updated top-of-file header comment to reference M9 doc and explain the peek strategy.
- [x] Existing YAML-shape assertions in `test_config_loader.py::test_default_path_loads_shipped_config` and `test_runner.py::test_shipped_config_all_rounds` continue to pass (they check gate IDs and `after_round: every`, both unchanged).

### 5.6 Verify no dual-write needed (per Q2-audit)

- [x] Q2-audit confirms no framework-internal or script consumers of the pre-M9 top-level metric keys. Skip Step 6.5 from the plan draft (dual-write compat is unnecessary).

### 5.7 Documentation updates — ✅ DONE (Milestone 3)

- [x] **`docs/design/collapse_detection_framework_generic.md` §4.7** added — task-agnostic multi-file peek pattern documentation including threshold-direction-via-predicate concept, aggregation modes table, backward-compat, empirical-basis link.
  ```markdown
  ### 4.7 Multi-file peek strategy

  Peek at multiple files instead of one, then aggregate the per-file
  verdicts. Configurable per gate via `peek_file_indices: [int, ...]`
  and `aggregation: <mode>`. Six modes supported (see
  `execute_tools/health_checks/_multi_file_peek.py::AggregationMode`).

  Rationale: single-file peek is a canary. Any collapse mechanism
  affecting only a subset of files (partial collapse) can evade a canary.
  Multi-file peek costs O(N) more I/O per gate where N = |peek_file_indices|
  but provides O(N) more evidence.

  Task-specific docs own the *which files* and *which aggregation*
  decisions; the generic framework only defines the mechanism.
  ```

- [x] **`docs/design/paper_and_collapse_reference_baselines.md` §6.4** revised — replaced the pre-M9 "empirically sufficient" language with the M9-adopted framing including the triplet rationale for files 3, 10, 17.

- [x] **`docs/design/m8_gate_coverage_and_diversity_metrics_execution_plan.md` §3.5** — added a paragraph noting the peek strategy is superseded by M9, with backward-compat note.

- [x] **`reports/health_metrics_scan.md` §8** added — records M9 as adopted decision with rationale (per-file variance up to 3×), empirical margin preservation (file 3 in the triplet), and semantic-loss note for `dominant_class`.

- [x] **`docs/README.md`** — new row added for `m9_multi_file_peek_execution_plan.md` (status: active).

## 6. Validation gates

### Gate G1 — Helper unit tests (after §5.1)

```bash
python -m pytest tests/unit/execute_tools/health_checks/test_multi_file_peek.py -v
```
Expected: all cases pass; count matches §5.1 checklist.

### Gate G2 — Refactored check unit tests (after §5.2 + §5.3)

```bash
python -m pytest tests/unit/execute_tools/health_checks/test_output_diversity_check.py \
                 tests/unit/execute_tools/health_checks/test_output_std.py \
                 tests/unit/execute_tools/health_checks/test_amplitude_collapse_check.py \
                 tests/unit/execute_tools/health_checks/test_schemas.py -v
```
Expected: all pass. Delta from pre-M9 baseline: same test count, updated assertions.

### Gate G3 — Real-YAML integration test (after §5.5)

```bash
python -m pytest tests/integration/health_checks/test_gate_coverage_round_7.py -v
```
The existing G1-reproduction test for agent_012 must still invalidate round 7 with the new triplet+any_pass config. If the agent_012 fingerprint clears the triplet (file 3 / 10 / 17 all fail on unique=2 → any_pass returns False → gate fails), the test passes unchanged.

### Gate G4 — Full regression

```bash
python -m pytest tests/unit/ tests/integration/health_checks/ -q
```
Expected: no new failures beyond intentional metric-shape assertion updates. Delta from pre-M9 baseline: same test count + N new multi-file-peek tests, all passing.

### Gate G5 — Local pre-push parity (per user's meta note)

```bash
ruff check .
ruff format --check .
uv run pyright execute_tools/ tests/ nodes/
```
All must pass. If pyright is unavailable locally (Node.js issues on this environment), rely on CI but document the gap.

## 7. Draft §6.4 replacement text for `paper_and_collapse_reference_baselines.md`

**Current** (post-M8):
> Single-file `min(denoised_paths)` peek is empirically sufficient. Strategy C (triplet peek with `[3, 10, 17]` + any-pass aggregation) is documented as a future option for cases where partial-collapse (some files healthy, some collapsed) evades single-file detection. Not adopted for V17.

**Proposed replacement** (post-M9):
> **Strategy C adopted (M9)**: multi-file peek with `peek_file_indices: [3, 10, 17]` and `aggregation: any_pass` is the default for all three blocking checks. The three indices span all four frequency bands (file 3 = low-freq narrowest FCNet margin, file 10 = first high-signal file, file 17 = high-freq exemplar) — a multi-band peek is robust against partial-collapse cases where a subset of files might be healthy and a subset collapsed. `any_pass` chosen for consistency with the M8 threshold of `unique_int8=25` (which FCNet's file-3 minimum of 52 clears comfortably); a real-learning model that clears any one band is credible evidence of learning. `amplitude_collapse`'s `all_pass` semantics would arguably be stricter and worth empirical validation post-V17 (see M9 §8 Q1).

## 8. Definition of Done

- [ ] All checklist items in §5.1-§5.7 marked complete
- [ ] All 5 validation gates pass with recorded evidence
- [ ] PR opened, CI green, merged to master
- [ ] New GitHub issue for M9 opened + closed with reference to merge commit SHA
- [ ] `docs/design/v17_priorities.md` updated: M9 row added (COMPLETE)

## 9. Open questions / risks

- **Q1 (post-V17 empirical validation)**: does `amplitude_collapse` benefit from `all_pass` over `any_pass`? Any single file with >95% single-value dominance is a strong collapse signal — `all_pass` would gate on "no file may be dominated"; `any_pass` gates on "at least one file must be non-dominated". Both catch the current collapse cases (baseline mode_fraction min 0.994 fails on every peeked file); the discriminator would be edge cases where a real model has mode_fraction ~0.94-0.96 on some files and ~0.4 on others. Deferred to a post-V17 empirical run.
- **Q2 (per-check triplet)**: uniform `[3, 10, 17]` across all three checks — is there a case for per-check divergence (e.g. `amplitude_collapse` peeks all 20 files because peek cost is low and single-value dominance is uniform across bands)? Deferred; recommend uniform for V17.
- **Risk: metric-shape breaking change with no dual-write** — Q2-audit found no consumers, but if a future Run Monitor consumer needs top-level `unique_count`, they must `json.loads(metrics["per_file_json"])[0]["metric_value"]`. Trivial to add dual-write later if a real consumer emerges.
- **Risk: `all_pass` + triplet on `amplitude_collapse`** would false-positive on files 0-3 for FCNet-like models more aggressively — FCNet's mode_fraction on file 3 is 0.059, well below 0.95, so `all_pass` currently doesn't false-positive on FCNet, but a weaker V17 model with mode_fraction ~0.7-0.9 on the low band would trip `all_pass` while `any_pass` on the high band would still catch real learning.

## 10. Related docs

- **Parent design**: [`docs/design/collapse_detection_framework_generic.md`](./collapse_detection_framework_generic.md), [`docs/design/paper_and_collapse_reference_baselines.md`](./paper_and_collapse_reference_baselines.md)
- **Framework rev-6 architecture**: [`docs/design/pluggable_health_checks.md`](./pluggable_health_checks.md)
- **Prior execution plans**: [`m7_loss_implementor_contract_execution_plan.md`](./m7_loss_implementor_contract_execution_plan.md), [`m8_gate_coverage_and_diversity_metrics_execution_plan.md`](./m8_gate_coverage_and_diversity_metrics_execution_plan.md)
- **Empirical basis**: [experiment report](https://github.com/Galileo-Sandbox/siderius-exp/blob/e9e5063b/reports/health_metrics_scan.md)
- **Priorities**: [`docs/design/v17_priorities.md`](./v17_priorities.md) — add M9 row after issue opens
