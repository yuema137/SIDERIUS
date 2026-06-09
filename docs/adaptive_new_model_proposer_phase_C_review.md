# Phase C Data Flow Review (post bug-fix)

Generated: 2026-04-15. Covers the vocabulary feedback loop as implemented after
fixing the three bugs found in the initial review.

---

## 1. Workflow-level long-term memory

Four Python variables are carried across all iterations in `run_workflow()`.
Nothing else is shared between iterations — these are the only cross-iteration
channels.

| Variable | Type | Updated when |
|---|---|---|
| `model_knowledge_cache` | `dict[str → {LLM text + _stats}]` | After each interpretation run (written from `interp_output.model_knowledge_cache`) |
| `current_runtime_vocab` | `List[VocabEntry]` | After each interpretation run (written from `interp_output.runtime_vocab`) |
| `previous_proposal_data` | `dict` (serialized `ProposalOutput`) | After each successful tune (written as `proposal.model_dump()`) |
| `latest_new_summary` | `ModelRunSummary` | After each successful tune (the just-tuned model only) |

Initialization (before iteration 1):

```
model_knowledge_cache    = {}
current_runtime_vocab    = vocab_seed   (21 canonical entries from vocab_seed.json)
previous_proposal_data   = None
latest_new_summary       = None
```


---

## 2. Per-iteration data flow

