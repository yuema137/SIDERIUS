# Aggregated Score Table Awareness — Design Doc

## Status: **Phases 1–6 landed; Phase 6.5 Stage 1 green (2026-04-22).** Phase 6.5 Stage 2 (real-GPU semantic smoke) is the last gate before Phase 7 (`small_sample_trial_v1` launch).

---

## 1. Problem statement

Today every agent in the graph — tuner, interpreter, proposer — sees per-file
performance as a bare length-20 `file_vector` of log-space scores. The numbers are
numerically correct (post-Option-B), but they carry **no anchor for "how good is
this?"**:

- A per-file score of `4.45` on file 11 is *meaningless* without knowing that the
  raw baseline at file 11 is `-0.06` and the ground-truth ceiling is `8.81`.
- The tuner prompt currently tells the LLM that "a per-file score of ~1.0 means the
  model performs about the same as no denoising at all (raw data)"
  (`agent/prompts.py:149-151`). This is an *approximation* — the actual raw
  baseline per file varies from `-13.854` (clip floor, files 0–2) to `+1.83`
  (file 17) and the ceiling varies from `-13.854` to `+11.22`. The single number
  "~1.0" has no grounding in the actual reference data.
- The prompt instructs "compare your `file_vector` against the baseline's"
  (`agent/prompts.py:155`) but we never actually pass the baseline's file_vector
  into the prompt — the LLM has nothing to compare against.

The agents are therefore guessing at context that we have precisely measured and
committed to the repo (`reference_data/raw_and_ground_score.md` + the 20 + 20
per-file JSONs at `{SIDERIUS_DATA_DIR}/{raw_baseline,ground_truth}/`).

## 2. Goal

Replace the bare `file_vector` surfaced to every agent with a **comprehensive
per-file score comparison table**. Each row contains:

| file | raw_baseline | ground_truth | model | gain vs raw | headroom vs gt |

Plus an aggregated-scalar sub-table with one number per row — the log-space
scalar from `score_vector()` for raw baseline, model, and ceiling — and the
percent-of-ceiling recovery (ratio of log scalars). The log scalar is the
*only* aggregation that exists; there is no separate "grand mean" concept.

The exact rendered markdown format is specified in §6 below. Reference columns
(`raw_baseline`, `ground_truth`) come from the committed, canonical
`reference_data/raw_and_ground_score.md` — which in turn loads from the
per-file JSONs under `{SIDERIUS_DATA_DIR}/raw_baseline/` and
`{SIDERIUS_DATA_DIR}/ground_truth/`.

All three columns use **global s_max** (from `segment_anchors.json`). This is
not a design choice — it is already the committed state of every scorer:
`compute_raw_baseline.py:112`, `compute_ground_truth.py:70`, and
`scoring_utils.score_vector` all divide per-segment values by the same global
`s_max` from the anchor map.

The same aggregated table flows:

```
scoring_utils.score_vector(...)            ← produces linear file_vector
      │
      ▼
tuner ───────────────────► interpreter ──────────────────► proposer
   ^                            ^                              ^
   │                            │                              │
   └─ render comparison table ──┴── carry structured table ────┘
       into prompts.py                 forward through
                                       model_knowledge_cache
```

## 3. Current flow of `file_vector`

**Produced:**
- `execute_tools/scoring_utils.py::score_vector` — returns `(fv_linear, scalar)`
- Caller applies `log_{5.27}(round(v,2) + 1e-10)` per element → log-space fv

**Stored:**
- `agent/schemas/hyperparam_tuning.py`:
  - `ExperimentRecordSchema.file_vector` (line 227) — per-experiment
  - `HyperparamTuningOutput.best_file_vector` (line 1152) — per-run best
- Tuner persists records to `{workspace}/{run_name}/agent/run_output_*.json`

**Consumed downstream:**
- `agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py` — maps tuner
  `best_file_vector` + `formal_file_vector` into interpretation input
- `agent/schemas/interpretation.py`:
  - `InterpretationInput.best_file_vector` (line 81)
  - `InterpretationInput.formal_file_vector` (line 92)
  - `InterpretationOutput.per_model_file_vectors` (line 316)
  - `InterpretationOutput.weak_frequency_files` (line 322) — derived
- `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py:72` —
  carries `per_model_file_vectors` into proposal input
- `agent/prompts.py:142-159` — tuner system prompt "FILE VECTOR AND SCORING"
  section (the only place today it gets rendered)

## 4. Proposed data contract: `ScoreComparisonTable`

New Pydantic model in **`agent/schemas/score_table.py`** (new file — shared by
tuner, interpreter, proposer schemas).

```python
class PerFileRow(BaseModel):
    file_index: int                   # 0..19
    raw_baseline: Optional[float]     # log-space, global s_max; None → not sampled
    ground_truth: Optional[float]     # log-space, global s_max
    model:        Optional[float]     # log-space; None → file not included in the run
    gain_vs_raw:  Optional[float]     # model - raw_baseline (None if either missing)
    headroom_vs_gt: Optional[float]   # ground_truth - model

class AggregateScalars(BaseModel):
    # All three scalars are computed over the SAME subset of file indices —
    # the ones where model_fv_log[i] is not None. See Decision 14.
    raw_baseline_scalar: float        # grand-mean over the sampled subset
    ground_truth_scalar: float        # grand-mean over the sampled subset
    model_scalar: float               # final_scalar from score_vector() on denoised CH1
    percent_of_ceiling_log: float     # model_scalar / ground_truth_scalar
    num_sampled_files: int            # |sampled_indices|; 20 for formal, <20 for trial

class ScoreComparisonTable(BaseModel):
    rows: List[PerFileRow]            # len == 20 (always — non-sampled files carry model=None)
    aggregate: AggregateScalars
    s_max_global: float               # 295_715_680.1425
    reference_source: str             # "reference_data/raw_and_ground_score.md"
    rendered_markdown: str            # pre-rendered prompt-ready table (§6)
```

**Decision 3 (resolved → A, rendered_markdown lives on the schema):** exactly one place
(`nodes/scoring_helpers.py::render_comparison_table`) is responsible for the
text the LLM sees. The tuner prompt reads this string verbatim — no ad-hoc
formatting inside prompts.py. This is a deliberate separation: the schema
carries both machine-consumable rows (for derived analysis in the interpreter)
and the human/LLM-consumable markdown (for prompt injection).

## 5. Reference-data loader

New module **`nodes/scoring_reference.py`**:

```python
@dataclass(frozen=True)
class ReferenceScores:
    # Per-file log-space values — feed directly into PerFileRow.raw_baseline /
    # PerFileRow.ground_truth.
    raw_per_file_log:        list[float]      # len 20
    gt_per_file_log:         list[float]      # len 20
    # Per-file linear_sum + n_segments — required by build_score_table to
    # recompute the raw/gt grand-mean scalars over a non-full subset
    # (trial-mode runs). See Decision 14.
    raw_per_file_linear_sum: list[float]      # len 20
    raw_per_file_n_segments: list[int]        # len 20
    gt_per_file_linear_sum:  list[float]      # len 20
    gt_per_file_n_segments:  list[int]        # len 20
    # On-disk full-20-file scalars — cheap reference values, redundant with
    # the subset-aware recomputation when all 20 files are sampled.
    raw_scalar_full:         float
    gt_scalar_full:          float
    s_max:                   float

def load_reference_scores() -> ReferenceScores:
    """
    Reads from {SIDERIUS_DATA_DIR}/raw_baseline/*.json (20 per-file + scalar)
    and {SIDERIUS_DATA_DIR}/ground_truth/*.json (20 per-file + scalar).
    Cached module-level on first call.
    """
```

Source of truth is the JSONs, *not* the markdown — the markdown is a human
artifact, the JSONs are the generator output. If any JSON is missing at import
time, raise a configuration error with a pointer to `compute_raw_baseline.py`
and `compute_ground_truth.py`.

**Decision 10 (resolved → C, split helpers by concern):** the reference-data
loader stays in `nodes/` because it does disk I/O, caches state, and serves
as a node-side input-prep step. The pure table-math + rendering helpers
(`build_score_table`, `render_comparison_table`) move to
`execute_tools/scoring_helpers.py` — zero I/O, zero side effects, fit the
"atomic tool" contract alongside `execute_tools/scoring_utils.py`. This
respects the CLAUDE.md Agent-vs-Tool boundary without forcing everything into
one directory.

**Decision 1 (resolved → A):** the raw baseline has no pre-computed scalar today
(`reference_data/raw_and_ground_score.md` line 71 says `n/a`). We need one. The
scalar comes from the same path every other scalar uses — the `final_scalar`
returned by `scoring_utils.score_vector()` — applied to the raw CH1 (i.e. the
raw validation file itself, where CH1 is undenoised). There is no separate
aggregation logic.

- **(a)** extend `compute_raw_baseline.py` to emit
  `{SIDERIUS_DATA_DIR}/raw_baseline/scalar_anchor_normalized.json` alongside
  the per-file JSONs — exact mirror of how `compute_ground_truth.py` produces
  `ceiling_anchor_normalized.json`.
- **(b)** call `score_vector` on raw CH1 inside `load_reference_scores()` at
  import time — no disk file, but ~15 min of redundant FFT work per process
  start.
- **Chosen:** (a). Symmetric with the ceiling, one-time cost.

**Decision 13 (resolved → grow per-file JSON with `linear_sum` + `n_segments`):**
the existing per-file `raw_baseline_score_file_*.json` stores only the
log-space `score`, which is **lossy** (`round(·, 2)` applied before the log).
The grand-mean scalar must be built from the *unrounded linear* per-segment
values, so it cannot be reconstructed from existing JSONs. Therefore:

- `_calculate_score` in `compute_raw_baseline.py` returns
  `(log_score, linear_sum, n_segments)` instead of just `log_score`, where
  `linear_sum = float(np.sum((snr_sg / s_max) * snr_squid))` (unrounded).
- Per-file JSONs grow two additive fields: `"linear_sum"`, `"n_segments"`.
  Existing fields are untouched.
- A new main-scope aggregator `_maybe_write_anchor_normalized_scalar` scans
  the 20 fine per-file JSONs (indices 0–19 only; coarse 20–39 excluded), and
  if all 20 are present and carry the new fields, computes
  `grand_mean = Σ linear_sum / Σ n_segments` then
  `scalar = log_{5.27}(round(grand_mean, 2) + 1e-10)` — symmetric with
  `compute_ground_truth.py::_anchor_normalized_ceiling`.
- Output file shape mirrors `ceiling_anchor_normalized.json` exactly (same
  keys, same ordering, `formula="anchor_normalized_raw_baseline"`).
- One-time cost: the 20 existing per-file JSONs must be regenerated with
  `--override` to populate the new fields. ~15 min on 8 parallel workers.

## 6. Rendered markdown format

Exact template, produced by `render_comparison_table(table: ScoreComparisonTable) → str`:

```markdown
### Per-file performance (log-space, all three columns on global s_max)

| file | raw_baseline | ground_truth | **model** | gain vs raw | headroom vs gt |
|-----:|-------------:|-------------:|----------:|------------:|---------------:|
|    0 |     −13.8540 |     −13.8540 |       N/A |         N/A |            N/A |
|  ... |              |              |           |             |                |

### Aggregated scalar (log space, global s_max)

Single number per row — the `final_scalar` returned by `score_vector()` for
each source. This is the only aggregation in the pipeline.

| metric               | log scalar |
|----------------------|-----------:|
| ground_truth ceiling |    10.1134 |
| **model**            | **5.5763** |
| raw baseline         |     1.3200 |

Recovery: **55.1% of ceiling** (model_scalar / ground_truth_scalar).
```

**Below-baseline relabel (Phase 4 closeout hardening):** when
`model_scalar < raw_baseline_scalar` the Recovery line is replaced by:

```markdown
Recovery: < 0% (Model performance is below raw baseline).
```

Rationale: log-space scalars can be negative (below the ε-shifted log
floor), and a negative `raw_baseline_scalar` flips the sign of the
`model_scalar / ground_truth_scalar` ratio in ways that produce
actively misleading percentages — e.g. an all-negative file_vector
with `model_scalar=-7.5`, `ground_truth_scalar=-1.386` yields
`percent_of_ceiling_log = +5.41` which would render as **"541% of
ceiling"** despite the model being worse than raw baseline. The
machine-readable `aggregate.percent_of_ceiling_log` field is left
untouched for programmatic consumers; only the LLM-facing markdown is
sanitized. Covered by
`tests/unit/execute_tools/test_score_table_adversarial.py::TestBelowBaselineRelabel`.

If the run sampled fewer than 20 files (trial mode), append one footer line
below the aggregate table:

```markdown
_Note: scalars computed over {num_sampled_files} sampled files._
```

N/A rendering for `None` entries (file not included in a trial-mode run).
Numbers pre-rounded to 4 dp (log space is the only space).

**Decision 5 (resolved → A, render all 20 rows always):** in trial mode, files
outside the sampled set render as `model=N/A` (plus N/A for the two derived
columns) but keep their `raw_baseline` and `ground_truth` anchors. The full
20-row topology is always visible — the LLM reasons about which files to
include next round, and omitting skipped rows would hide that structure.
`rows` length is always 20.

**Decision 14 (resolved → subset-scoped aggregates):** in trial mode the model
only scored a subset of files, so quoting the full-20-file ceiling or baseline
alongside a subset model scalar would compare apples to oranges. Instead,
`build_score_table` identifies the sampled indices (where `model_fv_log[i] is
not None`) and recomputes **all three aggregate scalars** — raw, ground
truth, and model — over that same subset, using the grand-mean formula from
Phase 1 (`Σ linear_sum[f] / Σ n_segments[f]` then `log_{5.27}(round(·, 2) +
1e-10)`). This is why `ReferenceScores` carries `linear_sum` and
`n_segments` per file, not just the pre-computed scalars — subset
re-aggregation requires the unrounded linear primitives.

The **only** skip condition is `model_scalar is None` (totally failed run):
in that case `build_score_table` returns `None` and the record carries no
`score_table`. If even one file was scored, we build the table — partial
information is strictly more useful than no information.

For a full 20-file formal run, the recomputed `raw_baseline_scalar` equals
`ReferenceScores.raw_scalar_full` by construction (same formula, same linear
sums). The `num_sampled_files=20` field on `AggregateScalars` makes the scope
explicit regardless.

## 7. Schema changes

### 7.1 `agent/schemas/hyperparam_tuning.py`

Add on `ExperimentRecordSchema` and `HyperparamTuningOutput`:

```python
score_table: Optional[ScoreComparisonTable] = Field(
    default=None,
    description="Per-file comparison table (model vs raw baseline vs ground truth). "
                "Populated when file_vector is present. The pre-rendered markdown "
                "is what the tuner/interpreter/proposer actually see in prompts.",
)
```

Keep `file_vector` as-is — it's still the raw primitive. `score_table` is the
*enriched* view. This is **additive**; v0 records without `score_table` remain
valid (`Optional[...] = None`).

**Decision 11 (resolved → both record and top-level):** `score_table` lives on
`ExperimentRecordSchema` (per-record) *and* `HyperparamTuningOutput`
(`best_score_table` + `formal_score_table` at the top level). Symmetric with
the existing `file_vector` / `best_file_vector` / `formal_file_vector`
pattern, and gives downstream nodes direct access to the "best" view without
having to resolve `records[best_idx].score_table`. No derived-at-read
indirection.

### 7.2 `agent/schemas/interpretation.py`

- Add `best_score_table: Optional[ScoreComparisonTable]` and
  `formal_score_table: Optional[ScoreComparisonTable]` on `InterpretationInput`.
- On `InterpretationOutput`, **replace** `per_model_file_vectors: Dict[str, List[float]]`
  with `per_model_score_tables: Dict[str, ScoreComparisonTable]`. The new field
  is a strict superset (every `fv[i]` is now `rows[i].model`), so there is no
  information loss. All internal consumers migrate in the same commit — see
  Decision 6 below.

**Decision 6 (resolved → B, replace `per_model_file_vectors` immediately):**
grep confirmed zero external readers — all consumers are internal to the graph
(`result_interpretation_agent.py` ×3, `ml_model_proposal_agent.py`, `proposal_helpers.py`,
the tune→interp→propose protocol, and two test files). The old field is
redundant with `per_model_score_tables.rows[i].model`, so keeping both would
invite drift without serving any external contract. All 7 call sites are
switched in the same commit that introduces `per_model_score_tables`.

