# agent/schemas/interpretation.py
"""
Input and output schemas for result_interpretation_agent.

This node consumes run-level summaries (one per model) and produces a structured
interpretation — key findings, bottlenecks, and a take-home message — for
consumption by ml_model_proposal_agent.

InterpretationInput accepts:
  - summaries: a list of ModelRunSummary objects (one per model)
  - model_types: an explicit list of model types whose descriptions to include
  - Either summaries or model_types must be non-empty (or both)

ModelRunSummary is a condensed view of a HyperparamTuningOutput — it contains
the run-level aggregates (best/worst score, best config, status) and a condensed
per-round trajectory (scores + conclusions), but NOT the raw experiment records.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from agent.schemas.health_feedback import (
    CollapseFingerprint,
    CollapseFingerprintHistoryEntry,
    HealthFeedbackRetentionPolicy,
    RoundHealth,
)
from agent.schemas.hyperparam_tuning import ExpertAdviceInput
from agent.schemas.proposal import VocabEntry
from agent.schemas.score_table import ScoreComparisonTable
from agent.schemas.storage import LocalStorageConfig, StorageConfig


class RoundOrdering(BaseModel):
    """What data ordering one round actually ran, and where it came from.

    Interpreter-facing view of the ordering provenance
    (``docs/design/v19_priorities/pr2_data_ordering.md`` §3.7). Two rules
    govern how downstream reasoning may use it:

    - ``resolved_*`` is the ONLY pair that describes execution. A proposal
      the operator overrode was not what ran, and must never be reported as
      though it were.
    - a REJECTED proposal is not the same as no proposal. The agent tried to
      steer this round and was overruled by validation; reading that as
      agent silence would misdescribe its behavior.

    Ordering can differ between rounds of one iteration (the agent may
    propose differently each round when no override is set), so these are
    carried per round rather than collapsed to one value for the run.
    """

    exp_id: str | None = Field(
        default=None,
        description="Experiment this ordering belongs to. None on legacy records.",
    )
    resolved_order_strategy: str | None = Field(
        default=None,
        description=(
            "The visitation order that ACTUALLY RAN for this round. None when "
            "nothing ran — i.e. resolution_source is 'not_executed', an "
            "attempt rejected at pre-flight. Downstream must not describe a "
            "None as having executed any ordering."
        ),
    )
    resolved_file_order: list[int] | None = Field(
        default=None,
        description="File order that actually ran; None when the strategy was 'shuffle'.",
    )
    resolution_source: str = Field(
        description=(
            "Which level decided it: 'operator_override', 'agent_proposal', "
            "or 'default' when an ordering actually ran; 'legacy_default' for "
            "a pre-ordering artifact; 'not_executed' for a current attempt "
            "rejected at pre-flight, where no ordering ran at all."
        ),
    )
    proposed_order_strategy: str | None = Field(
        default=None,
        description="What the agent proposed, rejected or not. None = it proposed nothing.",
    )
    proposal_rejected: bool = Field(
        default=False,
        description="True when a proposal arrived but was not applied.",
    )
    proposal_rejection_reason: str | None = Field(
        default=None,
        description="Why the proposal was not applied. None unless rejected.",
    )


class ModelRunSummary(BaseModel):
    """
    Condensed summary of one tuning run for one model type.

    Built from HyperparamTuningOutput by extracting aggregates and condensing
    per-round information. The raw experiment records are NOT included — only
    the score trajectory and one-line conclusions from each round.
    """

    model_type: str = Field(
        description="Architecture key (e.g. 'punet', 'fcnet').",
    )
    run_name: str = Field(
        description="Run identifier (e.g. 'v3_file6').",
    )
    status: str = Field(
        description="Run status: 'completed', 'partial', or 'failed'.",
    )
    completed_rounds: int = Field(
        description="Number of successfully completed experiment rounds.",
    )
    best_denoising_score: float | None = Field(
        default=None,
        description="Highest raw denoising score achieved in this run.",
    )
    best_valid_denoising_score: float | None = Field(
        default=None,
        description="Highest HealthGate-valid denoising score; None when none is valid.",
    )
    best_raw_health_validity: str = Field(
        default="unknown",
        description="Health validity of the raw-best record: valid, invalid, or unknown.",
    )
    worst_denoising_score: float | None = Field(
        default=None,
        description="Lowest denoising score achieved in this run (excluding OOM-skipped).",
    )
    best_config: dict[str, Any] | None = Field(
        default=None,
        description="The params dict (model_config, train_config, loss_config) "
        "that produced the best denoising score.",
    )
    best_valid_config: dict[str, Any] | None = Field(
        default=None,
        description="Config that produced the highest HealthGate-valid score.",
    )
    round_scores: list[float | None] = Field(
        default_factory=list,
        description="Denoising score per round in chronological order. "
        "None entries indicate OOM-skipped or failed rounds.",
    )
    round_conclusions: list[str] = Field(
        default_factory=list,
        description="One-line conclusion from each round's LLM reflection. "
        "Extracted from the 'memory.conclusion' field of each record.",
    )
    round_ordering: list[RoundOrdering] = Field(
        default_factory=list,
        description="Data ordering that actually ran, per round, in the same "
        "chronological order as round_scores. Kept per round because ordering "
        "may legitimately differ between rounds when no operator override is "
        "in force. Empty on runs that predate the ordering option.",
    )
    round_health: list[RoundHealth] = Field(
        default_factory=list,
        description="Condensed HealthGate evidence per round, in the same "
        "chronological order as round_scores (V19 PR 3, "
        "docs/design/v19_priorities/pr3_healthgate_feedback.md §3.2). Built "
        "deterministically from each record's persisted gate fields under "
        "the evidence-precedence rule — never from LLM prose. Provenance "
        "labels the evidence source (gated / gates_disabled / "
        "round_fields_only / gate_not_evaluated / legacy); a round without "
        "evidence is carried labeled, never guessed at. Empty on summaries "
        "built before this field existed.",
    )
    model_description: str | None = Field(
        default=None,
        description="Architecture description (markdown + math). For built-in models "
        "this is loaded from description.md by the interpretation agent. "
        "For agent-generated models, the workflow passes it directly so "
        "the interpretation agent doesn't need filesystem access.",
    )

    # --- Per-file performance (from file_vector) ---
    best_file_vector: list[float | None] | None = Field(
        default=None,
        description="Score vector from the best experiment, one entry per validation "
        "file. None for files not evaluated. Per-file semantics are defined "
        "by the dataset configuration; the agent reads opportunity from the "
        "Impact_Score column rather than fixed file-index labels.",
    )
    formal_score: float | None = Field(
        default=None,
        description="Denoising score from the formal (final) round specifically. "
        "Distinct from best_denoising_score which may come from a trial round.",
    )
    best_valid_formal_score: float | None = Field(
        default=None,
        description="Highest HealthGate-valid formal score; None when none is valid.",
    )
    scientific_authority: dict[str, Any] | None = Field(
        default=None,
        description=(
            "V20 PR D (D-C5) — the authority verdict of the FORMAL record "
            "this summary's `formal_score` came from "
            "(core.scientific_authority.ScientificAuthority.model_dump()). "
            "Decides whether this model's formal result may inform a "
            "scientific aggregate; `execute_tools.scientific_aggregation` "
            "consumes it. None on a summary with no formal record, and on "
            "summaries predating the field — both of which are EXCLUDED "
            "from aggregation, because authority that cannot be established "
            "is not authority. HealthGate validity is a different question: "
            "a diagnostic run's formal record can be perfectly valid and "
            "still carry no scientific authority."
        ),
    )
    formal_file_vector: list[float | None] | None = Field(
        default=None,
        description="File vector from the formal round. Definitive per-file performance.",
    )

    # --- Enriched per-file tables (file_vector + baseline + ground truth) ---
    best_score_table: ScoreComparisonTable | None = Field(
        default=None,
        description="ScoreComparisonTable for the best experiment — the enriched "
        "view of best_file_vector alongside raw_baseline and "
        "ground_truth columns with pre-rendered markdown. "
        "Downstream agents prefer this over best_file_vector.",
    )
    best_valid_score_table: ScoreComparisonTable | None = Field(
        default=None,
        description="Score table for the highest HealthGate-valid experiment.",
    )
    formal_score_table: ScoreComparisonTable | None = Field(
        default=None,
        description="ScoreComparisonTable for the formal (final) round. "
        "Definitive enriched per-file view without the trial-subset caveat.",
    )

    # --- Model efficiency ---
    best_model_params: int | None = Field(
        default=None,
        description="Number of trainable parameters in the best-scoring model.",
    )

    # --- Compute cost ---
    best_timing: dict[str, Any] | None = Field(
        default=None,
        description="Timing dict from the best experiment: "
        "train_time_s, inference_time_s, scoring_time_s. "
        "Used to generate timing discoveries and warn the planner.",
    )

    # --- Data volume context ---
    training_psd_segments: int | None = Field(
        default=None,
        description="PSD segments used for training in the best experiment. "
        "Compare against baseline (typically 4000) to assess data sufficiency.",
    )
    eval_psd_segments: int | None = Field(
        default=None,
        description="PSD segments used for evaluation in the best experiment.",
    )
    trial_portion: float | None = Field(
        default=None,
        description="Trial portion used in the best experiment (if trial mode).",
    )

    # --- Per-round detail (for trend analysis) ---
    round_trial_portions: list[float | None] | None = Field(
        default=None,
        description="Trial portion used in each round. Shows if the agent adapted data volume.",
    )
    round_model_params: list[int | None] | None = Field(
        default=None,
        description="Model parameter count per round. Shows if the agent explored model sizes.",
    )


class InterpretationInput(BaseModel):
    """
    Input to result_interpretation_agent.

    Accepts run-level summaries from one or more models. Each summary is a
    condensed view of a tuning run — NOT the raw experiment records.

    Constraint: at least one model type must be reachable — either derived from
    summaries or listed explicitly in model_types.
    """

    summaries: list[ModelRunSummary] = Field(
        default_factory=list,
        description="Condensed summaries for NEW models only — models being interpreted "
        "for the first time this iteration. Models already in model_knowledge_cache "
        "do not need a summary here; Phase 1 will use the cache instead. "
        "On the first iteration, pass all seed model summaries (cache is empty).",
    )
    model_knowledge_cache: dict[str, Any] = Field(
        default_factory=dict,
        description="Carry-forward cache from the previous InterpretationOutput.model_knowledge_cache. "
        "Each entry is self-sufficient: Phase 1 LLM text + '_stats' with numerical facts. "
        "Agent skips Phase 1 LLM calls for models present here. "
        "Empty on the first iteration.",
    )
    model_types: list[str] | None = Field(
        default=None,
        description="Explicit list of model types whose descriptions to include. "
        "When None, model types are derived from summaries. "
        "Cannot be an empty list — use None to derive from summaries.",
    )
    cold_start: bool = Field(
        default=False,
        description="Explicit cold-start state. True means this is the first "
        "iteration of a chain with NO prior experimental evidence (no seeds, no "
        "committed prior iters, empty cache). Set by the workflow — never inferred "
        "downstream from missing prompt text. When True, require_at_least_one_model "
        "permits an empty model set and the interpreter renders explicit 'no prior "
        "evidence' language instead of ranking non-existent history. Registries "
        "remain available options, not historical runs.",
    )
    task_description: str = Field(
        default="",
        description="Plain-English description of the research task, sourced from "
        "``configs/task_config.yaml``. Injected into the ``{TASK_DESCRIPTION}`` "
        "placeholder in both ``PER_MODEL_SYSTEM_PROMPT`` and "
        "``SYNTHESIS_SYSTEM_PROMPT`` at call time. Default empty string is for "
        "test fixtures only; production callers (workflow) always populate via "
        "``get_task_description(load_task_config())`` which rejects empty values "
        "upstream. The interpreter only needs the description (not the full "
        "forward contract) — its job is reading run summaries and synthesizing "
        "findings, not designing models.",
    )
    expert_advice: ExpertAdviceInput = Field(
        default="",
        description="Structured guidance from upstream agents or orchestrators. "
        "Accepts a plain string or a structured ExpertAdvice object.",
    )
    human_advice: str | None = Field(
        default=None,
        description="Optional human-provided guidance (highest priority — overrides expert_advice). "
        "When present, injected into the LLM prompt as high-priority context.",
    )
    # --- Vocabulary feedback (Phase C) ---
    runtime_vocab: list[VocabEntry] = Field(
        default_factory=list,
        description="Current vocabulary (seed + candidates + discoveries) from "
        "previous iterations. Empty on first iteration (uses seed). "
        "This IS the compressed memory of iterations 0..N-2.",
    )
    previous_proposal: dict[str, Any] | None = Field(
        default=None,
        description="Serialized ProposalOutput from the previous iteration. "
        "Contains falsifiable_prediction, proposed_vocab_links, "
        "inherited_components. None on the first iteration.",
    )

    # --- Centrifugal metrics (carried forward across iterations) ---
    cumulative_information_gain: float = Field(
        default=0.0,
        description="Sum of information_gain from all previous iterations. "
        "Carries forward the history of how many bold predictions were confirmed. "
        "Populated by the previous InterpretationOutput.cumulative_information_gain "
        "via the workflow's carry-forward logic. Zero on the first iteration.",
    )

    # --- Scientific accuracy (carried forward across iterations) ---
    prediction_outcomes_history: dict[str, int] = Field(
        default_factory=lambda: {"confirmed": 0, "partial": 0, "refuted": 0},
        description="Running count of each prediction outcome across all past iterations. "
        "Carry forward from InterpretationOutput.prediction_outcomes_history. "
        "Zero on first iteration.",
    )

    # --- Vocab link promotion tracking (carried forward across iterations) ---
    vocab_link_confirmations: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Carry-forward mapping: 'feature:capability' → list of run_names "
        "where that link was confirmed. Populated by "
        "InterpretationOutput.vocab_link_confirmations. Empty on first iteration.",
    )

    # --- Structured HealthGate feedback (V19 PR 3 —
    #     docs/design/v19_priorities/pr3_healthgate_feedback.md §3.6/§3.8/§3.9) ---
    enable_structured_health_feedback: bool = Field(
        default=False,
        description="Gates the PROMPT rendering of structured HealthGate "
        "evidence (§3.6 trajectory labels, HealthGate summary section, "
        "system-prompt instruction block). OFF (default): prompts are "
        "byte-identical to the pre-PR3 condition. The OUTPUT fields below "
        "are populated deterministically REGARDLESS of this flag "
        "(recording-only provenance). Part of the run-invariants lock — "
        "flipping it mid-workspace is rejected at startup.",
    )
    collapse_fingerprint_history: dict[str, list[CollapseFingerprintHistoryEntry]] = Field(
        default_factory=dict,
        description="Carry-forward from the previous "
        "InterpretationOutput.collapse_fingerprint_history: model_type → "
        "bounded per-iteration occurrence history of collapse fingerprints. "
        "Deterministic data — never LLM-derived. Empty on the first "
        "iteration and on legacy digests without the field.",
    )
    health_feedback_history_window_iterations: int = Field(
        default=3,
        ge=1,
        description="Retention window for the fingerprint history: the TOTAL "
        "number of iterations retained INCLUDING the current one "
        "(minimum_retained_iter = current_iter - window + 1). Part of the "
        "run-invariants lock. Follows the active_model_* typed-knob "
        "convention; consumed as a resolved HealthFeedbackRetentionPolicy, "
        "never as a module constant.",
    )
    health_feedback_history_max_entries_per_model: int = Field(
        default=8,
        ge=1,
        description="Deterministic trim bound on retained fingerprint history "
        "entries per model. Part of the run-invariants lock.",
    )

    def health_feedback_retention_policy(self) -> HealthFeedbackRetentionPolicy:
        """The RESOLVED retention policy (design §3.8) — the single object
        renderers and the history merge consume."""
        return HealthFeedbackRetentionPolicy(
            history_window_iterations=self.health_feedback_history_window_iterations,
            max_entries_per_model=self.health_feedback_history_max_entries_per_model,
        )

    storage: StorageConfig = Field(
        default_factory=lambda: StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace="./siderius_workspace", run_name="v1"),
        ),
        description="Where this node reads its inputs and writes its interpretation output.",
    )

    # --- Iteration index (V8 Domain 3 — evolution observability) ---
    iteration: int = Field(
        default=1,
        ge=1,
        description="1-based iteration index within the current chain or workflow "
        "run. Stamped into the per-iter row appended to "
        "{workspace}/evolution_log.jsonl by the interpretation agent. "
        "Populated by the workflow (model_exploration.run_workflow) "
        "from its loop variable. Defaults to 1 for ad-hoc / single-iter "
        "callers. See docs/V8_Gap_Report.md Domain 3.",
    )

    # --- Active-Model policy (Commit 6.1 — Stability Filter + Synthesis Window) ---
    # K/N/Δ thresholds shared by select_active_models() and should_recall_per_model()
    # in nodes/interpretation_helpers.py. The active model_types are the union of:
    #   Top-K by best_denoising_score ∪ Last-N by recency ∪ models with |Δ| ≥ threshold
    # Stable (non-active) models are pulled from the cache verbatim — no fresh LLM call.
    active_model_top_k: int = Field(
        default=3,
        ge=0,
        description="Top-K cap by best_denoising_score for the active-model set. "
        "These models keep their full per_model summary expanded in "
        "the synthesis prompt and are eligible for fresh per_model "
        "LLM re-calls. Set to 0 to disable the Top-K pathway.",
    )
    active_model_last_n: int = Field(
        default=2,
        ge=0,
        description="Last-N cap by recency for the active-model set. The N model_types "
        "from the current iter's `summaries` list (taken in the order "
        "supplied) are unconditionally active. Set to 0 to disable the "
        "Last-N pathway.",
    )
    active_model_score_delta: float = Field(
        default=0.05,
        ge=0.0,
        description="Absolute score-delta threshold (in normalized denoising-score "
        "units) at or above which a model with both a prior cache entry "
        "and a current-iter summary is considered active. Also used by "
        "should_recall_per_model() to decide whether new evidence "
        "warrants a fresh per_model LLM call. Set to 0.0 to make any "
        "non-zero score change trigger activation.",
    )

    @model_validator(mode="after")
    def require_at_least_one_model(self) -> InterpretationInput:
        if self.model_types is not None and len(self.model_types) == 0:
            raise ValueError(
                "model_types cannot be an empty list. "
                "Use None to derive model types from summaries."
            )
        derived = {s.model_type for s in self.summaries}
        effective = derived | set(self.model_types or []) | set(self.model_knowledge_cache.keys())
        if not effective and not self.cold_start:
            raise ValueError(
                "At least one model type must be provided — "
                "via summaries, model_types, or model_knowledge_cache. "
                "(Set cold_start=True to intentionally start a chain with no "
                "prior experimental evidence.)"
            )
        return self


class InterpretationOutput(BaseModel):
    """
    Output of result_interpretation_agent.

    Covers all model types provided in the input. Per-model scores give
    the full performance picture; overall best/worst give the global range.
    Consumed by ml_model_proposal_agent via interpretation_to_proposal_v1.
    """

    # --- Models covered ---
    model_types: list[str] = Field(
        description="All model types analysed (union of summaries and explicit model_types).",
    )
    model_descriptions: dict[str, str] = Field(
        description="model_type → full markdown description loaded from description.md. "
        "Carries architecture knowledge forward to the proposal agent.",
    )

    # --- Experiment counts ---
    total_experiments: int = Field(
        description="Total completed rounds across all summaries.",
    )

    # --- Cold-start state ---
    cold_start: bool = Field(
        default=False,
        description="True when this interpretation was produced for a cold-start "
        "iteration (no prior experimental evidence). Propagated to the proposer so "
        "its prompt states there is no history and treats registries as available "
        "options, not completed runs. False for all history-backed iterations.",
    )

    # --- Per-model scores ---
    per_model_best: dict[str, float | None] = Field(
        default_factory=dict,
        description="model_type → best denoising score. "
        "None if the model has no successful experiments.",
    )
    per_model_best_valid: dict[str, float | None] = Field(
        default_factory=dict,
        description="model_type → highest HealthGate-valid score; None when unavailable.",
    )
    per_model_raw_best_health_validity: dict[str, str] = Field(
        default_factory=dict,
        description="model_type → validity label for its raw-best record.",
    )
    per_model_worst: dict[str, float | None] = Field(
        default_factory=dict,
        description="model_type → worst denoising score. "
        "None if the model has no successful experiments.",
    )
    scientific_aggregation: dict[str, Any] | None = Field(
        default=None,
        description=(
            "V20 PR D (D-C5) — which formal results informed the scientific "
            "aggregate and which were excluded, as an "
            "execute_tools.scientific_aggregation.AggregationScope dump: "
            "included / excluded / included_count / excluded_count / "
            "all_excluded / no_records / exclusion_reason_counts. Derived "
            "DETERMINISTICALLY before any LLM call and never written by a "
            "model (§4.7): a model may simply omit the exclusion, and "
            "exclusion text placed inside a prompt can steer the "
            "interpretation it then writes. Excluded results are retained "
            "here as evidence — nothing is deleted. `all_excluded` is "
            "explicit because an empty aggregate alone is ambiguous: it "
            "reads identically to a campaign that found nothing, which is "
            "the opposite conclusion. Render with "
            "AggregationScope.provenance_lines()."
        ),
    )

    # --- Overall best ---
    best_denoising_score: float | None = Field(
        default=None,
        description="Highest raw denoising score observed across all models.",
    )
    best_valid_denoising_score: float | None = Field(
        default=None,
        description="Highest HealthGate-valid score observed across all models.",
    )
    worst_denoising_score: float | None = Field(
        default=None,
        description="Lowest denoising score observed across all models.",
    )
    best_config: dict[str, Any] | None = Field(
        default=None,
        description="The params dict that produced the overall raw-best score.",
    )
    best_valid_config: dict[str, Any] | None = Field(
        default=None,
        description="The params dict that produced the overall best valid score.",
    )

    # --- Per-model knowledge cache (from Phase 1) ---
    model_knowledge_cache: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="model_type → self-sufficient cache entry produced by Phase 1. "
        "Each entry contains: Phase 1 LLM text (key_findings, bottlenecks, "
        "best_config_analysis, score_trend, per_file_analysis, data_sensitivity, "
        "efficiency_assessment, strategy_assessment) plus a '_stats' sub-dict "
        "(best_denoising_score, worst_denoising_score, best_file_vector, "
        "best_model_params, completed_rounds). Carry this forward as "
        "InterpretationInput.model_knowledge_cache in the next iteration — "
        "the agent skips Phase 1 LLM calls for models already in the cache.",
    )

    # --- LLM-generated analysis (from Phase 2) ---
    key_findings: list[str] = Field(
        description="Concrete, ranked observations extracted from the run summaries.",
    )
    bottlenecks: list[str] = Field(
        description="Root causes currently limiting further improvement.",
    )
    take_home_message: str = Field(
        description="Single critical insight that directly motivates proposing a new architecture.",
    )

    # --- Per-file analysis (from score_table) ---
    per_model_score_tables: dict[str, ScoreComparisonTable] | None = Field(
        default=None,
        description="model_type → best ScoreComparisonTable. Strict superset of the "
        "old per_model_file_vectors (every rows[i].model equals the old "
        "fv[i]) plus raw_baseline, ground_truth, gain_vs_raw, "
        "headroom_vs_gt, linear_weight, and impact_score columns plus "
        "pre-rendered markdown. The Impact_Score column is the canonical "
        "per-file opportunity ranking — downstream consumers read levers "
        "from the table directly rather than relying on a separate "
        "threshold-derived index list.",
    )

    # --- Efficiency context ---
    per_model_params: dict[str, int] | None = Field(
        default=None,
        description="model_type → parameter count of best model.",
    )

    # --- Data volume context ---
    per_model_training_segments: dict[str, int] | None = Field(
        default=None,
        description="model_type → training PSD segments used in best experiment.",
    )

    # --- Vocabulary feedback (Phase C) ---
    runtime_vocab: list[VocabEntry] = Field(
        default_factory=list,
        description="Updated vocabulary: seed + candidates + discoveries from all "
        "iterations including this one. This is the compressed memory "
        "that the next iteration's proposal agent receives. "
        "Empty in legacy mode (no vocabulary).",
    )
    prediction_evaluation: dict[str, Any] | None = Field(
        default=None,
        description="Evaluation of the previous proposal's FalsifiablePrediction. "
        "Outcome is SOTA-based (not predicted-value-based): "
        "confirmed = beat SOTA, partial = within 5%% of SOTA, refuted = clearly below. "
        "Contains: metric, predicted_value, actual_value, current_sota, "
        "delta_from_sota, outcome ('confirmed'/'partial'/'refuted'), boldness, "
        "information_gain. predicted_value is echoed from the proposal so that "
        "generate_discoveries can render it; the outcome does not depend on it. "
        "None if no previous prediction exists.",
    )
    new_discoveries: list[VocabEntry] = Field(
        default_factory=list,
        description="New kind='discovery' entries generated from this round's "
        "evaluation. These are empirical findings expressed as "
        "sentences, added to runtime_vocab for the next iteration.",
    )
    vocab_changes: list[str] = Field(
        default_factory=list,
        description="Human-readable log of vocabulary promotion events made "
        "this iteration. One entry per promoted candidate, e.g. "
        "'Promoted log_fno to canonical (seen in 3 runs).' "
        "Empty when no candidates met the promotion threshold.",
    )

    # --- Centrifugal health metrics ---
    vocab_diversity_ratio: float | None = Field(
        default=None,
        description="Fraction of feature/capability vocab entries that are still candidates "
        "(not yet promoted to canonical). Range [0, 1]. A low value signals "
        "vocabulary stagnation — the system is reusing only established terms "
        "rather than proposing new ones. The exploration resolver uses this to "
        "trigger explore mode when the ratio falls below policy.vocab_stagnation_threshold.",
    )
    cumulative_information_gain: float = Field(
        default=0.0,
        description="Running total of information_gain across all iterations. "
        "Increases when a bold prediction is confirmed (boldness × 1). "
        "Unchanged when predictions are refuted or partial. "
        "Surfaced to the Phase 2 synthesis prompt so the LLM can see "
        "how much confirmed knowledge has been built up over the run.",
    )

    # --- Scientific accuracy (Phase E) ---
    scientific_accuracy: dict[str, float] | None = Field(
        default=None,
        description="Prediction hit-rate fractions: e.g. {'confirmed': 0.38, 'partial': 0.22, "
        "'refuted': 0.40}. Values sum to 1.0. None until the first prediction "
        "has been evaluated (first iteration has no prior prediction).",
    )
    prediction_outcomes_history: dict[str, int] = Field(
        default_factory=lambda: {"confirmed": 0, "partial": 0, "refuted": 0},
        description="Cumulative count of each prediction outcome across all iterations. "
        "Carry forward as InterpretationInput.prediction_outcomes_history "
        "in the next iteration.",
    )

    # --- Vocab link promotion (Phase E.7) ---
    vocab_link_confirmations: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Updated feature→capability link confirmation counts: "
        "'feature:capability' → list of run_names where the link was confirmed. "
        "Carry forward as InterpretationInput.vocab_link_confirmations "
        "in the next iteration.",
    )

    # --- Structured HealthGate feedback (V19 PR 3 — deterministic, NEVER
    #     LLM-derived; populated regardless of the prompt flag and of
    #     interpreter degradation, per the §3.10 invariant) ---
    per_model_round_health_counts: dict[str, dict[str, int]] = Field(
        default_factory=dict,
        description="model_type → {'valid': n, 'invalid': n, 'unknown': n} "
        "over this iteration's rounds, from each round's deterministic "
        "health_validity classification. Computed from RoundHealth, not "
        "from LLM findings.",
    )
    per_model_collapse_fingerprints: dict[str, list[CollapseFingerprint]] = Field(
        default_factory=dict,
        description="model_type → distinct collapse fingerprints observed "
        "THIS iteration (deduped by signature, chronological first-seen "
        "order). Deterministic — built from persisted gate evidence only.",
    )
    collapse_fingerprint_history: dict[str, list[CollapseFingerprintHistoryEntry]] = Field(
        default_factory=dict,
        description="Bounded cross-iteration fingerprint history AFTER this "
        "iteration's deterministic merge and retention "
        "(pr3_healthgate_feedback.md §3.8). Carry forward as "
        "InterpretationInput.collapse_fingerprint_history. The merge runs "
        "regardless of interpreter LLM success or degradation — real gate "
        "evidence is never lost to an LLM failure.",
    )

    # --- Degraded-mode flag (V8 hardening Domain 2b) ---
    is_degraded: bool = Field(
        default=False,
        description="True when the interpreter produced this digest via the "
        "fallback path (LLM call failed after the Bridge's 3-retry "
        "envelope). Degraded outputs preserve the incoming "
        "runtime_vocab verbatim (no growth this iter), have empty "
        "key_findings/bottlenecks/new_discoveries, and are still "
        "written to disk so the chain's load_latest_knowledge() "
        "step finds a digest. Without this flag, an interp LLM "
        "failure left no digest on disk and the next iter's "
        "load_latest_knowledge skipped the affected iter — "
        "causing a 2-iter vocab regression. See "
        "docs/V8_Gap_Report.md Domain 2b.",
    )

    # --- Per-iteration evolution metrics (V8 hardening Domain 3) ---
    evolution_stats: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-iteration vocabulary evolution metrics, snapshotted at "
        "the end of result_interpretation_agent.run(). Populated keys: "
        "vocab_total (int), vocab_canonical (int), vocab_candidate "
        "(int), promoted_this_iter (int — count from "
        "promote_candidates() this iter, reflects the Tested-only "
        "threshold), is_degraded (bool — mirrors the field above). "
        "Also appended as one row to {workspace}/evolution_log.jsonl "
        "for tail -f monitoring. See docs/V8_Gap_Report.md Domain 3.",
    )
