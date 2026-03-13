# agent/schemas/interpretation.py
"""
Input and output schemas for result_interpretation_agent.

This node consumes experiment records produced by tune_ml_hyperparam_agent
and produces a structured interpretation — key findings, bottlenecks, and
a single take-home message — for consumption by ml_model_proposal_agent.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from agent.schemas.storage import StorageConfig, LocalStorageConfig


class InterpretationInput(BaseModel):
    """
    Input to result_interpretation_agent.

    Typically populated via the hyperparam_to_interpretation_v1 protocol,
    which maps HyperparamTuningOutput → InterpretationInput.
    """

    summary_records: List[Dict[str, Any]] = Field(
        description="Experiment records from summary_{run_name}.json. "
                    "Each record contains params, results, timing, and LLM memory fields.",
    )
    model_type: str = Field(
        description="The model architecture that was tuned (e.g. 'punet', 'fcnet').",
    )
    max_records: int = Field(
        default=50,
        ge=1,
        description="Maximum number of records passed to the LLM. "
                    "Most recent records are preferred when truncating.",
    )
    storage: StorageConfig = Field(
        default_factory=lambda: StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace="./siderius_workspace", run_name="v1"),
        ),
        description="Where this node reads its inputs and writes its interpretation output. "
                    "When running standalone, the node reads summary_{run_name}.json "
                    "from storage.local.workspace.",
    )


class InterpretationOutput(BaseModel):
    """
    Output of result_interpretation_agent.

    A structured summary of what the experiment history reveals.
    Consumed by ml_model_proposal_agent via interpretation_to_proposal_v1.
    """

    model_type: str = Field(
        description="The model architecture that was analysed.",
    )
    model_description: str = Field(
        description="Full markdown description of the model architecture, "
                    "loaded from ml_models/{model_type}/description.md. "
                    "Carried forward to ml_model_proposal_agent so it understands "
                    "what currently exists before proposing something new.",
    )
    total_experiments: int = Field(
        description="Total number of experiment records analysed (including OOM-skipped).",
    )
    best_denoising_score: Optional[float] = Field(
        default=None,
        description="Highest denoising score observed across all successful experiments.",
    )
    best_config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="The params dict (model_config, train_config, loss_config) that "
                    "produced the best denoising score.",
    )
    key_findings: List[str] = Field(
        description="Concrete, ranked observations extracted from the experiment history. "
                    "Each entry is a specific, actionable statement "
                    "(e.g. 'focal loss with gamma=2 consistently outperforms ce').",
    )
    bottlenecks: List[str] = Field(
        description="What is currently limiting further improvement. "
                    "Each entry identifies a specific architectural or training constraint.",
    )
    take_home_message: str = Field(
        description="Single critical message summarising the most important insight "
                    "for the proposal agent. Should directly motivate why a new "
                    "architecture is needed.",
    )
