# agent/schemas/validator.py
"""
Input and output schemas for code_validator_agent.

This node receives the file paths written by ml_model_implementor,
attempts to load the plugin via ml_models/plugin_loader, and runs the
generated pytest test file. No LLM calls. Fully deterministic.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field

from agent.schemas.storage import StorageConfig, LocalStorageConfig


class ValidatorInput(BaseModel):
    """
    Input to code_validator_agent.

    Typically populated via the implementor_to_validator_v1 protocol,
    which maps ImplementorOutput → ValidatorInput.
    """

    model_type: str = Field(
        description="The PLUGIN_MODEL_TYPE key to validate.",
    )
    model_file_path: str = Field(
        description="Absolute path to the plugin file written by ml_model_implementor.",
    )
    test_file_path: str = Field(
        description="Absolute path to the test file written by ml_model_implementor.",
    )
    storage: StorageConfig = Field(
        default_factory=lambda: StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace="./siderius_workspace", run_name="v1"),
        ),
        description="Where this node writes its validation report "
                    "(e.g. validation_output_{run_name}.json).",
    )


class ValidatorOutput(BaseModel):
    """
    Output of code_validator_agent.

    Consumed by tune_ml_hyperparam_agent via validator_to_hyperparam_v1
    to confirm the plugin is safe to use before starting a tuning run.
    """

    passed: bool = Field(
        description="True only if both plugin registration and all pytest tests succeed.",
    )
    model_type: str = Field(
        description="The model type key that was validated.",
    )
    plugin_registered: bool = Field(
        description="Whether the plugin file loaded successfully into MODEL_REGISTRY "
                    "(PLUGIN_MODEL_TYPE, PLUGIN_CONFIG_CLASS, PLUGIN_MODEL_CLASS all present).",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Full error output (plugin load error or pytest output) on failure. "
                    "None if passed=True.",
    )
