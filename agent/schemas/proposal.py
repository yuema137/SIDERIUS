# agent/schemas/proposal.py
"""
Input and output schemas for ml_model_proposal_agent.

This node consumes InterpretationOutput and produces a full model specification —
mathematical definition, model name, motivation, and structured expert advice —
for consumption by both ml_model_implementor and tune_ml_hyperparam_agent.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from agent.schemas.hyperparam_tuning import ExpertAdvice, ExpertAdviceInput
from agent.schemas.storage import StorageConfig, LocalStorageConfig


class ProposalInput(BaseModel):
    """
    Input to ml_model_proposal_agent.

    Typically populated via the interpretation_to_proposal_v1 protocol,
    which maps InterpretationOutput → ProposalInput.
    """

    interpretation: Dict[str, Any] = Field(
        description="Serialised InterpretationOutput — key findings, bottlenecks, "
                    "and take-home message from result_interpretation_agent.",
    )
    existing_model_types: List[str] = Field(
        default_factory=list,
        description="Model type keys already registered in MODEL_REGISTRY. "
                    "The proposal agent must not reuse any of these names.",
    )
    constraints: List[str] = Field(
        default_factory=list,
        description="Hard limits the proposed architecture must respect "
                    "(e.g. 'VRAM < 10 GB', 'params < 50M', 'no external dependencies').",
    )
    human_advice: Optional[ExpertAdviceInput] = Field(
        default=None,
        description="Optional human-provided guidance for the proposal agent. "
                    "Accepts either a plain string or a structured ExpertAdvice object. "
                    "When present, the agent treats this as high-priority input — "
                    "it should explicitly address the stated focus areas, respect the "
                    "constraints, and consider the suggested directions.",
    )
    previous_failures: List[str] = Field(
        default_factory=list,
        description="Validation error messages from previous failed attempts in this "
                    "iteration. The workflow populates this when retrying after a "
                    "validation failure so the proposal agent avoids the same mistakes. "
                    "Each entry is the error_message from a ValidatorOutput.",
    )
    storage: StorageConfig = Field(
        default_factory=lambda: StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace="./siderius_workspace", run_name="v1"),
        ),
        description="Where this node reads its inputs and writes its proposal output. "
                    "When running standalone, the node reads interpretation output "
                    "from storage.local.workspace.",
    )


class ProposalOutput(BaseModel):
    """
    Output of ml_model_proposal_agent.

    A complete model specification ready for implementation and hyperparameter tuning.
    Consumed by ml_model_implementor (via proposal_to_implementor_v1) and by
    tune_ml_hyperparam_agent (via proposal_to_hyperparam_seeded_v1).
    """

    model_name: str = Field(
        min_length=1,
        description="Short, unique, snake_case identifier for the proposed model "
                    "(e.g. 'attn_unet', 'dilated_rnn'). Must not clash with existing model types.",
    )
    model_description: str = Field(
        description="One paragraph plain-English description of the architecture "
                    "and why it is expected to improve on the current best.",
    )
    mathematical_definition: str = Field(
        description="Precise layer-by-layer specification of the architecture. "
                    "Must be concrete enough for an LLM to implement directly: "
                    "include layer types, dimensions, activation functions, skip connections, "
                    "and the forward pass data flow. "
                    "Forward contract is fixed: input [B, T] int64 → output [B, 256, T] float32.",
    )
    motivation: str = Field(
        description="Why this specific architecture addresses the bottlenecks identified "
                    "by result_interpretation_agent. Should reference the take-home message directly.",
    )
    expert_advice: ExpertAdvice = Field(
        description="Structured guidance for tune_ml_hyperparam_agent. "
                    "Specifies safe starting hyperparameter ranges, known failure modes, "
                    "and exploration focus areas for this specific architecture.",
    )
    baseline_config: Dict[str, Any] = Field(
        description="A safe, moderate starting configuration for this architecture. "
                    "Should use a conservative parameter count and GPU memory footprint "
                    "suitable for initial exploration. "
                    "Must include model_config, train_config, and loss_config keys.",
    )
