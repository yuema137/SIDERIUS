# Adaptive New Model Proposer — Overall Review and Development Plan

**Status**: Post-Phase-F review. All six phases (A-reverted, B, C, E, F) are implemented.
977 unit tests pass. This document catalogs the remaining critical gaps and the ordered
plan for fixing them and writing integration tests.

---

## 1. What is already covered

### Implemented (phases shipped)
| Phase | What it delivers | Tests |
|-------|-----------------|-------|
| B | 3-stage pipeline (compare → reason → propose), `DiscoveryMemo`, `FalsifiablePrediction`, `ExpertContextItem`, `ReasoningPipelineConfig`, `ModelSelectionStrategy` | 977 unit tests |
| C | Vocabulary lifecycle: `build_runtime_vocab`, `promote_candidates`, `_dedup_promoted`, `proposed_by_run` injection, `generate_discoveries`, stale-SOTA fix, `formal_score` in cache | H.1–H.3 dual-mode integration tests |
| E | `evaluate_prediction` (SOTA-based), `scientific_accuracy`, `prediction_outcomes_history`, `vocab_link_confirmations`, `update_vocab_link_confirmations` | H.4 dual-mode integration test; 61 unit tests |
| F | `AgentCard`, `VocabEntry.origin`, `render_agent_cards()`, `render_expert_context()` dedup+sort, `local_full_context` `mindset`/`agent_cards` params | 26 unit tests |

### Existing integration tests in `tests/integration/workflows/test_vocab_accumulation.py`
| Test | What it verifies |
|------|-----------------|
| H.1 `test_vocab_grows_across_two_iterations` | vocab grows monotonically; REFUTED/CONFIRMED both produce discoveries; protocol maps vocab into `vocab_seed` |
| H.2 `test_vocab_candidate_promotion_across_three_iterations` | `seen_in_runs` accumulation; `promote_candidates` fires at count=3; `_dedup_promoted` keeps genuine new entries; `vocab_changes` logged |
| H.3 `test_vocab_discoveries_appear_in_proposal_prompt` | discovery names from iter N reach Stage 1 user prompt in iter N+1 (pseudo: prompt inspection; real-LLM: schema validity + vocab engagement) |
| H.4 `test_scientific_accuracy_and_vocab_links_accumulate` | Phase E carry-forward: `prediction_outcomes_history`, `scientific_accuracy` ratios, `vocab_link_confirmations` keyed correctly, not promoted before threshold |

---

## 2. Critical gaps

Gaps are grouped into two categories: **code gaps** (missing enforcement that the design doc
explicitly requires) and **behavioral gaps** (things that require a real LLM run to observe
and that no test currently catches).

### 2A. Code gaps — missing enforcement

**G1 — `boldness` check not enforced in the pipeline runner**