The full flowchart below covers one iteration (N ≥ 1). Differences between
iteration 1 and later iterations are called out explicitly.

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  WORKFLOW — run_workflow(), one iteration                                           │
│                                                                                     │
│  LONG-TERM MEMORY (in)                    NEW DATA (in)                             │
│  model_knowledge_cache                    latest_new_summary        (None on iter 1)│
│  current_runtime_vocab                    previous_proposal_data    (None on iter 1)│
│         │                                         │                                 │
│         └──────────────┬──────────────────────────┘                                 │
│                        ▼                                                             │
│  ┌────────────────────────────────────────────────────────────────────────────────┐ │
│  │  STEP 1 — Assemble InterpretationInput                                        │ │
│  │                                                                                │ │
│  │  summaries =  iter 1: ALL seed ModelRunSummary objects (cache is empty)        │ │
│  │               iter 2+: [latest_new_summary]  (one model only)                 │ │
│  │  model_knowledge_cache = carried forward from previous iter (empty on iter 1) │ │
│  │  runtime_vocab         = current_runtime_vocab                                │ │
│  │  previous_proposal     = previous_proposal_data                               │ │
│  └───────────────────────────────┬────────────────────────────────────────────────┘ │
│                                  │ InterpretationInput                               │
│                                  ▼                                                   │
│  ┌────────────────────────────────────────────────────────────────────────────────┐ │
│  │  STEP 2 — ResultInterpretationAgent.run()                                     │ │
│  │                                                                                │ │
│  │  Phase 1 — Per-model summarization (cache-first, O(1) per iteration)          │ │
│  │    effective_types = summaries.model_type ∪ model_knowledge_cache.keys()      │ │
│  │    For each model type:                                                        │ │
│  │      cache HIT  → copy entry unchanged (0 LLM calls)                          │ │
│  │      cache MISS → 1 LLM call → build entry:                                   │ │
│  │        {key_findings, bottlenecks, best_config_analysis, score_trend,         │ │
│  │         frequency_analysis, data_sensitivity, efficiency_assessment,          │ │
│  │         strategy_assessment,                                                  │ │
│  │         _stats: {best_denoising_score, worst_denoising_score,                 │ │
│  │                  best_file_vector, best_model_params, completed_rounds,       │ │
│  │                  best_config, formal_score}}          ← Bug 3 fix             │ │
│  │                                                                                │ │
│  │  Phase 2 — Cross-model synthesis (1 LLM call, skipped if only 1 model)        │ │
│  │    Input: all models' Phase 1 text + per_model_best + per_model_formal        │ │
│  │           + runtime_vocab discoveries (injected as "Established Discoveries") │ │
│  │    Output: key_findings, bottlenecks, take_home_message                       │ │
│  │    Formal score rendered per model when formal_score ≠ best_score             │ │
│  │                                        ← Bug 3 fix                           │ │
│  │                                                                                │ │
│  │  Phase C — Vocabulary feedback (fully deterministic, 0 LLM calls)             │ │
│  │    C-1  evaluate_prediction():                                                │ │
│  │           previous_proposal.falsifiable_prediction vs per_model_best          │ │
│  │           → prediction_evaluation {outcome, boldness, information_gain}       │ │
│  │    C-2  generate_discoveries():                                               │ │
│  │           uses max(prediction current_value, overall_best_score) as SOTA      │ │
│  │                                        ← Bug 2 fix                           │ │
│  │           → up to 3 VocabEntry(kind="discovery") sentences                   │ │
│  │    C-3  inject proposed_by_run:                                               │ │
│  │           proposed_vocab_candidates from previous_proposal get                │ │
│  │           proposed_by_run = previous_proposal["model_name"]                   │ │
│  │                                        ← Bug 1 fix                           │ │
│  │    C-4  build_runtime_vocab():                                                │ │
│  │           incoming_vocab + new_discoveries + proposed_candidates              │ │
│  │           → deduplication by name, seen_in_runs extended per candidate        │ │
│  │    C-5  promote_candidates():                                                 │ │
│  │           tier="candidate", kind in {feature,capability},                     │ │
│  │           len(seen_in_runs) >= 3 → tier="canonical"                           │ │
│  │    C-6  _dedup_promoted():                                                    │ │
│  │           1 LLM call per promoted entry → remove synonyms, add aliases        │ │
│  └───────────────────────────────┬────────────────────────────────────────────────┘ │
│                                  │ InterpretationOutput                             │
│                                  │                                                   │
│  InterpretationOutput fields:                                                       │
│    model_types, model_descriptions, total_experiments                               │
│    per_model_best, per_model_worst, best_denoising_score, best_config               │
│    model_knowledge_cache   ← updated cache (all models ever seen)                   │
│    key_findings, bottlenecks, take_home_message                                     │
│    per_model_file_vectors, weak_frequency_files                                     │
│    per_model_params, per_model_training_segments                                    │
│    runtime_vocab           ← accumulated vocab (seed + candidates + discoveries)    │
│    prediction_evaluation   ← confirmed/refuted/partial + boldness + info_gain       │
│    new_discoveries         ← VocabEntry(kind="discovery") from this round           │
│    vocab_changes           ← human-readable log of promotions                       │
│                                  │                                                   │
│                                  ▼                                                   │
│  ┌────────────────────────────────────────────────────────────────────────────────┐ │
│  │  STEP 3 — Protocol: local_full_context() → ProposalInput                     │ │
│  │                                                                                │ │
│  │  From InterpretationOutput:                                                    │ │
│  │    interpretation       = full output.model_dump()                            │ │
│  │    existing_model_types = output.model_types                                  │ │
│  │  From workflow (not from interpretation):                                      │ │
│  │    expert_context       = wrapped human_advice_propose                        │ │
│  │    reasoning_pipeline   = 3-stage pipeline config                             │ │
│  │  Vocab routing (protocol prefers accumulated over static seed):               │ │
│  │    if output.runtime_vocab non-empty → vocab_seed = output.runtime_vocab      │ │
│  │    else                              → vocab_seed = static vocab_seed.json    │ │
│  └───────────────────────────────┬────────────────────────────────────────────────┘ │
│                                  │ ProposalInput                                    │
│                                  ▼                                                   │
│  ┌────────────────────────────────────────────────────────────────────────────────┐ │
│  │  STEP 4 — MLModelProposalAgent.run()  (3-stage pipeline)                     │ │
│  │                                                                                │ │
│  │  Pre-filter: select_candidate_models() splits all known models into two tiers │ │
│  │                                                                                │ │
│  │    Tier 1 — candidates (top-N by score, default N=5):                         │ │
│  │      source_code, description, best_score, file_vector, model_params          │ │
│  │      → full detail, the LLM can read and borrow from their architecture       │ │
│  │                                                                                │ │
│  │    Tier 2 — non_candidates_overview (all remaining models):                   │ │
│  │      best_score, description, key_findings, bottlenecks,                      │ │
│  │      score_trend, strategy_assessment  (no source code)                       │ │
│  │      → lightweight record of what was tried and why it fell short             │ │
│  │      → prevents the LLM from re-proposing failed directions                   │ │
│  │                                                                                │ │
│  │  Resolve:    resolve_exploration_mode() → "explore" or "exploit"              │ │
│  │                                                                                │ │
│  │  Stage 1 — Comparison (1 LLM call):                                           │ │
│  │    Input: candidates (Tier 1, with source code)                               │ │
│  │           + non_candidates_overview (Tier 2, text-only)                       │ │
│  │           + interpretation_summary + vocab_seed                               │ │
│  │    Output: List[ModelComparison]                                               │ │
│  │            proposed_vocab_candidates: [{name, kind, description}, ...]        │ │
│  │            ProposedVocabLink hypotheses                                        │ │
│  │                                                                                │ │
│  │  Stage 2 — Causal Reasoning (1 LLM call):                                     │ │
│  │    Input: Stage 1 output + expert_context                                      │ │
│  │    Output: DiscoveryMemo fields:                                               │ │
│  │            sota_model_type, sota_mechanism, proposed_change,                  │ │
│  │            causal_hypothesis, falsifiable_prediction,                          │ │
│  │            predicted_failure_modes, inherited_components,                     │ │
│  │            source_refs                                                    │ │
│  │                                                                                │ │
│  │  Stage 3 — Proposing (1 LLM call):                                            │ │
│  │    Input: full DiscoveryMemo + accumulated pipeline context                   │ │
│  │    Output: ProposalOutput:                                                     │ │
│  │            model_name, mathematical_definition, baseline_config,              │ │
│  │            expert_advice, model_description,                                  │ │
│  │            inherited_components  (from DiscoveryMemo)                         │ │
│  │            falsifiable_prediction (from DiscoveryMemo)                        │ │
│  │            proposed_vocab_candidates (kind∈{feature,capability} from          │ │
│  │                                       Stage 1+2 LLM output)                  │ │
│  │            proposed_vocab_links     (from DiscoveryMemo)                      │ │
│  │            proposed_discoveries     (kind="discovery" entries, if any)        │ │
│  │            memo_consistency_notes                                              │ │
│  └───────────────────────────────┬────────────────────────────────────────────────┘ │
│                                  │ ProposalOutput                                   │
│                                  ▼                                                   │
│  STEPS 5–7 — Implement → Validate → Tune                                           │
│    MLModelImplementor    writes plugin .py + description.md                        │
│    MLCodeValidatorAgent  runs 9 checks including inheritance pattern match          │
│    HyperparamTuningAgent runs N rounds → HyperparamTuningOutput                    │
│                                  │ HyperparamTuningOutput                           │
│                                  ▼                                                   │
│  ┌────────────────────────────────────────────────────────────────────────────────┐ │
│  │  STEP 8 — Update long-term memory                                             │ │
│  │                                                                                │ │
│  │  latest_new_summary     = tuning_output_to_model_run_summary(tune_output)     │ │
│  │                           with s.model_description = proposal.model_description│ │
│  │  model_knowledge_cache  = interpretation.model_knowledge_cache                │ │
│  │  previous_proposal_data = proposal.model_dump()                               │ │
│  │  current_runtime_vocab  = interpretation.runtime_vocab                        │ │
│  │  all_model_types.append(proposal.model_name)                                  │ │
│  └────────────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────────┘
```


---

## 3. Disk persistence (archive layer)

These files are written each iteration. They are for human inspection and crash
recovery only — the agent never reads them in a subsequent iteration.
The four long-term memory variables (Section 1) are the live state; the files
below are the audit trail.

```
{workspace}/{run_name}/
├── workflow_{run_name}.json              ← final workflow summary written once at end
│
├── iteration_001/
│   ├── interpretation_{run_name}.json   ← full InterpretationOutput (all Phase 1/2/C fields)
│   │
│   │   Each proposal attempt gets its own numbered dir.
│   │   Failed attempts keep the plain number; the successful attempt is
│   │   renamed to include the model name once the proposal is accepted.
│   │
│   ├── attempt_001/                     ← created first (before proposal name is known)
│   │   ... (renamed to attempt_001_{model_name}/ after proposal accepted)
│   │
│   ├── attempt_001_{model_name}/        ← final name after rename
│   │   ├── proposal_{run_name}.json     ← ProposalOutput (model name, config, prediction)
│   │   ├── implementor_{run_name}.json  ← ImplementorOutput (plugin write result)
│   │   ├── validation_{run_name}.json   ← ValidatorOutput (9-check result)
│   │   ├── models/{model_name}.py       ← plugin source (also copied to agent_generated/)
│   │   └── tests/test_{model_name}.py   ← plugin unit test generated by implementor
│   │
│   └── {model_name}/                   ← tuning output dir, named by accepted model
│       ├── run_output_{run_name}.json   ← HyperparamTuningOutput (full, used for reload)
│       ├── run_config_{run_name}.json   ← the input config the tuner was called with
│       ├── summary_{run_name}.json      ← per-round experiment records (LocalRecorder)
│       ├── configs/{run_name}/          ← per-round trial_config_{exp_id}.json files
│       ├── cached_models/               ← compiled model checkpoints (if any)
│       └── records/                     ← raw per-experiment result dicts
│
├── iteration_002/
│   └── ...
```


---

## 4. Information preservation matrix

### What IS preserved (by design)

| Information | Mechanism |
|---|---|
| Best score per model (all models, all iters) | `model_knowledge_cache[mt]["_stats"]["best_denoising_score"]` — written once on cache miss, carried forward unchanged |
| Formal score per model *(Bug 3 fix)* | `model_knowledge_cache[mt]["_stats"]["formal_score"]` — preserved alongside `best_denoising_score` so Phase 2 can flag when the best score came from a cheaper trial round |
| Per-file frequency scores | `model_knowledge_cache[mt]["_stats"]["best_file_vector"]` |
| Architectural analysis per model (Phase 1 LLM output) | `model_knowledge_cache[mt]` LLM text fields: `key_findings`, `bottlenecks`, `score_trend`, etc. |
| Best hyperparameter config per model | `model_knowledge_cache[mt]["_stats"]["best_config"]` |
| No model re-proposed | `all_model_types` list passed as `existing_model_types` to the proposal agent; proposal schema rejects repeats |
| Empirical discoveries (what we learned this iteration) | `current_runtime_vocab` — `kind="discovery"` entries accumulate across iterations, never dropped |
| Confirmed/refuted predictions (as discovery sentences) | `generate_discoveries()` converts `prediction_evaluation` into a `kind="discovery"` `VocabEntry` and adds it to `runtime_vocab`; carried forward each iteration |
| Vocabulary candidates (proposed features/capabilities) *(Bug 1 fix)* | `proposed_vocab_candidates` from the proposal stored in `previous_proposal_data`; the interpretation agent injects `proposed_by_run = model_name` before calling `build_runtime_vocab()`, so `seen_in_runs` accumulates correctly and `promote_candidates()` can fire at count ≥ 3 |
| Model description for agent-generated models | `s.model_description = proposal.model_description` attached to `ModelRunSummary` before storing as `latest_new_summary`; interpretation agent reads it without needing filesystem access |

### What is NOT preserved (by design)

| Information | Why not / impact |
|---|---|
| Round-by-round score trajectory for old (cached) models | Exists only in the Phase 1 LLM text — no structured access after caching. Medium impact: trend analysis relies on the LLM summary, not raw data |
| Raw experiment records | Never carried across iterations by design; `model_knowledge_cache` + `runtime_vocab` are the intended compressed representation |
| Within-iteration validation failures | `previous_failures` is reset each iteration. Low impact: these are implementation bugs, not scientific findings |
| Vocab candidates from failed proposal attempts | Proposals that never reached tuning have no results to attribute `seen_in_runs` to — excluded by design |


---

## 5. Detailed information-flow checklist

Each item describes what should happen in plain language, gives a concrete
example to make it tangible, then cites the code location and the test that
verifies it. All listed tests are currently green.

---

### A. model_knowledge_cache: construction and carry-forward

  ☑ A.1  **First time a model is seen, the cache saves its full numeric summary.**
         When a model type has never appeared before, the agent calls the LLM
         once for Phase 1, then stores the result — including all `_stats` numbers
         — in the cache under that model's name.
         Example: iter 1, wavenet is new → LLM called → cache stores
         `cache["wavenet"] = {key_findings: "...", _stats: {best_denoising_score: 6.1, ...}}`.
         Code: `result_interpretation_agent.run()` lines 530–540.
         Test: `TestModelKnowledgeCache::test_cache_miss_stores_stats`  [PASS]

  ☑ A.2  **The cache stores both the trial best score and the official formal score (Bug 3 fix).**
         A trial round can show a higher score than the full-dataset formal round
         because it only runs on a cheap subset. Both scores are now saved so the
         Phase 2 prompt can distinguish them for cached models.
         Example: wavenet trial best = 6.5, formal = 6.1 → `_stats` stores both.
         Before the fix only 6.5 was stored; after caching, the Phase 2 prompt
         would wrongly treat wavenet as a 6.5 model.
         Code: `result_interpretation_agent.run()` line 540 (`"formal_score": summary.formal_score`).
         Test: `TestFormalScore::test_formal_score_stored_in_stats_on_cache_miss`  [PASS]
               `TestFormalScore::test_formal_score_none_stored_when_absent`  [PASS]

  ☑ A.3  **Once a model is in the cache, its Phase 1 LLM call is never repeated.**
         On every iteration after the first, cached models skip the Phase 1 call
         completely and their saved entry is used as-is.
         Example: iter 3 has wavenet and fcnet already cached → 0 Phase 1 LLM calls
         for them, regardless of how many total models exist.
         Code: `result_interpretation_agent.run()` lines 498–518 (cache-first branch).
         Test: `TestModelKnowledgeCache::test_cache_hit_skips_llm_call`  [PASS]
               `TestModelKnowledgeCache::test_cache_hit_reuses_entry`  [PASS]

  ☑ A.4  **The updated cache is passed to the next iteration.**
         After interpretation finishes, the workflow saves
         `interp_output.model_knowledge_cache` back into `model_knowledge_cache`,
         which is then handed to the next iteration as `InterpretationInput.model_knowledge_cache`.
         Example: iter 2 adds fcnet to the cache → iter 3 receives a cache that
         already contains both wavenet and fcnet.
         Code: workflow lines 633–635 (`model_knowledge_cache = interpretation.model_knowledge_cache`).
         Test: `TestModelKnowledgeCache::test_cache_carry_forward`  [PASS]

  ☑ A.5  **Scores for cached models are reconstructed from `_stats`, not from raw records.**
         Raw tuning records from previous iterations are not re-loaded. Instead,
         `per_model_best` and `per_model_worst` are filled from the cached `_stats`.
         Example: iter 3, wavenet's raw tuning records are not in memory, but
         `cache["wavenet"]["_stats"]["best_denoising_score"] = 6.1` is → Phase 2
         sees `per_model_best["wavenet"] = 6.1` correctly.
         Code: `result_interpretation_agent.run()` lines 465–484.
         Test: `TestModelKnowledgeCache::test_cached_model_scores_reconstructed`  [PASS]

  ☑ A.6  **When formal score differs from best score, the synthesis prompt shows a warning (Bug 3 fix).**
         The Phase 2 synthesis prompt includes a note like
         "Formal score: 6.1 (best_score above may be from a trial round)" when
         `formal_score ≠ best_denoising_score` for a model. If they are equal, no
         extra line is added.
         Example: wavenet best=6.5 (trial), formal=6.1 → warning shown in prompt.
         wavenet best=6.1, formal=6.1 → no warning.
         Code: `_build_synthesis_prompt()` formal score rendering block.
         Test: `TestFormalScore::test_formal_score_rendered_in_synthesis_when_different`  [PASS]
               `TestFormalScore::test_formal_score_not_rendered_when_equal_to_best`  [PASS]
               `TestFormalScore::test_formal_score_reconstructed_from_cache`  [PASS]

---

### B. runtime_vocab: construction and carry-forward

  ☑ B.1  **The vocabulary starts from 21 seed entries on iteration 1.**
         At workflow startup, `vocab_seed.json` is loaded and stored as
         `current_runtime_vocab`. On iteration 1, this seed is passed directly
         to `InterpretationInput.runtime_vocab`. All later entries accumulate on
         top of these 21 canonical entries — they are never replaced.
         Code: workflow lines 414, 430 (`_load_vocab_seed()`, `current_runtime_vocab = vocab_seed`).
         Test: `TestVocabSeed` (in `test_phase_b_schemas.py`)  [PASS]

  ☑ B.2  **Every discovery sentence produced this iteration is added to the vocab and stays forever.**
         `generate_discoveries()` produces sentences like
         "CONFIRMED: wavenet achieved denoising_score=6.2 (predicted 6.0)."
         These are added to `runtime_vocab` by `build_runtime_vocab()` and are
         never removed in subsequent iterations.
         Code: `interpretation_helpers.py build_runtime_vocab()` lines 281–337.
         Test: `TestBuildRuntimeVocab::test_adds_discoveries`  [PASS]
               `test_vocab_grows_across_two_iterations` (integration)  [PASS]

  ☑ B.3  **The accumulated vocab is passed to the next iteration.**
         After interpretation, the workflow saves `interp_output.runtime_vocab`
         back into `current_runtime_vocab`, which is handed to the next iteration
         as `InterpretationInput.runtime_vocab`.
         Example: iter 2 adds 2 new discovery entries → iter 3 starts with those
         2 entries already present in `runtime_vocab`.
         Code: workflow lines 639–645.
         Test: `test_vocab_grows_across_two_iterations` (monotonic growth check)  [PASS]

  ☑ B.4  **The proposal agent always receives the accumulated vocab, not the static seed.**
         The protocol function `local_full_context()` sets `ProposalInput.vocab_seed`
         to `output.runtime_vocab` when it is non-empty, rather than re-loading
         the static `vocab_seed.json`.
         Example: by iter 3, `runtime_vocab` has 30 entries (21 seed + 9 accumulated)
         → the proposal agent's `vocab_seed` has all 30 entries.
         Code: protocol lines 94–100 (`if output.runtime_vocab: use it, else seed`).
         Test: `test_vocab_grows_across_two_iterations` (protocol assertion block)  [PASS]

  ☑ B.5  **No vocab entry is ever silently dropped between iterations.**
         Any entry present in iter N's `runtime_vocab` must still be present in
         iter N+1's `runtime_vocab`. The dedup-by-name dict in `build_runtime_vocab()`
         only overwrites on name collision — it never removes existing entries.
         Example: a "high_pass_filter" discovery added in iter 2 must still appear
         in `runtime_vocab` at iter 10.
         Code: `build_runtime_vocab()` dedup-by-name dict.
         Test: `test_vocab_grows_across_two_iterations` (dropped-entries assertion)  [PASS]

---

### C. proposed_vocab_candidates: injection and seen_in_runs tracking

  ☑ C.1  **`proposed_by_run` is injected by the interpretation agent before vocab merging (Bug 1 fix).**
         The proposal agent's LLM output produces candidates as plain dicts
         `{name, kind, description}` with no `proposed_by_run` field. The
         interpretation agent injects `proposed_by_run = previous_proposal["model_name"]`
         before calling `build_runtime_vocab()`, so `seen_in_runs` can be populated.
         Example: wavenet's proposal emitted `{"name": "attn_pool", "kind": "feature", ...}`.
         Injection adds `"proposed_by_run": "wavenet"` → after merging,
         `vocab["attn_pool"].seen_in_runs = ["wavenet"]`. Before the fix, `seen_in_runs`
         stayed empty forever and no candidate could ever be promoted.
         Code: `result_interpretation_agent.run()` lines 670–681 (injection block).
         Test: `TestProposedByRunInjection::test_proposed_by_run_injected_from_model_name`  [PASS]

  ☑ C.2  **If a candidate already has `proposed_by_run` set, the injection step leaves it alone.**
         The injection guard `if not c.get("proposed_by_run")` ensures that a
         pre-existing value is never overwritten.
         Example: `{"name": "attn_pool", "proposed_by_run": "custom_model"}` → still
         `"custom_model"` after the injection step.
         Code: injection block `if not c.get("proposed_by_run")` guard.
         Test: `TestProposedByRunInjection::test_existing_proposed_by_run_not_overwritten`  [PASS]

  ☑ C.3  **Iteration 1 (no previous proposal) works fine and produces no candidates.**
         On iteration 1, `inp.previous_proposal` is None. The injection block is
         guarded by `if inp.previous_proposal`, so it is skipped entirely and
         `proposed_candidates = []`.
         Code: injection block guarded by `if inp.previous_proposal`.
         Test: `TestProposedByRunInjection::test_no_previous_proposal_no_crash`  [PASS]

  ☑ C.4  **When the same candidate appears again in a later iteration, its run list grows.**
         `build_runtime_vocab()` appends the new run to `seen_in_runs` instead of
         resetting it. The same run name cannot appear twice.
         Example: "attn_pool" was first seen from wavenet (iter 1). In iter 3, fcnet
         also proposes it → `seen_in_runs = ["wavenet", "fcnet"]`. Running iter 3
         again would not add "fcnet" a second time.
         Code: `build_runtime_vocab()` lines 330–335 (extend-without-duplicates branch).
         Test: `TestSeenInRuns::test_existing_candidate_seen_in_runs_extended`  [PASS]
               `TestSeenInRuns::test_same_run_not_duplicated_in_seen_in_runs`  [PASS]

  ☑ C.5  **A candidate proposed by 3 distinct runs is promoted from candidate to canonical.**
         `promote_candidates()` checks every `tier="candidate"` entry with
         `kind in {"feature", "capability"}`. When `len(seen_in_runs) >= 3`,
         the entry is upgraded to `tier="canonical"`.
         Example: "attn_pool" proposed independently by wavenet, fcnet, and transformer
         → after iter 3, `vocab["attn_pool"].tier = "canonical"`.
         Code: `promote_candidates()` lines 240–278.
         Test: `TestSeenInRuns::test_seen_in_runs_enables_promotion_after_three_iterations`  [PASS]
               `TestPromoteCandidates::test_promotes_feature_at_min_runs`  [PASS]
               `TestPromoteCandidates::test_promotes_capability_at_min_runs`  [PASS]

  ☑ C.6  **Discovery entries are never promoted, no matter how often they appear.**
         `kind="discovery"` entries are sentences about past experiments (e.g.,
         "CONFIRMED: wavenet achieved 6.2"). They are observations, not reusable
         concepts, so `promote_candidates()` skips them via the
         `kind in {"feature", "capability"}` guard.
         Example: "prediction_wavenet_confirmed" is in `seen_in_runs` 10 times →
         still `tier="candidate"` (or rather it starts as "candidate" by construction
         and is never promoted).
         Code: `promote_candidates()` `kind` guard.
         Test: `TestPromoteCandidates::test_discovery_never_promoted_regardless_of_runs`  [PASS]

  ☑ C.7  **Semantic dedup skips the LLM call when there are no existing canonicals to compare against.**
         After promotion, `_dedup_promoted()` looks for existing canonical entries
         of the same `kind` to check for synonyms. If none exist yet, the LLM
         call is unnecessary and is skipped.
         Example: "attn_pool" is the very first feature ever promoted → no existing
         canonical features → skip LLM → "attn_pool" is kept as-is.
         Code: `_dedup_promoted()` early-return when `comparison_set` is empty.
         Test: `TestDedupPromoted::test_no_existing_canonicals_of_same_kind_skips_llm`  [PASS]

  ☑ C.8  **When the LLM decides a newly promoted entry is a synonym, the duplicate is merged.**
         If `_dedup_promoted()` determines "receptive_field_extension" means the
         same thing as the existing canonical "large_receptive_field", the new entry
         is removed and its name is added to the existing entry's `aliases` list.
         Example: `vocab["large_receptive_field"].aliases = ["receptive_field_extension"]`.
         Code: `_dedup_promoted()` merge branch.
         Test: `TestDedupPromoted::test_duplicate_removed_and_aliased`  [PASS]

  ☑ C.9  **Each promotion is recorded as a human-readable log entry in `vocab_changes`.**
         `InterpretationOutput.vocab_changes` accumulates one string per promoted
         entry so a human can inspect what changed this iteration.
         Example: `vocab_changes = ["Promoted 'attn_pool' from candidate to canonical (seen in 3 runs)"]`.
         Code: `result_interpretation_agent.run()` lines 682–686.
         Test: `TestVocabChanges` (in `test_vocab_feedback.py`)  [PASS]

---

### D. Prediction evaluation and discovery generation

  ☑ D.1  **A prediction is "confirmed" when the actual score is at least as good as predicted.**
         Example: predicted 6.2, actual 6.4 → confirmed. Predicted 6.2, actual 6.2
         → also confirmed (the `>=` boundary is inclusive).
         Code: `interpretation_helpers.py` lines 54–56.
         Test: `TestEvaluatePrediction::test_confirmed_when_actual_meets_predicted`  [PASS]

  ☑ D.2  **A prediction is "refuted" when the actual score falls below the stated threshold.**
         Example: predicted 6.5, threshold_for_refutation 6.0, actual 5.8
         → refuted because 5.8 ≤ 6.0. If no threshold was given, the outcome
         falls through to "partial" instead.
         Code: `interpretation_helpers.py` lines 57–59.
         Test: `TestEvaluatePrediction::test_refuted_when_actual_below_threshold`  [PASS]

  ☑ D.3  **When the score cannot be computed, the result is "partial" — no crash.**
         If `best_denoising_score` is missing from the results dict, or if
         `predicted_value` is None, `evaluate_prediction()` returns
         `outcome="partial"` gracefully.
         Example: `actual_results = {}` → `actual = None` → outcome = "partial".
         Code: `interpretation_helpers.py` lines 42–51.
         Test: `TestGenerateDiscoveries::test_partial_with_none_actual`  [PASS]

  ☑ D.4  **The SOTA baseline used in discovery sentences is always the strictest available score (Bug 2 fix).**
         The proposal was written at some earlier time when the SOTA was, say, 6.0.
         Since then, wavenet was tuned and scored 6.3. When generating the discovery
         for the current model (score 6.2), we must use the updated SOTA of 6.3,
         not the stale 6.0, otherwise we falsely claim "beating SOTA".
         The fix uses `max(prediction_current_value, overall_best_score)` as the baseline.
         Example (before fix): current model scores 6.2 > stale SOTA 6.0 → "beating SOTA" (wrong).
         Example (after fix): SOTA = max(6.0, 6.3) = 6.3 → 6.2 < 6.3 → "within 5% of SOTA" (correct).
         Code: `interpretation_helpers.py generate_discoveries()` SOTA selection block.
         Test: `TestGenerateDiscoveries::test_overall_best_score_overrides_stale_sota`  [PASS]
               `TestGenerateDiscoveries::test_overall_best_score_negates_false_beat`  [PASS]
               `TestGenerateDiscoveries::test_overall_best_score_only_no_prediction`  [PASS]

  ☑ D.5  **Discovery sentences use the correct label (CONFIRMED / REFUTED / PARTIAL).**
         The text written into the `VocabEntry.description` must match the actual outcome.
         Example confirmed: `"CONFIRMED: transformer achieved denoising_score=6.4000 (predicted 6.2000). The hypothesis was supported."`
         Example refuted: `"REFUTED: fcnet achieved denoising_score=5.8000 (predicted 6.5000). The hypothesis was NOT supported."`
         Code: `interpretation_helpers.py` lines 173–181.
         Test: `TestGenerateDiscoveries::test_confirmed_prediction`  [PASS]
               `TestGenerateDiscoveries::test_refuted_prediction`  [PASS]

  ☑ D.6  **On iteration 1 there is no prediction to evaluate — both fields are empty and no crash occurs.**
         Because `previous_proposal` is None on iter 1, there is no
         `falsifiable_prediction` to check. `InterpretationOutput.prediction_evaluation`
         is `None` and `new_discoveries` is `[]`.
         Code: `result_interpretation_agent.run()` Phase C block; schema defaults.
         Test: `TestInterpretation::test_prediction_evaluation_none_on_first_iter`  [PASS]

---

### E. Protocol: InterpretationOutput → ProposalInput

  ☑ E.1  **The full interpretation output is forwarded to the proposal agent — nothing is cherry-picked.**
         The protocol sets `ProposalInput.interpretation = output.model_dump()`,
         giving the proposal agent the complete serialized `InterpretationOutput`.
         Code: protocol line 85.
         Test: `TestLocalFullContext::test_interpretation_fully_serialized`  [PASS]

  ☑ E.2  **The list of already-tried model types is forwarded to prevent re-proposals.**
         The protocol sets `ProposalInput.existing_model_types = output.model_types`.
         The proposal agent's schema rejects any model name already in this list,
         so the same architecture is never proposed twice.
         Example: after iter 2, `existing_model_types = ["wavenet", "fcnet"]` →
         the proposal agent cannot propose wavenet or fcnet in iter 3.
         Code: protocol line 86.
         Test: `TestLocalFullContext::test_existing_model_types_set`  [PASS]

  ☑ E.3  **The proposal agent receives the accumulated vocab, not the original seed.**
         When `output.runtime_vocab` is non-empty, the protocol sets
         `ProposalInput.vocab_seed` to it instead of loading `vocab_seed.json`.
         This means the proposal agent reasons over everything the system has
         learned so far, not just the static starting knowledge.
         Code: protocol lines 94–100.
         Test: `test_vocab_grows_across_two_iterations` (protocol assertion block)  [PASS]

  ☑ E.4  **Plain-text human advice is converted into the structured `expert_context` format.**
         The `human_advice` string (e.g. "focus on reducing model size") is wrapped
         into an `ExpertContextItem(source="human", content=human_advice)` and placed
         in `expert_context`. No information is lost in the conversion.
         Code: protocol lines 73–82.
         Test: `TestLocalFullContext::test_human_advice_wrapped_into_expert_context`  [PASS]

---

### F. ProposalOutput fields forwarded to next iteration

  ☑ F.1  **`previous_proposal_data` is only updated when tuning actually succeeds.**
         If a proposal fails to implement or validate, the old `previous_proposal_data`
         from the last successful run is still used next iteration — no partial or
         broken proposal overwrites it.
         Code: workflow line 638 (assignment is inside the successful-tune branch).

  ☑ F.2  **The vocab candidate list survives serialization and deserialization intact.**
         `ProposalOutput.proposed_vocab_candidates` goes through `model_dump()` into
         `previous_proposal_data`, and then is read back by the next iteration's
         interpretation agent. The candidate dicts must be identical before and after.
         This round-trip is what makes the Bug 1 injection work — if the candidates
         were lost or corrupted, injection would have nothing to operate on.
         Code: `proposal.py` `ProposalOutput` field definition.
         Test: `TestProposalOutput::test_proposed_vocab_candidates_round_trips`  [PASS]

  ☑ F.3  **The numerical prediction for the next model survives serialization.**
         `ProposalOutput.falsifiable_prediction` is stored in `previous_proposal_data`
         and read back as a dict by the interpretation agent. The numeric fields
         (`predicted_value`, `threshold_for_refutation`, etc.) must be accessible.
         Example: `previous_proposal_data["falsifiable_prediction"]["predicted_value"] = 6.2`
         is what `evaluate_prediction()` reads on the next iteration.
         Code: `result_interpretation_agent.run()` line 631.
         Test: `TestEvaluatePrediction` (end-to-end via interpretation agent)  [PASS]

  ☑ F.4  **The natural-language description of an agent-generated model is attached to its summary.**
         After tuning, `s.model_description = proposal.model_description` is set on
         the `ModelRunSummary` before it is stored as `latest_new_summary`. This means
         the next iteration's Phase 1 LLM prompt can describe the model without
         reading any files from disk.
         Example: "A wavenet-style model with dilated convolutions and attention pooling"
         is attached to the summary and shown to the LLM in Phase 1.
         Code: workflow lines 626–630.
         Test: `TestModelRunSummary::test_model_description_attached`  [PASS]

---

### G. LLM call count is O(1) per iteration

  ☑ G.1  **Phase 1 makes exactly 1 LLM call for the 1 new model, and 0 for all cached models.**
         After iter 1 establishes the baseline models, every later iteration brings
         exactly 1 new model. All existing models skip Phase 1 via the cache hit
         branch, so Phase 1 always costs exactly 1 call per iteration.
         Example: iter 3 has wavenet + fcnet cached + transformer new →
         1 Phase 1 call (transformer only).
         Code: cache-first branch in Phase 1 loop.
         Test: `TestModelKnowledgeCache::test_cache_hit_skips_llm_call`  [PASS]

  ☑ G.2  **Phase 2 (synthesis) makes 1 LLM call when 2+ models exist, and 0 when there is only 1.**
         A synthesis comparison requires at least 2 models. On iter 1 with only a
         single baseline model, the synthesis call is skipped and Phase 1's findings
         are used directly.
         Code: single-model skip condition in Phase 2.
         Test: `TestSingleModel::test_phase1_findings_used` (no synthesis call)  [PASS]

  ☑ G.3  **Phase C (the entire vocab feedback loop) costs 0 LLM calls in the common case.**
         `evaluate_prediction()`, `generate_discoveries()`, `build_runtime_vocab()`,
         and `promote_candidates()` are all deterministic Python — no LLM calls.
         The only exception is `_dedup_promoted()`, which makes 1 call per newly
         promoted entry. Promotions require 3 independent run proposals, so they
         are rare and their cost is bounded.
         Code: all Phase C functions in `interpretation_helpers.py`.
         Test: `TestDedupPromoted::test_no_promotions_skips_llm`  [PASS]

---

### H. Proposal pipeline: two-tier model context

  ☑ H.1  **Top-N candidates receive full source code and all metadata in the Stage 1 prompt.**
         After `select_candidate_models()` returns the top-N models, `enrich_candidates_with_source()`
         loads their source code. Each candidate dict in `accumulated["candidates"]` contains:
         `model_type`, `best_score`, `source_code`, `description`, `file_vector`, `model_params`.
         The comparison LLM can read and borrow from their architecture directly.
         Example: with `top_n=2` and wavenet (5.5) + gated_fno (4.2) selected, the Stage 1
         prompt includes wavenet's full dilated-conv implementation.
         Code: `ml_model_proposal_agent._run_pipeline()` — `enrich_candidates_with_source()` call.
         Test: `TestPipelineRunner::test_pipeline_produces_valid_output`  [PASS]

  ☑ H.2  **Non-selected models appear as a lightweight text summary — no source code.**
         Every model not in the top-N is placed in `accumulated["non_candidates_overview"]`
         with: `model_type`, `best_score`, `description`, `key_findings`, `bottlenecks`,
         `score_trend`, `strategy_assessment` (all from `model_knowledge_cache` and
         `model_descriptions`). Source code is intentionally excluded.
         This tells the Stage 1 LLM what was tried and why it underperformed, preventing
         it from re-proposing failed directions.
         Example: with `top_n=2`, punet (1.8) and fcnet (0.9) are excluded. The Stage 1
         prompt includes "FC architecture unsuitable for this task" for fcnet and
         "No temporal context" as a bottleneck for punet — but no code.
         Code: `ml_model_proposal_agent._run_pipeline()` — `non_candidates_overview` block.
         Test: `TestPipelineRunner::test_non_candidates_included_in_prompt`  [PASS]

  ☑ H.3  **When all models fit within top-N, `non_candidates_overview` is empty.**
         If the total number of models is ≤ N (e.g. 4 models with the `top_n=5`
         default, or any `n_candidates` override ≥ total-model-count), every
         model is a candidate and nothing is excluded. `non_candidates_overview = []`.
         Code: `non_candidates_overview` loop — only appends models not in `candidate_names`.
         Test: `TestPipelineRunner::test_non_candidates_empty_when_all_selected`  [PASS]
