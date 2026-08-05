# ResultInterpretationAgent

> Two-phase node that turns one or more `ModelRunSummary` records (per-model condensed views of a hyperparameter-tuning run) into a single `InterpretationOutput` carrying key findings, bottlenecks, runtime-vocabulary updates, and a cross-iteration knowledge cache that downstream proposal + future-iteration nodes read.

## Position in the pipeline

- **Node type**: **standalone-capable** — `nodes/result_interpretation_agent/result_interpretation_agent.py` exposes a CLI `main()` that reads a tuning agent's `run_output_{run_name}.json` from disk, builds the `InterpretationInput` itself, runs the two-phase pipeline, and writes `interpretation_{run_name}.json` back to the same workspace.
- **Upstream**: `ml_hyperparameter_tune_agent` (provides `HyperparamTuningOutput` per model, converted by `tuning_output_to_model_run_summary` into the `ModelRunSummary` entries this node consumes).
- **Downstream**: `ml_model_proposal_agent` (consumes `InterpretationOutput` via the `local_full_context` protocol; specific fields read: `key_findings`, `bottlenecks`, `take_home_message`, `runtime_vocab`, `model_descriptions`, plus per-model best/worst scores).
- **Protocol**: `local_full_context` in `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` — maps `InterpretationOutput` (this node's output) plus the next-iter's chain state into the proposer's `ProposalInput`.

## Input

**Schema**: `InterpretationInput` in `agent/schemas/interpretation.py`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `summaries` | `list[ModelRunSummary]` | Yes | — | Condensed summaries for **new** models only — models being interpreted for the first time this iteration. Each `ModelRunSummary` holds best/worst denoising scores, formal score, trajectory, conclusions, and optionally a `model_description` for plugin-generated models. |
| `model_types` | `list[str] \| None` | No | `None` | Explicit list of model types whose descriptions to include. When `None`, model types are derived from `summaries`. Cannot be an empty list — use `None` to disable. Workflow rarely sets this directly. |
| `expert_advice` | `str \| ExpertAdvice` | No | `""` | Structured guidance from upstream agents or orchestrators. Accepts a plain string or a structured `ExpertAdvice` object. |
| `human_advice` | `str \| None` | No | `None` | Optional human-provided guidance — **highest priority**, overrides `expert_advice` when present. Injected into the LLM prompt as high-priority context. |
| `active_model_top_k` | `int` | No | `3` | Top-K cap by `best_denoising_score` for the active-model set. These models keep their full per-model summary expanded in the synthesis prompt and are eligible for proposing. |
| `active_model_last_n` | `int` | No | `2` | Last-N cap by recency for the active-model set. The N model_types from the current iter's `summaries` list (in order supplied) are unconditionally active. |
| `active_model_score_delta` | `float` | No | `0.05` | Absolute score-delta threshold (in normalized denoising-score units) at or above which a model with both a prior cache entry and a current-iter summary is promoted into the active set despite not making the top-K. |

### Workflow-populated fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `storage` | `StorageConfig` | Yes | — | Where the node reads its inputs and writes its interpretation output. In standalone CLI use, constructed by `main()` from `--workspace` + `--run_name`; in workflow use, populated by `workflows/model_exploration.py`. |
| `iteration` | `int` | No | `1` | 1-based iteration index within the chain. Stamped into the per-iter row appended to `{workspace}/evolution_log.jsonl`. |
| `model_knowledge_cache` | `dict[str, Any]` | No | `{}` | Carry-forward cache from the previous `InterpretationOutput.model_knowledge_cache`. Each entry is self-sufficient: Phase 1 LLM text + `_stats` block with numeric trends. Skipping re-summarisation of models already in cache is the main mechanism for keeping per-iter LLM cost bounded. |
| `runtime_vocab` | `list[VocabEntry]` | No | `[]` | Current runtime vocabulary (seed + candidates + discoveries) carried from prior iterations. Empty on first iteration (uses seed). Compressed memory of what the system has learned. |
| `previous_proposal` | `dict[str, Any] \| None` | No | `None` | Serialized `ProposalOutput` from the previous iteration. Contains `falsifiable_prediction`, `proposed_vocab_links`, `inherited_components`. Drives the prediction-evaluation step (was the previous round's bold prediction confirmed, partial, or refuted?). |
| `cumulative_information_gain` | `float` | No | `0.0` | Sum of `information_gain` from all previous iterations — running history of how many bold predictions were confirmed. |
| `prediction_outcomes_history` | `dict[str, int]` | No | `{}` | Running count of each prediction outcome across all past iterations. Carry-forward from previous `InterpretationOutput`. |
| `vocab_link_confirmations` | `dict[str, list[str]]` | No | `{}` | Carry-forward mapping `"feature:capability"` → list of run_names where that vocab link was confirmed. |
| `enable_structured_health_feedback` | `bool` | No | `False` | V19 PR 3 prompt flag. **OFF (default): prompts are byte-identical to pre-PR3** (golden-parity tested) even when structured evidence is present; the deterministic output fields below are populated regardless (recording-only). ON: the per-model prompt gains `[GATE ...]` trajectory labels, a `### HealthGate summary` section, and a system-prompt instruction block. Part of the run-invariants lock — flipping it mid-workspace is rejected at startup. |
| `health_feedback_history_window_iterations` | `int` (`>= 1`) | No | `3` | Fingerprint-history retention window: the TOTAL number of iterations retained INCLUDING the current one (`minimum_retained_iter = current_iter - window + 1`; e.g. window 3 at iteration 5 retains 3, 4, 5). Locked. |
| `health_feedback_history_max_entries_per_model` | `int` (`>= 1`) | No | `8` | Deterministic trim bound on retained fingerprint-history entries per model (ordering: last-retained-iteration desc, windowed count desc, signature asc). Locked. |
| `collapse_fingerprint_history` | `dict[str, list[CollapseFingerprintHistoryEntry]]` | No | `{}` | Typed carry-forward from the previous `InterpretationOutput.collapse_fingerprint_history` — the ONLY history source (digest → typed restore → workflow → here). Never rebuilt from proposer output, prompts, or LLM findings. Empty on the first iteration and on legacy digests without the field. |

## Output

**Schema**: `InterpretationOutput` in `agent/schemas/interpretation.py`

| Field | Type | Description |
|---|---|---|
| `model_types` | `list[str]` | All model types analysed (union of `summaries` and explicit `model_types`). |
| `model_descriptions` | `dict[str, str]` | `model_type` → full markdown description loaded from `description.md` (or inline for plugins). Carries architecture knowledge forward to the proposer. |
| `total_experiments` | `int` | Total completed rounds across all summaries (new + cached). |
| `per_model_best` | `dict[str, float \| None]` | `model_type` → best denoising score. `None` if the model has no successful experiments. |
| `per_model_worst` | `dict[str, float \| None]` | `model_type` → worst denoising score. `None` if the model has no successful experiments. |
| `best_denoising_score` | `float \| None` | Highest denoising score observed across all models. |
| `worst_denoising_score` | `float \| None` | Lowest denoising score observed across all models. |
| `best_config` | `dict[str, Any] \| None` | The params dict that produced the overall best denoising score. |
| `model_knowledge_cache` | `dict[str, dict[str, Any]]` | `model_type` → self-sufficient cache entry produced by Phase 1. Each entry contains Phase 1 LLM text (key_findings, bottlenecks, best_config_analysis) plus `_stats`. **This is what gets carried forward** to the next iteration's `InterpretationInput.model_knowledge_cache`. |
| `key_findings` | `list[str]` | Concrete, ranked observations extracted from the run summaries — PRIMARY input to the proposal agent's synthesis. |
| `bottlenecks` | `list[str]` | Root causes currently limiting further improvement — PRIMARY input that grounds proposal hypotheses and literature-review search queries. |
| `take_home_message` | `str` | Single critical insight that directly motivates proposing a new architecture. |
| `per_model_score_tables` | `dict[str, ScoreComparisonTable] \| None` | `model_type` → best `ScoreComparisonTable` (superset of the legacy per_model_file_vectors plus raw baseline columns). |
| `per_model_params` | `dict[str, int] \| None` | `model_type` → parameter count of the best model. |
| `per_model_training_segments` | `dict[str, int] \| None` | `model_type` → training PSD segments used in the best experiment. |
| `runtime_vocab` | `list[VocabEntry]` | Updated vocabulary: seed + candidates + discoveries from all iterations. Compressed memory the next iteration reads. |
| `prediction_evaluation` | `dict[str, Any] \| None` | Evaluation of the previous proposal's `FalsifiablePrediction`. Outcome is SOTA-based: confirmed = beat SOTA, partial = within a tolerance band, refuted = below the band. |
| `new_discoveries` | `list[VocabEntry]` | New `kind="discovery"` entries from this round's evaluation. Empirical findings expressed as sentences, added to `runtime_vocab`. |
| `vocab_changes` | `list[str]` | Human-readable log of vocabulary promotion events made this iteration. |
| `vocab_diversity_ratio` | `float \| None` | Fraction of feature/capability vocab entries still in candidate tier (range `[0, 1]`). Low values signal vocabulary stagnation. |
| `cumulative_information_gain` | `float` | Running total of `information_gain` across all iterations. Increases when a bold prediction is confirmed. |
| `scientific_accuracy` | `dict[str, float] \| None` | Prediction hit-rate fractions: e.g. `{"confirmed": 0.38, "partial": 0.22, "refuted": 0.40}`. Sums to 1.0. `None` until the first prediction has been evaluated. |
| `prediction_outcomes_history` | `dict[str, int]` | Cumulative count of each prediction outcome. Carry-forward to next iteration. |
| `vocab_link_confirmations` | `dict[str, list[str]]` | Updated feature→capability link confirmation counts. Carry-forward. |
| `per_model_round_health_counts` | `dict[str, dict[str, int]]` | V19 PR 3. `model_type` → `{"valid": n, "invalid": n, "unknown": n}` over this iteration's rounds, from each round's deterministic `classify_candidate_health` verdict. Computed from `RoundHealth`, NEVER from LLM findings; populated regardless of the prompt flag (recording-only when OFF) and regardless of LLM degradation. |
| `per_model_collapse_fingerprints` | `dict[str, list[CollapseFingerprint]]` | V19 PR 3. `model_type` → distinct collapse fingerprints observed THIS iteration (deduped by signature, chronological first-seen order). Deterministic — built from persisted gate evidence only. |
| `collapse_fingerprint_history` | `dict[str, list[CollapseFingerprintHistoryEntry]]` | V19 PR 3. Bounded cross-iteration fingerprint history AFTER this iteration's deterministic merge + retention (per-iteration occurrence buckets; expired buckets removed at merge, so stored counts ARE retained-window counts). Carry forward as the next `InterpretationInput.collapse_fingerprint_history`. The merge runs even on the degraded path — real gate evidence is never lost to an LLM failure. |
| `is_degraded` | `bool` | `True` when the interpreter produced this output via the fallback path (LLM call failed after `LLMBridge`'s 3-retry envelope). Degraded outputs preserve numeric stats but carry empty LLM text. |
| `evolution_stats` | `dict[str, Any]` | Per-iteration vocab-evolution metrics: `vocab_total`, `vocab_canonical`, `vocab_candidate`, `promoted_this_iter`, `is_degraded`. Also written as one line into `evolution_log.jsonl`. |

## CLI usage

```bash
.venv/bin/python nodes/result_interpretation_agent/result_interpretation_agent.py \
    --workspace ./siderius_workspace \
    --run_name v1 \
    --model_type punet \
    --provider gemini \
    --model_id gemini-3.1-flash-lite-preview
```

The CLI reads `{workspace}/run_output_{run_name}.json` (the upstream tuning agent's output), converts it to a `ModelRunSummary` via `tuning_output_to_model_run_summary`, runs the agent, and writes `{workspace}/interpretation_{run_name}.json`.

**Limitation of standalone CLI use**: only one model type per invocation, and the cross-iteration carry-forward state (`model_knowledge_cache`, `runtime_vocab`, `previous_proposal`, etc.) is empty — there is no `--cache_from_prev_iter` flag. For multi-model + chained iteration use, drive the node via `workflows/model_exploration.py`.

### CLI arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `--workspace` | `str` | `./siderius_workspace` | Root directory for reading the upstream tuning agent's `run_output_{run_name}.json` and writing `interpretation_{run_name}.json`. |
| `--run_name` | `str` | `v1` | Filename suffix shared with the upstream run. |
| `--model_type` | `str` | required | Model architecture (e.g. `punet`, `wavenet`, `fcnet`). |
| `--provider` | `str` (`gemini` \| `openai`) | `gemini` | LLM provider for the per-model + synthesis + dedup calls. |
| `--model_id` | `str` | `gemini-3.1-flash-lite-preview` | Specific model id passed to the provider. |

## Python API usage

```python
from nodes.result_interpretation_agent.result_interpretation_agent import (
    ResultInterpretationAgent,
    tuning_output_to_model_run_summary,
)
from agent.schemas.interpretation import InterpretationInput, ModelRunSummary
from agent.schemas.storage import StorageConfig, LocalStorageConfig

# Build summaries from upstream tuning agent outputs (one per model).
summaries = [
    tuning_output_to_model_run_summary(tune_output_punet),
    tuning_output_to_model_run_summary(tune_output_wavenet),
    # ...
]

inp = InterpretationInput(
    summaries=summaries,
    storage=StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace="./workspace", run_name="iter_001"),
    ),
    # Carry-forward state from the previous iteration (empty on iter 1):
    model_knowledge_cache=prev_output.model_knowledge_cache,
    runtime_vocab=prev_output.runtime_vocab,
    previous_proposal=prev_proposal_dict,
    cumulative_information_gain=prev_output.cumulative_information_gain,
    prediction_outcomes_history=prev_output.prediction_outcomes_history,
    vocab_link_confirmations=prev_output.vocab_link_confirmations,
    iteration=2,
    # Optional advice:
    expert_advice="focus on architectural diversity, less weight on hyperparameter sweeps",
    human_advice=None,
)

agent = ResultInterpretationAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview")
output = agent.run(inp)  # -> InterpretationOutput
```

The constructor accepts `bridge_factory` (for test injection — defaults to `LLMBridge`) and `max_retries` (defaults to `None`, meaning infinite retry on LLM quota errors per the project's `feedback_llm_bridge_infinite_retry_intentional` policy).

## Storage outputs

- **Interpretation JSON**: `{storage.local.workspace}/interpretation_{run_name}.json` — the validated `InterpretationOutput` dumped at the end of `run()`. The workflow does NOT read this back — downstream nodes receive data through the protocol function in memory. This is the audit log of the iteration.
- **Evolution log**: `{SIDERIUS_CHAIN_WORKSPACE or storage.local.workspace}/evolution_log.jsonl` — **append-only** JSONL file, one line per `run()` call. Each line carries the iteration's `evolution_stats` plus a timestamp. In chain mode (`run_one_iteration.py` sets `SIDERIUS_CHAIN_WORKSPACE`), the log accumulates at the chain root across all iterations and is `tail -f`-friendly. In single-process / CLI mode the env var is unset and the log lands at the agent's own workspace. **IO errors are logged but swallowed** — observability never breaks the pipeline.

## Key behavioral notes

- **Two-phase LLM pipeline.** Phase 1 = one `bridge.generate()` per model type, taking the condensed `ModelRunSummary` (scores + trajectory + conclusions — NOT raw experiment records) and producing per-model `key_findings`, `bottlenecks`, `best_config_analysis`. Phase 2 = exactly one `bridge.generate()` consuming all per-model summaries to produce the cross-model `InterpretationOutput`. A Phase 3 dedup call may fire to consolidate vocabulary candidates with the existing canonical set.
- **`model_knowledge_cache` is the cross-iteration memory.** Models already in the input cache do NOT get a Phase 1 LLM call — their cached Phase 1 text + `_stats` flow directly into Phase 2's synthesis prompt. This is the dominant per-iter cost lever: only NEW models in `summaries` incur Phase 1 cost.
- **Active-model selection** uses three criteria together: `active_model_top_k` (best-K by `best_denoising_score`), `active_model_last_n` (most-recent N from this iter's `summaries` order), and `active_model_score_delta` (significant-change threshold for models with both a cached entry and a fresh summary). The active set is the union of those three and is what gets full per-model summary expansion in Phase 2's prompt. Models outside the active set get a compressed one-line entry.
- **Prediction evaluation is SOTA-based, not predicted-value-based.** A `FalsifiablePrediction` from the previous proposal is judged confirmed/partial/refuted based on whether the current iteration's best score beat the SOTA band — not on whether the proposer's specific numeric prediction was hit. This is intentional: the proposer's job is to bet on direction, not on a specific number.
- **Degraded fallback path.** If the synthesis LLM call fails after `LLMBridge`'s 3-retry envelope, the agent emits an `InterpretationOutput` with `is_degraded=True`, preserving numeric stats but with empty `key_findings` / `bottlenecks` / `take_home_message`. Downstream nodes can detect this and fall back to deterministic priors. Phase 1 failures are not degraded — they raise.
- **Vocabulary candidates need 3 distinct actually-tried runs** to be promoted to canonical (the "Tested-only" threshold). Promotion events are logged into `vocab_changes` and counted into `evolution_stats.promoted_this_iter`. Skipping the dedup step (because no new candidates this iter) is normal and is NOT a degraded path.
- **`HyperparamTuningOutput` → `ModelRunSummary` conversion** is done by the public helper `tuning_output_to_model_run_summary(output)`. The conversion drops raw experiment records and keeps best/worst scores, formal score, trajectory, conclusions, and (if present) the inline `model_description` for plugin-generated models. Since V19 PR 3 it also builds `round_health` (one `RoundHealth` per record, chronological, parallel to `round_scores`): provenance via the evidence-precedence ladder (`gated` / `gates_disabled` / `round_fields_only` / `gate_not_evaluated` / `legacy` — persisted evidence is never discarded by a status rule, and an empty-but-present result list is never read as legacy), validity via `classify_candidate_health`, and a deterministic `CollapseFingerprint` for gated collapse rounds.
- **Structured HealthGate feedback (V19 PR 3)** is split into recording and rendering. RECORDING is unconditional: `per_model_round_health_counts`, `per_model_collapse_fingerprints`, and the merged `collapse_fingerprint_history` are computed deterministically BEFORE the LLM calls and written into both the healthy and the degraded output — an interpreter LLM failure keeps `is_degraded=True` commentary semantics but never loses the iteration's gate evidence. RENDERING is gated by `enable_structured_health_feedback` (default `False`): OFF keeps every prompt byte-identical to pre-PR3 (proven by golden string equality); ON adds gate labels to the score trajectory, a `### HealthGate summary` section (validity counts, distinct fingerprints with round indices, best-round recording diagnostics — never an empty heading), and a system-prompt instruction block (preserve fingerprints verbatim; an invalid high score is a failure; no verdict from absence; no cross-model transfer). History flows ONE way: latest digest → typed restore → workflow → this input → deterministic merge → new digest. Retention: bounded iteration window (`health_feedback_history_window_iterations`, default 3, total-including-current) with `health_feedback_history_max_entries_per_model` (default 8) deterministic trimming; both are run-invariants-locked together with the flag — a changed value on the same workspace fails startup with a `RunInvariantsViolation` naming the field and both values, and a legacy workspace resolves to OFF / 3 / 8 (enabling ON over a legacy workspace is likewise rejected — use a new workspace).

> **Experimental status (V19 PR 3, final).** This optional feature is
> fully implemented and operationally validated, but no universal
> performance-improvement claim is made. A controlled 40-sample
> descriptive evaluation (Control vs Treatment, 4 scenario families)
> found more precise evidence grounding in some scenarios (exact gate
> and fingerprint naming, supported feedback-use claims), no primary
> behavioral improvement under the tested fixtures, and no observed
> safety regressions in either arm. Its effect is context-dependent —
> do not assume improvement without task-specific evaluation. The
> default remains OFF; enabling it on an existing default-OFF
> workspace is rejected by the run-invariants lock — use a new
> workspace.
- **Data ordering is exposed per round, and only the RESOLVED value describes execution (V19 PR 2).** `ModelRunSummary.round_ordering` is a `list[RoundOrdering]` parallel to `round_scores`, one entry per round, each carrying `exp_id`, the resolved strategy and file order, the resolution source, and the proposal (rejected or not). Two rules govern its use:
  - `resolved_order_strategy` / `resolved_file_order` are the **only** fields that say what ran. An ordering the agent proposed but the operator overrode was *not* executed and must never be attributed as such — `resolution_source` names which level decided.
  - A **rejected** proposal (`proposal_rejected=True`) is not the same as no proposal. The agent tried to steer that round and was overruled by validation; reading it as agent silence would misdescribe its behavior.
  - A **`resolved_order_strategy` of `None`** means no ordering ran at all — the attempt was rejected at pre-flight (`resolution_source="not_executed"`). Do not describe such a round as having executed any ordering, and do not read the `None` as a default.

  Ordering is kept per round, not per run, because it may legitimately differ between rounds of one iteration when no operator override is in force. Absence of an executed ordering has two distinct readings, both produced by `ResolvedOrdering.from_record` and never guessed at: `legacy_default` (a **pre-PR2 artifact** that predates the feature — reconstructed as `shuffle` for compatibility) and `not_executed` (a **current-code attempt** that never reached training — `resolved_order_strategy=None`). Conflating them would report a current run as partly produced by old code. See `docs/design/v19_priorities/pr2_data_ordering.md` §3.7.

## Dependencies

- **LLM**: up to three call sites per run, all via `LLMBridge.generate()` (returns a parsed dict; validated with `model_validate`):
  - **Phase 1 — per-model summarization** — one call per model in `summaries` that is NOT already in `model_knowledge_cache`. System prompt: `PER_MODEL_SYSTEM_PROMPT` (module-level constant).
  - **Phase 2 — cross-model synthesis** — exactly one call per run. System prompt: `SYNTHESIS_SYSTEM_PROMPT` (module-level constant).
  - **Phase 3 — vocab dedup** — one call when there are new candidate vocab entries that need consolidation against existing canonicals. System prompt: `DEDUP_SYSTEM_PROMPT` (module-level constant). Skipped (no LLM call) when no new candidates exist.
- **GPU**: not required.
- **External services**: none directly. Depends on the upstream tuning agent's experiment records (already on disk in `{workspace}/run_output_{run_name}.json`) and on `ml_models/{model_type}/description.md` for any model_type not carrying an inline description in its `ModelRunSummary`.

## Scientific aggregation (V20 PR D, D-C5)

`ModelRunSummary.scientific_authority` carries the verdict of the FORMAL record its `formal_score` came from, so the score and its authority cannot describe different experiments. Before any LLM call, `run()` partitions the summaries via `execute_tools.scientific_aggregation.partition_for_aggregation()` and filters `per_model_formal` to authoritative results only — a non-authoritative formal score therefore never reaches the synthesis prompt and cannot inform a scientific claim.

Nothing is deleted. The excluded results are retained in `InterpretationOutput.scientific_aggregation` (`included` / `excluded` / `excluded_count` / `all_excluded` / `no_records` / `exclusion_reason_counts`), written at BOTH the healthy and the degraded assembly so an interpreter LLM failure cannot lose the provenance. Render it with `AggregationScope.provenance_lines()`.

The exclusion is derived and rendered **deterministically, never by the model** (design §4.7): a model may simply omit it, and exclusion text placed inside a prompt can steer the interpretation it then writes. `all_excluded` is explicit because an empty aggregate alone reads identically to a campaign that found nothing — the opposite conclusion.
