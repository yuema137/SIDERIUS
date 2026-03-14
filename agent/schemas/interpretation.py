# agent/schemas/interpretation.py
"""
Input and output schemas for result_interpretation_agent.

This node consumes experiment records from one or more tuning runs and produces
a structured interpretation — key findings, bottlenecks, and a take-home message
— for consumption by ml_model_proposal_agent.

InterpretationInput accepts:
  - summaries: a list of SummaryGroup objects (one per model/run combination)
  - model_types: an explicit list of model types whose descriptions to include
  - Either summaries or model_types must be non-empty (or both)

InterpretationOutput carries descriptions for all effective model types so that
ml_model_proposal_agent knows exactly what already exists before proposing something new.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator

from agent.schemas.storage import StorageConfig, LocalStorageConfig


class SummaryGroup(BaseModel):
    """
    One group of experiment records from a single (model_type, run_name) tuning run.
    """
    model_type: str = Field(description="Architecture key (e.g. 'punet', 'fcnet').")
    run_name:   str = Field(description="Run identifier matching the summary filename.")
    records:    List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Experiment records from summary_{run_name}.json.",
    )


class InterpretationInput(BaseModel):
    """
    Input to result_interpretation_agent.

    Accepts experiment records from multiple runs and/or multiple model types.
    Descriptions are always loaded for every effective model type.

    Constraint: at least one model type must be reachable — either derived from
    summaries or listed explicitly in model_types.
    """

    summaries: List[SummaryGroup] = Field(
        default_factory=list,
        description="Experiment records grouped by (model_type, run_name). "
                    "Can be empty if model_types is provided.",
    )
    model_types: Optional[List[str]] = Field(
        default=None,
        description="Explicit list of model types whose descriptions to include. "
                    "When None, model types are derived from summaries. "
                    "Cannot be an empty list — use None to derive from summaries.",
    )
    max_records_per_group: int = Field(
        default=50,
        ge=1,
        description="Maximum number of records passed to the LLM per summary group "
                    "(most recent records preferred when truncating).",
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
        derived = {g.model_type for g in self.summaries}
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
        description="Total experiment records across all summary groups (including OOM-skipped).",
    )

    # --- Per-model scores ---
    per_model_best: Dict[str, Optional[float]] = Field(
        default_factory=dict,
        description="model_type → best denoising score across all its runs. "
                    "None if the model has no successful experiments.",
    )
    per_model_worst: Dict[str, Optional[float]] = Field(
        default_factory=dict,
        description="model_type → worst denoising score across all its runs. "
                    "None if the model has no successful experiments.",
    )

    # --- Overall best ---
    best_denoising_score: Optional[float] = Field(
        default=None,
        description="Highest denoising score observed across all models and runs.",
    )
    worst_denoising_score: Optional[float] = Field(
        default=None,
        description="Lowest denoising score observed across all models and runs.",
    )
    best_config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="The params dict that produced the overall best denoising score.",
    )

    # --- LLM-generated analysis ---
    key_findings: List[str] = Field(
        description="Concrete, ranked observations extracted from the experiment history.",
    )
    bottlenecks: List[str] = Field(
        description="Root causes currently limiting further improvement.",
    )
    take_home_message: str = Field(
        description="Single critical insight that directly motivates proposing a new architecture.",
    )