*Scope note:* this decision applies only to `InterpretationOutput.per_model_file_vectors`.
At the tuner level (`ExperimentRecordSchema.file_vector`,
`HyperparamTuningOutput.best_file_vector`) `file_vector` stays as the raw
primitive — `score_table` is the enriched view built on top of it. See §7.1.

### 7.3 `agent/schemas/proposal.py`

- Add `per_model_score_tables: Dict[str, ScoreComparisonTable]` on the proposal
  input schema.
- `FalsifiablePrediction.metric` is **not changed** in this landing — see
  Decision 9 below.

**Decision 9 (resolved → C, defer metric-path extension):** a richer `metric`
surface (e.g. `"score_table.rows[17].headroom_vs_gt"` or slice/reduction
expressions) was considered but deferred. We have no evidence yet of what the
LLM *wants* to predict once it sees the tables. Designing the evaluator
surface now risks building a DSL the model never uses. The feature lands with
richer *context* only; `FalsifiablePrediction.metric` stays scalar-only.
Follow-up PR revisits this after 1–2 adaptive iterations, informed by actual
prediction text, at which point Option A (minimal path reference) or B (full
DSL) can be chosen from data rather than speculation. Keeps this PR tight on
the core scoring infrastructure.

## 8. Protocol changes

### 8.1 `ml_model_tune_to_ml_result_interp.py`

Map `HyperparamTuningOutput.best_score_table` → `InterpretationInput.best_score_table`
and `formal_score_table` → `formal_score_table`. Keep the existing file_vector
mappings for one cycle.

### 8.2 `ml_result_interp_to_ml_model_propose.py`

Swap `per_model_file_vectors` → `per_model_score_tables` in the forwarded
payload (same aggregation logic, richer value type). Line 72 docstring updates
accordingly. No parallel plumbing — Decision 6 replaces rather than coexists.

## 9. Prompt changes

### 9.1 Tuner (`agent/prompts.py:142-159`)

Replace the `### FILE VECTOR AND SCORING:` block with `### PER-FILE PERFORMANCE
TABLE:` — an explicit description keyed to the new columns, followed by a
**placeholder token** `{SCORE_COMPARISON_TABLE}` that the tuner node substitutes
at prompt-render time with `best_score_table.rendered_markdown` (or a compact
"no prior round yet" notice on iteration 1).

Concretely:

```
### PER-FILE PERFORMANCE TABLE:

Below is a comparison of your most recent experiment's per-file scores against
two reference columns:

- **raw_baseline**  = no denoising at all (CH1 passed through the scorer).
- **ground_truth**  = what a perfect denoiser (CH2 substituted for CH1) scores.
- **model**         = your current experiment.

All three are log-space under the same global s_max, so differences are
directly comparable.

- `gain vs raw > 0`  → your model is doing useful work on that file.
- `headroom vs gt`   → how far below the theoretical ceiling you are.

{SCORE_COMPARISON_TABLE}

Use this table — not just the scalar — to decide where to focus next.
```

The old paragraph about "per-file score of ~1.0 means no denoising" is
**deleted** — the comparison table makes it superfluous and the "~1.0" was
never precise anyway.

### 9.2 Interpreter prompt

Wherever `best_file_vector` is rendered into the interpreter prompt, replace
with the same `{SCORE_COMPARISON_TABLE}` token fed from
`InterpretationInput.best_score_table.rendered_markdown`.

### 9.3 Proposer prompt

The proposer already has a two-tier split between *candidates* (top-N by
`best_score`, filtered by `ModelSelectionStrategy`) and *non-candidates* (the
rest). See `nodes/proposal_helpers.py::select_candidate_models` and the
non_candidates_overview builder in `nodes/ml_model_proposal_agent.py:753-770`.
The new `score_table` integrates cleanly into this split:

| Tier           | What the proposer sees for this model                                      |
|----------------|----------------------------------------------------------------------------|
| Candidate      | Full `score_table.rendered_markdown` (3-col table + aggregate scalar)      |
| Non-candidate  | One-line summary: `log_scalar=X.XX, recovery=YY% of log-ceiling`           |

No new config knobs — `ModelSelectionStrategy` remains the only dial that
decides which models cross the threshold. The rendering tier is a pure
consequence of that split.

**Decision 4 (resolved → A, inline raw + gt in every `score_table`):** the raw
and ground_truth columns are global constants, so a shared prompt header could
deduplicate them across N models in the proposer prompt. Rejected because
every `score_table` must be self-describing: any call site that shows a single
record (tuner latest, interpreter per-model, future dashboards) gets the full
three-column comparison for free, without needing to render a separate
"reference anchors" header. Token cost on the proposer is bounded — N × 20
repeated rows is negligible compared to per-model free-text reasoning. Single
renderer, single source of truth.

**Decision 7 (resolved → extend existing two-tier split, no new knobs):**
proposer rendering reuses the candidate/non-candidate split already defined by
`ModelSelectionStrategy`:

- *Candidates* get the full `rendered_markdown` from their `score_table`.
  This replaces the candidate summary's `file_vector` field with
  `score_table`. Concretely, in `select_candidate_models`, line 48's
  `file_vectors = interpretation.get("per_model_file_vectors") or {}` becomes
  `score_tables = interpretation.get("per_model_score_tables") or {}`, and
  line 60's `"file_vector": file_vectors.get(mt)` becomes
  `"score_table": score_tables.get(mt)`. The candidate detail carried into
  the comparison stage now includes the full 3-column table plus source code.
- *Non-candidates* get a compact one-liner computed from their
  `score_table.aggregate`: `"log_scalar=X.XX, recovery=YY% of log-ceiling"`.
  This is built inside the `non_candidates_overview` loop — alongside the
  existing `best_score`, `description`, and cache text fields. It replaces
  no existing field; it's a new compact metric line.

**Token-budget note (RESOLVED in Phase 5 E):** the default `top_n = 10`
(`ModelSelectionStrategy.params`) predated the switch to full tables. Phase 5 E
lowered the default to `n = 5` (`agent/schemas/proposal.py:358-360`) and
exposed `n_candidates: Optional[int]` on `workflows.model_exploration.run_workflow`
/ `_get_reasoning_pipeline` so large-scale experiments can bump it back up
without a schema change. Measured baseline at n=5 worst case (full
rendered_markdown + ~30-line source code per candidate): **13,513 chars ≈ 3,378
tokens** — ~2.6 % of gpt-4o-mini's 128 k context window. Regression guarded by
`TestStagePromptSizeBudget` in `tests/unit/agent/ml_model_proposal_agent/test_pipeline_runner.py`
(absolute bound 200 k chars + sub-linear-scaling check across n=5 → n=10).

### 9.4 Reflector prompt

The reflector is the tuner's per-round "memory builder" — it runs after every
experiment (`nodes/ml_hyperparameter_tune_agent.py:1350-1433`) and produces
the `hypothesis`/`discovery`/`memory_update` that feeds the *next* planner
call's memory history. Today it receives `file_vector` via `score_results` but
its `reflection_context` carries only scalar comparisons
(`baseline_score`, `best_score_so_far`, `is_new_best`, `rank`). The
`REFLECTOR_PROMPT` "HOW TO JUDGE THE DENOISING SCORE" section tells it to
compare against the baseline scalar — which is exactly the blind spot this
feature targets.

Add `score_comparison_table` to `reflection_context` carrying
`score_table.rendered_markdown`, and extend `REFLECTOR_PROMPT` with a section
pointing the LLM at it:

```
### PER-FILE COMPARISON (frequency-band awareness):
The score_comparison_table below shows per-file performance against the raw
baseline and the ground-truth ceiling. Use it to produce frequency-aware
discoveries and hypotheses — e.g., "architecture X handled files 15-19 but
regressed on files 0-3" rather than "score went up." These band-level
insights compound across rounds when the next planner inherits them.

{SCORE_COMPARISON_TABLE}
```

**Decision 8 (resolved → A, reflector receives full rendered_markdown):** the
reflector's output is the primary vehicle by which per-round insights flow
into the next round's planning. Shallow reflector output → shallow
inheritance. The full table unlocks band-aware hypotheses at every round. The
reflector is intentionally routed to Gemini Flash (the cheap slot), so the
~30 extra lines per call are a negligible cost relative to the compounding
memory quality. Rejected Option B (compact diff line) — partial information
bias: if the LLM sees a summary like "worst=-3.2 at file 0", it anchors to
that single worst case instead of reasoning about the whole band distribution.
Rejected Option C (no change) — concedes exactly the blind spot this feature
exists to fix.

## 10. Tuner-node plumbing

`nodes/ml_hyperparameter_tune_agent.py` already computes `file_vector` from
`score_vector()`. Add right after that computation:

```python
from nodes.scoring_reference import load_reference_scores
from execute_tools.scoring_helpers import build_score_table

raw_ref, gt_ref, raw_sc, gt_sc, s_max = load_reference_scores()
score_table = build_score_table(
    model_fv_log=fv_log,     # what we already compute
    model_scalar=scalar,
    raw_per_file_log=raw_ref,
    gt_per_file_log=gt_ref,
    raw_scalar=raw_sc,
    gt_scalar=gt_sc,
    s_max=s_max,
)
record.score_table = score_table      # persist on ExperimentRecordSchema
```

Per Decision 10, the helpers split by concern:
- **`nodes/scoring_reference.py`** — disk I/O + module-level caching for the
  reference-data JSONs. Node-side input-prep.
- **`execute_tools/scoring_helpers.py`** — pure `build_score_table` +
  `render_comparison_table`. Zero I/O, zero side effects, directly
  unit-testable alongside `scoring_utils.py`.

Additionally (per Decision 8), thread `score_table.rendered_markdown` into the
reflector call at `nodes/ml_hyperparameter_tune_agent.py:1406`:

```python
reflection_context = {
    ...                                         # existing scalar fields
    "score_comparison_table": score_table.rendered_markdown,  # NEW
}
```

The reflector receives the same pre-rendered markdown string the planner
sees — single-source-of-truth.

## 11. Backward compatibility

- v0 run_output JSONs lack `score_table` → loads fine under `Optional` field.
- When the interpreter encounters a record with `score_table=None` it falls
  back to rendering just the `file_vector` (the v0 prompt behavior) and logs a
  one-line "no comparison table available for this record" note.
- `per_model_file_vectors` is **removed**, not deprecated — grep confirmed no
  external consumer (no dashboard reader, no external script). All 7 internal
  call sites migrate in the same commit as the schema change. See Decision 6.

## 12. Implementation phases

Each phase lands as its own commit (per
`~/.claude/projects/.../memory/feedback_commits.md`). "Real-run test" means
actually executing the affected code path with real inputs (not just unit
tests) before committing, per `feedback_test_before_commit.md`.

---

### Phase 1 — Reference data: raw-baseline scalar generator

**Goal:** `{SIDERIUS_DATA_DIR}/raw_baseline/scalar_anchor_normalized.json`
exists on disk, symmetric with `ground_truth/ceiling_anchor_normalized.json`.

**Status:** ✅ complete. Landed on `master` 2026-04-21 as three sibling
commits:

- `4104463` — `docs(score_table):` design doc for comparison-table awareness
  (7-phase plan).
- `f97b613` — `feat(raw_baseline):` emit scalar_anchor_normalized.json
  (grand-mean, global s_max).
- `c7e9667` — `docs(reference_data):` raw_and_ground_score.md — fill in raw
  baseline scalar.

Steps:
- [x] Edit `compute_raw_baseline.py::_calculate_score` — return changed from
      `float` to `(log_score: float, linear_sum: float, n_segments: int)`.
- [x] Update the caller in `main()` — unpacks the 3-tuple and stores
      `linear_sum` + `n_segments` in the per-file JSON alongside existing
      fields.
- [x] Add `_maybe_write_anchor_normalized_scalar(output_dir, s_max,
      anchor_src)` at end of `main()` — scans fine JSONs (0–19), aggregates
      grand-mean, writes `scalar_anchor_normalized.json`, or prints a
      missing-indices warning if incomplete.
- [x] Smoke test: `--indices 0 --override -p -n 8` → per-file JSON gained
      `linear_sum=1.10e-6` + `n_segments=200`; scalar file correctly skipped
      with `indices without linear_sum/n_segments: [1..19]` message.
- [x] Sanity: file 0 reconstruction `5.27 ** score == round(linear_sum/n, 2)
      + 1e-10` — matched exactly. Revealed `mean_linear = 5.5e-9` for file 0,
      which is the exact "rounded to zero" case Decision 13 was designed for:
      without `linear_sum` the weak-signal files are unrecoverably pinned at
      the `-13.854` clip floor.
- [x] Full regen (bg id bpjvph1aw, completed): all 20 fine per-file JSONs
      regenerated with new fields; `scalar_anchor_normalized.json` emitted
      at scalar = **1.001141** (in the expected 1.0–2.0 range).
- [x] Post-regen: `scalar_anchor_normalized.json` shape matches
      `ceiling_anchor_normalized.json` exactly (same 7 keys; `num_files=20`;
      `formula="anchor_normalized_raw_baseline"`; file_vector is linear
      per-file means — confirmed file 0–3 at 1e-9 to 1e-5, file 17 at 21.0).
- [x] Unit test `tests/unit/test_compute_raw_baseline.py` — 9 tests, all
      passing (5 updated for 3-tuple return; 4 new for the aggregator:
      happy path, missing index, legacy-without-fields, weighted grand mean).
- [x] Commits (3, per `feedback_commits.md` small-commits rule):
      - `4104463` — design doc
      - `f97b613` — `feat(raw_baseline): emit scalar_anchor_normalized.json
        (grand-mean, global s_max)`
      - `c7e9667` — `docs(reference_data): raw_and_ground_score.md — fill
        in raw baseline scalar` (reflects the new disk artifact)

---

### Phase 2 — Schema + loader + renderer

**Status:** ✅ complete. Landed on `master` 2026-04-22 as one commit
(`a0ec78e`), following the GT-generator upgrade sibling commit
(`5c37c94`) that aligned the ground-truth per-file JSONs with the
Phase-1 raw-baseline schema (linear_sum + n_segments).

**Goal:** three new files exist, all deterministic, all unit-tested. No node
touches them yet.

Design-time answers locked (2026-04-22, this session):
- **Q-P2-A** → (i) plain `rendered_markdown: str` field, populated by
  `build_score_table` at construction time; survives JSON round-trip
  identically in run_output records.
- **Q-P2-B** → structured `ReferenceScores` frozen dataclass (see §5); no
  5-tuple.
- **Q-P2-C** → per-file row values use the log-space `"score"` field from
  the on-disk per-file JSONs (byte-matches `reference_data/
  raw_and_ground_score.md`).
- **Q-P2-D** → subset-scoped aggregates; see Decision 14 for the full
  contract. `build_score_table` returns `None` iff `model_scalar is None`.

Steps:
- [x] Create `agent/schemas/score_table.py` with `PerFileRow`,
      `AggregateScalars` (5 fields incl. `num_sampled_files`), and
      `ScoreComparisonTable` per §4.
- [x] Create `nodes/scoring_reference.py` — `ReferenceScores` frozen
      dataclass (9 fields per §5: two log vectors, two linear_sum vectors,
      two n_segments vectors, both full-20 scalars, s_max).
      `load_reference_scores()` reads the 20 raw + 20 gt per-file JSONs +
      `scalar_anchor_normalized.json` + `ceiling_anchor_normalized.json`;
      module-level cache; missing file raises `FileNotFoundError` with a
      pointer to `compute_raw_baseline.py` / `compute_ground_truth.py`.
- [x] Create `execute_tools/scoring_helpers.py::build_score_table(
      model_fv_log: list[Optional[float]], model_scalar: Optional[float],
      reference: ReferenceScores) -> Optional[ScoreComparisonTable]`:
      - If `model_scalar is None` → return `None` (hard skip, Decision 14).
      - Always produces `rows` of length 20; `model`/`gain`/`headroom`
        None-propagate on unsampled indices.
      - Identifies `sampled = [i for i, v in enumerate(model_fv_log) if v
        is not None]`; computes subset grand-mean for raw + gt from the
        reference linear sums over `sampled`; model scalar passed in
        as-is (already subset-scoped by `score_vector`).
