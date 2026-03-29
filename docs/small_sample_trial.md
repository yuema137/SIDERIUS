# Proposal: Physics-Anchored Multi-Fidelity Tuning for TIDMAD

## Status: Phase 6 logic complete — formal mode blocked by data loader memory (Phase 4b)

---

## 1. Objective

Optimize the `tune_ml_hyperparam_agent` for 20 large-scale files (10 MS/s). Implement a
**Segment-Level Fixed-Anchor Scoring** system to ensure mathematical consistency between
"Trial" (sparse sampling) and "Formal" (full data) modes, enabling precision targeting of
specific frequency bands.

## 2. Core Logic: The "Budgeted Linear" Workflow

* **Trial Mode:** Rapid iteration using a `trial_portion` of data. Outputs a **Score Vector**
  for the specific files/segments sampled.
* **Formal Mode:** A comprehensive pass over all 20 files. Outputs the **Full 20-element
  Vector** and a **Final Scalar Score**.
* **Linearity:** Every run is treated as an atomic task (Input → Experiment → Result).

---

## 3. Physical Constraints & Dynamic Scoring (The "Fixed Ruler")

To eliminate "Score Drift" across different sampling portions, we must anchor the scoring
to a fixed physical reference.

### A. Pre-computation: The Segment Anchor Map (One-time)

A new script scans all 20 raw validation files (CH2 ground truth only), computes the
per-segment SNR, and stores the results. This needs to be built.

1. **Scan:** Iterate through every 1-second segment $j$ in every validation file $i$
   (files 0–19, 200 segments per file = 4000 segments total).
2. **Calculate:** Compute the injected signal SNR from **CH2 (Ground Truth)**:
   $S_{i,j} = \text{getSNR}(\text{PSD}(\text{CH2}_{i,j}))$.
3. **Universal Peak:** Identify the global maximum SNR across all segments in all files:
   $S_{max} = \max(S_{i,j})$.
4. **Store:** Save the mapping $\{ (i, j): S_{i,j} \}$ and the constant $S_{max}$ into
   `segment_anchors.json`.
5. **Rationale:** $S_{max}$ serves as the "Universal Denominator," representing the
   hardware's maximum possible output.

**Implementation note:** The building blocks already exist. `GetOneSecPSD()` and `getSNR()`
in `execute_tools/denoising_score_single.py` compute exactly the per-segment CH2 SNR
needed here (via `process_iteration` with `ch=2`). The pre-computation script is essentially
a loop calling these functions across all 20 files and collecting the results, with parallel
processing support for speed. No new physics code is needed — only the orchestration and
storage.

### B. Detailed Denoising Score Calculation (Dynamic & Normalized)

The Denoising Score is **not** a static file-level attribute. It must be computed dynamically
for each specific sample to reflect the true performance on the data seen by the model.

For each **sampled** segment $j$ in file $i$:

