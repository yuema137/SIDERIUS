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

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator

from agent.schemas.storage import StorageConfig, LocalStorageConfig
from agent.schemas.hyperparam_tuning import ExpertAdviceInput
from agent.schemas.proposal import VocabEntry, ProposedVocabLink, FalsifiablePrediction


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
    best_denoising_score: Optional[float] = Field(
        default=None,
        description="Highest denoising score achieved in this run.",
    )
    worst_denoising_score: Optional[float] = Field(
        default=None,
        description="Lowest denoising score achieved in this run (excluding OOM-skipped).",
    )
    best_config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="The params dict (model_config, train_config, loss_config) "
                    "that produced the best denoising score.",
    )
    round_scores: List[Optional[float]] = Field(
        default_factory=list,
        description="Denoising score per round in chronological order. "
                    "None entries indicate OOM-skipped or failed rounds.",
    )
    round_conclusions: List[str] = Field(
        default_factory=list,
        description="One-line conclusion from each round's LLM reflection. "
                    "Extracted from the 'memory.conclusion' field of each record.",
    )
    model_description: Optional[str] = Field(
        default=None,
        description="Architecture description (markdown + math). For built-in models "
                    "this is loaded from description.md by the interpretation agent. "
                    "For agent-generated models, the workflow passes it directly so "
                    "the interpretation agent doesn't need filesystem access.",
    )

    # --- Per-file performance (from file_vector) ---
    best_file_vector: Optional[List[Optional[float]]] = Field(
        default=None,
        description="Length-20 score vector from the best experiment. Each index = one "
                    "validation file (frequency, log scale: 0=lowest, 19=highest). "
                    "None for files not evaluated. Reveals frequency-dependent weaknesses.",
    )
    formal_score: Optional[float] = Field(
        default=None,
        description="Denoising score from the formal (final) round specifically. "
                    "Distinct from best_denoising_score which may come from a trial round.",
    )
    formal_file_vector: Optional[List[Optional[float]]] = Field(
        default=None,
        description="File vector from the formal round. Definitive per-file performance.",
    )

    # --- Model efficiency ---
    best_model_params: Optional[int] = Field(
        default=None,
        description="Number of trainable parameters in the best-scoring model.",
    )

    # --- Compute cost ---
    best_timing: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Timing dict from the best experiment: "
                    "train_time_s, inference_time_s, scoring_time_s. "
                    "Used to generate timing discoveries and warn the planner.",
    )

    # --- Data volume context ---
    training_psd_segments: Optional[int] = Field(
        default=None,
        description="PSD segments used for training in the best experiment. "
                    "Compare against baseline (typically 4000) to assess data sufficiency.",
    )
    eval_psd_segments: Optional[int] = Field(
        default=None,
        description="PSD segments used for evaluation in the best experiment.",
    )
    trial_portion: Optional[float] = Field(
        default=None,
        description="Trial portion used in the best experiment (if trial mode).",
    )

    # --- Per-round detail (for trend analysis) ---
    round_trial_portions: Optional[List[Optional[float]]] = Field(
        default=None,
        description="Trial portion used in each round. Shows if the agent adapted data volume.",
    )
    round_model_params: Optional[List[Optional[int]]] = Field(
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

    summaries: List[ModelRunSummary] = Field(
        default_factory=list,
        description="One condensed summary per model tuning run. "
                    "Can be empty if model_types is provided.",
    )
    model_types: Optional[List[str]] = Field(
        default=None,
        description="Explicit list of model types whose descriptions to include. "
                    "When None, model types are derived from summaries. "
                    "Cannot be an empty list — use None to derive from summaries.",
    )
    expert_advice: ExpertAdviceInput = Field(
        default="",
        description="Structured guidance from upstream agents or orchestrators. "
                    "Accepts a plain string or a structured ExpertAdvice object.",
    )
    human_advice: Optional[str] = Field(
        default=None,
        description="Optional human-provided guidance (highest priority — overrides expert_advice). "
                    "When present, injected into the LLM prompt as high-priority context.",
    )
    # --- Vocabulary feedback (Phase C) ---
    runtime_vocab: List[VocabEntry] = Field(
        default_factory=list,
        description="Current vocabulary (seed + candidates + discoveries) from "
                    "previous iterations. Empty on first iteration (uses seed). "
                    "This IS the compressed memory of iterations 0..N-2.",
    )
    previous_proposal: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Serialized ProposalOutput from the previous iteration. "
                    "Contains falsifiable_prediction, proposed_vocab_links, "
                    "inherited_components. None on the first iteration.",
    )

    storage: StorageConfig = Field(
        default_factory=lambda: StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace="./siderius_workspace", run_name="v1"),
        ),
        description="Where this node reads its inputs and writes its interpretation output.",
    )

    @model_validator(mode="after")
    def require_at_least_one_model(self) -> "InterpretationInput":
        if self.model_types is not None and len(self.model_types) == 0:
            raise ValueError(
                "model_types cannot be an empty list. "
                "Use None to derive model types from summaries."
            )
        derived = {s.model_type for s in self.summaries}
        effective = derived | set(self.model_types or [])
        if not effective:
            raise ValueError(
                "At least one model type must be provided — "
                "either via summaries or model_types."
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
    model_types: List[str] = Field(
        description="All model types analysed (union of summaries and explicit model_types).",
    )
    model_descriptions: Dict[str, str] = Field(
        description="model_type → full markdown description loaded from description.md. "
                    "Carries architecture knowledge forward to the proposal agent.",
    )

    # --- Experiment counts ---
    total_experiments: int = Field(
        description="Total completed rounds across all summaries.",
    )

    # --- Per-model scores ---
    per_model_best: Dict[str, Optional[float]] = Field(
        default_factory=dict,
        description="model_type → best denoising score. "
                    "None if the model has no successful experiments.",
    )
    per_model_worst: Dict[str, Optional[float]] = Field(
        default_factory=dict,
        description="model_type → worst denoising score. "
                    "None if the model has no successful experiments.",
    )

    # --- Overall best ---
    best_denoising_score: Optional[float] = Field(
        default=None,
        description="Highest denoising score observed across all models.",
    )
    worst_denoising_score: Optional[float] = Field(
        default=None,
        description="Lowest denoising score observed across all models.",
    )
    best_config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="The params dict that produced the overall best denoising score.",
    )

    # --- Per-model summaries (from Phase 1) ---
    per_model_summaries: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="model_type → structured summary from Phase 1 (per-model LLM call). "
                    "Each summary contains key_findings, bottlenecks, best_config_analysis, "
                    "and score_trend. Carried forward for debugging and downstream consumption.",
    )

    # --- LLM-generated analysis (from Phase 2) ---
    key_findings: List[str] = Field(
        description="Concrete, ranked observations extracted from the run summaries.",
    )
    bottlenecks: List[str] = Field(
        description="Root causes currently limiting further improvement.",
    )
    take_home_message: str = Field(
        description="Single critical insight that directly motivates proposing a new architecture.",
    )

    # --- Frequency analysis (from file_vector) ---
    per_model_file_vectors: Optional[Dict[str, List[Optional[float]]]] = Field(
        default=None,
        description="model_type → best file_vector. Enables the proposal agent to see "
                    "which frequency ranges each architecture handles well.",
    )
    weak_frequency_files: Optional[Dict[str, List[int]]] = Field(
        default=None,
        description="model_type → list of file indices where the model scores poorly. "
                    "Computed from file_vector analysis (scores below threshold).",
    )

    # --- Efficiency context ---
    per_model_params: Optional[Dict[str, int]] = Field(
        default=None,
        description="model_type → parameter count of best model.",
    )

    # --- Data volume context ---
    per_model_training_segments: Optional[Dict[str, int]] = Field(
        default=None,
        description="model_type → training PSD segments used in best experiment.",
    )

    # --- Vocabulary feedback (Phase C) ---
    runtime_vocab: List[VocabEntry] = Field(
        default_factory=list,
        description="Updated vocabulary: seed + candidates + discoveries from all "
                    "iterations including this one. This is the compressed memory "
                    "that the next iteration's proposal agent receives. "
                    "Empty in legacy mode (no vocabulary).",
    )
    prediction_evaluation: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Evaluation of the previous proposal's FalsifiablePrediction. "
                    "Contains: metric, predicted_value, actual_value, "
                    "outcome ('confirmed'/'refuted'/'partial'), boldness, "
                    "information_gain. None if no previous prediction exists.",
    )
    new_discoveries: List[VocabEntry] = Field(
        default_factory=list,
        description="New kind='discovery' entries generated from this round's "
                    "evaluation. These are empirical findings expressed as "
                    "sentences, added to runtime_vocab for the next iteration.",
    )
