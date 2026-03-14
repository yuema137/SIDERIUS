# workflows/llm_config.py
"""
Per-node LLM configuration for SIDERIUS workflows.

Allows each node in a workflow to use a different LLM provider and model.
Nodes not listed in the config use their own built-in defaults.

Usage:
    # From a JSON file:
    config = WorkflowLLMConfig.from_json("llm_config.json")

    # Programmatic:
    config = WorkflowLLMConfig(
        implement=NodeLLMConfig(provider="gemini", model_id="gemini-3.1-pro-preview"),
        propose=NodeLLMConfig(provider="openai", model_id="gpt-4o"),
    )

    # Get config for a node (returns kwargs dict for the node constructor):
    interpret_kwargs = config.get("interpret")
    # → {} if not configured (node uses its own defaults)
    # → {"provider": "gemini", "model_id": "..."} if configured
"""

from __future__ import annotations

import json
from typing import Literal, Optional
from pydantic import BaseModel, Field


class NodeLLMConfig(BaseModel):
    """LLM configuration for a single node."""

    provider: Literal["gemini", "openai"] = Field(
        default="gemini",
        description="LLM provider.",
    )
    model_id: str = Field(
        default="gemini-3.1-flash-lite-preview",
        description="Specific model ID passed to the provider.",
    )


class WorkflowLLMConfig(BaseModel):
    """
    Per-node LLM configuration for a workflow.

    Each field is optional. When None, the corresponding node uses its own
    built-in default (e.g. the implementor defaults to gemini-3.1-pro-preview).
    """
    model_config = {"populate_by_name": True}

    interpret: Optional[NodeLLMConfig] = Field(
        default=None,
        description="LLM config for the interpretation agent.",
    )
    propose: Optional[NodeLLMConfig] = Field(
        default=None,
        description="LLM config for the proposal agent.",
    )
    implement: Optional[NodeLLMConfig] = Field(
        default=None,
        description="LLM config for the implementor agent.",
    )
    validate_model: Optional[NodeLLMConfig] = Field(
        default=None,
        description="LLM config for the validator agent.",
        alias="validate",
    )
    tune: Optional[NodeLLMConfig] = Field(
        default=None,
        description="LLM config for the tuning agent.",
    )

    def get(self, node_name: str) -> dict:
        """
        Get LLM constructor kwargs for a node.

        Args:
            node_name: One of "interpret", "propose", "implement", "validate", "tune".

        Returns:
            {"provider": ..., "model_id": ...} if configured for this node,
            {} if not configured (node should use its own defaults).
        """
        # Handle "validate" alias → stored as validate_model
        attr = "validate_model" if node_name == "validate" else node_name
        config = getattr(self, attr, None)
        if config is None:
            return {}
        return {"provider": config.provider, "model_id": config.model_id}

    @classmethod
    def from_json(cls, path: str) -> "WorkflowLLMConfig":
        """Load from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.model_validate(data)

    @classmethod
    def uniform(cls, provider: str, model_id: str) -> "WorkflowLLMConfig":
        """Create a config that uses the same provider/model for all nodes."""
        cfg = NodeLLMConfig(provider=provider, model_id=model_id)
        return cls(
            interpret=cfg,
            propose=cfg,
            implement=cfg,
            validate_model=cfg,
            tune=cfg,
        )