- [x] Add `execute_tools/scoring_helpers.py::render_comparison_table(table)`
      — pure markdown per §6; 4-dp log rounding; "N/A" for None entries;
      append `_Note: scalars computed over {n} sampled files._` when
      `aggregate.num_sampled_files < 20`. Negatives use U+2212 for column
      alignment.
- [x] Unit test `tests/unit/agent/schemas/test_score_table.py` — 14 tests:
      Pydantic validation (all-None row, mixed row, file_index bounds,
      num_sampled_files bounds 1..20, extra-forbidden) + JSON round-trip.
- [x] Unit test `tests/unit/nodes/test_scoring_reference.py` — 10 tests:
      happy-path shapes + value alignment; missing raw/gt/scalar files;
      legacy per-file JSON without `linear_sum` or `n_segments`; s_max
      mismatch; cache-returns-same-object and cache-reset behaviors.
- [x] Unit test `tests/unit/execute_tools/test_scoring_helpers.py` — 16
      tests: full-20 aggregate matches on-disk scalars by construction;
      trial-mode subset (files 10..14) aggregate vs hand-math; rows
      None-propagate; `model_scalar=None` → `None`; wrong-length FV and
      all-None-FV-with-non-None-scalar raise; markdown header + exactly
      20 body rows + N/A cells + aggregate block + conditional subset
      footer + Unicode-minus rendering.
- [x] Real-run test: `.venv/bin/python -c "from nodes.scoring_reference
      import load_reference_scores; r = load_reference_scores();
      print(r.raw_scalar_full, r.gt_scalar_full, r.s_max)"` — reproduces
      `raw_scalar_full=1.001141`, `gt_scalar_full=10.113401`,
      `s_max=2.95716e+08`, matching `reference_data/
      raw_and_ground_score.md` byte-exact.
- [x] Sibling commit `5c37c94`: upgrade `compute_ground_truth.py` to
      emit `linear_sum` + `n_segments` and regenerate all 20 fine GT
      JSONs. Scalar ceiling unchanged at 10.113401 after regen (proves
      formula symmetry; no value drift).
- [x] Commit `a0ec78e`: `feat(score_table): add ScoreComparisonTable
      schema + reference loader + renderer`. Single commit (8 files,
      1379 insertions) per the Phase 2 checklist.

---

### Phase 3 — Tuner plumbing + tuner prompt

**Goal:** tuner emits records and run-output carrying `score_table`; tuner
planner prompt renders the table token.

**Status (2026-04-22):** split into three sub-commits for clean review.
All three sub-commits landed (A schemas → B tuner wiring → C prompts).

Sub-commit A — schemas (landed `879cdd7`):
- [x] Extend `agent/schemas/hyperparam_tuning.py` — added optional
      `score_table: Optional[ScoreComparisonTable]` on `ExperimentRecord`;
      added `best_score_table` + `formal_score_table` on `HyperparamTuningOutput`
      (per Decision 11). `file_vector` fields kept for backwards compat.
- [x] Unit tests: +7 cases covering backward-compat optional, populated
      round-trip, invalid rejection, both-tables-independently-populated.

Sub-commit B — tuner wiring (landed `36e0e9c`):
- [x] Wire `nodes/ml_hyperparameter_tune_agent.py` — pre-load
      `reference_scores = load_reference_scores()` once in `run()` (module-
      cached, one disk read per run). After `score_vector(...)` returns,
      call `build_score_table(...)` inside a try/except with None fallback
      so rendering bugs never crash the long tuning loop. Populate
      `final_record["score_table"]` next to `file_vector`.
- [x] Populate `best_score_table` + `formal_score_table` at run-output
      emission time via dual-track selection: `best` from `top_record`
      (highest `denoising_score` across all modes); `formal` from
      `max(successful_records where not is_trial)` — surfaces the canonical
      full-20 table without the trial-mode subset caveat.
- [x] Reflector plumbing (Decision 8 / §9.4 half 1): thread
      `score_table.rendered_markdown` into `reflection_context` at line
      1406 as `score_comparison_table`. Token consumption in
      `REFLECTOR_PROMPT` pending in sub-commit C.
- [x] Unit tests: +5 TestScoreTablePropagation cases — per-record
      attachment, reflector-context threading, legacy-path None,
      dual-track output populated, and `build_score_table` fault-tolerance
      (monkeypatched exception → `score_table=None`, run completes).
      Hermetic `load_reference_scores` stubs added to all existing
      `run()`-touching fixtures so no test depends on real on-disk data.
      420 passed across the relevant test scope.

Sub-commit C — prompts (landed):

Prerequisite (not strictly part of this design, but was a blocker for
the sub-commit C real-run smoke test): the 24 GiB RLIMIT_AS ceiling in
`core/sandbox_executor.py` was calibrated against observed RSS but
applied to VA, and CUDA context init alone reserves ~18 GiB of VA on
RTX 5090. Every training attempt in the first smoke test failed at
focal-loss allocation with ~27 GiB of GPU memory still free. Fixed by
making the ceiling role-aware (scoring=24 GiB, training/inference=40 GiB
per the 20+16+4 breakdown, landed `cd901f1`); a follow-up regex fix to
`_is_oom_failure` (landed `21f3366`) stopped false-positiving on
`torch.OutOfMemoryError`. See `docs/optimize_inference_and_scoring.md`
§Fix 1 addendum for the full derivation.

- [x] Update `agent/prompts.py:142-159` — replaced the `### FILE VECTOR AND
      SCORING:` block per §9.1 with `### PER-FILE PERFORMANCE TABLE:` and
      the `{SCORE_COMPARISON_TABLE}` placeholder token.
- [x] `LLMBridge.plan()` substitutes `{SCORE_COMPARISON_TABLE}` with the
      tuner-threaded `score_table_md` kwarg (or the "no prior round yet"
      italicised fallback on iteration 1). Uses `str.replace()` — safe
      because no other `{...}` tokens exist in the prompt.
- [x] Extended `REFLECTOR_PROMPT` with the `### PER-FILE COMPARISON`
      section (Decision 8 / §9.4 half 2). `LLMBridge.reflect()` consumes
      `reflection_context["score_comparison_table"]` threaded by sub-commit B.
- [x] `nodes/ml_hyperparameter_tune_agent.py` — added the best-so-far
      selector before `brain.plan()`: filters `memory_history` for
      `status=="success"` + non-None `denoising_score` + dict-shaped
      `score_table` + populated `rendered_markdown`, then max by
      `denoising_score`. Threads the winner's markdown via new
      `score_table_md=` kwarg to `plan()`.
- [x] Unit tests: +8 `LLMBridge` token-substitution cases (planner hit
      path, planner fallback, reflector both halves, idempotence,
      reflector with `reflection_context=None`), +7
      `TestScoreTablePropagation` cases for the tuner-side selector
      (empty history, single-record, tie-break by score, status filter,
      None-score filter, missing-table filter, fallback to None).
- [x] Real-run smoke (2-round `punet` trial, gpt-5-mini, `--is_trial`):
      Round 1 trained to completion under the 40 GiB VA cap, emitted a
      populated `score_table`; Round 2 planner prompt rendered the full
      20-row table with real numbers. Frequency-band awareness confirmed
      visible — e.g. file 11 `gain_vs_raw=+8.26` near-ceiling, file 15
      `gain_vs_raw=+7.36`, file 19 `gain_vs_raw=−0.64` (model regressed
      vs raw on the highest-frequency band). The scalar alone (recovery
      4.0% of ceiling) would have hidden this structure.
- [x] Commit: `feat(prompts): render score_table in planner + reflector
      prompts`.

---

### Phase 4 — Protocol wiring (tune → interp → propose)

**Goal:** the score_table payload flows end-to-end through the graph;
`per_model_file_vectors` is removed per Decision 6.

**Status (2026-04-22):** in progress. Decision 6's hard swap removes
`per_model_file_vectors` from `InterpretationOutput` in the same commit
that introduces `per_model_score_tables` — so Phase 4 cannot be split
into separate commits without leaving intermediate state broken. Instead
we work in two *staged* passes within a single uncommitted worktree,
then commit the whole bundle when the narrow test suite is green.

Staged plan:

**Stage 1 — contract layer (schemas + protocols).** Uncommitted;
schemas import-clean but the tree is red because node readers still
reference the removed `per_model_file_vectors` key.

- [x] Extend `agent/schemas/interpretation.py` — added
      `best_score_table` + `formal_score_table` on `ModelRunSummary`
      (alongside the existing `best_file_vector` / `formal_file_vector`).
      Replaced `InterpretationOutput.per_model_file_vectors` with
      `per_model_score_tables: Optional[Dict[str, ScoreComparisonTable]]`.
- [x] Extend `agent/schemas/proposal.py` — added
      `ProposalInput.per_model_score_tables: Optional[Dict[str, ScoreComparisonTable]]`
      as a typed mirror of the interpretation dict-carry.
- [x] `agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py` —
      docstring now calls out the `best_score_table` / `formal_score_table`
      threading. Actual population happens inside
      `tuning_output_to_model_run_summary` (migrated in Stage 2 below).
- [x] `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` —
      docstring renamed `per_model_file_vectors` → `per_model_score_tables`;
      code explicitly populates `result["per_model_score_tables"]` by
      dumping the dict of `ScoreComparisonTable` when upstream has tables.

**Stage 2 — consumers (node readers + tests).** Restores a green tree.

- [x] `nodes/result_interpretation_agent.py` — done (uncommitted). All 7
      call sites migrated:
      - `tuning_output_to_model_run_summary`: populates `best_score_table`
        + `formal_score_table` — prefers the tuner's top-level
        `HyperparamTuningOutput.best_score_table` / `formal_score_table`,
        with a fallback to `best_rec`/`formal_rec`'s own `score_table`
        field. Raw `best_file_vector` / `formal_file_vector` still emitted
        alongside per §7.2 scope note.
      - `_stats` cache dict in Phase 1: gained
        `"best_score_table": summary.best_score_table.model_dump()` so the
        cache round-trips through JSON cleanly; reads validate it back
        via `ScoreComparisonTable.model_validate`. The legacy
        `best_file_vector` key is kept for any consumer that still needs
        a flat list.
      - `_register_file_vector` renamed to `_register_score_table`;
        internal var `per_model_file_vectors` renamed to
        `per_model_score_tables: Dict[str, ScoreComparisonTable]`; the
        weak-files logic now extracts `r.file_index` from
        `table.rows` where `r.model < 1.0` — behavior identical.
      - `_build_synthesis_prompt` call site: kwarg renamed.
      - `_build_synthesis_prompt` signature + body: param renamed to
        `per_model_score_tables`; the "File Vector Summary" block now
        synthesizes `fv = [r.model for r in table.rows]` on the fly so
        the existing prompt text stays byte-identical. Phase 5 will
        replace this block with `table.rendered_markdown`.
      - Prediction-eval block (old line 691): `prev_fv` synthesized from
        `prev_table.rows[i].model`; the `actual_results["best_file_vector"]`
        key is unchanged — it's the reflector-side contract consumed by
        `evaluate_prediction` (reads "mean(file_vector[N:M])",
        "file_vector[N]" metrics).
      - Output emission (old line 836): now emits
        `"per_model_score_tables"`.
      - *Scope correction from the original plan:* `_build_per_model_prompt`
        (lines 131/137) is **not** migrated in Phase 4 — `summary.best_file_vector`
        / `summary.formal_file_vector` stay in that function's rendering.
        Those fields are still on `ModelRunSummary` per §7.2, so the
        current code is already green. Phase 5 (interpreter prompt
        overhaul) swaps this render path to `score_table.rendered_markdown`.
- [x] `nodes/ml_model_proposal_agent.py` — done (uncommitted). 2 sites
      migrated:
      - `_build_synthesis_prompt` render block now reads
        `interp.get("per_model_score_tables")` and synthesizes the
        per-file list from each serialized table's `rows[i].model`. The
        "Per-model File Vectors" heading and weak/strong text stay
        byte-identical. Phase 5 replaces this block with the
        pre-rendered table markdown.
      - Key in the forwarded `interpretation_summary` tuple renamed to
        `"per_model_score_tables"`.
- [x] `nodes/proposal_helpers.py` — done (uncommitted). 1 site migrated:
      `select_candidate_models` reads
      `interpretation.get("per_model_score_tables")` and synthesizes the
      candidate-summary `file_vector` list via a small
      `_fv_from_score_table` helper. The `"file_vector"` candidate key
      is **intentionally unchanged** — Phase 5 replaces it with a
      `"score_table"` key once downstream consumers migrate.
- [x] Test fixtures — done (uncommitted):
      - `test_interpretation_agent.py`: added a `_make_score_table(fv)`
        helper at module scope (builds a `ScoreComparisonTable` with
        constant placeholder reference columns); `ENRICHED_SUMMARY`
        gained `best_score_table` + `formal_score_table` alongside the
        existing `best_file_vector` / `formal_file_vector` fields;
        `test_includes_file_vector_summary` now feeds
        `per_model_score_tables={"punet": ENRICHED_SUMMARY.best_score_table}`
        to `_build_synthesis_prompt`; `test_per_model_file_vectors_populated`
        renamed to `test_per_model_score_tables_populated` and asserts the
        output is a `ScoreComparisonTable` with 20 rows; the None-fields
        test now checks `output.per_model_score_tables is None`.
      - `test_proposal_agent.py`: added `_make_score_table_dict(fv)` — a
        serialized (`model_dump()`) ScoreComparisonTable matching the
        shape the interp dict carries through the protocol;
        `test_includes_file_vectors` feeds
        `per_model_score_tables={"punet": _make_score_table_dict(fv)}`.
      - `test_tune_to_interp.py`: rewrote the optional output-check to
        read `output.per_model_score_tables.get("wavenet")`, synthesize
        `fv = [r.model for r in table.rows]`, and re-assert the
        low/high-frequency thresholds. The fixture
        `_WAVENET_TUNING_OUTPUT` has no `best_score_table` so the block
        is skipped in pseudo mode — identical behavior to the pre-
        migration soft check on `per_model_file_vectors`.
- [x] Run the narrow test scope: the 3 migrated test files plus
      `tests/unit/agent/tune_ml_hyperparam_agent/test_tuning_agent.py` and
      `tests/unit/agent/test_llm_bridge.py` as cross-module canaries.
      **Result: 226 passed in 178s.** No interpretation, proposal, tuner,
      or llm-bridge regressions from the `per_model_file_vectors` →
      `per_model_score_tables` rename.
- [x] Commit `45bb835`: `refactor(graph): replace per_model_file_vectors
      with per_model_score_tables; wire score_table through protocols`.
      11 files, +363/-74. Phase 4 complete.

**Adversarial probes (pre-Phase-5 audit, now in CI)**

Full suite at `tests/unit/execute_tools/test_score_table_adversarial.py`
(promoted from the throwaway `/tmp/adversarial_score_table.py` probe
script after Phase 4 Stage 2 landed). Covers: schema validator
robustness on LLM-style junk values, `build_score_table` subset edge
cases, the below-baseline relabel guard in `render_comparison_table`,
and proposer prompt-render resilience to malformed `rendered_markdown`.

- [x] Schema robustness: `None`, `NaN`, `Inf` accepted (canonical
      unsampled marker). LLM string nulls `"n/a"`, `"N/A"`, `"-"`, `""`
      all cleanly rejected with readable `ValidationError`. `rows`
      length ≠ 20, `num_sampled_files<1`, `file_index>19`, and extra
      keys all rejected. Numeric-string coercion (`"5.5"` → 5.5) is
      Pydantic-default and not exploitable on our path — carrier is
      always `model_dump()` → `model_validate()`.
- [x] `build_score_table` subset edges: `model_scalar=None` + all-None
      fv returns `None` gracefully; `model_scalar` set + all-None fv
      raises with clear message; single-file sample works; `fv`
      length ≠ 20 raises.
- [x] **FINDING RESOLVED (option b hardening, in Phase 4 closeout):**
      when `model_scalar < raw_baseline_scalar`, `render_comparison_
      table` now emits `"Recovery: < 0% (Model performance is below
      raw baseline)."` instead of the raw `percent_of_ceiling_log *
      100` percentage. Machine-readable `aggregate.percent_of_ceiling_
      log` field is untouched. See §6 for the rendered format and
      `tests/unit/execute_tools/test_score_table_adversarial.py::
      TestBelowBaselineRelabel` for the guard tests.