1. **Identify Ground Truth Strength:** Retrieve the pre-computed $S_{i,j}$ (the "local
   weight") and $S_{max}$ (the "global scale") from the Anchor Map.
2. **Calculate Segment Weight:** $$Weight_{i,j} = \frac{S_{i,j}}{S_{max}}$$
   *(This ensures that segments with stronger hardware injection contribute more to the
   final score, regardless of which segments were sampled).*
3. **Compute Denoised SNR:** Calculate $SNR_{SQUID, i, j}$ from the model's output (CH1).
4. **Calculate File-Level Vector Element:** The score for file $i$ is the average of the
   weighted SNRs of the **sampled segments only**:
   $$\text{FileScore}_i = \frac{1}{n_{\text{sampled}}} \sum_{j \in \text{SampleSet}_i} (SNR_{SQUID, i, j} \times Weight_{i,j})$$
5. **Aggregate Final Scalar:**
   $$\Lambda = \frac{1}{N_{\text{non-NaN}}} \sum_{i \in \text{non-NaN}} \text{FileScore}_i \quad \rightarrow \quad Score = \log_{5.27}(\Lambda + 1e-10)$$

### C. Score Vector Convention

The score vector always has **fixed length = 20** (indices 0–19). Files not included in
the run have value `NaN`. Aggregation (final scalar) averages only over non-NaN entries.
This ensures the vector shape is stable regardless of trial strategy.

### D. How This Differs from the Current Scoring

**Current** (`execute_tools/denoising_score_single.py`):
- Operates on a **single file** (one `file_index`).
- Already works at the segment level (1-second segments, `N=10,000,000` samples).
- Per-segment: computes `snr_sg` (CH2 ground truth) and `snr_squid` (CH1 denoised).
- **Normalization is file-local**: `snr_sg = snr_sg / np.amax(snr_sg)` — divides by
  the max SNR within that one file.
- Final score: `log_{5.27}(weighted_mean + 1e-10)`.

**Legacy** (`/home/tidmad/TIDMAD/denoising_score_old.py`):
- Operates on **all 20 files at once** (builds a file list of all 20 validation files).
- Same segment-level computation (`process_iteration` → `GetOneSecPSD` → `getSNR`).
- **Normalization is global**: because all 20 files are in one array, `np.amax(snr_sg)`
  is the global max across all files — effectively a cross-file anchor.
- Same log-base-5.27 scoring formula.

**Proposed change**:
- Replace file-local normalization with the **pre-computed global anchor** from
  `segment_anchors.json`. At scoring time, segment weights are looked up from the
  anchor map instead of being re-computed and normalized per-file.
- This makes trial-mode scores (sparse sampling of a few files) directly comparable
  to formal-mode scores (all 20 files), because the denominator ($S_{max}$) is fixed
  and identical in both cases.
- The segment-level SNR computation itself (`GetOneSecPSD`, `getSNR`, `process_iteration`)
  does not change — only the normalization step changes.

---

## 4. Sampling Strategies & Alignment

### A. Strict Segmentation and the Two Segment Concepts

There are two distinct "segment" concepts in the system — they must not be confused:

| Concept | Size | Who controls it | Flexible? |
|---------|------|-----------------|-----------|
| **PSD segment** | 10,000,000 samples (1 second) | Physics / scoring | **No** — fixed by PSD frequency resolution |
| **ML segmentation_size** | Varies (e.g. 10k–100k) | Tuning agent / model config | **Yes** — hyperparameter |

The **PSD segment** is the atomic, indivisible unit for data loading and scoring. The
`SampleSet` specifies data in units of PSD segments (file index + segment index). The
ML model's `segmentation_size` further subdivides each PSD segment internally during
training/inference — this is the tuning agent's concern, not the sampling strategy's.

The constraint `segmentation_size` divides evenly into 10,000,000 is naturally satisfied
by all current models (e.g. 10M / 50k = 200 chunks).

**All sampling must be aligned to integer multiples of PSD segment length** (10,000,000
samples = 1 second). Partial PSD segments are strictly prohibited.

### B. Trial Strategies

| Strategy | Selection Logic | Use Case |
| :--- | :--- | :--- |
| **`snapshot`** | Randomly sample `portion` from **each of all 20 files**. | Evaluate generalization across the entire spectrum. |
| **`anchors`** | Sample `portion` only from **File 0, 10, and 19**. | Rapid detection of performance at frequency extrema. |
| **`target`** | Sample only from **specified `target_files`**. | Deep optimization of specific problematic bands (e.g., [0,1,2,3]). |

### C. `train_validation_align` Definitions

* **`True` (Performance Peak):** The Validation set uses the **exact same** segment indices
  as the Training set.
* **`False` (Generalization):** The Validation set follows the same strategy but uses a
  **different random seed or offset**, ensuring the model is tested on unseen 1-second
  segments.

---

## 5. Implementation Strategy: Additive, Non-Breaking

**Critical constraint:** All existing code must remain runnable. New functionality is added
alongside existing functions, never replacing them. The existing single-file flow
(`sandbox_executor` → CLI → `calculateBenchmark`) is untouched.

### A. The SampleSet: Single Source of Truth

In trial mode, training, inference, and scoring all need to agree on **which segments from
which files** to operate on. This is the `SampleSet` — determined once by the sampling
strategy and passed consistently through all three stages.

```
SampleSet = {
    file_index: [segment_indices],   # e.g. {0: [3, 17, 42], 6: [0, 1, ..., 199]}
    ...
}
```

The current single-file flow is a special case: `SampleSet = {file_index: all_segments}`.

### B. Three-Layer Data Flow (Current vs Trial)

| Layer | Current flow | Trial mode |
|-------|-------------|------------|
| **Training** | Load full file by `file_index` via `TIDMADDataset` | Load specific segments from specific files per `SampleSet` |
| **Inference** | Denoise full file by `file_index` | Denoise only the segments in `SampleSet` |
| **Scoring** | `denoising_score_single.py` CLI: score all segments in one file, file-local normalization | New function: score only `SampleSet` segments, anchor-normalized |

All three layers receive the same `SampleSet`. This ensures the model is scored on exactly
the data it was trained on (or a controlled offset if `train_validation_align=False`).

### C. Changes to `execute_tools/denoising_score_single.py`

**Keep untouched** (existing callers depend on these):
- `GetOneSecPSD()`, `findPeak()`, `getSNR()`, `process_iteration()` — segment-level
  building blocks, already correct.
- `calculateBenchmark()` — the existing full-file scoring function.
- The `argparse` CLI block at the bottom — `sandbox_executor.py` calls this via subprocess.

**Add new functions** (used by the trial-mode path):

1. **`build_anchor_map(data_dir, parallel, num_workers) → dict`**
   One-time pre-computation. Scans all 20 raw validation files (CH2 only), computes
   per-segment SNR using the existing `process_iteration()`, returns
   `{"anchors": {(i, j): snr_sg}, "s_max": float}`. Writes to `segment_anchors.json`.
   Could also live in a separate script.

2. **`score_segments(data_dir, denoised_file, segment_indices, anchor_map, s_max) → float`**
   Scores only the specified segments of one denoised file. For each segment:
   computes `snr_squid` (CH1), looks up the pre-computed weight from the anchor map,
   returns the weighted average (one `FileScore` float). Uses the existing `GetOneSecPSD()`
   and `getSNR()` internally.

3. **`score_vector(data_dir, sample_set, anchor_map, s_max) → (List[float], float)`**
   Calls `score_segments()` for each file in the `SampleSet`. Returns:
   - A length-20 list (`NaN` for files not in the sample set)
   - The aggregated scalar score (average of non-NaN entries, log-base-5.27)

### D. What Does NOT Change

- The existing `sandbox_executor.py` → `denoising_score_single.py` CLI path is untouched.
- `calculateBenchmark()` still works for the current single-file flow.
- All existing unit and integration tests pass without modification.
- New functions share the same low-level building blocks (`GetOneSecPSD`, `getSNR`, etc.).

---

## 6. Schema Design (Resolved)

### A. Input: Flat optional fields on `HyperparamTuningInput`

Trial-mode fields are added **directly** to the existing `HyperparamTuningInput` as
optional fields with defaults that preserve current behavior. No nested `TuningBudget`
object — the interface stays flat.

When none of the trial fields are provided, the tuner runs in **normal mode** with a
required `file_index`, exactly as today. When `is_trial=True`, the tuner switches to
**trial-explore mode** and builds a `SampleSet` from the trial strategy.

```python
# --- Existing fields (unchanged) ---
class HyperparamTuningInput(BaseModel):
    model_type: str
    file_index: int = 6
    max_rounds: int = 10
    expert_advice: ...
    # ... all current fields ...

    # --- New optional trial fields (default = normal mode) ---
    is_trial: bool = Field(default=False,
        description="When True, run in trial-explore mode with sparse sampling.")
    trial_portion: float = Field(default=0.1, ge=0.0, le=1.0,
        description="Fraction of segments to sample per file. Only used when is_trial=True.")
    trial_strategy: Literal["snapshot", "anchors", "target"] = Field(default="snapshot",
        description="Sampling strategy. Only used when is_trial=True.")
    target_files: List[int] = Field(default_factory=list,
        description="File indices to sample from. Required when trial_strategy='target'.")
    train_validation_align: bool = Field(default=True,
        description="When True, validation uses same segments as training.")
```

**Normal mode** (`is_trial=False`, the default): `file_index` is required, trial fields
are ignored. The tuner runs on a single file as today.

**Trial mode** (`is_trial=True`): the `SampleSet` is built from `trial_strategy`,
`trial_portion`, and `target_files`. `file_index` is ignored (or used as a fallback).

### B. Output: Unified scoring across both modes

Both modes produce the same scoring structure. The current `best_denoising_score` (float)
is replaced by a unified `DenoisingResults` that always contains a vector and a scalar.

```python
class DenoisingResults(BaseModel):
    file_vector: List[float]  # Fixed length 20. NaN for files not included.
    final_scalar_score: float  # Average of non-NaN entries, log-base-5.27.
```

**Normal mode** (single `file_index=6`): vector has 19 NaN entries and 1 real value at
index 6. `final_scalar_score` equals that single value.

**Trial mode** (e.g. snapshot strategy, 20% portion): vector has real values for all 20
files (sparse-sampled), NaN for none. `final_scalar_score` is the average.

**Trial mode** (e.g. target strategy, files [0,1,2,3]): vector has 4 real values, 16
NaN entries. `final_scalar_score` averages the 4 non-NaN values.

The scalar is always derivable from the vector, but stored explicitly for convenience
and backward compatibility (it replaces `best_denoising_score` in the output).

### C. Experiment Record: Trial context in agent memory

The agent's research memory must capture **what data was used** to produce a score.
Without this, the agent cannot reason about results correctly — e.g., distinguishing a
score drop caused by a worse config from one caused by sampling harder files.

Trial parameters are recorded per experiment record. The concrete segment indices are
**not** stored — only the strategy-level parameters that the agent can reason about.
The sampling is reproducible from these parameters.

Fields added to `ExperimentRecord` (alongside the existing config/score fields):

```python
# Trial context — only meaningful when is_trial=True.
# When is_trial=False, these are absent or set to defaults,
# and the record looks identical to today's format.
is_trial: bool = False
trial_strategy: Optional[str] = None       # "snapshot" / "anchors" / "target"
trial_portion: Optional[float] = None      # e.g. 0.1
train_validation_align: Optional[bool] = None
target_files: Optional[List[int]] = None   # only for "target" strategy
file_vector: Optional[List[float]] = None  # length 20, NaN for excluded files
```

**Why this matters for the agent's reasoning:**
- The agent can see that "experiment A scored 0.7 on 10% snapshot across all 20 files"
  while "experiment B scored 0.8 on file 6 only" — these are not directly comparable.
- When switching from trial to formal mode, the agent understands why scores may shift.
- The `file_vector` lets the agent identify which frequency bands (files) are weak and
  propose targeted strategies (e.g., switch to `target` mode on the worst-scoring files).

---

## 7. Iteration Control: Who Decides Trial vs Formal

The decision of *whether* to run trial mode and *which strategy* to use is governed by
three levels of authority. The hierarchy is: **hard constraints (code) > expert advice
(upstream agent or human) > LLM judgment (brain.plan).**

### A. The agent loop enforces the final-round constraint

The final round of a tuning run **must** be formal (`is_trial=False`). This is not a
suggestion — it is enforced in code inside the agent's `run()` loop:

```python
while completed_rounds < max_rounds and total_attempts < max_attempts:
    is_last_round = (completed_rounds == max_rounds - 1)

    if is_last_round:
        # Hard constraint: final round is always formal.
        is_trial_this_round = False
        sample_set = None
    else:
        # LLM decides, within expert-advice constraints (see below).
        is_trial_this_round = decision.get("is_trial", True)
        if is_trial_this_round:
            sample_set = build_sample_set(...)
        else:
            sample_set = None
```

This guarantees every tuning run ends with a complete, formal score over all 20 files,
regardless of what the LLM or expert advice chose in earlier rounds.

**Special case: `max_rounds=1`.** When there is only one round, it is both the first
and last round — formal mode is enforced. The `is_trial` input field is ignored. This
means single-round runs always produce a definitive score.

### B. Expert advice constrains LLM choices

Expert advice (from upstream agents or human input via `expert_advice` / `human_advice`)
can constrain the LLM's trial/formal decisions for non-final rounds. This follows the
same pattern as hyperparameter guidance — the agent respects expert constraints but
retains autonomy within those bounds.

Examples of expert-advice constraints:
- `"Always use trial mode with snapshot strategy for the first 5 rounds"` — the LLM
  must use trial/snapshot but can choose `trial_portion` and other params.
- `"Use formal mode for all rounds"` — the LLM cannot use trial mode at all. The
  final-round constraint is redundant but still enforced.
- `"trial_portion must be >= 0.2"` — the LLM can choose portion freely above 0.2.
- `"Focus on files [0, 1, 2, 3] using target strategy"` — the LLM uses target mode
  with those files but can choose portion and alignment.

When no expert advice mentions trial parameters, the LLM has full autonomy (subject
to the final-round constraint).

### C. The LLM decides strategy for non-final rounds

For all rounds except the last (and within expert-advice constraints), the LLM planner
chooses:
- **Whether to use trial mode** (`is_trial`): the LLM may choose formal mode early if
  it believes the current config is promising and wants a definitive score.
- **Which strategy** (`trial_strategy`): snapshot for broad exploration, anchors for
  quick extrema checks, target for deep optimization of weak files.
- **Sampling density** (`trial_portion`): start with 10% for fast iteration, increase
  to 50% when narrowing in.
- **Validation alignment** (`train_validation_align`): True for peak performance
  measurement, False to test generalization.

The LLM sees the full research memory (including `file_vector` from prior rounds)
and can adapt its strategy. For example:
1. Rounds 1–5: snapshot at 10% — broad hyperparameter search.
2. Rounds 6–8: target on files [0, 1, 2, 3] at 30% — the vector showed these are weak.
3. Round 9 (final): formal — full pass over all 20 files, enforced by code.

### D. What the LLM planner outputs

The existing `plan()` method returns a config dict. The LLM additionally outputs trial
parameters alongside the usual hyperparameter decisions:

```json
{
    "model_type": "punet",
    "hypothesis": "Increasing lr to 3e-4 with focal loss...",
    "config": { ... },
    "is_trial": true,
    "trial_strategy": "target",
    "trial_portion": 0.3,
    "target_files": [0, 1, 2, 3],
    "train_validation_align": true
}
```

When the agent overrides `is_trial=False` on the final round, the LLM's trial fields
are simply ignored. When expert advice constrains a field (e.g. forces
`trial_strategy="snapshot"`), the LLM's value for that field is overridden.

### E. Schema implications

The `HyperparamTuningInput` field `is_trial` changes meaning. Previously it was a
static flag for the entire run. Now:

- **`is_trial` on input**: serves as the **default** for non-final rounds when the LLM
  does not specify. When `is_trial=False` on input, the agent runs in formal mode for
  all rounds (the LLM cannot override this to trial — it is treated as an expert
  constraint). When `is_trial=True`, the LLM has autonomy to choose per-round.
- **`trial_strategy`, `trial_portion`, etc. on input**: serve as defaults / constraints
  that the LLM can adjust within bounds.
- **Per-round decisions**: stored in each `ExperimentRecord` so the research memory
  accurately reflects what mode each experiment used.

---

## 8. Implementation Plan

Phases are ordered by dependency. Each phase is independently testable and must not
break existing behavior. After each phase, all existing tests must still pass.

### Phase 0: Anchor map pre-computation — DONE

**What:** Build the `segment_anchors.json` file — the one-time pre-computation that
scans all 20 raw validation files and produces per-segment CH2 SNR weights + global max.

**Files created:**
- `execute_tools/scoring_utils.py` — shared low-level functions (`get_one_sec_psd`,
  `get_snr`, `find_peak`, `process_segment`) and constants (`SEGMENT_LENGTH`,
  `SEGMENTS_PER_FILE`, `NUM_FILES`). Clean importable versions — the originals in
  `denoising_score_single.py` are untouched.
- `execute_tools/build_anchor_map.py` — `build_anchor_map()` for programmatic use,
  `load_anchor_map()` for reading back, CLI for one-time generation.
- `tests/unit/execute_tools/test_build_anchor_map.py` — 11 unit tests (mocked, no
  real data needed).

**Verified on real data:** ran on all 20 TIDMAD files, produced 78 KB JSON with 4000
entries and `S_max = 295,715,731`.

---

### Phase 1: New scoring functions — DONE

**What:** Add `score_segments()` and `score_vector()` to `scoring_utils.py`. These use
the pre-computed anchor map for normalization instead of file-local normalization.

**Design note:** new functions live in `scoring_utils.py` (not `denoising_score_single.py`)
because that file's argparse runs at module level, making it un-importable.
`denoising_score_single.py` and `calculateBenchmark()` are completely untouched.

**Files changed:**
- `execute_tools/scoring_utils.py` — added `score_segments()`, `score_vector()`, and
  `SampleSet` type alias.
- `tests/unit/execute_tools/test_scoring_utils.py` (new) — 11 unit tests covering
  anchor weight application, averaging, NaN handling, scalar formula, edge cases.

**Verified on real data:** scored file 6 (punet baseline denoised) with the real anchor
map. Full-file anchor-normalized score: -0.2915. 10% sample (20 segments): -0.3670.
The difference between the existing file-local score (1.7921) and anchor-normalized
score (-0.2915) is expected — anchor normalization divides by the global S_max (~296M)
rather than the file-local max (~9.3M), producing scores on a cross-file physical scale.

**Total unit tests after Phase 0+1:** 540 passed (22 new), 0 broken.

---

### Phase 2: Schema changes — DONE

**What:** Extend `HyperparamTuningInput`, `ExperimentRecord`, and `HyperparamTuningOutput`
with optional trial fields. All new fields have defaults that preserve current behavior.

**Files changed:**
- `agent/schemas/hyperparam_tuning.py`:
  - `HyperparamTuningInput`: added 5 optional trial fields (`is_trial`, `trial_portion`,
    `trial_strategy`, `target_files`, `train_validation_align`). All default to normal
    mode — existing callers are unaffected.
  - `ExperimentRecord`: added 6 optional trial context fields (`is_trial`,
    `trial_strategy`, `trial_portion`, `train_validation_align`, `target_files`,
    `file_vector`). All `None`/`False` by default.
  - `HyperparamTuningOutput`: added `best_file_vector: Optional[List[float]] = None`.
- `tests/unit/agent/tune_ml_hyperparam_agent/test_hyperparam_schemas.py`:
  11 new tests covering backward compatibility, default values, trial-mode validation,
  invalid strategy/portion rejection.

**All 28 existing schema tests pass unchanged. 39 total (28 + 11 new).**

**Note:** No real API call test added — trial fields are pure schema with no runtime
behavior change yet. Integration tests come at Phase 5 when the agent reads `is_trial`.

**Total unit tests after Phase 0+1+2:** 551 passed, 0 broken.

---

### Phase 3: SampleSet builder — DONE

**What:** A pure function `build_sample_set()` that translates trial parameters into
a concrete `SampleSet` (`dict[int, list[int]]` — file index → sorted segment indices).
This is the single object passed to training, inference, and scoring.

**Inputs:** `is_trial`, `file_index`, `trial_strategy`, `trial_portion`, `target_files`,
`seed`. These map directly to the `HyperparamTuningInput` fields from Phase 2 (except
`seed`, which is controlled by the caller for `train_validation_align` behavior).

**Output:** `SampleSet` dict. Examples:
- Normal mode: `{6: [0, 1, ..., 199]}`
- Snapshot 10%: `{0: [6, 7, 8, ...], 1: [1, 6, 40, ...], ..., 19: [2, 17, ...]}`
- Target [0,1,2,3] at 30%: `{0: [1, 6, 7, ...], 1: [8, 14, ...], ...}`

**Files created:**
- `execute_tools/sample_set_builder.py` — `build_sample_set()` implementing all three
  strategies (snapshot, anchors, target) plus normal mode. Pure function, deterministic
  with seed, minimum 1 segment per file, no I/O.
- `tests/unit/execute_tools/test_sample_set_builder.py` — 21 tests: normal mode (4),
  snapshot (7), anchors (2), target (5), edge cases (3).

**Verified interactively:** all modes produce correct file/segment counts, segments are
sorted with no duplicates, same seed = identical results.

**Total unit tests after Phase 0+1+2+3:** 572 passed, 0 broken.

---

### Phase 4: Training and inference with SampleSet — DONE

**What:** Extend data loading, inference, and the sandbox executor to accept an optional
`SampleSet`. When absent, all behavior is identical to before. When provided, training
loads specific PSD segments from multiple files, and inference denoises only those
segments, writing one H5 per file.

**Files changed:**
- `execute_tools/train_engine_sandbox.py`:
  - `TIDMADDataset`: added optional `sample_set` parameter and
    `_pull_events_from_sample_set()` method. Each PSD segment (10M samples) is
    subdivided into ML segments of `segmentation_size`. Normal mode path untouched.
  - Added `--sample_set_json` CLI argument.
- `execute_tools/inference_single.py`:
  - Added `--sample_set_json` CLI argument. Trial mode loops over files in the
    SampleSet, denoises only requested PSD segments, writes one H5 per file.
    Normal mode path untouched.
- `core/sandbox_executor.py`:
  - `execute_training()` and `execute_inference()`: added optional `sample_set`
    parameter. When provided, writes SampleSet to temp JSON and passes
    `--sample_set_json` to the subprocess. When absent, identical to before.

**Tests:**
- No new unit tests — trial-mode data loading requires real HDF5 files.
- All 572 existing unit tests pass unchanged (regression confirmed).
- Real integration test deferred to Phase 5, where the full pipeline (build SampleSet
  → train → infer → score) can be tested end-to-end.

**Output convention:** trial-mode denoised files use the same naming as normal mode:
`abra_validation_denoised_{model}_{run_name}_{exp_id}_{file_index:04d}.h5`.
The `exp_id` is unique per experiment, and trial parameters are recorded in the
`ExperimentRecord` — no separate naming needed.

**Total unit tests after Phase 0–4:** 572 passed, 0 broken.

**⚠ CRITICAL LIMITATION — Memory model does not scale to formal mode (all 20 files):**

The `_pull_events_from_sample_set()` method in `TIDMADDataset` loads **all files'
segments into memory simultaneously** via `self.idict` and `self.tdict`. This works for
trial mode (sparse sampling → small total data), but **causes OOM when used for formal
mode** (all 200 segments × 20 files = 4000 PSD segments ≈ 40+ GB of training data in RAM).

This was confirmed during Phase 6 integration testing: the formal round (final round,
`trial_portion=1.0, snapshot, all 20 files`) triggered a kernel OOM kill at ~50 GB RSS
on a 61 GB machine.

**Root cause:** The data loader accumulates extracted segments from every file into
in-memory dicts (`idict[filename] = array`, `tdict[filename] = array`), then shuffles
across all files. This cross-file shuffling requires all data to be resident
simultaneously. Additionally, each file is loaded in full (`np.array(f[...])`) even
when only a subset of segments is needed — HDF5 direct slicing is not used.

**How the legacy scripts (`/home/tidmad/TIDMAD/`) avoid this:**

| Script | Strategy | Peak memory per file | All-files memory |
|--------|----------|---------------------|-----------------|
| `train.py` | **Sequential file streaming** — trains on one file at a time, frees it, moves to next. No cross-file shuffling. | ~400 MB (2 GB / subsample) | ~400 MB (one file at a time) |
| `train_nosplit.py` | **Aggressive subsampling** — loads all 20 files but keeps only 1/5 of each (`sample_size=5`), stores as `int8`. | ~400 MB | ~8 GB (20 × 400 MB) |
| **Our code** | **Full accumulation** — loads all requested segments from all files into memory, stores CH2 as `int16`. | ~2 GB (full file load) + extracted segments | **40+ GB for formal mode** |

**Two-part fix required (Phase 4b — not yet implemented):**

1. **HDF5 direct slicing**: Instead of `np.array(f['timeseries'][...])` (loads entire
   2 GB file), read only the needed segments directly from HDF5:
   `chunk = f['timeseries']['channel0001']['timeseries'][start:end]`. This eliminates
   the peak ~2 GB per-file overhead during extraction.

2. **Sequential file training (streaming)**: Follow `train.py`'s pattern — train on
   one file's segments, free them, move to the next file. This means no cross-file
   shuffling within an epoch, but each epoch sees all files in sequence. This limits
   peak memory to one file's extracted segments (~200 MB at `segmentation_size=10000`).

   The tradeoff: cross-file shuffling may improve generalization, but the legacy
   approach without it produced the paper's published results — so sequential training
   is validated and sufficient.

**Impact on formal mode:** Until this fix is implemented, formal mode (all 20 files ×
all 200 segments) will OOM on machines with < ~60 GB free RAM. Trial mode with small
portions (≤ 10%) works fine. The same limitation applies to inference
(`inference_single.py`), though inference processes files one at a time already and is
less affected.

---

### Phase 5: Wire into tuning agent (static trial mode) — DONE (partial)

**What:** Connect the trial fields in `HyperparamTuningInput` to the actual execution
pipeline. When `is_trial=True`, the agent builds a `SampleSet`, passes it to training/
inference/scoring, and records trial context in `ExperimentRecord`.

**Completed:**
- `nodes/ml_hyperparameter_tune_agent.py` — trial-mode branch in `run()`: builds
  SampleSet once at startup, passes to training/inference skills, uses `score_vector()`
  for scoring, records trial context in `ExperimentRecord`.
- `agent/skills/training_skill/wrapper.py` — passes `sample_set` to executor.
- `agent/skills/inference_skill/wrapper.py` — passes `sample_set` to executor.
- Integration test: `TestTrialModeGemini::test_punet_trial_snapshot` in
  `tests/integration/nodes/test_tune_ml_hyperparam_agent.py`.

**Limitation:** trial mode is currently **static** — `is_trial` is read once from input
and applied identically to every round. The LLM cannot choose trial vs formal per round,
and there is no final-round formal enforcement.

**Known bug (found during Phase 5 testing):** `score_segments()` reads the denoised file
using the original PSD segment index (e.g. 185), but trial-mode inference packs segments
contiguously (segment 185 → local position 1). Fix: use `local_idx` (enumerate position)
for the denoised file, original `seg_idx` for the raw file and anchor lookup. See
`execute_tools/scoring_utils.py:206`.

**Depends on:** Phase 2 (schemas), Phase 3 (SampleSet), Phase 4 (data loading).

---

### Phase 6: Dynamic per-round trial/formal control — DONE (partial)

**What:** Upgrade the agent's internal loop from static `is_trial` to dynamic per-round
decisions. The agent's `brain.plan()` returns trial parameters each round, and the loop
enforces the final-round formal constraint in code.

**Completed:**

1. **`ExperimentPlan` schema** (`agent/schemas/hyperparam_tuning.py`):
   Pydantic model validating `brain.plan()` output. Hyperparameter fields (`model_type`,
   `hypothesis`, `reasoning`, `model_cfg`, `train_cfg`, `loss_cfg`) plus per-round trial
   fields (`is_trial`, `trial_strategy`, `trial_portion`, `target_files`,
   `train_validation_align`). Defaults bias toward trial mode (`is_trial=True`,
   `trial_portion=0.02`). `with_defaults()` classmethod strips invalid trial fields on
   `ValidationError` and retries with defaults. `model_config` is aliased to `model_cfg`
   because `model_config` is reserved by Pydantic v2.

2. **Agent loop** (`nodes/ml_hyperparameter_tune_agent.py`):
   - SampleSet built **per-round** inside the loop from `ExperimentPlan`.
   - Override chain: `not trial_allowed` → formal; `completed_rounds == max_rounds - 1`
     → formal. Formal mode builds a full SampleSet (`snapshot, portion=1.0`).
   - Legacy single-file mode preserved when `trial_allowed=False` (`sample_set=None`).
   - `trial_config_{exp_id}.json` written before each round — makes the mode explicit
     (trial, formal, or single_file) with all structured parameters.
   - All `decision.get()` replaced with validated `plan.X` fields.
   - Trial record fields populated from per-round `plan`, not static `agent_input`.

3. **LLM planner** (`agent/prompts.py`):
   - `### TRIAL vs FORMAL MODE` section added to system prompt explaining strategies,
     portions, and when to use each mode.
   - `get_planner_user_prompt()` extended with `current_round`, `max_rounds`,
     `trial_allowed`. Round context section tells the LLM which round it's on and
     whether this is the final round.
   - OUTPUT FORMAT includes `is_trial`, `trial_strategy`, `trial_portion`.

4. **LLM bridge** (`agent/llm_bridge.py`):
   - `plan()` forwards `current_round`, `max_rounds`, `trial_allowed` to prompt generator.

5. **Scoring**: Both trial and formal rounds use `score_vector()` with anchor-normalized
   scoring. The legacy `denoising_score_single.py` is only used when `trial_allowed=False`.

6. **Bug fix** (`execute_tools/scoring_utils.py`): `score_segments` local-index bug
   fixed — uses `local_idx` (enumerate position) for denoised file, original `seg_idx`
   for raw file and anchor lookup.

**Files changed:**
- `agent/schemas/hyperparam_tuning.py` — `ExperimentPlan` schema, `ConfigDict` import
- `nodes/ml_hyperparameter_tune_agent.py` — per-round loop refactor, `trial_config` write
- `agent/prompts.py` — trial mode system prompt, round context in user prompt
- `agent/llm_bridge.py` — forward round context through `plan()`
- `execute_tools/scoring_utils.py` — local-index bug fix

**Unit tests (all pass, 611 total):**
- `TestExperimentPlan`: 12 tests — validation, defaults, fallback, strategies
- `TestDynamicTrialFormal`: 4 tests — final-round enforcement, trial_allowed=False,
  round context passing, invalid field fallback
- All 21 existing agent loop tests pass unchanged (regression confirmed)

**Integration test status:**
- Single-file legacy mode (`TestRealRunGemini::test_punet_gemini[loss_cfg0]`): **PASSED**
- Trial→formal 2-round test (`TestTrialModeGemini::test_punet_trial_to_formal`):
  **Round 1 (trial) PASSED, round 2 (formal) OOM-killed.** See Phase 4 limitation above.
  The formal round builds `SampleSet(snapshot, portion=1.0)` = 4000 PSD segments across
  20 files. The training data loader tries to hold all files' data in memory
  simultaneously, exceeding available RAM (~50 GB RSS on a 61 GB machine).

**⚠ BLOCKING LIMITATION for formal mode integration test:**

The formal round (final round of a trial-allowed run) cannot complete on current hardware
due to the Phase 4 data loader memory model. The agent logic is correct — it correctly
builds the full SampleSet and attempts training. The failure is in the data pipeline, not
the trial/formal control logic.

**Options to unblock:**
1. **Fix the data loader** (Phase 4b): implement sequential file streaming as described
   in the Phase 4 limitation section. This is the correct long-term fix.
2. **Reduce formal scope for testing**: use a smaller formal round in the integration
   test (e.g. fewer files) to validate the trial→formal transition mechanism without
   triggering OOM. This validates the code path but not production-scale formal mode.

**Depends on:** Phase 5 (static trial wiring). Full formal mode depends on Phase 4b
(data loader fix).

---

### Phase 7: Downstream consumers (if needed)

**What:** Update downstream modules that read `denoising_score` or `best_denoising_score`
to also handle the new `file_vector` field. These changes are **optional** — existing
scalar fields are preserved, so downstream consumers work without changes. This phase
adds *enriched* support.

**Files potentially affected** (only if we want vector-aware display):
- `agent/schemas/interpretation.py` — `best_denoising_score` / `worst_denoising_score`
- `agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py`
- `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py`
- `dashboard/api/models.py` — `ExperimentRecord.denoising_score`
- `dashboard/static/app.js` — chart rendering
- `dashboard/data_sources/local_json.py` — leaderboard ranking

**Tests:** update corresponding unit tests if any schema or protocol changes.

**Depends on:** Phase 5 (data flowing through the system).

---

### Dependency graph

```
Phase 0 (anchor map) ✓
    └── Phase 1 (scoring functions) ✓

Phase 2 (schemas) ✓         Phase 3 (SampleSet builder) ✓
    │                           │
    └───────────┬───────────────┘
                │
          Phase 4 (data loading) ✓
                │
          Phase 4b (streaming data loader) ← BLOCKS formal mode
                │
          Phase 5 (static trial wiring) ✓
                │
          Phase 6 (dynamic trial/formal) ✓ (formal round blocked by 4b)
                │
          Phase 7 (downstream, optional)
```

Phases 0, 2, and 3 have no dependencies on each other and can be built in parallel.
Phase 6 logic is complete but formal-mode integration testing is blocked by Phase 4b.
