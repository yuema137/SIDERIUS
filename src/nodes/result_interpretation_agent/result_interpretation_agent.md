# ResultInterpretationAgent

> Two-phase node that turns one or more `ModelRunSummary` records (per-model condensed views of a hyperparameter-tuning run) into a single `InterpretationOutput` carrying key findings, bottlenecks, runtime-vocabulary updates, and a cross-iteration knowledge cache that downstream proposal + future-iteration nodes read.

## Module layout

The node has exactly ONE public interface — `result_interpretation_agent.py` +
this file. Everything else in the package is PRIVATE by ownership; the plain
filenames are a guard convention (`tests/unit/nodes/test_node_public_boundary.py`
only inspects non-underscore modules), not public-API status.

| module | visibility | owns |
|---|---|---|
| `result_interpretation_agent.py` | **PUBLIC** | `ResultInterpretationAgent`, the `run()` lifecycle, the CLI `main()`, `_dedup_promoted`, evolution-log I/O, output assembly and persistence. Since Step 09b C1 it owns NO prompt byte: the prompt constants and builders live in `agent/prompt_templates/interpretation/rendering.py` (a byte-exact move), and this module imports exactly the builders its lifecycle calls |
| `result_interpretation_agent.md` | **PUBLIC** | this contract |
| `agent/prompt_templates/interpretation/rendering.py` | framework (outside the node) | the interpreter's ENTIRE prompt surface: the two system-prompt TEMPLATES (task-free since 09b C2 — they carry a `{TASK_GUIDANCE_SECTIONS}` slot, not task science), `DEDUP_SYSTEM_PROMPT`, `HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS`, the user-prompt builders, the system-prompt assemblers, `_render_health_summary_section`, `_flatten_entry_for_prompt`, and the explicit evidence renderers (`render_metric_identity`, `render_interpretation_diagnosis_lines`, `render_secondary_metrics`, `render_failure_counts`, `render_prediction_track_record`). Layering rule: it imports schemas/framework authorities only and must never import the node package |
| `agent/prompt_templates/interpretation/task_blocks.py` | framework (outside the node) | the BOUNDED Regime-A adapter: `load_interpretation_task_blocks(path=None)` + the ONE self-labelled default-path constant `LEGACY_DEFAULT_TASK_INTERPRETATION_CONFIG` (`configs/task_interpretation/tidmad.yaml`, anchored to THIS checkout via `_task_blocks_loader.SIDERIUS_ROOT` — it was cwd-relative until the N-1 release remediation, so a zero-arg load from any other working directory raised `FileNotFoundError`). Fail-closed on a missing / non-mapping / unknown-key / empty-section declaration. It is compatibility PACKAGING, never a registry or loader ecosystem: the constant feeds no branch, and Step 12's composition root replaces the CALL SITE, not the contract |
| `evidence.py` | private | persisted evidence → typed projections: `tuning_output_to_model_run_summary`, `_round_ordering`, `_round_health`, `_collect_health_evidence`, `_required_denoising_score`, `reconcile_metric_spec`, `project_failure_counts`, `InterpretationContractError` |
| `ordering.py` | private | the run-scoped deterministic boundary: `bind_run_order` → the ONE `MetricOrder`; `precompute_evidence` → `PrecomputedEvidence` (per-model/overall best, valid, worst, formal, configs, `total_experiments`, the summary index and the scientific-aggregation scope) and `collect_enriched_fields` → `EnrichedFields` (score tables, parameter counts, training volumes) |
| `prediction.py` | private | prediction grammar and semantics: `evaluate_prediction`, `_compute_metric`, the FROZEN legacy alias table, and the versioned accumulators `accumulate_prediction_outcomes` / `accumulate_information_gain` / `prediction_pool_sizes`. It IMPLEMENTS the v2 rule but does not own its NAME: the semantics ids and the outcome vocabulary are declared once in `agent/schemas/interpretation.py` (the schema owning the fields they key) and re-exported here under the same names, so the schema, the helpers and `core/resume.py` all read one authority |

Rules, all executable:

- the dependency graph is one-way — `result_interpretation_agent.py` →
  `{evidence, ordering, prediction}`, never the reverse, and no cycle among
  the private modules;
- production code OUTSIDE the node imports the node's public interface only;
- every symbol is DEFINED exactly once in the package — the main module
  re-exports moved names by IMPORT, never by keeping a second copy;