The design doc (§2A centrifugal force #2) says predictions below `policy.minimum_boldness`
(default 0.05) must be rejected. `FalsifiablePrediction.boldness` is a computed property on
the schema. But the pipeline runner (`_run_pipeline`) never calls `.boldness` or compares it
against `policy.minimum_boldness`. The `minimum_boldness` value is only surfaced to the LLM
as a string in the prompt template — it is never enforced programmatically.

**Impact**: trivial or zero-delta predictions pass validation silently, defeating the
purpose of the boldness constraint.

**Fix location**: `nodes/ml_model_proposal_agent.py` — after Stage 2 output is parsed into a
`DiscoveryMemo`, check `memo.falsifiable_prediction.boldness < policy.minimum_boldness` and
treat it as a validation failure (retry Stage 2 or full pipeline, with an error message
injected into `accumulated`).

---

**G2 — `citation_sources` validator not enforced**

The design doc (§2A centrifugal force #5 and §2D "Why citation matters") says each
`cite_id` in `DiscoveryMemo.citation_sources` must appear verbatim in `causal_hypothesis`
or `proposed_change` text. The `DiscoveryMemo` schema documents this requirement but the
pipeline runner never checks it.

**Impact**: the LLM can cite all available `ExpertContextItem`s by default (to "appear
rigorous") without actually using any of them. The citation audit trail is meaningless.

**Fix location**: `nodes/ml_model_proposal_agent.py` — after Stage 2 output is validated,
add a `_check_citation_discipline(memo, expert_context_items)` helper that cross-checks each
`cite_id` in `citation_sources` against the text of `causal_hypothesis` and `proposed_change`.
Violations are injected as warnings (not hard failures) on the first iteration; converted to
failures after one retry.

---

**G3 — Uncommitted changes in `ml_model_proposal_agent.py` are untested**

Four related improvements exist locally but have no unit tests:

| Change | What it does | Risk if wrong |
|--------|-------------|---------------|
| `n_confirmed_links` computed from `vocab_seed.related_to` | Fixes a hardcoded `"0"` TODO; now the prompt template shows actual confirmed link count | Template always showed `"0"` before; wrong count misleads the LLM about knowledge state |
| Vocab rendering adds `→ enables:` / `← enabled by:` | Features show which capabilities they enable; capabilities show which features enable them | If `related_to` field access is wrong (Pydantic model vs dict), rendering silently falls back to no links |
| `scientific_accuracy` + `cumulative_information_gain` surfaced in reasoning prompt | LLM sees its own track record; can adjust boldness and exploration | If keys are missing in `interpretation` dict, sections are silently skipped |
| `vocab_diversity_ratio` surfaced in reasoning prompt | LLM sees vocabulary health warning | Same silent-skip risk |

These changes are correct in intent but untested. They must have unit tests before commit.

**Fix**: write `tests/unit/agent/ml_model_proposal_agent/test_prompt_context_surfacing.py`
covering all four changes (detailed in §3 below).

---

**G4 — `VocabEntry.related_to` link promotion not yet end-to-end tested**

Phase E's `update_vocab_link_confirmations()` accumulates link confirmations.
`build_runtime_vocab` promotes confirmed links into `VocabEntry.related_to` once a link
reaches `min_runs_for_promotion` (default 3). H.4 verifies 1 confirmation does NOT
promote. But no test verifies that 3 confirmations DO populate `related_to` — and that
the newly populated `related_to` is then rendered with `→ enables:` / `← enabled by:` in
the proposal prompt (the G3 change).

**This is a chain of two untested steps**: link threshold → `related_to` populated →
rendered in vocab block.

**Fix**: extend H.4 to a 3-confirmation scenario (or add H.5) to verify the full
`confirmation → related_to → rendered` pipeline.

---

### 2B. Behavioral gaps — require real-LLM observation

These gaps cannot be caught by deterministic pseudo-mode tests. They require `--real-llm`
runs and assertion on LLM output quality.

**BG1 — Does the LLM actually use accumulated vocabulary in its reasoning?**

H.3 verifies that discovery names *appear in the Stage 1 prompt*. It does NOT verify that
the LLM's output actually references those discoveries in its reasoning memo.

**Observable signal**: `DiscoveryMemo.proposed_change` or `DiscoveryMemo.causal_hypothesis`
should contain vocabulary names that appeared in the prompt's discovery block. After several
iterations, proposals should cite specific past discoveries by name, not just invent
free-text descriptions.

**Test to write**: in real-LLM mode, after at least one iteration of vocabulary accumulation,
check that `DiscoveryMemo.causal_hypothesis` contains at least one string that verbatim
matches a `kind="discovery"` entry name from `vocab_seed`. (A name that is in the prompt
AND in the output = the LLM is using the vocabulary.)

---

**BG2 — Does the exploration mode actually change the LLM's reasoning tone?**

`resolve_exploration_mode()` switches between `"explore"` and `"exploit"` based on
`n_agent_proposed` count and `vocab_diversity_ratio`. The two modes inject different
system prompt additions. But no test verifies:
1. (Pseudo) That the correct mode-specific string appears in the Stage 1 system prompt
   given a controlled input.
2. (Real-LLM) That in `"explore"` mode the LLM frames predictions as conditional ("IF...
   THEN...") rather than assertive ("X will improve by Y").

The pseudo check is purely deterministic and belongs in unit or pseudo integration tests.
The real-LLM check requires reading `FalsifiablePrediction.rationale` and checking for
conditional framing.

---

**BG3 — Does the prediction track record influence LLM boldness?**

The G3 change surfaces `scientific_accuracy` and `cumulative_information_gain` in the
reasoning prompt. The design doc says the LLM should "adjust" in response to low hit rates.
But no test checks whether a high `refuted` rate actually changes prediction behavior.

**Observable signal** (real-LLM): run two proposals — one with
`scientific_accuracy={"confirmed": 0.8, "refuted": 0.2}` (strong track record) and one
with `scientific_accuracy={"confirmed": 0.2, "refuted": 0.8}` (weak track record). Compare
`FalsifiablePrediction.boldness` — the weak-track-record run should produce more cautious
predictions (unless the LLM is ignoring the track record entirely, which is the failure mode
to catch).

This test is observational, not a hard assertion. It produces a printed comparison that a
human reviews.

---

**BG4 — Does Stage 3 stay tethered to Stage 2's `proposed_change`?**

The design doc (§2A Stage 3) says the proposing stage must reference the memo's
`proposed_change` verbatim and that deviations should be logged in `memo_consistency_notes`.
But no test checks that the architecture in `ProposalOutput` is actually consistent with the
`DiscoveryMemo`'s `proposed_change`. 

**Observable signal** (real-LLM): check that `proposed_change` contains keywords that also
appear in `model_config` keys or `ProposalOutput.model_description`. A proposal that says
"replace gating with spectral filtering" in the memo but implements a standard transformer
in the config is a Stage 3 drift failure.

---

**BG5 — `AgentCard` influence on reasoning (Phase F first real test)**

Phase F implemented the `AgentCard` infrastructure but no external agent populates it yet.
The first real test will come with `ml_literature_review`. Until then, the behavioral gap is:
does the "Contributors" section in the Stage 1 system prompt actually cause the LLM to
calibrate trust differently between empirical and theoretical sources?

**Test to write**: inject one `AgentCard` with `trust_guidance="treat as empirical ground
truth"` and one with `trust_guidance="treat as a prior only"`, both providing conflicting
advice. Check that `DiscoveryMemo.citation_sources` reflects the empirical source more
heavily. (Real-LLM only.)

---

## 3. Fixing plan (ordered)

Fix in this order. Each fix is independently committable.

### Fix 1 — Unit tests for uncommitted changes (G3) ✅ DONE
**File**: `tests/unit/agent/ml_model_proposal_agent/test_prompt_context_surfacing.py` (new)

**Status**: 28 tests written and passing. Code changes in `nodes/ml_model_proposal_agent.py`
are staged locally (uncommitted pending user approval).

28 tests across three groups:

| Group | What it covers | Tests |
|-------|---------------|-------|
| `TestBuildReasoningPromptTrackRecord` | Phase E fields (`scientific_accuracy`, `cumulative_information_gain`, `prediction_outcomes_history`) surfaced in `_build_reasoning_prompt` | 9 |
| `TestBuildReasoningPromptVocabHealth` | Phase C `vocab_diversity_ratio` surfaced, LOW/OK threshold, formatting | 6 |
| `TestRenderVocabularyLinks` | `→ enables:` / `← enabled by:` for features/capabilities with confirmed links; Pydantic + dict + mixed | 9 |
| `TestNConfirmedLinksTemplateVar` | `n_confirmed_links` computed from `vocab_seed.related_to` (not hardcoded "0"); Pydantic + dict + mixed | 4 |

**Regression guards confirmed**: `test_n_confirmed_links_counts_entries_with_related_to`
would fail if the code was still hardcoded `"0"` (expects `"2 confirmed"` in system prompt).
`test_feature_with_single_link_shows_enables` would fail if `→ enables:` rendering was absent.

**Pending**: commit both `nodes/ml_model_proposal_agent.py` and `test_prompt_context_surfacing.py`
together (awaiting user approval).

---

### Fix 2 — Boldness enforcement in pipeline runner (G1) ✅ DONE
**File**: `nodes/ml_model_proposal_agent.py`

After Stage 2 produces a `DiscoveryMemo`, add:

```python
pred = memo.falsifiable_prediction
if pred and pred.boldness < policy.minimum_boldness:
    accumulated["proposing_stage_errors"] = accumulated.get("proposing_stage_errors", []) + [
        f"BOLDNESS_TOO_LOW: prediction boldness={pred.boldness:.4f} is below "
        f"minimum_boldness={policy.minimum_boldness}. Current: {pred.current_value}, "
        f"Predicted: {pred.predicted_value}. Make a bolder prediction."
    ]
    # Retry Stage 2 rather than Stage 3 — the prediction is in the memo.
    # Implementation: mark the stage for retry (mirrors B.22 memo retry pattern).
```

This mirrors the existing B.22 retry mechanism. The error is injected into `accumulated` and
Stage 2 is re-run (not Stage 1 — comparisons are expensive and don't need to change).

**Unit tests**: `tests/unit/agent/ml_model_proposal_agent/test_boldness_enforcement.py`
- `test_boldness_passes_when_above_threshold`
- `test_boldness_rejected_when_below_threshold` — error injected into `accumulated`
- `test_boldness_zero_delta_rejected` — `current_value == predicted_value` → boldness=0
- `test_boldness_custom_policy_threshold` — `policy.minimum_boldness=0.20`
- `test_boldness_uses_abs_delta` — negative predictions still compute absolute boldness

---

### Fix 3 — Citation discipline validator (G2) ✅ DONE
**File**: `nodes/ml_model_proposal_agent.py`

Added module-level `_check_citation_discipline(citation_sources, causal_hypothesis, proposed_change) -> list`
that returns a violation message for each `cite_id` not appearing verbatim in either text field.
Violations are appended to `ProposalOutput.memo_consistency_notes` (soft warning, not a hard rejection).
Wired just before `return output` in the proposing retry block, using the raw `reasoning_output` dict.

**Unit tests**: `tests/unit/agent/ml_model_proposal_agent/test_citation_discipline.py`

14 tests across two groups:

| Group | What it covers | Tests |
|-------|---------------|-------|
| `TestCheckCitationDiscipline` | Pure function: empty list, cite_id in hypothesis, cite_id in proposed_change, absent cite_id, multiple cites (all present / one absent / all absent), empty fields, verbatim-match requirement | 10 |
| `TestCitationDisciplinePipelineIntegration` | violations appended to `memo_consistency_notes`; no violations when all cited; existing notes preserved; empty `citation_sources` → no notes | 4 |

All 14 tests pass. Committed in two steps: code (`da490d1`), then tests + doc.

---

### Fix 4 — `related_to` full pipeline test (G4) ✅ DONE
**File**: `tests/integration/workflows/test_vocab_accumulation.py`

Added **H.5** — `test_vocab_link_confirmed_populates_related_to_and_renders`:

Pre-seeds `vocab_link_confirmations` with 2 prior confirmed runs ("run_a", "run_b") and a
`dilated_causal_conv` feature entry. Runs one CONFIRMED interpretation iteration (spectral_net,
run_name="spectral_net") using `result_interpretation_agent_iter2` pseudo data. The 3rd
confirmation triggers `update_vocab_link_confirmations()` promotion. Three assertions:

1. `vocab_link_confirmations["dilated_causal_conv:receptive_field"]` has 3 distinct runs.
2. `dilated_causal_conv` in `runtime_vocab` has `related_to=["receptive_field"]`.
3. Protocol maps `runtime_vocab` into `ProposalInput.vocab_seed`; proposal agent (pseudo,
   `ml_model_proposal_agent_h5` canned data) Stage 1 user prompt contains `"→ enables: receptive_field"`.

This closes the chain: **confirmation accumulation → `related_to` populated → rendered in
prompt** — the three steps were each tested separately before but never as a connected chain.

All 5 H-tests pass (H.1–H.5). Committed in two steps: test + pseudo data, then review doc.

---

## 4. Integration test development plan

After all four fixes are landed, write the following integration tests in order.

All new tests go in `tests/integration/workflows/test_proposer_reasoning_quality.py`
(new file) unless noted. All are `@pytest.mark.dual_mode`.

### T1 — Exploration vs. exploitation mode switching (pseudo + real-LLM)
**What**: verify that `resolve_exploration_mode()` selects the right mode and that the
correct mode-specific system prompt addition appears.

**Pseudo assertions**:
- With `n_agent_proposed < 5` (cold start): `mode == "explore"` and Stage 1 system prompt
  contains `"EXPLORATION MODE"`.
- With `n_agent_proposed >= 5` and `vocab_diversity_ratio >= 0.1`: `mode == "exploit"` and
  Stage 1 system prompt contains `"EXPLOITATION MODE"`.
- With `vocab_diversity_ratio < 0.1` (stagnation override): force `"explore"` regardless of
  record count.
- With `exploration_mode="exploit"` explicitly set: force `"exploit"` regardless of count.

**Real-LLM assertions**: in `"explore"` mode, `FalsifiablePrediction.rationale` contains
conditional framing (`"IF"` or `"whether"` or `"to test"`). In `"exploit"` mode, rationale
references a specific prior round or prior score directly.

**File**: `tests/integration/workflows/test_proposer_reasoning_quality.py`

---

### T2 — Prediction track record reaches proposal reasoning (pseudo)
**What**: end-to-end pipe from `InterpretationOutput.scientific_accuracy` through the
protocol into the proposal agent's Stage 2 reasoning prompt.

**Setup**: build `InterpretationOutput` with
`scientific_accuracy={"confirmed": 0.2, "refuted": 0.8}` and
`cumulative_information_gain=0.15`. Run proposal agent in pseudo mode. Inspect Stage 2
user prompt.

**Assertions**:
- `"confirmed=20%"` appears in Stage 2 user prompt.
- `"Cumulative information gain : 0.150"` appears in Stage 2 user prompt.
- Stage 2 (not just Stage 1) receives this context — the track record block must be in
  `_build_reasoning_prompt` output, which feeds all stages via `accumulated`.

---

### T3 — Vocabulary-constrained lab report quality (real-LLM only)
**What**: the interpretation agent's Phase 2 synthesis prompt references vocabulary terms.
Corresponds to deferred task C.16.

**Setup**: provide a rich `runtime_vocab` with several `kind="discovery"` entries. Run the
interpretation agent with a real summary that contradicts one of the discoveries.

**Assertions**:
- `InterpretationOutput.take_home_message` contains at least one string that verbatim
  matches a vocabulary entry name from `runtime_vocab`.
- `new_discoveries` produced by this run are distinct from (and additive to) prior
  discoveries — the LLM is not re-generating existing discoveries.

This is observational; output is printed for human review alongside the assertion.

---

### T4 — Vocab usage in DiscoveryMemo (real-LLM only)
**What**: corresponds to BG1 above. The LLM's Stage 2 output actually references
accumulated vocabulary, not free-form paraphrase.

**Setup**: run two interpretation iterations (REFUTED then CONFIRMED) to build a non-empty
`runtime_vocab` with `kind="discovery"` entries. Then run the proposal agent on the
accumulated vocab. Inspect `DiscoveryMemo.causal_hypothesis` and `proposed_change`.

**Assertions**:
- At least one vocabulary entry name (from `kind="discovery"` entries in `vocab_seed`)
  appears verbatim in `DiscoveryMemo.causal_hypothesis`.
- `proposed_discoveries` in `ProposalOutput` is non-empty (LLM adds to, not just reads
  from, the vocabulary).
- `inherited_components` is non-empty (LLM claims at least one lineage connection).

---

### T5 — Boldness enforcement integration (pseudo + real-LLM)
**Depends on**: Fix 2 being landed.

**Pseudo assertions**:
- Feed a `DiscoveryMemo` where `FalsifiablePrediction.boldness < 0.05`. The pipeline runner
  injects a `BOLDNESS_TOO_LOW` error and the proposal agent retries Stage 2. Assert that
  `bridge.calls` for Stage 2 are ≥ 2 (one initial, one retry) and that the retry call's
  user prompt contains the error message.
- Feed a bold prediction (`boldness >= 0.05`). Assert Stage 2 runs exactly once.

**Real-LLM assertions**: in practice, the retry produces a more extreme `predicted_value`.
Assert `retry_memo.falsifiable_prediction.boldness > initial_memo.falsifiable_prediction.boldness`.

---

### T6 — Stage 3 tethering (real-LLM only)
**What**: corresponds to BG4 above. Stage 3 architecture matches Stage 2 memo.

**Setup**: run the full 3-stage pipeline with a strong `expert_context` injection directing
a specific modification (e.g., "add spectral gating"). Inspect `DiscoveryMemo.proposed_change`
and `ProposalOutput.model_config`.

**Assertions**:
- Keywords from `proposed_change` appear in at least one of: `model_name`, `model_config`
  field names, or `ProposalOutput.model_description`.
- `memo_consistency_notes` is an empty list (no detected deviations from the memo).
- If deviations exist, they are printed and the test logs a warning (not a failure) — this
  test is diagnostic, not a gate.

---

### T7 — Citation discipline integration (real-LLM only)
**What**: corresponds to BG4 (G2 enforcement in practice). Depends on Fix 3 being landed.

**Setup**: run the full pipeline with several `ExpertContextItem`s, only one of which is
genuinely relevant to the proposed change. Inspect `DiscoveryMemo.citation_sources`.

**Assertions** (soft — these are quality checks, not hard gates):
- `len(citation_sources) <= 5` (enforced by `max_length=5` on the schema field).
- Every `cite_id` in `citation_sources` appears in `causal_hypothesis` or `proposed_change`.
- The irrelevant `ExpertContextItem`s are NOT cited (the signal-to-noise check).

Print a citation quality report: which items were cited, which were ignored, and whether
the cited items actually appeared in the reasoning text.

---

### T8 — AgentCard trust calibration (real-LLM only)
**What**: corresponds to BG5. Phase F infrastructure test.

**Setup**: inject two `AgentCard`s — one empirical (`data_analysis_agent`, high confidence)
and one literature prior (`ml_literature_review`, lower confidence, explicit "treat as
prior only" in `trust_guidance`). Both provide conflicting `ExpertContextItem`s: the
empirical one says "low-frequency performance is bottlenecked by receptive field"; the
literature one says "attention mechanisms dominate in recent SOTA".

**Assertions** (observational):
- `DiscoveryMemo.citation_sources` cites the empirical source's `cite_id` and/or the
  literature source's `cite_id`. Print which was cited.
- `causal_hypothesis` text references the domain it chose to follow.
- If both sources are cited, print a note: the LLM did not discriminate — worth inspecting.

---

## 5. Execution order summary

```
Phase 1 — Fix and commit (no real-LLM needed)
  Fix 1: unit tests for uncommitted changes in ml_model_proposal_agent.py   (1-2h)
  Fix 2: boldness enforcement + unit tests                                   (1h)
  Fix 3: citation discipline validator + unit tests                          (1h)
  Fix 4: H.5 related_to full pipeline test                                   (1h)

Phase 2 — Pseudo integration tests (no real-LLM needed)
  T1 (pseudo path): exploration/exploitation mode switching                  (1-2h)
  T2: prediction track record in proposal prompt                             (1h)
  T5 (pseudo path): boldness enforcement integration                         (1h)

Phase 3 — Real-LLM integration tests (require GEMINI_API_KEY)
  T1 (real-LLM path): conditional vs assertive framing per mode
  T3: vocabulary-constrained lab report quality
  T4: vocab usage in DiscoveryMemo
  T5 (real-LLM path): boldness retry produces bolder prediction
  T6: Stage 3 tethering
  T7: citation discipline integration
  T8: AgentCard trust calibration
```

**Why fix first, then test**: the four code fixes (G1–G4) add enforcement that the design
doc requires but the code does not yet implement. Writing behavioral integration tests
against enforcement that doesn't exist produces tests that pass silently for the wrong reason
(the LLM happens to produce a bold prediction by chance, not because the system required it).
Fixing first gives the tests a real invariant to verify.

The behavioral real-LLM tests (T3–T8) are observational — they cannot be written until the
structural enforcement is in place, because the LLM's output is influenced by the prompts
and the enforcement signals. A test written against the pre-fix prompts would need to be
rewritten after the fixes anyway.

---

## 6. Out of scope (deferred by design)

These items appear in the design doc's open checklist but are **not planned for this phase**:

| Item | Why deferred |
|------|-------------|
| C.16 vocabulary-constrained lab report | Prompt quality improvement; current prompts work. Deferred until chain run data shows memory loss. |
| Component delta scoring (Concern #4) | Requires per-component ablation data not yet available from real chain runs. |
| Strategy Performance Report | Requires Phase E data to calibrate; C.16 is a prerequisite. |
| `vocab_promotion_mode: "review"` flag | No evidence of autonomous promotion misbehaving yet. |
| Regex → AST upgrade for inheritance checks | Current regex approach is functional; upgrade only if false negatives appear in real chains. |
| Guided mode (`ResearchDirective.mode="guided"`) | Infrastructure in schemas; validator checks not yet implemented. Deferred to its own phase. |
| First external agent (`ml_literature_review`) | Designed in `docs/external_agents_for_proposer.md`; out of scope for this review cycle. |
