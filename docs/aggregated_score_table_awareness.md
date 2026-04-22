# Aggregated Score Table Awareness — Design Doc

## Status: Phases 1 + 2 + 3 complete (2026-04-22); Phase 4 (protocol wiring: tune → interp → propose) next. Still blocks `small_sample_trial_v1` rerun.

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

**Token-budget note (non-blocking):** the default `top_n = 10`
(`ModelSelectionStrategy.params`) predates the switch to full tables. With
score_tables ~30 lines each, 10 candidates is ~300 lines of table markdown on
top of source code. This may push against the proposer prompt's token budget
in practice. *Deferred:* we do not change `n` as part of this feature. If we
hit limits, revisit the default (suggest 5–7) in a follow-up commit — do not
bundle the tuning into this landing.

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
- [ ] **E.** `@real_run` test + final commit:
      `feat(interp+proposer): render score_table in prompts (candidate
      full / non-candidate one-liner)`. **Token-budget watch (user steer,
      2026-04-22):** during the real-run smoke, record total prompt
      tokens for each pipeline stage and compare against the
      provider-side context limit. If the 10-candidate markdown tables
      cause truncation, response degradation, or any provider-side
      `context_length_exceeded`-class error, lower
      `ModelSelectionStrategy.params["n"]` in the default pipeline
      config (not a code refactor — a config/policy tune) and re-run.
      Log the before/after token counts in the closeout note.

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

Steps:
- [ ] Update pseudo fixtures under
      `tests/pseudo_data/api_call_outputs/**` that reference
      `file_vector` / `per_model_file_vectors` to carry a `score_table` or
      `per_model_score_tables` field.
- [ ] Update `tests/integration/protocols/test_tune_to_interp.py` assertions
      from `per_model_file_vectors` to `per_model_score_tables`.
- [ ] Update `tests/integration/protocols/test_interp_to_propose.py`
      accordingly.
- [ ] Update `tests/integration/workflows/test_full_exploration_loop.py` and
      any other dual-mode workflow test touching the vectors.
- [ ] Run the relevant test subset (per `feedback_run_relevant_tests_only.md`)
      — no full-suite regression run unless justified.
- [ ] Tier 3 real-run spot-check: one adaptive iteration end-to-end with a
      real LLM; assert the tuner prompt rendered to the LLM contains the
      three-column table (spot-check one line).
- [ ] Commit: `test(score_table): update integration + pseudo fixtures for
      ScoreComparisonTable`.

---

### Phase 7 — Launch gate (small_sample_trial_v1)

**Goal:** kick off the v1 rerun only after Phases 1–6 are committed and
green.

Steps:
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
