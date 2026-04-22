# Aggregated Score Table Awareness — Design Doc

## Status: design (pre-implementation). Blocks `small_sample_trial_v1` rerun.

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
    raw_baseline_scalar: float        # final_scalar from score_vector() on raw CH1
    ground_truth_scalar: float        # final_scalar from score_vector() on CH2 (ceiling)
    model_scalar: float               # final_scalar from score_vector() on denoised CH1
    percent_of_ceiling_log: float     # model_scalar / ground_truth_scalar

class ScoreComparisonTable(BaseModel):
    rows: List[PerFileRow]            # len == 20
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
def load_reference_scores() -> tuple[list[float], list[float], float, float, float]:
    """
    Returns (raw_per_file_log, gt_per_file_log, raw_scalar, gt_scalar, s_max).
    Reads from {SIDERIUS_DATA_DIR}/raw_baseline/*.json (20 files)
    and {SIDERIUS_DATA_DIR}/ground_truth/*.json (20 files + ceiling_anchor_normalized.json).
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

N/A rendering for `None` entries (file not included in a trial-mode run).
Numbers pre-rounded to 4 dp (log space is the only space).

**Decision 5 (resolved → A, render all 20 rows always):** in trial mode, files
outside the sampled set render as `model=N/A` (plus N/A for the two derived
columns) but keep their `raw_baseline` and `ground_truth` anchors. The full
20-row topology is always visible — the LLM reasons about which files to
include next round, and omitting skipped rows would hide that structure.
`rows` length is always 20.

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

**Status:** implementation + verification complete. All real-data + unit
tests green. Commit pending user approval.

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
- [ ] Commit: `feat(raw_baseline): emit scalar_anchor_normalized.json
      (grand-mean, global s_max)`.

---

### Phase 2 — Schema + loader + renderer

**Goal:** three new files exist, all deterministic, all unit-tested. No node
touches them yet.

Steps:
- [ ] Create `agent/schemas/score_table.py` with `PerFileRow`,
      `AggregateScalars`, `ScoreComparisonTable` per §4.
- [ ] Create `nodes/scoring_reference.py::load_reference_scores()` — reads
      the 20+20 per-file JSONs + both scalar JSONs; module-level cache;
      missing-file raises configuration error.
- [ ] Create `execute_tools/scoring_helpers.py::build_score_table(...)` —
      pure math, None-propagates for trial-mode entries, always returns
      `rows` of length 20.
- [ ] Add `execute_tools/scoring_helpers.py::render_comparison_table(table)`
      — pure markdown rendering per §6 template; 4-dp log rounding; "N/A"
      for None entries.
- [ ] Unit test `tests/unit/agent/schemas/test_score_table.py` — Pydantic
      validation + JSON round-trip.
- [ ] Unit test `tests/unit/nodes/test_scoring_reference.py` — happy path +
      missing-file path.
- [ ] Unit test `tests/unit/execute_tools/test_scoring_helpers.py` —
      `build_score_table` math + None-propagation; `render_comparison_table`
      exact markdown output (compare against fixture string).
- [ ] Real-run test: `python -c "from nodes.scoring_reference import
      load_reference_scores; print(load_reference_scores())"` — verifies the
      actual on-disk JSONs load correctly under the Phase 1 artifacts.
- [ ] Commit: `feat(score_table): add ScoreComparisonTable schema + reference
      loader + renderer`.

---

### Phase 3 — Tuner plumbing + tuner prompt

**Goal:** tuner emits records and run-output carrying `score_table`; tuner
planner prompt renders the table token.

Steps:
- [ ] Extend `agent/schemas/hyperparam_tuning.py` — add optional
      `score_table: Optional[ScoreComparisonTable]` on `ExperimentRecordSchema`;
      add `best_score_table` + `formal_score_table` on `HyperparamTuningOutput`
      (per Decision 11). `file_vector` fields stay.
- [ ] Wire `nodes/ml_hyperparameter_tune_agent.py` — after
      `score_vector(...)` returns, call `load_reference_scores()` +
      `build_score_table(...)`; populate `record.score_table`.
- [ ] Populate `best_score_table` + `formal_score_table` at run-output
      emission time, mirroring how `best_file_vector` is populated today
      (line ~1666).
- [ ] Update `agent/prompts.py:142-159` — replace the `### FILE VECTOR AND
      SCORING:` block per §9.1 with `### PER-FILE PERFORMANCE TABLE:` and
      the `{SCORE_COMPARISON_TABLE}` placeholder token.
- [ ] Update the prompt-render site that substitutes the token with
      `best_score_table.rendered_markdown` (or the "no prior round yet"
      fallback on iteration 1).
- [ ] Reflector plumbing (per Decision 8 / §9.4): thread
      `score_table.rendered_markdown` into `reflection_context` at line
      ~1406 as `score_comparison_table`; extend `REFLECTOR_PROMPT` with the
      `### PER-FILE COMPARISON` section.
- [ ] Unit test: per-record `score_table` populated correctly (mocked
      reference data).
- [ ] Real-run test: one tuner round in trial mode, verify rendered prompt
      sent to LLM contains the three-column table (assert on the captured
      prompt text).
- [ ] Commit: `feat(tuner): score_table on records + run-output + planner +
      reflector prompts`.

---

### Phase 4 — Protocol wiring (tune → interp → propose)

**Goal:** the score_table payload flows end-to-end through the graph;
`per_model_file_vectors` is removed per Decision 6.

Steps:
- [ ] Update `agent/schemas/interpretation.py` — add `best_score_table` +
      `formal_score_table` on `InterpretationInput`; **replace**
      `per_model_file_vectors` with `per_model_score_tables` on
      `InterpretationOutput`.
- [ ] Update `agent/schemas/proposal.py` — add `per_model_score_tables` on
      proposal input.
- [ ] Update `agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py`
      — map `best_score_table` / `formal_score_table`.
- [ ] Update `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py`
      — swap `per_model_file_vectors` → `per_model_score_tables`; update
      docstring at line 72.
- [ ] Migrate all 7 internal readers of `per_model_file_vectors` found by
      grep (`nodes/result_interpretation_agent.py` ×3 sites,
      `nodes/ml_model_proposal_agent.py`, `nodes/proposal_helpers.py`,
      2 test files) to read `per_model_score_tables`.
- [ ] Unit + protocol tests updated, including the two test fixtures at
      `tests/unit/agent/result_interpretation_agent/test_interpretation_agent.py`
      and `tests/unit/agent/ml_model_proposal_agent/test_proposal_agent.py`.
- [ ] Real-run test (Tier 2): tune→interp protocol integration test passes
      with the new field.
- [ ] Commit: `refactor(graph): replace per_model_file_vectors with
      per_model_score_tables; wire score_table through protocols`.

---

### Phase 5 — Interpreter + proposer prompts

**Goal:** downstream agents see the rendered table; proposer respects the
candidate/non-candidate split per Decision 7.

Steps:
- [ ] Interpreter prompt (whichever template file renders
      `best_file_vector`): replace with `{SCORE_COMPARISON_TABLE}` fed from
      `InterpretationInput.best_score_table.rendered_markdown`.
- [ ] `nodes/proposal_helpers.py::select_candidate_models` — read from
      `per_model_score_tables`, populate candidate summaries with
      `"score_table": score_tables.get(mt)` (replaces the
      `"file_vector": ...` line 60).
- [ ] `nodes/ml_model_proposal_agent.py::_run_pipeline` — in the
      `non_candidates_overview` loop (lines 753–766), compute the one-liner
      `log_scalar=X.XX, recovery=YY%` from the model's `score_table.aggregate`
      and add to each overview entry.
- [ ] Update the proposer comparison-stage prompt template to render each
      candidate's `score_table.rendered_markdown` (replacing any prior
      file_vector dump) and include non-candidates' one-liners.
- [ ] Real-run test: one proposer iteration in `@real_run`; assert the
      rendered prompt contains the comparison table for the top-ranked
      candidate and the compact line for a non-candidate.
- [ ] Commit: `feat(interp+proposer): render score_table in prompts
      (candidate full / non-candidate one-liner)`.

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
