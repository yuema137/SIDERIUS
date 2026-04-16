# agent/schemas/implementor.py
"""
Input and output schemas for ml_model_implementor.

This node consumes a ProposalOutput and produces a validated plugin file
and test file in agent_generated/. It does not register the plugin itself —
that is verified by code_validator_agent.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from agent.schemas.storage import StorageConfig, LocalStorageConfig
from agent.schemas.hyperparam_tuning import ExpertAdviceInput


class ImplementorInput(BaseModel):
    """
    Input to ml_model_implementor.

    Typically populated via the proposal_to_implementor_v1 protocol,
    which maps ProposalOutput → ImplementorInput.
    """

    model_name: str = Field(
        description="snake_case model type key. Used as the filename and PLUGIN_MODEL_TYPE constant.",
    )
    model_description: str = Field(
        description="Plain-English description of the architecture. Injected into the LLM prompt.",
    )
    mathematical_definition: str = Field(
        description="Precise layer-by-layer spec from the proposal agent. "
                    "The LLM uses this to write __init__ and forward.",
    )
    baseline_config: Dict[str, Any] = Field(
        description="Safe starting configuration from the proposal agent. "
                    "Used to derive sensible default values for the Pydantic config fields.",
    )
    plugin_dir: str = Field(
        default="agent_generated/models",
        description="Directory where the model plugin file will be written. "
                    "This is a fixed output destination independent of storage.local.workspace.",
    )
    test_dir: str = Field(
        default="agent_generated/tests",
        description="Directory where the test file will be written. "
                    "This is a fixed output destination independent of storage.local.workspace.",
    )
    max_retries: int = Field(
        default=2,
        ge=0,
        description="Maximum self-correction attempts after the initial code commit. "
                    "On each retry the LLM receives the validation error and its previous "
                    "code, and produces a targeted fix. Total attempts = 1 + max_retries. "
                    "Set to 0 to disable self-correction.",
    )
    reference_code: Dict[str, str] = Field(
        default_factory=dict,
        description="Source code of referenced ancestor models. Keyed by model_type. "
                    "Loaded automatically from inherited_components — the implementor "
                    "uses this as a template to copy-and-modify rather than writing "
                    "from scratch. Empty dict = no reference code available.",
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
    previous_validation_failure: Optional[str] = Field(
        default=None,
        description="Validation error message from the previous implementation attempt "
                    "for this same proposal. When set, the implementor knows upfront "
                    "what spec-alignment issue to fix and can target the repair in its "
                    "reasoning phase rather than discovering the problem after the fact. "
                    "None on the first attempt.",
    )
    storage: StorageConfig = Field(
        default_factory=lambda: StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace="./siderius_workspace", run_name="v1"),
        ),
        description="Where this node reads its inputs and writes its own output record "
                    "(e.g. implementor_output_{run_name}.json). "
                    "Note: plugin_dir and test_dir are separate — they are fixed "
                    "code output destinations, not part of the workspace.",
    )


class ImplementorOutput(BaseModel):
    """
    Output of ml_model_implementor.

    Paths to the written files. Consumed by code_validator_agent
    via implementor_to_validator_v1 to confirm the plugin is valid.
    """

    model_type: str = Field(
        description="The PLUGIN_MODEL_TYPE key written into the plugin file. "
                    "Same as the input model_name.",
    )
    description_file_path: str = Field(
        description="Absolute path to the written description.md "
                    "(e.g. .../agent_generated/models/attn_unet/description.md). "
                    "Used by result_interpretation_agent to load the model description "
                    "when interpreting results from this agent-generated model.",
    )
    model_file_path: str = Field(
        description="Absolute path to the written plugin file "
                    "(e.g. .../agent_generated/models/attn_unet.py).",
    )
    test_file_path: str = Field(
        description="Absolute path to the written test file "
                    "(e.g. .../agent_generated/tests/test_attn_unet.py).",
    )
    config_fields: Dict[str, Any] = Field(
        description="Summary of the Pydantic config fields generated by the LLM. "
                    "Keys are field names, values are their default values. "
                    "Used for logging and downstream context.",
    )
    model_description: str = Field(
        description="Plain-English description of the architecture, passed through from ImplementorInput. "
                    "Carried forward so ml_code_validator_agent can provide it to the LLM code reviewer.",
    )
    mathematical_definition: str = Field(
        description="Precise mathematical/architectural specification from the proposal, passed through "
                    "from ImplementorInput. Used by ml_code_validator_agent to verify implementation matches spec.",
    )