- [x] Proposer prompt-render resilience: `_build_reasoning_prompt`
      tolerates empty / whitespace-noisy / unicode / non-table / even
      `aggregate`-missing `rendered_markdown`. This passes because the
      current block only reads `rows[].model`; `rendered_markdown` is
      unused in Phase 4. **Must be re-probed in Phase 5** once prompt
      consumption flips to the rendered table.

*Decision 6 scope reminder:* the hard swap applies only to
`InterpretationOutput.per_model_file_vectors`. `ExperimentRecordSchema.file_vector`,
`HyperparamTuningOutput.best_file_vector`, and
`ModelRunSummary.best_file_vector` all stay — `file_vector` is the raw
primitive, `score_table` is the enriched view built on top of it. See §7.1
and §7.2 scope note.

---

### Phase 5 — Interpreter + proposer prompts

**Goal:** downstream agents see the rendered table; proposer respects the
candidate/non-candidate split per Decision 7.

**Sub-commit plan (approved 2026-04-22):** split across 5 sub-commits so
each lands reviewable and reversible. Ordering A → B → C → D → E is
forced by data-flow dependencies (C reads the key B renames; D gates
on C since it probes `rendered_markdown` consumption).

| # | Scope | Primary files |
|---|-------|---------------|
| A | Interpreter per-model prompt swap: `_build_per_model_prompt` drops the 20-line per-file listing in favor of `summary.best_score_table.rendered_markdown` + `formal_score_table.rendered_markdown`. **Steer:** keep the explicit "Weak Frequency Files" callout even with the table present — it acts as an attention mechanism for the LLM. | `nodes/result_interpretation_agent.py`, `tests/unit/agent/result_interpretation_agent/test_interpretation_agent.py` |
| B | Candidate-summary key rename: `select_candidate_models` returns `"score_table": <serialized dict>` instead of `"file_vector": [...]`. | `nodes/proposal_helpers.py`, associated tests |
| C | Proposer prompt (pipeline + legacy). Pipeline path: lift `rendered_markdown` + `source_code` out of the JSON-escaped candidate dicts into a **top-level markdown block** the LLM reads natively; non-candidates gain a `score_summary` one-liner; `per_model_score_tables` dropped from `interpretation_summary` as it is now redundant. Legacy `_build_reasoning_prompt`: replace weak/strong one-liner with per-model `rendered_markdown`. **Steers:** (1) top-level rendering > JSON-escaped markdown for LLM readability; (2) the non-candidate one-liner MUST include `num_sampled_files`, e.g. `recovery=55% on 20 files`. | `nodes/proposal_helpers.py` (3 new helpers), `nodes/ml_model_proposal_agent.py` (pipeline + legacy), `tests/unit/agent/ml_model_proposal_agent/{test_pipeline_runner,test_proposal_agent}.py` |
| D | Adversarial re-probe now that `rendered_markdown` is consumed. **Steer:** specifically cover truncated tables — an LLM-constructed JSON with a partial `rows` list must be caught by schema validation (not silently rendered). | `tests/unit/execute_tools/test_score_table_adversarial.py` extension (+ proposer hardening if a crash surfaces) |
| E | `@real_run` integration test: one proposer iteration asserting the rendered prompt contains the comparison table for the top-ranked candidate and the compact line for a non-candidate. Close out design-doc check-offs. | `tests/integration/...`, `docs/aggregated_score_table_awareness.md` |

Steps (live checklist):
- [x] **A.** Interpreter prompt swap (retain Weak-Frequency-Files callout). `b7ade87`.
- [x] **B.** `select_candidate_models` → `"score_table"` key. `8d93d44`.
- [x] **C.** Proposer prompt render (LLM readability refinement).
      Pipeline: lift `rendered_markdown` + `source_code` into a top-level
      markdown block above the cleaned JSON region (via
      `_render_stage_user_prompt` — replaces 3 `json.dumps` sites);
      non-candidates gain `score_summary` one-liner; drop
      `per_model_score_tables` from `interpretation_summary`.
      Legacy: per-model `rendered_markdown` sections. Three new helpers
      in `nodes/proposal_helpers.py` + 20 new unit tests across 4 classes.
      See "Sub-commit C detailed plan" below.
- [x] **D.** Adversarial re-probe + genericity tests.
      `TestProposerRenderAdversarial` (7 cases): below-baseline priority
      over recovery, recovery=0.0 boundary, non-dict score_table
      robustness, empty-string fallback for both rendered_markdown and
      source_code, missing model_type → `<unknown>`, non-dict per-
      candidate score_table.
      `TestProposerGenericity` (4 cases): `mystery_model_x` flows through
      `build_candidate_markdown_block`, `build_score_summary_line` is
      name-indifferent, full `_render_stage_user_prompt` carries the
      synthetic name verbatim, empty-candidate fall-through has zero
      leakage. **Litmus substring scan passes** — no `wavenet`/`punet`/
      `fcnet` leaks into a `mystery_model_x`-only assembled prompt.
      No hardening needed; all edge paths already handled. Helpers
      land green on first pass.
- [x] **E.** `@real_run` test + final commit.
      **Config changes (2026-04-22):** lowered `ModelSelectionStrategy`
      default from `n=10` → `n=5` (`agent/schemas/proposal.py:358-360`)
      and exposed `n_candidates: Optional[int]` on
      `workflows.model_exploration.run_workflow` +
      `_get_reasoning_pipeline` so large-scale experiments can override
      without a schema change. **Unit budget guard:**
      `TestStagePromptSizeBudget` — absolute bound 200 k chars, plus a
      sub-linear scaling check (n=10 must be < 2.5× n=5).
      **Measured baseline at n=5 worst case** (5 candidates × full
      `rendered_markdown` + ~30-line source code): **13 513 chars ≈
      3 378 tokens** at 4 chars/token — ~2.6 % of gpt-4o-mini's 128 k
      context window. **Real-API validation:**
      `TestInterpToProposalOpenAI::test_interp_to_proposal_full_chain`
      (gpt-4o-mini) ran 51.95 s end-to-end: interp emitted
      `per_model_score_tables`, protocol carried it through, legacy
      proposer rendered the new-schema markdown at
      `nodes/ml_model_proposal_agent.py:497-507`, valid `ProposalOutput`
      produced (`tcn_low_freq_recovery`). No truncation, no
      `context_length_exceeded`. Pipeline-mode `_render_stage_user_prompt`
      coverage lives in the unit suite (344 passing including the 20
      Sub-commit C tests + 11 adversarial/genericity probes).

#### Sub-commit C detailed plan (LLM-readability refinement, 2026-04-22)

**Architectural insight.** The pipeline stage user prompt is currently a
single `json.dumps(accumulated, ...)` call (3 sites: `ml_model_proposal_agent.py:858,911,980`).
With Sub-commit B, candidates carry the full serialized `ScoreComparisonTable`
dict under `"score_table"`. JSON-escaping a 20-row markdown table collapses
it into a `\n`-soup string — technically parseable by the LLM, but
suboptimal for reasoning. Sub-commit C lifts the heavy, read-intensive
content out of JSON into a top-level markdown block the LLM consumes
natively, while scalar metadata stays in the JSON registry.

**User-prompt shape after C.** Each pipeline stage user prompt becomes
two concatenated regions:

```
## Candidate Models — detailed view

### Candidate: wavenet
<score_table.rendered_markdown>

#### Source Code
```python
<source code for wavenet>
```

---

### Candidate: gated_fno
...

## Accumulated context

```json
{
  "candidates": [
    {"model_type": "wavenet", "best_score": 5.5, "description": "...",
     "model_params": 55000, "training_segments": 200, "source": "seed"}
  ],
  "non_candidates_overview": [
    {"model_type": "punet", "best_score": 1.8,
     "score_summary": "log_scalar=1.80, recovery=17.8% on 20 files",
     "description": "...", "key_findings": [...]}
  ],
  "interpretation_summary": { /* per_model_score_tables dropped */ },
  "existing_model_types": [...],
  "previous_failures": [...]
}
```

**Field migration table.**

| Field | Today | After C |
|---|---|---|
| `candidate["score_table"]` | in JSON dict | **stripped from JSON** → top-level markdown via `rendered_markdown` |
| `candidate["source_code"]`, `["source_code_lines"]` | in JSON dict (`\n`-escaped) | **stripped from JSON** → fenced Python code block in top-level markdown |
| `candidate["model_type/best_score/description/model_params/training_segments/source"]` | in JSON | unchanged — stays in JSON as scalar metadata |
| `non_candidates_overview[i]["score_summary"]` | absent | **new**: `"log_scalar=X.XX, recovery=YY% on N files"` or `"log_scalar=X.XX, below raw baseline on N files"` |
| `interpretation_summary["per_model_score_tables"]` | duplicated | **dropped** — redundant with top-level markdown + non-candidate one-liners |

**New helpers in `nodes/proposal_helpers.py`.**

1. `build_score_summary_line(score_table_dict) -> Optional[str]`
   - Reads `aggregate.{model_scalar, raw_baseline_scalar, percent_of_ceiling_log, num_sampled_files}`.
   - Mirrors the below-baseline guard in `render_comparison_table`: when
     `model_scalar < raw_baseline_scalar`, emit the "below raw baseline"
     variant instead of a misleading negative/flipped percentage.
   - Returns `None` when `score_table_dict` is `None` (fully-failed run) —
     caller decides whether to omit the field entirely.

2. `build_candidate_markdown_block(candidates: list[dict]) -> str`
   - For each candidate, emits: `### Candidate: <model_type>` → blank line
     → `score_table.rendered_markdown` → `#### Source Code` →
     fenced python block with the source (or `_Source code unavailable._`
     if absent) → `---` separator.
   - Returns `""` when `candidates` is empty (legacy shape caller checks
     before concatenation).

3. `strip_heavy_fields_for_json(candidates: list[dict]) -> list[dict]`
   - Shallow-copy per candidate with `score_table`, `source_code`, and
     `source_code_lines` removed. Preserves every other field (so stage
     prompts that enumerate candidate scalars continue to work).

**Pipeline-path refactor in `nodes/ml_model_proposal_agent.py`.**

- Extract user-prompt construction into
  `_render_stage_user_prompt(accumulated: dict) -> str` (used at the 3
  `json.dumps(accumulated)` sites). Inside:
  - Pull `candidates` and build the top-level markdown via
    `build_candidate_markdown_block`.
  - Build a cleaned copy of `accumulated` where `candidates` is stripped,
    `interpretation_summary` no longer contains `per_model_score_tables`,
    everything else is passthrough.
  - Return `f"{markdown_block}\n\n## Accumulated context\n\n```json\n{dump}\n```"`
    (omit the markdown block + its leading `## Candidate Models — detailed view`
    header when there are no candidates — legacy-mode tests expect it
    absent).
- Update the non-candidate loop at `:758-771` to compute
  `score_summary = build_score_summary_line(score_tables.get(mt))` and
  attach it to `overview` when non-None. Left-join on `interp.get("per_model_score_tables", {})`.

**Legacy-path change in `nodes/ml_model_proposal_agent.py:450-465`.**

- Replace the weak/strong one-liner block with per-model rendered_markdown
  sections: iterate `interp.get("per_model_score_tables")`, emit
  `#### <model_type>` + blank line + `rendered_markdown` per table, skip
  entries where `rendered_markdown` is missing/empty. No candidate split
  in this path (no `ModelSelectionStrategy`) — every model gets the full
  table.

**Tests.**

- `tests/unit/agent/ml_model_proposal_agent/test_pipeline_runner.py`:
  - New `TestScoreSummaryLine` class — happy path (positive recovery),
    below-baseline (mirrors `render_comparison_table` guard), trial mode
    subset (`num_sampled_files=3 on 3 files`), None input.
  - New `TestCandidateMarkdownBlock` class — headings present, rendered
    markdown verbatim, source code falls back to "unavailable" when absent,
    empty string on empty list.
  - New `TestStripHeavyFieldsForJson` — score_table/source_code removed,
    other fields preserved, input list not mutated.
  - New `TestStageUserPrompt` (integration-style, no LLM) — after
    `_render_stage_user_prompt(accumulated)`:
    * Top-level markdown block present with `## Candidate Models` header
      when candidates exist.
    * `"rendered_markdown"` key does NOT appear anywhere in the JSON
      region (confirming strip worked).
    * `score_summary` present on each non-candidate overview entry.
    * `per_model_score_tables` absent from `interpretation_summary`.
- `tests/unit/agent/ml_model_proposal_agent/test_proposal_agent.py`:
  - `test_includes_file_vectors` → rename to
    `test_includes_rendered_markdown_per_model`; assert the rendered table
    heading + rendered_markdown substring in the legacy prompt.
  - Other `TestBuildReasoningPromptEnriched` expectations unchanged
    (they do not probe the file_vector text directly).

**Hardened genericity directives (2026-04-22 — post-`e7aec71` follow-up).**

SIDERIUS must support any future architecture proposed via `External
Advice`. The score-table awareness layer — the "Eyes" of the proposer —
must therefore be 100% generic at every boundary it owns. Five directives
govern this, with a one-line audit of the commit-`e7aec71` state
(✓ compliant, ⚠ gap identified, ✗ out of scope for Phase 5):

1. **No-Names rule — code paths we own (✓).** `build_candidate_markdown_block`,
   `build_score_summary_line`, `strip_heavy_fields_for_json`, and
   `_render_stage_user_prompt` carry zero hardcoded model names. Every
   heading is `### Candidate: {model_type}` with `model_type` pulled from
   the candidate dict. Audit command:
   `grep -nE "wavenet|punet|fcnet|diffusion" nodes/proposal_helpers.py nodes/ml_model_proposal_agent.py`
   returns only the `_BUILTIN_MODELS` set and the `_MODEL_CLASS_MAP`
   used by `load_model_source` — both are *dispatch tables keyed by
   `model_type`*, not natural-language strings, and are the one legitimate
   place names must live. Replacement language in prose should use "the
   candidate model" / "the current architecture" / "this specific
   configuration".

