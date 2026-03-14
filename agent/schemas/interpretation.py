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
    human_advice: Optional[str] = Field(
        default=None,
        description="Optional human-provided guidance for the interpretation agent. "
                    "When present, injected into the LLM prompt as high-priority context "
                    "(e.g. 'focus on comparing training stability across models').",
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