- `__all__` is the node's public surface; the moved helpers re-exported for
  backwards compatibility are listed separately in `_COMPATIBILITY_REEXPORTS`,
  are not part of the contract, and no NEW production consumer may be added —
  import the owning submodule from inside the node instead;
- the private modules are imported EAGERLY at the main module's top level.
  That is load-bearing: `__init__.py` rebinds
  `sys.modules["nodes.result_interpretation_agent"]` to the main module, so a
  lazily-imported submodule would be unreachable afterwards. From a test, reach
  one with `importlib.import_module("nodes.result_interpretation_agent.<name>")`,
  and stub an internal on the module that CALLS it.

## Task-owned interpretation guidance (Step 09b)

The framework owns the prompt STRUCTURE; the task owns the interpretation
SCIENCE. `InterpretationInput.task_blocks` carries a frozen
`InterpretationTaskBlocks` VALUE with exactly four optional sections —
`evidence_reading` (rendered in BOTH phase system prompts),
`per_model_guidance` (Phase 1), `synthesis_guidance` and
`prediction_guidance` (Phase 2). An absent section renders NOTHING: no
header, no bytes. A present-but-empty section is refused.

The interpreter never discovers task files. The CALLER supplies the value:
today `workflows/model_exploration.py` and this node's CLI `main()` resolve
TIDMAD's through the bounded adapter above; at Step 12 the composition root
supplies the same typed value and the adapter call disappears. An external
task supplies its own value — or its own YAML at any path — with no SIDERIUS
edit.

TIDMAD's declaration deliberately carries NO `prediction_guidance`: nothing
existed in the pre-09b prompts to migrate there, and inventing guidance
during a migration is not a migration.

## Rendered evidence (Step 09b C3/C4)

Each family has ONE renderer, and every section is presence-gated — an
absent family emits no header rather than a fabricated "none observed":

| section | source | absent ⇒ |
|---|---|---|
| `Metric               :` | `ModelRunSummary.metric_identity` (09a C2) | omitted (the run-level line still names the metric) |
| `### Training dynamics` | `best_training_diagnosis` / `formal_training_diagnosis` (09a C6), rendered per ROLE through the 07b line grammar | omitted; a PRESENT but degenerate diagnosis still renders ("none recorded" / "invalid (non-finite)") |
| `### Secondary metrics` | `secondary_metrics` (09a C6, populated by Step 10 / P2b) — each with its OWN id and direction; `scored` / `not scoreable (<contract id>)` / `declared, not evaluated this run` | omitted when the run declared no secondary (TIDMAD): no stamp ⇒ no rows ⇒ no header and no bytes |
| `### Record outcomes` | `failure_counts` (09a C6) — keys from existing authority vocabularies only, zero counts omitted | omitted; a cached model with no stored counts is ABSENT, never "0 failures" |
| `Prediction Track Record` (synthesis + the proposer) | the v1/v2 pools (09a C4/C5) rendered by ONE version-aware authority | omitted when no comparable prediction exists |

The prediction track record never pools `legacy_v1` with
`metric_order_signsafe_v2` and never renders one population's fraction over
the other's denominator; both N's count the comparable outcomes only.

### F-SCANE-4 — the honest per-model headline is rendered, and its absence is named

Every per-model headline the LLM used to see is mixed on one axis or the
other: `Raw best score` and `Best valid score` may come from a TRIAL round,
`Formal round score` may come from a health-INVALID record.
`ModelRunSummary.best_valid_formal_score` is the only one that is BOTH
HealthGate-valid and formal, and it had no production consumer past its own
construction in `evidence.py`. `_build_per_model_prompt` now renders it:

```text
Best valid formal    : <score>
Best valid formal    : NONE — this model produced no HealthGate-valid formal
                       result; every score above is from a trial round, a
                       health-invalid record, or both.
```

The absence is NAMED rather than omitted, deliberately: a model can have a
`Formal round score` and still have no VALID formal result, and omitting the
line leaves that number standing unqualified as the model's authoritative
headline — the shape of the defect, not a tidier prompt.

`ModelRunSummary.formal_file_vector` — declared "Definitive per-file
performance" — had no consumer of ANY kind while the MIXED `best_file_vector`
did. `formal_score_table` (its enriched twin) is rendered where one exists;
where it does not, which is every COMPOSED run since the enriched table is
built from TIDMAD reference science a composed run deliberately omits
(F-12e-UX-7), the raw vector now renders under
`### Per-sample performance (formal round — definitive, no enriched table)`.

**Two things F-SCANE-4 deliberately did NOT change**, so a later reader does
not mistake either for an oversight:

* `prediction._PER_SAMPLE_KEY` still resolves per-sample prediction forms
  from the MIXED best score table. Repointing it would change which value the
  prediction pool is scored against — a scientific change needing a new
  `prediction_evaluation_semantics` id and an operator decision.
* the `_stats` knowledge cache still carries only the mixed pair
  (`formal_score`, `best_file_vector`), so a model that goes QUIET loses its
  valid-formal headline. Writing the honest pair into `_stats` today would add
  a second field that is persisted and read by nothing — the exact defect this
  row records. Closing it properly means carrying a per-model valid-formal
  aggregate through `precompute_evidence` into the CROSS-MODEL synthesis
  block, beside `per_model_formal`. (N-2 later added `scientific_authority` to
  `_stats`, which is NOT this item: that field has a reader —
  `precompute_evidence`'s authority partition — and was added because it had
  one.)

## Position in the pipeline

- **CLI entry**: **present** — `main()` reads a tuning record from disk and constructs the input, while optional task guidance and run-scoped metric/evidence context remain caller-supplied; CLI presence is not a claim of complete workflow equivalence.
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
| `vocab_link_confirmations` | `dict[str, list[str]]` | No | `{}` | Carry-forward mapping `"feature:capability"` → list of run_names where that vocab link was confirmed. **Step 10 / P5+P6: this is now genuinely carried across iterations** — before it, the field existed on both schemas but nothing transported it, so every production digest's mapping held at most one run and promotion (`min_runs=3`) was unreachable in a real chain. See "Carried lifecycle" below. |
| `enable_structured_health_feedback` | `bool` | No | `False` | V19 PR 3 prompt flag. **OFF (default): prompts are byte-identical to pre-PR3** (golden-parity tested) even when structured evidence is present; the deterministic output fields below are populated regardless (recording-only). ON: the per-model prompt gains `[GATE ...]` trajectory labels, a `### HealthGate summary` section, and a system-prompt instruction block. Part of the run-invariants lock — flipping it mid-workspace is rejected at startup. |
| `baseline_isolation` | `bool` | No | `False` | **arXiv U3 (#260, ruling R6)** — the WITHOUT arm's explicit isolation flag, set by the workflow from its launch config. When `True`, the disk-description fallback (`get_model_description`) REFUSES a bundled `ml_models/*/description.md` (`FileNotFoundError` naming the refused path), so no bundled baseline prose can enter the prompts or the carried `model_knowledge_cache` `_stats`. Inline summary descriptions and workspace plugin descriptions resolve unchanged. |
| `health_feedback_history_window_iterations` | `int` (`>= 1`) | No | `3` | Fingerprint-history retention window: the TOTAL number of iterations retained INCLUDING the current one (`minimum_retained_iter = current_iter - window + 1`; e.g. window 3 at iteration 5 retains 3, 4, 5). Locked. |
| `health_feedback_history_max_entries_per_model` | `int` (`>= 1`) | No | `8` | Deterministic trim bound on retained fingerprint-history entries per model (ordering: last-retained-iteration desc, windowed count desc, signature asc). Locked. |
| `collapse_fingerprint_history` | `dict[str, list[CollapseFingerprintHistoryEntry]]` | No | `{}` | Typed carry-forward from the previous `InterpretationOutput.collapse_fingerprint_history` — the ONLY history source (digest → typed restore → workflow → here). Never rebuilt from proposer output, prompts, or LLM findings. Empty on the first iteration and on legacy digests without the field. |
| `metric_spec` | `MetricSpec \| None` | No | `None` | **Step 09a.** The run's ALREADY-RESOLVED evaluation metric, reconciled across every tuning output feeding this interpretation and supplied by the caller (`reconcile_metric_spec`). It is the SINGLE authority for ordering direction, the run-level metric identity and the prediction default. The node NEVER derives it. `None` is legal ONLY for a cold start or a genuinely scoreless input — see "Fail-closed metric contract" below. |

## Output

**Schema**: `InterpretationOutput` in `agent/schemas/interpretation.py`

| Field | Type | Description |
|---|---|---|
| `model_types` | `list[str]` | All model types analysed (union of `summaries` and explicit `model_types`). |
| `model_descriptions` | `dict[str, str]` | `model_type` → full markdown description loaded from `description.md` (or inline for plugins). Carries architecture knowledge forward to the proposer. |
| `total_experiments` | `int` | Total completed rounds across all summaries (new + cached). |
| `per_model_best` | `dict[str, float \| None]` | `model_type` → best denoising score. `None` if the model has no successful experiments. |
| `per_model_worst` | `dict[str, float \| None]` | `model_type` → worst denoising score. `None` if the model has no successful experiments. |
| `metric_identity` | `MetricIdentity \| None` | **Step 09a.** `{metric_id, direction}` PROVENANCE: the metric this iteration was actually ordered under, echoed from the run's bound `MetricSpec`. Written into BOTH the healthy and the degraded digest. `None` only on a cold start or a scoreless input — a NAMED absence, so a reader never has to guess whether the digest's numbers are higher- or lower-is-better. |
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
| `new_discoveries` | `list[VocabEntry]` | New `kind="discovery"` entries from this round's evaluation. Empirical findings expressed as sentences, added to `runtime_vocab`. **F-SCANE-3** — the `timing_{model}_slow` discovery calls its figure an *architectural* resource cost and recommends reducing the model, so when the record carries `timing.validation_time_s` it states the split (`train=X incl. validation V, training+overhead X−V`). **N-4** renamed the residual from `architecture`: `train_time_s` is the whole subprocess, so X−V also contains process start, CUDA init, dataset construction and checkpoint save. The rule and the rendering belong to `agent/prompt_templates/timing_attribution.py`, not to this module. A record with no split, or an incoherent one (validation > train, which production cannot produce), renders its pre-F-SCANE-3 bytes. |
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
.venv/bin/python src/nodes/result_interpretation_agent/result_interpretation_agent.py \
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

## Carried lifecycle (Step 10 / P5+P6)

Two values this node PRODUCES are now transported to the next iteration
and back into this node's own input, across a REAL process boundary.

| value | rule | authority |
|---|---|---|
| `vocab_link_confirmations` | **latest-wins on the WHOLE dict** — the newest digest that CARRIES the key wins; a digest missing the key is SKIPPED (not a reset); `{}` is a legitimate cleared state and DOES overwrite | `core.resume.project_vocab_link_confirmations` |
| `key_findings` | **chronological UNION** — non-empty `str` only, dedup by exact string, first occurrence wins, order preserved | `core.resume.union_key_findings` (the ONE authority; the workflow's loop closure and `project_knowledge` both CALL it) |

**A malformed confirmations value RAISES** (frozen Q-P5-1) rather than
projecting `{}`: a mapping that is not `dict[str, list[str]]` is a
corrupted lifecycle, and silently substituting an empty mapping would
restart a promotion counter without saying so.

**Cold start carries through (DD-2).** The cold-start branch copies
`inp.vocab_link_confirmations` into its output rather than emitting `{}`.
For every pre-P5 caller the input IS `{}`, so the digest bytes are
unchanged; what it prevents is a cold-start iteration in a RESUMED chain
silently discarding a mapping the restore just handed it.

**Temporal reachability.** Under cold start this node's first invocation
has no prior output to interpret, so it produces no findings. Findings
ABOUT iteration *N*'s experiment are produced by iteration *N+1* and reach
a proposer at *N+2* — which is why the Step-10 Gate runs three iterations
(F-P56-4), not two.

## Health eligibility inputs (Step 10 / P5+P6 W6)

`evidence.tuning_output_to_model_run_summary` and `_round_health` take a
keyword-only `required_gate_ids: frozenset[str] | None`. It is an
ALREADY-RESOLVED value, resolved ONCE at the composition edge by
`execute_tools.health_checks.candidate_eligibility.resolve_run_scientific_gate_ids`
and threaded in. This node never re-loads a Health config and never learns
which task it is looking at. `None` preserves pre-W6 behaviour (the legacy
default set).

## Dependencies

- **LLM**: up to three call sites per run, all via `LLMBridge.generate()` (returns a parsed dict; validated with `model_validate`):
  - **Phase 1 — per-model summarization** — one call per model in `summaries` that is NOT already in `model_knowledge_cache`. System prompt: `PER_MODEL_SYSTEM_PROMPT` (in `agent/prompt_templates/interpretation/rendering.py` since Step 09b C1).
  - **Phase 2 — cross-model synthesis** — exactly one call per run. System prompt: `SYNTHESIS_SYSTEM_PROMPT` (in `agent/prompt_templates/interpretation/rendering.py` since Step 09b C1).
  - **Phase 3 — vocab dedup** — one call when there are new candidate vocab entries that need consolidation against existing canonicals. System prompt: `DEDUP_SYSTEM_PROMPT` (in `agent/prompt_templates/interpretation/rendering.py` since Step 09b C1). Skipped (no LLM call) when no new candidates exist.
- **GPU**: not required.
- **External services**: none directly. Depends on the upstream tuning agent's experiment records (already on disk in `{workspace}/run_output_{run_name}.json`) and on `ml_models/{model_type}/description.md` for any model_type not carrying an inline description in its `ModelRunSummary`.

## Scientific aggregation (V20 PR D, D-C5)

`ModelRunSummary.scientific_authority` carries the verdict of the FORMAL record its `formal_score` came from, so the score and its authority cannot describe different experiments. Before any LLM call, `ordering.precompute_evidence()` partitions the evidence via `execute_tools.scientific_aggregation.partition_for_aggregation()` and filters `per_model_formal` to authoritative results only — a non-authoritative formal score therefore never reaches the synthesis prompt and cannot inform a scientific claim. The ordering is not merely conventional: `run()` calls the boundary before Phase 1, and Phase 1 consumes the summary index the same call returns.

**The partition ranges over `summaries` AND the cached-only models (N-2).** `per_model_formal` is filled from both, so partitioning only `summaries` left every cached model outside both halves of the verdict: its formal score was dropped by the authority filter and no exclusion reason existed to report it. In a chain subprocess that is the normal case — after the first iteration `model_exploration.run_workflow` passes exactly ONE new summary and carries every other model in `model_knowledge_cache`. A cached model is presented to the partition through the same structural protocol a fresh summary satisfies (`model_type` + `scientific_authority`), never through a second rule.

Nothing is deleted. The excluded results are retained in `InterpretationOutput.scientific_aggregation` (`included` / `excluded` / `excluded_count` / `all_excluded` / `no_records` / `exclusion_reason_counts`), written at BOTH the healthy and the degraded assembly so an interpreter LLM failure cannot lose the provenance. Render it with `AggregationScope.provenance_lines(scope=…)`.

The exclusion is derived and rendered **deterministically, never by the model** (design §4.7): a model may simply omit it, and exclusion text placed inside a prompt can steer the interpretation it then writes. `all_excluded` is explicit because an empty aggregate alone reads identically to a campaign that found nothing — the opposite conclusion.

**The `_stats` cache carries the verdict beside the score it judges (N-2).** Phase 1 writes `scientific_authority` into `_stats` alongside `formal_score`. Caching the number without its verdict made a model's authority expire the moment it went quiet: it could not be checked next iteration, so the score was dropped with nothing to report. A `_stats` block written before this — a resumed pre-N-2 workspace — carries no verdict, resolves to `unreconstructable_legacy` and is excluded fail-closed, which is the frozen rule for anything missing the authority contract.

**A conclusion may not out-scope its partition (N-3).** `provenance_lines()` takes a keyword-only `scope`, defaulting to `"this aggregation"` — the object's own reach, and therefore always true. `run()` passes `scope=f"iteration {inp.iteration}"`, so the all-excluded line reads *"EVERY result was excluded — no scientifically authoritative result is available in iteration N."* It previously concluded *"this campaign produced no scientifically authoritative result"* from one iteration's evidence, printed once per iteration, including in campaigns whose other iterations produced authoritative results. The `scope` word governs only that sentence; a partition that excluded nothing renders byte-identically with or without it.

### F-SCANE-1 — the exclusion is told, and it does not delete a warning

Two repairs, both required by the frozen `F-SCANE-1` row.

**The conclusion reaches a human.** `run()` prints
`AggregationScope.provenance_lines()` to stdout — one `    [scientific
aggregation] …` line each — immediately after `precompute_evidence()` and
therefore **before any LLM call**, so an interpreter failure cannot swallow it.
Until this call the renderer named directly above had ZERO production callers:
14 of 15 real digests concluded there was no authoritative result and nobody
was told. It is PRINTED and not prompted, because §4.7 keeps the exclusion
narrative deterministic and out of the model's reach. The sentence itself is
now iteration-scoped — see N-3 above; making it visible was the F-SCANE-1
repair, re-scoping it was the correction that repair needed.

**A withheld formal score is a NAMED ABSENCE in the synthesis prompt.** The
authority filter EMPTIES `per_model_formal` when every formal result is
non-authoritative, and the synthesis renderer gates its
`Formal score: …  (best_score above may be from a trial round)` caveat on that
dict being non-empty — so the run whose formal evidence was entirely unusable
was exactly the run that presented a trial-mixed best score with the warning
REMOVED. `precompute_evidence()` now captures
`per_model_formal_excluded` (`model_type` → typed exclusion reason) **BEFORE**
the filter runs and `_build_synthesis_prompt` renders, per affected model:

```text
Formal score: WITHHELD — this model's formal result was excluded from the
scientific aggregate (<reason>); the best_score above may be from a trial
round and is NOT a scientifically authoritative result.
```

Only models that HAD a formal score appear there: a model that never produced
one is an absence, not a withholding, and reporting it as withheld would be a
second fabrication. A fully authoritative run renders no such line and its
prompt bytes are unchanged.

**N-2 corrected the SET this ranged over.** As first shipped, the withheld
line could only be rendered for a model in `summaries` — the first-iteration
shape. Every later iteration hands the interpreter one new summary and N−1
cached models, so for N−1 of N models the formal score was still silently
deleted and the caveat still absent: the F-SCANE-1 defect, reproduced by the
F-SCANE-1 fix's own blind spot. The partition and the cache write above close
it, and the witness corpus in
`tests/unit/agent/result_interpretation_agent/test_fscane1_exclusion_is_told.py`
now covers the later-iteration shape as well as the first.

## Fail-closed metric contract (Step 09a)

The interpreter orders results. Ordering needs a DIRECTION, and "higher is
better" used to be assumed. Under a lower-is-better metric that assumption does
not error — it inverts the ranking silently, and every downstream proposal is
built on the wrong model. So the contract refuses rather than defaults.

**Where the spec comes from.** The tuner resolves the run's `MetricSpec` ONCE
(`ml_hyperparameter_tune_agent.py`) and `finalize_run_output` stamps it on
`HyperparamTuningOutput.metric_spec`. The workflow reconciles the stamps across
every output feeding one interpretation (`reconcile_metric_spec`: all present
specs must be EQUAL — one run, one metric) and passes the result as
`InterpretationInput.metric_spec`. Step 09 adds **zero** new metric-derivation
sites; the node transports a value, it never constructs one.

**What is refused, at input construction — before ordering, active-model
selection, prediction evaluation, rendering or any LLM call:**

| condition | outcome |
|---|---|
| the input carries ANY score (a summary score field, a `round_scores` entry, or a cached `_stats` score) and `metric_spec` is `None` | `ValueError` naming the first score-bearing summary or cache entry |
| a summary's evidence-borne `metric_identity.metric_id` differs from the run spec's `id` | `ValueError` naming both |
| a summary's evidence-borne `metric_identity.direction` differs from the run spec's `direction` | `ValueError` naming both |
| the tuning outputs do not agree on one spec, or some carry one and others do not | `InterpretationContractError` naming every offending `run_name` / `model_type` |

**What stays legal.** A cold start and a genuinely scoreless input need no
ordering and are accepted with `metric_spec is None`, recorded as the named
absence `metric_identity: null` in the digest.

**Legacy consequence, intentional.** Tuning outputs written before Step 09a
carry no spec. A chain resumed ACROSS that boundary stops at its first
post-09a interpretation with the refusal above; the compatibility path is a
freshly produced output, never a re-derived metric.

**Two owners, never substituted for each other.** The run-bound `MetricSpec`
owns ORDERING and the run-level identity; a record's `metric_result` owns
EVIDENCE (what actually scored that record), projected onto
`ModelRunSummary.metric_identity`. They are checked AGAINST each other; a
mismatch is an error, not a preference.

## Ordering direction (Step 09a C3)

Every comparison of golden-metric values on this node's surface asks the run's
`MetricOrder`. None of them spells `>`, `<`, `max`, `min`, `reverse=True` or a
negated sort key on a score, and none reads the metric's NAME.

That is not a style rule. Under a lower-is-better metric — DAVIS's `mse` is a
declared pack metric today — a direction literal does not error, it inverts:
the best model is reported as the worst, the Top-K active set becomes the
bottom K, and the cache evicts the models it should keep.

| consumer | what the direction decides |
|---|---|
| `ordering.precompute_evidence` | per-model and overall best / best-valid / worst, from summaries AND from cached `_stats` |
| `evidence.tuning_output_to_model_run_summary` | best, best-valid, best-valid-formal records; the worst round score |
| `interpretation_helpers.select_active_models` | which models are Top-K, i.e. which get a per-model LLM call |
| `workflows._cap_knowledge_cache` | which models survive the cache cap |
| `_render_health_summary_section` | which round's recording diagnostics are the "best round's" |
| `interpretation_helpers.generate_discoveries` | the strictest SOTA, whether it was beaten, and the relative band |

Two rules the migration froze:

* **`order` is keyword-only with NO default** on `precompute_evidence` and on
  `tuning_output_to_model_run_summary`. A defaulted direction is exactly how
  "higher is better" became invisible. `None` is accepted only where nothing
  ranks; the first comparison that needs a direction raises
  `InterpretationContractError`.
* **The discovery band's margin stays 0.05.** C3 corrected its DIRECTION and
  its negative-reference arithmetic — `abs(best - sota) <= 0.05 * abs(sota)`
  instead of scaling the reference — and did not retune its width. Scaling a
  NEGATIVE reference by `(1 - margin)` moves it toward zero, so the old
  "within 5% of SOTA" arm was unreachable for every TIDMAD score and a
  competitive model was always reported as "significantly below SOTA".

Enforced by an AST census over the node package, `interpretation_helpers.py`
and `_cap_knowledge_cache`, with planted-offender proofs; and by the Step-06
C5 `MIGRATED_TO_THE_ORDER_AUTHORITY` list, which pins each migrated literal as
ABSENT rather than deleting the row.

## Prediction semantics (Step 09a C4)

The previous iteration's `FalsifiablePrediction` is evaluated against the SOTA
it was written against — not against its own predicted value, because
predicting exact scores is unreliable and the meaningful question is whether
the architecture cleared the bar it was designed to beat.

**The frozen band.** No task branch, no value-sign branch:

```text
distance   = abs(actual - sota)
band_width = partial_margin * abs(sota)          # partial_margin = 0.05

actual or sota unavailable      -> unevaluated   (counted in NO pool)
order.is_better(actual, sota)   -> confirmed     (information_gain = distance)
distance <= band_width          -> partial       (gain 0)
otherwise                       -> refuted       (gain 0)
```

Equality is `partial` and the band edge is inclusive.

**`unevaluated` is not a fourth verdict.** It is the absence of an
observation. It is recorded on the individual evaluation, counted in neither
pool, and never published as a discovery. Before Step 09a an uncomputable
metric was labelled `partial`, which put a non-observation into the accuracy
statistic and published a finding reading "achieved metric=N/A".

**The metric grammar is bound, not task-named.** A prediction that omits
`metric` resolves to the RUN's metric id — `denoising_score` was one task's
name hardcoded as the framework's default. The frozen legacy alias table is
accepted READ-ONLY so a chain crossing the Step-09a boundary can still
evaluate its previous proposal, and every evaluation records HOW its metric
resolved: `bound_id`, `legacy_alias`, `per_sample_slice`, `per_sample_index`,
`per_sample_unavailable` (a scalar-only task, which Pets and DAVIS both are)
or `unrecognized`. The alias table is never grown for a new task.

**Counts are version-partitioned, and the digest says so.** Outcomes from the
corrected rule are not comparable with outcomes from the old one, so they are
never pooled:

| field | meaning |
|---|---|
| `prediction_outcomes_history` | the LEGACY v1 pool — carried forward unchanged, never incremented by Step 09a |
| `prediction_outcomes_by_semantics["metric_order_signsafe_v2"]` | the v2 counts; the only pool this node increments |
| `scientific_accuracy` | fractions over the v2 pool ALONE (`None` while it is empty) |
| `prediction_evaluation_semantics` | which semantics produced that accuracy |
| `cumulative_information_gain` | the LEGACY accumulated scalar, preserved and never added to |
| `cumulative_information_gain_by_semantics["metric_order_signsafe_v2"]` | the v2 running sum |
| `prediction_pool_sizes` | both pools' sizes, so a version-pure statistic cannot be mistaken for one over every prediction on record |

Old persisted digests are NEVER rewritten: a digest with no
`prediction_evaluation_semantics` key reads as `legacy_v1`, which is what
actually produced it.

**Downstream honesty.** Step 09a changes no proposer prompt template. The
proposer's existing "Prediction Track Record" renderer reads
`scientific_accuracy` (now v2-only), `cumulative_information_gain` (legacy)
and `prediction_outcomes_history` (legacy — its sum is the rendered `N`), so
next-iteration prompt CONTENT does change deterministically, and the rendered
`N` comes from the legacy pool while the fractions come from the v2 pool.
That is a declared consequence of the per-field rule, not an oversight.

## Evidence projection (Step 09a C6)

Before Step 09a the summary builder read NONE of `metric_result`,
`metric_refusal`, `training_history` or `training_diagnosis`. The interpreter
could see that a score existed but nothing about how the training that
produced it behaved, and could not name a not-scoreable round as a failure at
all. Step 07a computes the diagnosis and Step 06 computes the identity and the
refusal — both stopped at the tuner's records.

| field | source | note |
|---|---|---|
| `ModelRunSummary.best_training_diagnosis` | the BEST record's `training_diagnosis`, verbatim | one per ROLE: a best trial round and the formal round are different experiments |
| `ModelRunSummary.formal_training_diagnosis` | the FORMAL record's, verbatim | the interpreter never re-derives a diagnosis (parent §7) |
| `ModelRunSummary.failure_counts` | `RecordFailureCounts` over the model's records | counted by EXISTING vocabularies only |
| `ModelRunSummary.secondary_metrics` | the run's DECLARED secondaries (the output's `secondary_metric_specs` stamp) joined against the BEST record's carriers | live since Step 10 / P2b (see below) |
| `InterpretationOutput.per_model_failure_counts` | the above, per model | threaded into BOTH digest paths |
| `InterpretationOutput.per_model_secondary_metrics` | the above, per model | fresh from the summaries, plus a `_stats` restore for models that go quiet |
| `_stats["failure_counts"]` | the cache | so a model that goes quiet keeps its counts, exactly as `round_health_counts` does |
| `_stats["secondary_metrics"]` | the cache | Step 10 / P2b — the SAME write, for the same reason (audit B-6). Written only when there IS evidence: a run that declared no secondary creates no key at all |

**No new failure taxonomy.** `RecordFailureCounts` counts `status`,
`TrainingDiagnosis.state`, `ValidationState`, `NotScoreableResult`'s OPAQUE
contract id, `gate_action` and `RoundHealth.provenance` — every key owned by
an authority that already exists. They are open dicts, not enums, so a fourth
task's novel pathology is expressed at its owning layer and rendered here
without a SIDERIUS source change. `diagnosis_missing` is counted separately
from `absent`: "no diagnosis object" and "the diagnosis says the history was
absent" are different facts about different records.

**Secondary metrics are observational, and live since Step 10 / P2b.**
Q-09-7 = B gave Step 09 the interpreter-side CONTRACT and Step 10 the upstream
half — tuner-side evaluation, `ExperimentRecord` persistence, transport. P2b
landed it, so the builder now PROJECTS rather than leaving the collection
empty.

The projection is `_project_secondary_metrics(output, best_rec)`: the DECLARED
set comes from the output's `secondary_metric_specs` stamp, and the outcomes
from the record the summary's headline `best_denoising_score` came from — so a
secondary number always describes the same experiment as the score beside it.
Four states result:

| record state, under a stamp | projects |
|---|---|
| a matching `secondary_metric_results` entry | `scored` |
| a matching `secondary_metric_refusals` entry | `refused` |
| neither | `unavailable` — a NAMED absence |
| the secondary CRASHED (`secondary_metric_errors`) | `unavailable`; the diagnostic stays on the record and never becomes a fourth scientific state |

An output with **no stamp** — a legacy output, or a run of a task that
declares none — projects `[]` and therefore renders zero bytes, even when its
records carry secondary evidence. Reading the record anyway would resurrect
the hidden contract Q-09-7 = B forbade, and it is what keeps TIDMAD's prompt
bytes unchanged.

`SecondaryMetricEvidence` still distinguishes exactly `scored`, `refused` and
`unavailable`. Each carries its OWN direction — DAVIS declares `psnr` (higher)
and `mae` (lower) beside a `mse` primary that is lower-is-better, and each is
rendered with its own direction words.

**The quiet-iteration carry (audit B-6, closed by P2b).** Before P2b,
`per_model_secondary_metrics` was built from the summaries only, with no
`_stats` restore — so the Stability-Filter reuse path (a model that goes quiet
for an iteration and gets no fresh LLM call) was precisely the path that lost
the evidence, while `failure_counts` beside it survived. Both now ride the
same mechanism: typed `model_dump` on write, VALIDATED read-back on the reuse
path. A cache predating the key contributes absence, never zero; a corrupt
payload degrades to absence with a printed warning rather than crashing the
interpretation.

Secondaries can never reach a ranking. Enforced structurally (an AST census:
no secondary may be an operand of a comparison, an argument to a `MetricOrder`
method, or a sort key — with planted offenders for all three shapes) and
behaviourally (flipping every secondary value leaves every ordering output
identical).