2. **Table rendering neutrality (✓).** `execute_tools.scoring_helpers.render_comparison_table`
   is pure math: raw_baseline / ground_truth / model / gain_vs_raw /
   headroom_vs_gt columns + "recovery = % of ceiling" one-liner +
   below-baseline guard. No physics heuristics ("files 15-19 are
   high-frequency noise"). Physics interpretation stays with the
   `expert_context` layer + the LLM's real-time reasoning. Any future
   renderer change must preserve this — audit with
   `grep -nE "high-freq|low-freq|noise that" execute_tools/scoring_helpers.py agent/schemas/score_table.py`
   (currently returns 0 hits; keep it that way).

3. **Safe concatenation + deep-safe stripping (✓).**
   - `build_candidate_markdown_block([])` returns `""` — never a hanging
     `## Candidate Models —` header with no body. `_render_stage_user_prompt`
     then falls through to the JSON region alone. Covered by
     `TestCandidateMarkdownBlock::test_empty_candidates_returns_empty_string`
     and `TestStageUserPrompt::test_no_candidates_emits_json_only`.
   - Between candidates, the block emits a `\n---\n\n` separator (one per
     candidate, trailing separator trimmed on the last entry via
     `rstrip() + "\n"`).
   - `strip_heavy_fields_for_json` is a dict-comprehension shallow copy
     (`{k: v for k, v in candidate.items() if k not in _HEAVY_FIELDS}`) —
     it never mutates the input list or the per-candidate dict, so the
     original `accumulated["candidates"]` retains `score_table` /
     `source_code` for the markdown block. Covered by
     `TestStripHeavyFieldsForJson::test_does_not_mutate_input`.

4. **Legacy path dynamic iteration (✓).** `_build_reasoning_prompt` in
   `nodes/ml_model_proposal_agent.py:497-507` iterates
   `score_tables.items()` — no hardcoded model-name list. Any model the
   interpreter surfaces renders without a code change.

5. **Genericity test with a synthetic name (⚠ gap to close in D).** Most
   existing unit tests reuse `wavenet` / `punet` / `fcnet` as stand-ins
   because they match the production fixtures. A targeted
   `mystery_model_x` test would make the genericity contract explicit:
   if the code ever regresses to a name-dependent branch, the test fails.
   Action: as part of **Sub-commit D** (adversarial re-probe), add
   `TestCandidateMarkdownBlock::test_renders_unseen_model_name` and
   `TestStageUserPrompt::test_synthetic_model_name_flows_through` using
   `model_type="mystery_model_x"` with a minimal `ScoreComparisonTable`
   dict — assert the heading, the rendered markdown, the source-code
   fence fallback, and the JSON payload all carry `mystery_model_x`
   verbatim.

**Known gaps outside Phase 5's scope.** The stage *prompt templates*
(`agent/prompt_templates/proposal/comparison_stage.md`,
`causal_reasoning_stage.md`, `comparison_stage_explore.md`) contain
hardcoded `wavenet` references in *example JSON payloads* that ground
the LLM's output format. These are LLM-facing few-shot examples, not
code, and fixing them is an orthogonal prompt-genericity refactor.
Tracked here for visibility; not a Phase 5 blocker.

**Out of scope for C.**

- `ModelSelectionStrategy.params["n"]` stays at 10 — Decision 7's
  token-budget note is explicitly deferred.
- `agent/prompt_templates/proposal/comparison_stage*.md` natural-language
  references to "file_vector" are LLM-facing guidance, not code. Leave
  for a docs-only follow-up if needed.
- Stage-template `wavenet` few-shot examples (see gap note above) —
  separate prompt-genericity refactor. **User-acknowledged weak point
  (2026-04-22):** LLM bias toward `wavenet` in the proposer's "eyes"
  persists while these few-shot examples stand. Accepted as a known
  limitation for the current Phase 5 window; scheduled for a dedicated
  prompt-genericity refactor post-Phase-7.

---

### Phase 6 — Integration tests (dual-mode)

**Goal:** the existing dual-mode integration tier exercises the new field
end-to-end, pseudo mode covered; full suite green.

#### Post-Phase-5 audit (2026-04-22)

Phase 6 was authored *before* Phases 1–5 landed, so its original checklist
assumed a batch of stale fixtures and protocol assertions. A state audit
after `13d450c` (Phase 5 E closeout) found most of the "update X" items
already satisfied as side effects of Phases 3–5:

| Original checklist item | Actual state after Phase 5 |
|---|---|
| Update pseudo fixtures under `tests/pseudo_data/api_call_outputs/**` | No stale **schema keys**. Only 2 LLM-narrative strings still say `file_vector` (non-breaking narrative prose, not structural keys). |
| Update `test_tune_to_interp.py` — `per_model_file_vectors` → `per_model_score_tables` | Already references `per_model_score_tables` (line 170) but with a **SOFT** `if output.per_model_score_tables:` guard; missing `summary.best_score_table` + `summary.formal_score_table` assertions at the protocol layer. |
| Update `test_interp_to_propose.py` | `test_interp_to_propose_feedback_loop` (F.5) passes; no assertion yet that the Phase-5-C markdown actually reaches the final stage user prompt. |
| Update `test_full_exploration_loop.py` | No stale `per_model_file_vectors` refs. Tier 3 real-run only. |
| Run relevant test subset | 106 unit protocol tests + 2 dual-mode integration tests all green today. |
| Tier 3 real-run spot-check | **Deferred to Phase 7** — overlaps 1:1 with the launch gate (same GPU + real API requirement). |

So Phase 6's remaining work is **tightening** rather than **migrating**: the
field migration is done; the regression guards are not yet strict.

#### Sub-commit plan (approved 2026-04-22)

| # | Scope | Primary files |
|---|-------|---------------|
| A | Tighten `test_tune_to_interp.py` protocol assertions. Promote the soft `if output.per_model_score_tables:` guard to a **required** assertion. Add assertions for `summary.best_score_table` + `summary.formal_score_table` flow-through at the protocol layer (fields added in Phase 3 but never verified end-to-end in dual mode). | `tests/integration/protocols/test_tune_to_interp.py` |
| B | Dual-mode proposer-prompt end-to-end render assertion. Capture the final stage user prompt via the dual-mode bridge and assert it contains (1) `## Candidate Models — detailed view`, (2) `### Candidate: <name>`, (3) at least one score_table markdown row. This is the missing end-to-end validation of Phase 5 C through the full interp → `local_full_context` → proposer chain — unit tests cover the rendering path in isolation. | `tests/integration/protocols/test_interp_to_propose.py` (extend F.5 or add sibling) |
| C | *Optional, low priority.* Polish the 2 LLM-narrative `file_vector` strings in `api_call_outputs/result_interpretation_agent/generate.json` + `api_call_outputs/ml_model_proposal_agent/generate.json` to say `score_table` for consistency. Skip if Phase 7 is urgent. | `tests/pseudo_data/api_call_outputs/**/generate.json` |
| D | Single commit covering 6A + 6B (+ 6C if included). Mark Phase 6 checkboxes complete. | `docs/aggregated_score_table_awareness.md` + commit |

**Deferred out of Phase 6 (tracked under Phase 7):** Tier 3 real-run
spot-check of `test_full_exploration_loop.py`. Rationale: the test requires
CUDA GPU + TIDMAD data + real API key — exactly the setup needed for the
Phase 7 launch. Running it as a separate Phase 6 step would be pure
duplication of compute cost. The launch gate itself acts as the Tier 3
validation.

Steps (live checklist):
- [x] **A.** Tighten `test_tune_to_interp.py`. Added inline
      `_make_score_table` helper using the REAL `render_comparison_table`
      so fixture markdown matches production. Wired
      `best_score_table` + `formal_score_table` onto `_WAVENET_TUNING_OUTPUT`.
      Hard assertions added: `summary.best_score_table` + `summary.formal_score_table`
      non-None with canonical `| file | raw_baseline | ground_truth |` header;
      `output.per_model_score_tables` required (no soft `if:` guard);
      `"wavenet" in output.per_model_score_tables`; row-level low/high-freq
      checks unconditional. Regression-proven: stripping `best_score_table`
      from the fixture reproduces None on the summary side. 589 tests green
      (proposal + interp + protocol units + dual-mode integration).
- [x] **B.** Dual-mode end-to-end proposer-prompt render assertion. Added
      sibling `test_proposer_prompt_carries_score_tables` (F.6) in
      `tests/integration/protocols/test_interp_to_propose.py`. Builds a
      3-model `InterpretationOutput` with full `ScoreComparisonTable`s via the
      real `render_comparison_table`, applies `local_full_context` with
      `ModelSelectionStrategy(params={"n": 2})` so fcnet is forced into the
      non-candidate overview, runs the proposer against
      `RecordingLLMBridge.for_agent("ml_model_proposal_agent")`, and captures
      every `generate()` user prompt. Hard-asserts all three Phase 5-C
      signatures on the captured prompts: (1) `## Candidate Models — detailed
      view` heading, (2) `| file | raw_baseline | ground_truth |` canonical
      rendered_markdown header, (3) `score_summary` / `log_scalar=...` +
      exact `log_scalar=2.50, recovery=26.3% on 20 files` fcnet one-liner
      from `build_score_summary_line`. Pseudo-only (skips under `--real-llm`
      — bridge capture is meaningless without `RecordingLLMBridge`). 3/3
      captured stage prompts carry all signatures; 587 units + 3 dual-mode
      protocol tests green, no collateral damage.
- [~] **C.** *Skipped intentionally.* Narrative-prose polish of 2
      `file_vector` string mentions in pseudo-fixture `generate.json` files is
      cosmetic only — no structural schema keys are stale. Deferred as
      non-blocking; can be picked up opportunistically.
- [x] **D.** Commit `test(score_table): Phase 6 A + B — hard protocol
      assertions on ScoreComparisonTable flow-through`. Doc checkboxes closed,
      status line promoted to **Complete (2026-04-22)**.

Shipped shape: A + B + D in one commit (C skipped per directive). Phase 7
launch gate unblocked **in principle** — but see Phase 6.5 below: after
commit `4cce4d2` we realised Phase 6 proves wires, not semantics, and a
real-LLM probe is cheap enough to run before risking the Phase 7 launch.

---

### Phase 6.5 — Semantic smoke (two-stage gate, 2026-04-22)

**Why this phase exists.** Phase 6 is a wiring audit: Pydantic contracts
hold end-to-end and the Phase 5 C markdown signatures physically appear in
the proposer's stage prompts under a `RecordingLLMBridge`. It does **not**
prove that a real LLM, given those prompts, actually reads or cites the
table values. The audit of `4cce4d2` surfaced three gaps the mechanical
tests cannot close:

1. Does the LLM cite specific numerics from the injected table, or does
   it ignore the table and hallucinate generic prose?
2. Does the `runtime_vocab` grow across iterations when fed real
   interpreter output?
3. Do the per-round VRAM + wall-time budgets we plan to use at launch
   (60 s trial / 20 min formal) actually hold on the 5090?

Running the full `small_sample_trial_v1` launch to discover a "no" on
any of those is expensive. Phase 6.5 answers each cheaply by splitting
the probe into two stages with a hard gate in between.

#### Stage 1 — "The Brain" (pseudo training + real OpenAI)

**Goal:** prove the LLM reads and uses the score table, without spending
a single GPU second.

**Mechanism.**
- Real OpenAI (`gpt-4o-mini`) for both `ResultInterpretationAgent` and
  `MLModelProposalAgent`.
- Pseudo training: synthetic `ModelRunSummary` fixtures with
  distinctive `best_score_table` attached via the Phase 6 B helper.
  No GPU, no subprocess.
- 2 iterations:
  - Iter 1: interp → protocol → 3-stage proposer pipeline.
    Recording-bridge captures every proposer LLM response (comparison,
    causal_reasoning, proposing_commit). A regex scanner tallies hits
    across four signature families: (a) file-index citations (0–19),
    (b) injected scalar values rendered to 1–2 decimals,
    (c) recovery-% rounded to int, (d) snake_case column tokens that
    would not appear in plain English (`model_scalar`, `gain_vs_raw`,
    `raw_baseline`, `ground_truth`, `percent_of_ceiling`,
    `log_scalar`, `headroom_vs_gt`).
  - Iter 2: append a synthetic run of the iter-1 proposal with its own
    score table, re-run interp with iter-1 `runtime_vocab` carried
    forward, assert vocab strictly grew.

**Gate criteria.**
- Iter 1: total numeric hits across all proposer stages **> 0**
  (scanner calibrated: 0 hits on generic-architecture prose, 13 hits
  on well-formed citation text).
- Iter 2: `len(iter2.runtime_vocab) > len(iter1.runtime_vocab)` OR
  non-empty add/refine diff; zero entries may be dropped.

**File:** `tests/integration/workflows/test_score_table_pseudo_smoke.py`.
Marked `@pytest.mark.real_run`; skips without `OPENAI_API_KEY`.

**Status:** ✅ Green 2026-04-22. One run (86.4 s, 6 OpenAI calls).

- Iter 1 produced **19 numeric hits** across stages —
  comparison=13, causal_reasoning=5, proposing_commit=1. The LLM cited
  exact scalars (`5.58`, `2.35`), file-index ranges (`files 0-4`,
  `files 5-19`), per-file values (`4.2 to 9.0`, `1.5 to 3.4`,
  `below 0.2`), and recovery % (`58.7% of ceiling`). The `causal_reasoning`
  stage's falsifiable prediction was stated directly on
  `mean(file_vector[0:4])` with `current_value=0.15` — an average
  computed from the injected low-freq rows. The final committed
  `ProposalOutput.motivation` compresses this into generic prose
  (0 hits), which is fine: the decision (propose `wave_specialist`
  targeting the low-freq blind spot) was already shaped by the
  numerics at the earlier stages.
- Iter 2 `runtime_vocab` grew 0 → 3: `specialized_frequency_layers`
  + `prediction_wave_specialist_confirmed` +
  `score_wave_specialist_vs_sota`. Interp also computed
  `mean(file_vector[0:4]) = 1.025` from the injected iter-2 file
  vector — more evidence the numeric path is live.

The test file is kept committed as the standing semantic-contract
check; it doubles as the canary if future prompt changes silently
strip the score-table rendering.

#### Stage 2 — "The Body" (real GPU + real OpenAI)

**Goal:** prove the resource envelope holds for 2 real iterations
before launching the Phase 7 rerun, which is a longer/wider version of
the same loop.

**Mechanism.** Real `run_workflow` on `small_sample_trial_v1` seeds,
OpenAI for every agent in the chain, 2 iterations, budgets:

| Phase | Budget | Justification |
|---|---:|---|
| Trial per round | **60 s** | `trial_portion=0.02`, `max_epochs=1` on 5090 is ~20–40 s for seed-scale models. Agent-proposed archs may be heavier; log overruns but don't abort — overruns ARE signal. |
| Formal per round | **20 min** | Full 20-file × full-segment eval dominates. Seed-scale models fit in 10–15 min; transformer-scale proposals may be tight. Again: treat overrun as signal, not failure. |

Recorded per iteration:
- Peak VRAM via `torch.cuda.max_memory_allocated()`
- Wall-time per phase (tune, inference, score)
- Whether the iter completed without OOM/timeout

**Gate criteria.**
- Both iterations complete without hitting OOM or the wall-clock timeout.
- Peak VRAM stays under the 5090's 32 GB envelope.
- Aggregate wall-time per formal round ≤ 20 min with ≥ 10% headroom
  (i.e., ≤ 18 min observed average) — below that, Phase 7's 6+
  iterations are defensible.

**File:** `tests/integration/workflows/test_score_table_real_smoke.py`.
To be written after Stage 1 is committed. Not part of CI —
`@pytest.mark.real_run` + requires GPU + `OPENAI_API_KEY`.

**Status:** ⏳ pending (Stage 1 green — proceed to write).

---

### Phase 7 — Launch gate (small_sample_trial_v1)

**Goal:** kick off the v1 rerun only after Phases 1–6 are committed and
green.

Steps:
- [ ] Confirm Phase 6.5 Stage 2 green (resource envelope holds on 2
      real-GPU iterations with OpenAI + `small_sample_trial_v1` config).
- [ ] Confirm Phases 1–6 merged; relevant integration tier green.
- [ ] Verify `run_all_models_trial.sh` has `RUN_NAME="small_sample_trial_v1"`
      (already set) and the seeds in `run_exploration_adaptive.py` still
      point at the correct source paths.
- [ ] Launch `small_sample_trial_v1` for wavenet + punet + fcnet (tmux,
      per-model group ordering).
- [ ] First iteration: verify the tuner prompt and reflector prompt both
      contain the three-column table (tail the run log / inspect a captured
      prompt).

**Decision 12 (resolved → wait for Phase 6, do not launch earlier):** the
value of this feature is compounding insight across the whole chain
(tuner → interpreter → proposer → next-round planner). Launching after
Phase 3 would give the tuner score_tables but leave the downstream agents on
the old file_vector, which produces incomplete data and prevents validating
the core hypothesis of this design. v1 waits for full-graph awareness.

---

### Phase 8 — Cognitive Alignment (V9 launch gate, 2026-05-01)

**Status:** ⏳ in progress — foundation commits 1–3 landed; commit 4 (this doc) is the only one still in flight. After it lands, the foundation is closed and the next track is P3 (chain plumbing) → P1-Impact (zero-hardcoding refinement) → P2-Impact (prompt rewrite) → P4-Impact (cognitive-alignment behavioural test).

#### Foundation commits (prerequisite to P1-Impact / P2-Impact / P3 / P4)

These four commits land the data-correctness + observability bedrock that the
downstream cognitive-alignment work assumes. They were approved on 2026-05-01
after the Path-A regen verification (File 0 / File 18 hand-computed values
matched the regenerated JSONs).

| # | Title | Status | Notes |
|---|-------|--------|-------|
| 1 | `feat(scoring): drop round-2dp from compute_*.py + regen reference` | ✅ landed `8947511` (2026-05-01) | `compute_raw_baseline.py` + `compute_ground_truth.py` + `reference_data/raw_and_ground_score.md`. All 20 fine-file JSONs regenerated under `/home/klz/Data/SIDEREIS_DATA/{raw_baseline,ground_truth}/` with `*.bak_20260501_110716` backups. Scalars now read raw `1.0007` / gt `10.1134`. |
| 2 | `feat(observability): persistent audit stream for score tables` | ✅ landed `b222a16` (2026-05-01) | New `nodes/agent_data_stream.py` (best-effort JSONL appender at `{workspace}/logs/agent_data_stream.jsonl`) + audit-logging block in `nodes/ml_hyperparameter_tune_agent.py` only. Tune-agent imports cleanly; end-to-end exercise lands via Gate 2 in §12.5. |
| 3 | `fix(scoring): harmonize model column to log-space + clip headroom at 0` | ✅ landed `564e0ac` (2026-05-01) | `file_vector_to_log_space()` helper + `_LOG_OFFSET = 1e-10`; `PerFileRow.headroom_vs_gt` Pydantic `ge=0.0`; `_build_rows` clips negative headroom; tune-agent call site converts `score_vector`'s linear file_vector before `build_score_table`. **39/39** in the two relevant test files green pre-commit; 2 pre-existing tests updated to match the clip contract. |
| 4 | `docs(phase8): cognitive-alignment + zero-hardcoding refinement with impact-aware reasoning` | ✅ landed `92cd0e6` (2026-05-01) | This document — Phase 8 (problem + solution + commit plan), §12.5 V9 launch gates, Phase 8 Refinement rewritten under the **Zero-Hardcoding** principle (no fixed weight thresholds, no static "Inconsequential / IGNORE" partition; agent ranks dynamically by `Impact_Score`). +615 lines. Foundation tracker self-marked as landed. |
| 5 | `refactor(infra): replace range(20) with NUM_FILES; parameterise schema bounds` | ⏳ queued (Total Genericity Audit Tier 2 + 2.5) | Mechanical: `execute_tools/scoring_helpers.py:167`, `nodes/scoring_reference.py:27`, `compute_raw_baseline.py:154` — `range(20)` → `range(NUM_FILES)`. `agent/schemas/score_table.py` — `PerFileRow.file_index`, `AggregateScalars.num_sampled_files`, `ScoreComparisonTable.rows` length all reference `NUM_FILES` from `execute_tools/dataset_config`. Strips fixed-shape assumptions ahead of P1-Impact so the cognitive-alignment commits stay clean. |

**Audit decision (2026-05-01)**: during the commit-3 pause we audited the doc
for hardcoded classification logic. The committed and staged code carries
**no** static partition or threshold — schemas store raw numbers, helpers
clip headroom only as a unit invariant (a header comment explains "dead-zone
files" purely as background; the diagnostic itself is conveyed elsewhere).
The hard-coding lived entirely in the doc (original `HEADROOM_EPSILON = 0.5`
plan and the linear-weight refinement's `HIGH_IMPACT_CUMULATIVE_THRESHOLD =
0.90` / `INCONSEQUENTIAL_WEIGHT_THRESHOLD = 1e-3` plus an "IGNORE these
files" prompt block). That logic is being replaced in commit 4 — see the
revised **Phase 8 Refinement** section below.

#### Problem statement

V8 ran 6 chain iters (4 with valid formal scores) and produced 6
nearly-identical `take_home_message`s converging on a fictitious diagnosis:
*"low-frequency failure plus high-frequency over-amplification, need a
broadband-calibrated denoiser."* Each iter's proposer dutifully proposed a
"calibrated multiband" model targeting that same fiction. Best score
plateaued at 5.632 from iter_2 onward. SSM iters (3 and 5) were killed by
the time-risk gate, so 4 of 6 iters were uninformative on top of this.

Audit of the V8 records confirmed `best_score_table` was populated and
threaded correctly through the protocol layer — the data was honest. The
**framing around the data was potential-blind** in three concrete places:

1. **Interpreter pre-digests the table through an absolute threshold.**
   `nodes/result_interpretation_agent.py:313-321` (in `_build_synthesis_prompt`)
   flags `model < 1.0` as "Weak Frequency Files" and `model >= 10.0` as
   "Strong" — without consulting `headroom_vs_gt`. Files 0–3 have
   `ground_truth` intrinsically at the −13.854 clip floor (zero recoverable
   signal), so any model is structurally guaranteed to score below 1.0
   there. The "Weak Frequency Files (attention cue)" section, rendered
   immediately next to the table in the synthesis prompt every iteration,
   teaches the LLM that the dataset's lower limit is a model deficiency.

2. **Synthesis system prompt has no potential-aware framing.**
   `SYNTHESIS_SYSTEM_PROMPT` (lines 187–228) instructs *"Which frequency
   ranges are well-handled vs universally weak"* — absolute concepts. No
   reference to `gain_vs_raw` or `headroom_vs_gt` columns. No instruction
   to ignore files where headroom is structurally zero. The take_home
   instruction is leading: *"the single most critical insight that
   motivates designing a new architecture"* — pre-supposes the answer.
   Even when the right answer is "current architecture is at the dataset
   ceiling on the high-headroom files", the LLM is forced to manufacture a
   reason to change architecture.

3. **Chain instrumentation stamps every iter as `iteration=1`.**
   `workflows/model_exploration.py:820` always loops
   `for iteration in range(1, max_iterations + 1)`. Chain mode runs
   `max_iterations=1`, so each chain subprocess writes `iteration=1` into
   `evolution_log.jsonl`. The chain runner
   (`sdsc_submission_scripts/run_one_iteration.py:620`) consumes
   `--start_iteration` for plugin restoration but never threads it into
   `run_workflow`'s loop variable. Post-mortem reads of the evolution log
   cannot tell which chain iter wrote which line.

4. **Phase 6.5 Stage 1 semantic smoke test missed all of the above.** It
   asserted *"the LLM cites numbers from the table"* (19 numeric hits
   passed). It never asserted *"the LLM reasons in terms of headroom
   rather than absolutes"*. A run that cites *"files 0–3 score below 0.2"*
   passes the smoke test while making the exact wrong inference. The
   smoke test calibrated for "is the data being read?" not "is the data
   being interpreted correctly?"

#### Solution

Three priority-ordered fixes plus a new behavioral test that closes the
Phase 6.5 evaluation gap and acts as the V9 launch gate.

**P1 — Headroom-aware partitioning in the interpreter prompt.**
Replace the absolute-threshold callout with two lists computed from
`PerFileRow.headroom_vs_gt`:

- **Active Search Space** — files where `|headroom_vs_gt| > ε`. These
  are the only files where model improvements can move the score. Render
  with file indices and remaining headroom per file.
- **Information Dead Zone** — files where `|headroom_vs_gt| < ε`.
  Explicitly prefixed: *"IGNORE these files. They are dataset-limited.
  Any low score here is NOT the model's fault."*

`ε` is a small log-space constant (proposed default: `0.5` log-space units
on the global `s_max` — large enough to cover float noise on clip-floor
files, small enough to not exclude files with genuine recovery
opportunity). Calibrated against the on-disk reference scalars; covered
by a unit test that asserts files 0–3 land in the dead zone for every
realistic ground_truth profile.

**P2 — Neutralize the synthesis system prompt.**
Remove the leading instruction *"the single most critical insight that
motivates designing a new architecture"*. Replace with:

> *"Assess whether the current architecture has saturated the available
> headroom in the Active Search Space. If yes, state that the chain has
> reached the dataset ceiling — do not invent a fictitious deficiency.
> If no, identify which high-headroom bands are failing and suggest
> specific modular changes targeted at those bands. Files in the
> Information Dead Zone are dataset-limited; do not propose model changes
> aimed at improving them."*

Also rename the `frequency_comparison` field-instruction from *"well-handled
vs universally weak"* to *"reference `gain_vs_raw` and `headroom_vs_gt`
columns; bands with `|headroom_vs_gt| < ε` are dataset-limited and not
model-attributable."*

**P3 — Fix chain instrumentation.**
Add `start_iteration: int = 1` parameter to `run_workflow`. Change the
loop from `range(1, max_iterations + 1)` to
`range(start_iteration, start_iteration + max_iterations)`. Thread
`start_iteration=args.start_iteration` from `run_one_iteration.py`'s
`run_workflow(...)` call.

**P4 — New behavioral test: `test_cognitive_alignment_smoke.py`.**
Multi-iter pseudo-training + real OpenAI probe that asserts the LLM's
reasoning is headroom-aware, not just that it cites numbers. This is the
test V8 would have failed; it gates the V9 launch.

#### Detailed commit plan

| # | Scope | Files |
|---|-------|-------|
| 1 | **P1** — Headroom-aware callout. Replace `_build_synthesis_prompt:313-321` (and `_build_per_model_prompt` if the same `<1.0` heuristic exists there). Define `HEADROOM_EPSILON = 0.5` constant. Render *Active Search Space* + *Information Dead Zone* lists with explicit "IGNORE" prefix on the dead-zone block. Drop the absolute `<1.0` / `>=10.0` callout entirely. Unit tests (4 cases): files 0–3 at floor → dead zone; file 19 high recovery → active; all-zero-headroom → entire active list empty + ceiling-state cue; epsilon boundary. | `nodes/result_interpretation_agent.py` · `tests/unit/agent/result_interpretation_agent/test_interpretation_agent.py` |
| 2 | **P2** — Rewrite `SYNTHESIS_SYSTEM_PROMPT`. Drop the architecture-bias rule. Add headroom-aware framing per spec above. Add explicit "saturated → declare ceiling" branch. Rename `frequency_comparison` field-instruction to cite `gain_vs_raw` / `headroom_vs_gt`. Unit tests (2 cases): prompt string contains the ceiling branch substring; prompt string contains the high-headroom-bands branch substring. | `nodes/result_interpretation_agent.py` · `tests/unit/agent/result_interpretation_agent/test_interpretation_agent.py` |
| 3 | **P3** — Add `start_iteration: int = 1` arg to `run_workflow`. Change the loop. Thread from `run_one_iteration.py`. Update `evolution_log.jsonl` writer site to use the loop's `iteration` variable (already does — the bug is upstream of the writer). Unit tests (2 cases): `start_iteration=1` unchanged behavior; `start_iteration=5, max_iterations=1` writes a single iter row stamped `iteration=5`. | `workflows/model_exploration.py` · `sdsc_submission_scripts/run_one_iteration.py` · `tests/unit/workflows/test_model_exploration.py` |
| 4 | **P4** — `tests/integration/workflows/test_cognitive_alignment_smoke.py`. New file. `@pytest.mark.real_run`, skips without `OPENAI_API_KEY`. 3-iter pseudo-training loop with hand-crafted `ModelRunSummary` fixtures — files 0–3 at clip floor (dead zone), files 11/15 at moderate recovery, file 19 at high headroom. Real OpenAI for `ResultInterpretationAgent` and `MLModelProposalAgent`. `RecordingLLMBridge` captures every stage prompt and response. Assertions detailed below. This is the V9 launch gate. | `tests/integration/workflows/test_cognitive_alignment_smoke.py` |

#### P4 test design — the V9 gate

Pseudo training inputs (per iter): a synthetic `ModelRunSummary` with a
populated `best_score_table` shaped to the V8 dataset structure:

| File range | `raw_baseline` | `ground_truth` | `model` | classification |
|---|---|---|---|---|
| 0–3 | clip floor (≈ −13.85) | clip floor (≈ −13.85) | clip floor | dead zone |
| 4–10 | moderate | moderate | within ε of ground_truth | low headroom |
| 11–15 | moderate | high | partial recovery (≈ 50–70% of ceiling) | active — opportunity |
| 16–18 | low | high | high recovery (≈ 80–90% of ceiling) | active — near ceiling |
| 19 | low | very high | low recovery (≈ 30%) | active — biggest opportunity |

Across 3 iters, vary the `model` column slightly so the chain has
genuine signal to react to (iter_2 model improves on file 19 by 0.5;
iter_3 plateaus). The dead zone is invariant across iters.

**Assertions (all must pass for the test to gate V9):**

1. **Negative assertion (no false-positive dead-zone targeting).** Across
   all 3 iters' `take_home_message`s, scan for forbidden phrasings:
   `"low-frequency failure"`, `"low-band suppression"`, `"files 0-3 ..."`
   when used as a problem-to-fix. Permitted: dead-zone references with
   neutral framing (`"dataset-limited"`, `"ignored"`, `"clip floor"`,
   `"no headroom"`). At most 0 forbidden matches across all 3 iters.

2. **Positive assertion (correct reasoning surfaces).** Each iter's
   `take_home_message` must contain at least one of:
   - a "ceiling-reached" cue (`"saturated"`, `"ceiling"`, `"no further
     headroom"`, `"dataset-limited"` applied to the chain's progress), OR
   - a specific high-headroom file reference (`"file 19"`, `"files
     16-19"`, etc.) framed as the target for next-round work.

3. **Echo-chamber regression guard.** Compute pairwise normalised token
   overlap (Jaccard on lowercased word tokens) across the 3 take_homes.
   If all 3 pairs exceed 0.7, the test fails — this is the V8 echo
   chamber pattern. Acceptable patterns: (a) all 3 converge on "ceiling
   reached" with low pairwise overlap, OR (b) take_homes diverge across
   iters as the model evolves.

4. **Proposer dead-zone neutrality.** Capture the final
   `proposing_commit` stage prompt for each iter via `RecordingLLMBridge`.
   Assert it references files 0–3 only with neutral language; assert the
   proposed model description (free text) does not name files 0–3 as
   improvement targets.

5. **Numeric-citation continuity (Phase 6.5 Stage 1 carryover).** The
   per-iter scanner from `test_score_table_pseudo_smoke.py` still applies:
   total numeric hits across proposer stages > 0 per iter. Ensures the
   table is still being read, not just framed correctly.

**Calibration**: before promoting to gating, run the test against the
**existing (broken)** prompt to confirm assertions 1 and 3 fail — if they
pass on the V8-style prompt, the assertions are too weak.

#### Test plan summary

- **Unit (per commit, run before commit per `feedback_test_before_commit.md`):**
  Commit 1: 4 cases. Commit 2: 2 cases. Commit 3: 2 cases.
- **Integration (commit 4 only, `@real_run` + OpenAI):**
  3 iters × 2 LLM agents ≈ 6–10 calls, ~90 s wall time. Pseudo training
  only — no GPU dependency. Run before V9 launch.

#### Live checklist

- [ ] **1.** P1 headroom-aware callout
- [ ] **2.** P2 neutralize synthesis prompt
- [ ] **3.** P3 chain `iteration` field fix
- [ ] **4.** P4 cognitive-alignment behavioral test (calibrated against
      old prompt → fails; passes against new prompt)
- [ ] V9 launch — only after 1 + 2 + 3 are committed *and* 4 is green

#### Phase 8 Refinement — Impact-Aware Interpretation (Zero-Hardcoding, 2026-05-01)

**Status:** ⏳ supersedes both the original P1 (`HEADROOM_EPSILON = 0.5`
log-space partition) and the earlier "Linear-weight" version of this section
(`HIGH_IMPACT_CUMULATIVE_THRESHOLD = 0.90` / `INCONSEQUENTIAL_WEIGHT_THRESHOLD
= 1e-3`, "IGNORE these files" prompt). Both contained **static thresholds and
fixed file-class labels** — exactly the kind of hardcoding that prevents the
agent from learning where the next-iter opportunity actually lies. P3 + P4
are unchanged in spirit but their assertions are rewritten below.

##### Guiding principle — Zero-Hardcoding

The agent must read opportunity dynamically from the data each iteration.
Concretely:

- **No threshold constants** in code or prompts (no `0.90`, no `1e-3`, no
  `ε=0.5`). The schema stores raw numbers; the partition decision is *not*
  encoded.
- **No file-class labels** ("Inconsequential", "Dead Zone", "Active Search
  Space") and no instructions to **IGNORE** any subset of indices. A file
  that has near-zero linear weight today may become the only available lever
  later if higher-weight files saturate.
- **No baked-in outcome lists** in tests (no "files 0–3 land in the dead
  zone"). Tests assert *properties* (weights sum to 1, `Impact_Score = 0`
  iff `model = gt`, ranking is monotone in `Impact_Score`), not specific
  index identities.
- **Saturation is a relative reading**, not a threshold check. The LLM
  judges saturation from the shape of the `Impact_Score` distribution
  alongside the current `model_scalar` — both live on the same log-space
  ruler, so "is the largest remaining opportunity small?" is a comparison
  the LLM can make without any code-side cutoff.

The schema additions (`linear_weight`, `impact_score`) are **raw data**, not
classifiers. The agent ranks them at read time.

##### 1. Motivation — the "log-of-mean trap"

The production scalar is

```
final_scalar = log_{5.27}(  Σ_{f,i} per_segment[f,i]  /  Σ_f |S_f|  +  1e-10 )
```

— a **log of a sum**, not a mean of logs. Files contribute to the inner sum
proportionally to their **linear** per-segment energy. A multi-log-unit
improvement on a tiny-linear-energy file barely moves the sum; a fractional
log-unit improvement on a dominant-linear-energy file moves it
substantially.

Numerically, on the post-Path-A `gt` ceiling distribution today, file 17
alone carries ~31.5% of `Σ`; the top 6 files (14–19) carry ~91%; files 0–8
collectively carry <0.1%. **These are observations about today's dataset,
not classifications.** The agent reads them live each iter from the
`Linear_Weight` column. As the model improves and the contribution shape
shifts (e.g. once file 17 is fully recovered, its remaining `Impact_Score`
drops to zero and the lever moves elsewhere), the ranking that matters is
the live `Impact_Score` ranking — not yesterday's "high-impact list".

The "log-of-mean trap" is not "files 0–8 are inconsequential". It is the
geometric fact that **a log-space gap is not a linear-space contribution**.
The cure is to render both `Linear_Weight` (where the scalar lives now) and
`Impact_Score` (where the next-iter lever is) as columns and let the agent
rank them.

##### 2. The two metrics — Impact_Score (primary) and Linear_Weight (context)

Define, per-iteration, over the model-sampled file set $S$:

- **`Linear_Mean_f`** — the per-file linear value already on `PerFileRow`
  upstream (the linear `file_vector` entry, before the log conversion).
- **`Σ = Σ_{f∈S} Linear_Mean_f`** — the same denominator the scalar uses,
  restricted to the sampled subset.

**`Linear_Weight_f = Linear_Mean_f / Σ`** — fractional contribution of file
$f$ to the scalar **right now**. Sums to 1 over the sampled set. This is a
*context* metric: it tells the agent where the scalar's mass currently
sits, which by itself does not say where the next opportunity is. A file
can have high `Linear_Weight` and zero remaining headroom (already at the
ceiling); a file can have low `Linear_Weight` and large headroom (small
mass, but if higher-mass files saturate, this becomes the lever).

**`Impact_Score_f`** — the marginal log-scalar gain a file would induce if
its `model_linear` were lifted to its `gt_linear`:

```
Impact_Score_f =
  log_{5.27}(grand_mean_with_file_f_at_ceiling + 1e-10)
  − log_{5.27}(grand_mean_current + 1e-10)
```

Computed cheaply from cached `linear_sum`s. Properties:

- Non-negative (negative values clip to zero, mirroring `headroom_vs_gt`).
- Equals zero iff `model_linear ≥ gt_linear` (file already at or above
  ceiling).
- Folds in *both* "where the scalar lives now" (via `Σ`) *and* "how much
  room is left on this file" (via `gt_linear − model_linear`). A
  high-`Linear_Weight` file that is already saturated has
  `Impact_Score → 0` even though its weight stayed unchanged.

**`Impact_Score` is the primary opportunity metric**; the agent ranks by
it. `Linear_Weight` is rendered alongside as context only.

##### 3. Adaptive interpretation — no partitions, no thresholds, no IGNORE

The interpreter prompt **does not partition** files into named classes.
There is no "High-Impact / Mid-Impact / Inconsequential" block, no
`HIGH_IMPACT_CUMULATIVE_THRESHOLD`, no `INCONSEQUENTIAL_WEIGHT_THRESHOLD`,
no instruction to ignore any index.

Instead, the agent is given two columns and a reasoning frame:

- The 20-row table is rendered in file-index order (preserves spatial
  intuition the proposer relies on for frequency-band reasoning).
- A **secondary block** lists files re-sorted by `Impact_Score` descending,
  with their `Linear_Weight` and `headroom_vs_gt` shown alongside. This is
  the "where can the next iter push?" view.
- The prompt frame (§4 below) tells the agent how to read these — relative
  comparisons across the iter, not against fixed cutoffs.

**Adaptive saturation.** The agent declares the chain saturated when the
`Impact_Score` column shows that no remaining lever is large enough to
matter — a *relative* judgment the agent makes by comparing entries within
the column and against the magnitude of `model_scalar` itself (both live on
the same `log_{5.27}` ruler). There is no fixed `ε`; "small enough to call
the chain done" is the agent's reading. The audit stream
(`agent_data_stream.jsonl`) preserves the column values across iters so
post-hoc analysis can verify the call was reasonable, but the runtime path
carries no threshold.

This fully decouples the partition decision from the code: the *only* way
the agent's classification of a file changes is by reading a different
`Impact_Score` value next iter.

##### 4. Prompt engineering — Impact_Score-aware reasoning

Replace the existing `SYNTHESIS_SYSTEM_PROMPT` field-instructions for table
reading with the section below. Note: zero file-class labels, zero numeric
cutoffs, zero "IGNORE" verbiage.

> ### Reading the score table — the Log-of-Mean trap
>
> The aggregate scalar is `log_{5.27}` of a **sum** of per-segment linear
> energies, not a mean of per-file log scores. A file's contribution to
> the next-iter improvement budget is captured by **two** columns:
>
> - **`Linear_Weight`** — the file's current share of the scalar's linear
>   denominator. Tells you *where the scalar lives now*. Sums to 1 across
>   sampled files.
> - **`Impact_Score`** — the log-scalar gain you would obtain by lifting
>   this file's `model` to its `ground_truth`. Tells you *where the
>   next-iter lever is*. A high `Impact_Score` means a file with both
>   meaningful weight and remaining headroom; a near-zero `Impact_Score`
>   means either the file is already at its ceiling or its weight is too
>   small for any improvement to register.
>
> When you analyse bottlenecks:
>
> 1. **Rank by `Impact_Score` descending** to identify this iter's
>    largest available levers. A multi-log-unit `headroom_vs_gt` does not
>    by itself indicate opportunity — only `Impact_Score` does.
> 2. **Read `Linear_Weight` for context.** It is *not* a ranking metric on
>    its own — a high-weight file at its ceiling has zero `Impact_Score`
>    and is not actionable.
> 3. **Saturation is a relative reading.** If the entire `Impact_Score`
>    column is small in magnitude relative to the current `model_scalar`
>    and to the gains your chain has been making per iter, the chain has
>    reached the dataset ceiling — declare it explicitly. There is no
>    fixed cutoff; you compare the distribution against the scale of
>    progress.
> 4. **No file is permanently irrelevant.** Today's near-zero
>    `Impact_Score` may rise next iter if higher-`Impact_Score` files get
>    fully recovered. Re-read the column each iter; do not memorise
>    file-class labels across iterations.

Rewrite the `frequency_comparison` field-instruction to:

> *"Cite `Impact_Score`, `Linear_Weight`, and `gain_vs_raw` together when
> discussing bottlenecks. Rank candidates for the next iter's improvement
> by `Impact_Score` descending. Do not assert frequency-band failures
> based on `headroom_vs_gt` alone — a large headroom on a low-weight file
> implies a near-zero `Impact_Score` and is not actionable."*

##### 5. Schema + table presentation

`agent/schemas/score_table.py`:

- Add two columns to `PerFileRow`:
  - `linear_weight: Optional[float]` — `None` when the file is unsampled;
    otherwise in `[0, 1]`. Pydantic `ge=0.0, le=1.0`.
  - `impact_score: Optional[float]` — non-negative log-space marginal
    scalar gain. `None` when unsampled or when `ground_truth` is missing.
    Pydantic `ge=0.0`.
- Add **one** computed-once invariant field to `ScoreComparisonTable`:
  - `linear_weight_total: float` — must equal `1.0 ± float-eps` over
    sampled rows; asserted by a Pydantic `model_validator`. This is a
    *correctness invariant*, not a classification.
- **Do not add** `high_impact_files` / `mid_impact_files` /
  `inconsequential_files` index lists. The schema stores raw values; the
  ranking is the consumer's job.

`execute_tools/scoring_helpers.py`:

- Modify `build_score_table` to accept the linear file_vector alongside the
  log file_vector (today only the log version is threaded through; the
  linear vector is the unconverted output of `score_vector`, already
  available at the call site). Compute `Linear_Weight` and `Impact_Score`
  per row from it.
- `render_comparison_table` gains two columns in the per-file table
  (`Weight %` and `Impact`) and a **secondary block** rendered immediately
  after the main table that re-orders the *sampled* rows by `Impact_Score`
  descending. No partition labels appear in the secondary block; it is
  just a re-sorted projection.

Markdown sketch (no canonical file indices baked in — these are
placeholders the renderer fills from whatever the iter actually sampled):

```
| file | raw_baseline | ground_truth | model | gain_vs_raw | headroom_vs_gt | Weight % | Impact |
|-----:|-------------:|-------------:|------:|------------:|---------------:|---------:|-------:|
|    0 |          ... |          ... |  ...  |        ...  |           ...  |    ...  |   ...  |
|    1 |          ... |          ... |  ...  |        ...  |           ...  |    ...  |   ...  |
|  ... |          ... |          ... |  ...  |        ...  |           ...  |    ...  |   ...  |

### Sampled files re-ranked by Impact_Score (descending)
| file | Impact | Weight % | headroom_vs_gt | model |
|-----:|-------:|---------:|---------------:|------:|
| ⟨largest-impact-this-iter⟩ |  ... |  ... |  ... |  ... |
| ⟨next⟩                     |  ... |  ... |  ... |  ... |
| ...                         |  ... |  ... |  ... |  ... |
```

##### 6. Revised commit plan (zero-hardcoding)

These rows replace the original Phase 8 P1/P2/P3/P4 entries (line 1596) and
also supersede the prior "linear-weight partition" version of this section.

| # | Scope | Files |
|---|-------|-------|
| 1-zh | **P1-Impact (zero-hardcoding).** Add `linear_weight: Optional[float]` (`ge=0, le=1`) + `impact_score: Optional[float]` (`ge=0`) to `PerFileRow`. Add `linear_weight_total` invariant to `ScoreComparisonTable` with `model_validator` (≈ 1.0 over sampled rows). Modify `build_score_table` signature + body to accept linear fv and compute `Linear_Weight` + `Impact_Score` per row. Update `render_comparison_table`: add `Weight %` and `Impact` columns to the main table; render a secondary "re-sorted by Impact_Score descending" block under the main table (no partition labels, no threshold-driven list). **Remove** any `_build_synthesis_prompt:313-321` callout that classifies files by absolute thresholds. **No threshold constants are introduced.** Property-based unit tests (no fixed-index assertions): (a) `Σ Linear_Weight ≈ 1` over sampled rows; (b) `Impact_Score = 0` iff `model_linear ≥ gt_linear`; (c) `Impact_Score > 0` when `model < gt`; (d) ranking by `Impact_Score` is invariant under permutation of input order; (e) trial subset (only a strict subset sampled) — unsampled rows carry `None`, weights re-normalise over sampled subset; (f) `linear_weight_total` validator catches out-of-bounds. | `agent/schemas/score_table.py` · `execute_tools/scoring_helpers.py` · `nodes/result_interpretation_agent.py` · `tests/unit/agent/schemas/test_score_table.py` · `tests/unit/execute_tools/test_scoring_helpers.py` · `tests/unit/agent/result_interpretation_agent/test_interpretation_agent.py` |
| 2-zh | **P2-Impact (zero-hardcoding) — expanded by Total Genericity Audit.** Rewrite `SYNTHESIS_SYSTEM_PROMPT`: drop the architecture-bias rule; insert the new "Reading the score table — the Log-of-Mean trap" section verbatim per §4 above (which contains zero file-class labels, zero numeric thresholds, zero IGNORE verbiage); rewrite the synthesis output field per §4. **Audit-expanded surface:** also rewrite `agent/prompts.py` (tuner system prompt L89–106 + REFLECTOR_PROMPT L193–198), `nodes/result_interpretation_agent.py` per-model prompt (L52–80, including the JSON output field `frequency_analysis` → `per_file_analysis`), and `nodes/ml_model_proposal_agent.py` (proposer reasoning step L207–210 + L241, plus the rendered "Weak Frequency Bands" block L600 — replace with a dynamic top-Impact-Score block, no `< 1.0` threshold). Strip "frequency band" / "low-frequency" / "frequency range" / fixed-index examples ("files 0-3", "files 15-19") throughout. Rename the synthesis output field `frequency_comparison` → `per_file_comparison`; protocol consumers update in lockstep. Property unit tests: (a) prompt contains the exact `Impact_Score` ranking instruction; (b) prompt does **not** contain any of `{"Inconsequential", "IGNORE", "0.001", "1e-3", "0.90", "HEADROOM_EPSILON", "frequency_analysis", "frequency_comparison", "low-frequency", "mid-frequency", "high-frequency"}` — guards against regressions back to threshold-based or denoise-specific phrasing; (c) prompt contains the relative-saturation framing substring. | `agent/prompts.py` · `nodes/result_interpretation_agent.py` · `nodes/ml_model_proposal_agent.py` · `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` (field rename) · `tests/unit/agent/result_interpretation_agent/test_interpretation_agent.py` · `tests/unit/agent/ml_model_proposal_agent/test_*.py` |
| 3 | **P3** — chain `start_iteration` plumbing. Unchanged from the original Phase 8 P3 (line 1598). | `workflows/model_exploration.py` · `sdsc_submission_scripts/run_one_iteration.py` · `tests/unit/workflows/test_model_exploration.py` |
| 4-zh | **P4-Impact (zero-hardcoding) — `tests/integration/workflows/test_cognitive_alignment_smoke.py`.** Pseudo-training fixture varies the per-file shape across 3 iters so that the "lever" file *moves* between iters (e.g. iter_1 lever is one file, iter_3's largest `Impact_Score` is a different file because the iter_1 lever has been recovered). Assertions (all property-based, no fixed-index expectations): (i) take_home cites the file with the largest `Impact_Score` *that iter*; (ii) take_home does **not** assert any file is permanently irrelevant; (iii) when the fixture is shaped so all `Impact_Score`s are small relative to `model_scalar`, take_home declares saturation (relative reading); (iv) Jaccard < 0.7 across the 3 take_homes (echo-chamber guard from the original P4 carries over); (v) the captured synthesis prompt contains both `Impact_Score` and `Linear_Weight` columns. | `tests/integration/workflows/test_cognitive_alignment_smoke.py` |

Net effect: 1-zh and 2-zh are smaller in code (no constants, no partition
helpers, no index lists) and stricter in tests (regression-guard tests that
explicitly forbid the dropped vocabulary). Commit 3 is unchanged. 4-zh's
fixture is *more* dynamic — the lever has to *move* across iters, so the
test catches an agent that learns a one-iter classification and reuses it.

##### 7. What we're explicitly removing

The following items appeared in earlier drafts of this section and are
**not** part of the zero-hardcoding plan:

- `INCONSEQUENTIAL_WEIGHT_THRESHOLD = 1e-3` (and any equivalent constant).
- `HIGH_IMPACT_CUMULATIVE_THRESHOLD = 0.90` (and any equivalent constant).
- `HEADROOM_EPSILON = 0.5` (the original P1's log-space partition cutoff).
- `high_impact_files` / `mid_impact_files` / `inconsequential_files` index
  lists on `ScoreComparisonTable`.
- The named partition labels "High-Impact" / "Mid-Impact" /
  "Inconsequential" in any prompt or rendered markdown.
- Any prompt instruction telling the agent to "IGNORE" a class of files or
  to refuse to "propose architecture changes targeted at" any subset.
- Unit tests that assert specific file indices land in specific classes
  (e.g. "files 0–3 → dead zone").

The original P1 (`HEADROOM_EPSILON`) was never merged. The earlier
linear-weight partition draft of this Refinement was never committed; it
is replaced wholesale by the zero-hardcoding version.

##### 8. Live checklist

- [ ] **1-zh.** P1-Impact: schema columns (`linear_weight`, `impact_score`,
      `linear_weight_total`) + `build_score_table` body + renderer columns
      and re-sorted secondary block. **No threshold constants.**
- [ ] **2-zh.** P2-Impact: rewrite `SYNTHESIS_SYSTEM_PROMPT` per §4
      (`Impact_Score` ranking, relative saturation, no IGNORE, no labels).
- [ ] **3.** P3 chain `start_iteration` plumbing (unchanged).
- [ ] **4-zh.** P4-Impact behavioural test — fixture must shift the lever
      file across iters; calibrate against pre-rewrite prompt → must fail.
- [ ] V9 launch — only after **1-zh + 2-zh + 3** are committed *and* **4-zh**
      is green.

The original P1/P2 entries in the live checklist (line 1666) are superseded
by **1-zh** / **2-zh**.

#### Total Genericity Audit (executed 2026-05-01, post-Commit 4)

**Audit goal.** With the *soul* of V9 documented (Commit 4), sweep the *body*
(infra + system prompts) for residual denoise-specific assumptions and
hardcoded shapes that bake `num_files=20` and "frequency band" framing into
the LLM's mental model. The cognitive-alignment commits (1-zh / 2-zh /
4-zh) should not have to relitigate dataset cardinality or task-specific
vocabulary along the way.

**Scope.** Three categories: (T1) production prompts that bake denoise
framing into LLM-facing text; (T2) production code that hardcodes the
20-file shape when `NUM_FILES` is already exported by
`execute_tools/dataset_config.py:84`; (T2.5) Pydantic schema bounds that
hardcode `file_index ≤ 19` / `num_sampled_files ≤ 20`; (T3) test fixtures —
deferred unless a corresponding production change forces a fixture
rewrite.

##### Tier 1 — Production prompts (LLM-facing)

Highest priority because they shape the LLM's mental model directly. These
hits all teach the model that the task is *denoising 20 frequency bands*
rather than *improving where the largest opportunity sits this iter*.

| File | Lines | Hardcoded leak | Why it matters |
|------|-------|----------------|----------------|
| `agent/prompts.py` | 89–97 | "ALL 20 files", "20 files × 200 segments = ~2000 segments total" | Bakes `NUM_FILES=20` into the LLM's scope; if a future task adds files (or a different dataset replaces TIDMAD), the prompt lies. |
| `agent/prompts.py` | 98 | `anchors`: "files 0, 10, 19 only (lowest, mid, highest **frequency**)" | Fixed indices + frequency framing. The strategy itself ("sparse extrema sampling") is task-agnostic; the labels aren't. |
| `agent/prompts.py` | 104–106 | "specific weak **frequency bands** … if files 0-3 score < 1.0, use `target_files: [0, 1, 2, 3]` to dedicate all training data to improving **low-frequency denoising**" | Fixed indices, hardcoded `1.0` threshold, and explicit denoise terminology in a single block. |
| `agent/prompts.py` | 193–198 | REFLECTOR "PER-FILE COMPARISON (frequency-band awareness)" + example "files 15-19 but regressed on files 0-3" | Trains the reflector to think in band labels rather than per-file dimensions. |
| `nodes/result_interpretation_agent.py` | 65, 73, 76 | per-model JSON field `frequency_analysis`; example bottleneck `'low-frequency blindness'` | Schema-level field name is task-bound; the LLM is forced to fill a frequency slot even when the right diagnostic is dimension-agnostic. |
| `nodes/result_interpretation_agent.py` | 198 | "Per-model file vectors (per-file performance across **20 frequency bands**)" | NUM_FILES + frequency framing both hardcoded in the synthesis input description. |
| `nodes/result_interpretation_agent.py` | 215, 223 | synthesis JSON output field `frequency_comparison` | Same problem at the output schema layer — the LLM emits a frequency-named diagnosis by construction. |
| `nodes/ml_model_proposal_agent.py` | 207–210 | "**Frequency analysis** and trial strategy guidance: … if **low-frequency files (0-4)** score near zero across all models, the new architecture should specifically address **low-frequency signal recovery**" | Hardcoded indices + denoise objective in the proposer's reasoning template. |
| `nodes/ml_model_proposal_agent.py` | 241 | "Which **frequency bands** (file indices) to focus on if using target strategy" | Reinforces the band framing into the proposer's `expert_advice.suggested_directions`. |
| `nodes/ml_model_proposal_agent.py` | 600 | `"### Weak Frequency Bands (score < 1.0 = no denoising effect)"` | Hardcoded `1.0` threshold + frequency framing + denoise objective; rendered into the proposer prompt every iter. |

##### Tier 2 — Production code with `NUM_FILES` already exported

`execute_tools/dataset_config.py:84` already exports `NUM_FILES = TIDMAD.num_files`. The fix is mechanical — replace `range(20)` with `range(NUM_FILES)`.

| File | Line | Current | Fix |
|------|------|---------|-----|
| `execute_tools/scoring_helpers.py` | 167 | `for i in range(20):` | `for i in range(NUM_FILES):` |
| `nodes/scoring_reference.py` | 27 | `_FINE_INDICES = tuple(range(20))` | `_FINE_INDICES = tuple(range(NUM_FILES))` |
| `compute_raw_baseline.py` | 154 | `_FINE_INDICES = tuple(range(20))` | `_FINE_INDICES = tuple(range(NUM_FILES))` |

`compute_ground_truth.py` already imports and uses `NUM_FILES` (post-Path-A
regen, Commit 1) — no change needed.

##### Tier 2.5 — Pydantic schema bounds

`agent/schemas/score_table.py` carries three hardcoded bounds:

- `PerFileRow.file_index: int = Field(..., ge=0, le=19)` — the `19` is `NUM_FILES − 1`.
- `AggregateScalars.num_sampled_files: int = Field(..., ge=1, le=20)` — the `20` is `NUM_FILES`.
- `ScoreComparisonTable.rows: list[PerFileRow] = Field(..., min_length=20, max_length=20)` — the `20` is `NUM_FILES`.

Fix: import `NUM_FILES` from `execute_tools.dataset_config` and reference
it directly in the `Field(..., le=NUM_FILES − 1, ...)` etc. calls. This
also eliminates a subtle drift hazard: today the schema's upper bound
silently disagrees with `NUM_FILES` if a future dataset config redefines
`num_files`.

The two existing tests in `tests/unit/agent/schemas/test_score_table.py`
(line 53–54 asserting `file_index=20` is rejected; line 165 asserting
`num_sampled_files=21` is rejected) keep working with no change because
they probe `NUM_FILES + 1` and `NUM_FILES + 2`, which remain out of bounds
under the parameterised version.

##### Tier 3 — Test fixtures (deferred)

`range(20)` appears in ~6 test files (`test_scoring_helpers.py:117`,
`test_estimator.py:145`, `test_compute_raw_baseline.py:157`, etc.).
Touching them requires no production behaviour change; they will be
swept up only when 2-zh's prompt rewrite or 4-zh's behavioural fixture
forces a fixture rewrite. Deferring keeps the diff small and avoids
churning tests that already work.

##### Audit delta plan

Two work items, sequenced so the cognitive-alignment commits stay clean:

| # | When | Scope |
|---|------|-------|
| **Foundation Commit 5** | Pre-P1-Impact, mechanical | Tier 2 + Tier 2.5. One commit. Replaces `range(20)` with `range(NUM_FILES)` in the three production files; parameterises the three schema bounds via `NUM_FILES` import. Existing schema tests stay green by construction (they probe `NUM_FILES ± 1`, not literal `20`). |
| **Folded into 2-zh** | Cognitive alignment, prompt rewrite | Tier 1. The 2-zh row in §6 already rewrites `SYNTHESIS_SYSTEM_PROMPT`; expand its scope to also strip frequency-band / low-frequency / denoise-specific framing from `agent/prompts.py` (tuner + reflector), `nodes/result_interpretation_agent.py` (per-model + synthesis), and `nodes/ml_model_proposal_agent.py` (proposer + render). Replace with task-agnostic *per-file dimension* language anchored to dynamic `Impact_Score` ranking — no fixed indices, no `< 1.0` thresholds, no "low-frequency" labels. The `frequency_analysis` and `frequency_comparison` JSON fields rename to `per_file_analysis` and `per_file_comparison` respectively (rename is part of the same prompt commit; protocols using these fields update in lockstep). |
| Tier 3 | Deferred | Test fixtures. Sweep only when a 2-zh / 4-zh change forces a fixture rewrite. |

##### Audit checklist

- [x] **A1.** Audit executed: T1 prompts + T2 code + T2.5 schemas + T3
      tests catalogued; delta plan recorded above.
- [ ] **A2.** Foundation Commit 5 — Tier 2 + Tier 2.5 mechanical commit
      (`range(NUM_FILES)` + schema-bound parameterisation). All affected
      unit tests green pre-commit.
- [x] **A3.** Tier 1 prompt rewrites folded into 2-zh's scope. The §6
      2-zh row above now lists the expanded surface (`agent/prompts.py`,
      `result_interpretation_agent.py` per-model + synthesis,
      `ml_model_proposal_agent.py`), the field renames
      (`frequency_analysis` → `per_file_analysis`, `frequency_comparison`
      → `per_file_comparison`), and the expanded forbidden-string set
      (`low-frequency`, `mid-frequency`, `high-frequency`,
      `frequency_analysis`, `frequency_comparison`).
- [ ] **A4.** Post-2-zh regression-guard: grep for the banned vocabulary
      across `agent/`, `nodes/`, `workflows/` — `frequency_analysis`,
      `frequency_comparison`, `frequency_band`, `low-frequency`,
      `mid-frequency`, `high-frequency`, `denoising` (in prompts only —
      the runtime `denoising_score` field stays). All hits must live in
      task-config / docstring contexts, not in LLM-facing prompts.

#### Out of scope (tracked separately)

- **Vocab freeze** (`vocab_total=21, candidate=0, promoted=0` across all 6
  V8 chain iters). Distinct from cognitive alignment — likely an
  interaction between chain-mode runtime_vocab persistence and the
  centrifugal-force gate. Investigate as a follow-up phase.
- **`PerFileRow.model` units** (V8 records show `model` and
  `gain_vs_raw` in linear units, but `aggregate.model_scalar` is
  log-space; doc §6 says all three columns are log-space). Verify
  against `build_score_table` after the headroom fix lands. If linear,
  either fix the renderer or correct the doc — but do not gate Phase 8
  on this.
- **SSM time-estimator miscalibration** (V8 iters 3 + 5 killed by the
  time-risk gate at 524× / 446× over budget). Tracked under the
  inference-defaults follow-up.

---

## 12.5 V9 Launch Certification Gates

Before kicking V9 chains in formal workspaces, two gates must turn green. They
are intentionally cheap and cover orthogonal failure modes — Gate 1 stresses the
agent's *mental model* of the score table; Gate 2 stresses the *system's
data-flow* under real training. A green Gate 1 with a red Gate 2 means the
prompt rewrite worked but plumbing is still broken; a green Gate 2 with a red
Gate 1 means the data is unit-consistent but the LLM is still generating fake
diagnoses. Both must pass.

### Gate 1 — Pseudo-Cognitive Probe (Mental Model Check)

**Goal:** confirm the rewritten interpreter prompt + headroom-aware partition
make the LLM read the table the way Phase 8 intends.

**Setup:**
- 3 iterations of pseudo-training. Each iter feeds a synthetic
  `ModelRunSummary` fixture with a known per-file shape (e.g. dead-zone files
  0–3 at the floor, mid-band files 4–10 with substantial `headroom_vs_gt`,
  high-band files 11–19 close to the ceiling).
- LLM provider: real OpenAI API (no mocks at the synthesis step). Other
  subsystems (training, scoring, VRAM probe) stay pseudo.

**Success metrics (all three required):**
1. **Dead-zone elision.** Across the 3 `take_home_message`s, files 0–3 are not
   cited as a deficiency. The interpreter must have absorbed the gt-at-floor
   signal and treated those files as out-of-scope.
2. **Headroom citation.** At least one `take_home_message` per iter explicitly
   references `headroom_vs_gt` (or paraphrases it — "remaining room to grow",
   "ceiling distance") for an active-band file.
3. **Diagnostic diversity.** Pairwise Jaccard similarity over the 3
   `take_home_message`s (token-level, lower-cased, stop-words removed) is
   `< 0.7`. Higher than that means the LLM is still pattern-matching to one
   canned diagnosis the way V8 did.

A failure on any metric blocks V9 launch and routes back to the prompt /
partition layer.

### Gate 2 — Lightweight End-to-End Stress Test (System Logic Check)

**Goal:** confirm the post-Path-A reference data + P0 unit fix flow correctly
through real training, scoring, table assembly, and audit logging.

**Setup:**
- 3 iterations of real training + scoring on the 5090 (no pseudo subsystems).
- `trial_portion: 0.02`, `train_portion: 1.0`, `eval_portion: 0.02`.
- Hyperparameters held identical across the 3 iters — this is a logic /
  data-flow check, not a tuning experiment.

**Execution strategy:**
- Run with `--no-force_formal_round`. The final round respects the 0.02
  sampling portions instead of forcing a 20-file formal eval, so the gate
  fits inside a ~5-minute time budget. Forcing a formal round here would
  trade the cheap signal we want for an expensive one we don't need.

**Parameter policy:**
- Do **not** override formal parameters. Keep hyperparameters frozen across
  iters so any divergence in `agent_data_stream.jsonl` traces to a
  data-flow defect, not to a hyperparameter choice.

**Success metrics:**
1. **Unit consistency.** `{workspace}/logs/agent_data_stream.jsonl` shows the
   per-file table for every iter with `raw_baseline`, `ground_truth`, and
   `model` columns all in log-space (no linear-space outliers like 78441.83
   appearing next to −13.85 reference values). Spot-check at least file 0
   and file 18.
2. **Subset-scope footnote correctness.** The rendered markdown's footnote
   reads `_Note: scalars computed over N sampled files._` with `N`
   matching the actual subset size produced by `trial_portion = 0.02`
   (1 file in this config). Or, if a formal round was forced despite the
   `--no-force_formal_round` intent, `N = 20` and the footnote is absent
   — either form is valid as long as `N` matches the realised sample.
3. **Logging completeness.** Every iter that produced a non-None
   `model_scalar` produced exactly one `agent_data_stream.jsonl` entry.
   No silent drops, no double-logs.

A failure here means the unit-mismatch / observability fix did not actually
land in the live path, and V9 is not safe to launch.

---

## 13. Test plan

Unit:
- `tests/unit/nodes/test_scoring_reference.py` — JSON loader returns correct
  arrays + scalars; missing file raises.
- `tests/unit/execute_tools/test_scoring_helpers.py`:
  - `build_score_table` computes `gain_vs_raw` and `headroom_vs_gt` correctly,
    None-propagates when any input is None.
  - `render_comparison_table` produces the exact markdown template with N/A
    rendering and 4-dp log rounding.
- `tests/unit/agent/schemas/test_score_table.py` — Pydantic validation,
  serialization round-trip.
- `tests/unit/execute_tools/test_score_table_adversarial.py` (Phase 4
  closeout): adversarial probes covering (a) schema validator rejection
  of LLM string nulls (`"n/a"`, `"N/A"`, `"-"`, `""`) and length /
  bounds / extra-field violations; (b) `build_score_table` subset edge
  cases (all-None fv, single-file sample, wrong length); (c) the
  below-baseline relabel guard in `render_comparison_table` — ensures
  the `< 0%` honest line replaces the misleading percentage whenever
  `model_scalar < raw_baseline_scalar`, and that the normal `% of
  ceiling` framing remains for the happy path. 24 tests, all green.

Protocol (dual-mode):
- `tests/integration/protocols/test_tune_to_interp.py` — extend to assert
  `score_table` flows through.
- `tests/integration/protocols/test_ml_result_interp_to_ml_model_propose.py` —
  same.

Workflow (real-run):
- Run one adaptive iteration end-to-end in `@real_run` mode; assert the tuner
  prompt rendered to the LLM contains the three-column table (spot-check one
  line).

## 14. Decisions required from you

1. **Open decision 1** (§5): cache the raw-baseline scalar to disk (a), or
   recompute at import (b)? **My recommendation: (a).**
2. **Interpreter / proposer file_vector fields** — keep them alongside the new
   `score_table` for one release cycle, then delete; or delete immediately?
   Keeping them is safer for the dashboard; deleting is cleaner. **My
   recommendation: keep for one cycle.**
3. **Trial-mode rows.** When a file isn't in the sampled set, we have
   `raw_baseline` and `ground_truth` but no `model`. Render as `N/A` in the
   model column, or omit the row entirely? **My recommendation: render `N/A`
   — the row still informs the LLM about which frequency it skipped and what
   the reference looked like.**
4. **Confirm the seed scope.** Once this lands, the `small_sample_trial_v1`
   rerun uses the new schema from the start — no v0 backfill needed. Agreed?

---

**Dependencies on other in-flight work:** none. Can land independently of the
`small_sample_trial_v1` rerun but must land **before** v1 launches so that v1's
records carry the new schema natively.
