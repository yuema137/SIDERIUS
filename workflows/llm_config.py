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
    """
    A single LLM call's configuration: which provider, which model.

    This is the leaf-level type used by:
      (a) agents that make one type of LLM call (interpret, propose,
          implement, validate today) — `WorkflowLLMConfig.<slot>` is a
          NodeLLMConfig directly
      (b) sub-call slots within agents that have multiple sub-calls
          (tuner today) — TunerLLMConfig.planner and TunerLLMConfig.reflector
          are each a NodeLLMConfig

    Each NodeLLMConfig is a complete, independent specification: it carries
    its own `provider` and its own `model_id`. Two NodeLLMConfigs in the
    same agent can route to entirely different providers (e.g. planner on
    gemini, reflector on openai) — the underlying LLMBridge supports this.
    """

    provider: Literal["gemini", "openai"] = Field(
        default="gemini",
        description="LLM provider.",
    )
    model_id: str = Field(
        default="gemini-3.1-flash-lite-preview",
        description="Specific model ID passed to the provider.",
    )


class TunerLLMConfig(BaseModel):
    """
    LLM config for the hyperparameter tuning agent.

    The tuner makes two distinct LLM calls per round, each treated as a
    first-class sub-agent with its own provider and model:

      - planner   → reasoning-heavy, designs the next experiment (called
                    once at the start of each round)
      - reflector → templated extraction, summarizes one experiment's
                    result into a memory entry (called once at the end
                    of each round)

    Each sub-call is a complete `NodeLLMConfig`. They can independently
    use different providers and different models — see
    docs/break_tuner_agent.md for the rationale.

    The default values reflect the recommended split: pro for the
    reasoning-heavy planner, flash for the templated reflector. Override
    either or both via the JSON config or the Python constructor.
    """

    planner: NodeLLMConfig = Field(
        default_factory=lambda: NodeLLMConfig(
            provider="gemini",
            model_id="gemini-3.1-pro-preview",
        ),
        description=(
            "Sub-agent config for the tuner's plan() call. Reasoning-heavy "
            "task — recommend a frontier model. Default: gemini-3.1-pro-preview."
        ),
    )
    reflector: NodeLLMConfig = Field(
        default_factory=lambda: NodeLLMConfig(
            provider="gemini",
            model_id="gemini-2.5-flash",
        ),
        description=(
            "Sub-agent config for the tuner's reflect() call. Templated "
            "extraction task — recommend a fast/cheap model. Default: "
            "gemini-2.5-flash (GA, unlimited daily quota, strong JSON-mode)."
        ),
    )


class WorkflowLLMConfig(BaseModel):
    """
    Per-node LLM configuration for a workflow.

    Each field is optional. When None, the corresponding node uses its own
    built-in default (e.g. the implementor defaults to gemini-3.1-pro-preview).

    The 4 single-sub-call agents (interpret, propose, implement, validate)
    use a plain `NodeLLMConfig`. The tuner uses `TunerLLMConfig`, which
    contains nested `NodeLLMConfig` slots (`planner` and `reflector`),
    one per sub-call. Future agents that grow sub-call needs will define
    their own typed config classes following the same pattern.
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
    tune: Optional[TunerLLMConfig] = Field(
        default=None,
        description=(
            "LLM config for the tuning agent. Has nested planner/reflector "
            "slots (each a full NodeLLMConfig) so the tuner's two sub-calls "
            "can use different providers and/or different models."
        ),
    )

    def get(self, node_name: str) -> dict:
        """
        Get LLM constructor kwargs for a node, as a flat dict ready to
        splat into the node's input schema.

        For single-sub-call agents (interpret/propose/implement/validate):
            {"provider": ..., "model_id": ...}

        For the tuner (which has planner + reflector sub-calls), the dict
        is flattened into the legacy keys expected by `HyperparamTuningInput`
        and `LLMBridge.__init__`:
            {
                "provider":         <planner.provider>,
                "model_id":         <planner.model_id>,
                "reflect_provider": <reflector.provider>,
                "reflect_model_id": <reflector.model_id>,
            }

        Args:
            node_name: One of "interpret", "propose", "implement",
                       "validate", "tune".

        Returns:
            Flat dict of LLM kwargs, or `{}` if the node is not configured.
        """
        # Handle "validate" alias → stored as validate_model
        attr = "validate_model" if node_name == "validate" else node_name
        config = getattr(self, attr, None)
        if config is None:
            return {}
        if isinstance(config, TunerLLMConfig):
            # Flatten the nested TunerLLMConfig into the legacy flat keys
            # that HyperparamTuningInput / LLMBridge expect.
            return {
                "provider":         config.planner.provider,
                "model_id":         config.planner.model_id,
                "reflect_provider": config.reflector.provider,
                "reflect_model_id": config.reflector.model_id,
            }
        # Plain NodeLLMConfig — single-sub-call agent
        return {"provider": config.provider, "model_id": config.model_id}

    @classmethod
    def from_json(cls, path: str) -> "WorkflowLLMConfig":
        """Load from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.model_validate(data)

    @classmethod
    def uniform(cls, provider: str, model_id: str,
                reflect_provider: Optional[str] = None,
                reflect_model_id: Optional[str] = None) -> "WorkflowLLMConfig":
        """
        Create a config that uses the same provider/model for all nodes,
        with optional reflector overrides for the tuner slot only.

        - The 4 single-sub-call agents (interpret/propose/implement/validate)
          all get a plain `NodeLLMConfig(provider, model_id)`.
        - The tuner gets a `TunerLLMConfig` where:
          * planner   = NodeLLMConfig(provider, model_id)
          * reflector = NodeLLMConfig(
                            reflect_provider or provider,
                            reflect_model_id or model_id,
                        )

        When called with no reflector overrides, the tuner uses the same
        provider/model for both sub-calls (legacy behavior).

        When called with `reflect_model_id="gemini-2.5-flash"`, the planner
        keeps the main model and the reflector switches to gemini-2.5-flash
        on the same provider.

        When called with both `reflect_provider="openai"` and
        `reflect_model_id="gpt-4o-mini"`, the reflector uses an entirely
        different provider — the bridge will hold two clients internally.
        """
        # Cast to Literal at runtime; pydantic will validate the value.
        base_cfg = NodeLLMConfig(provider=provider, model_id=model_id)  # type: ignore[arg-type]
        tune_cfg = TunerLLMConfig(
            planner=base_cfg,
            reflector=NodeLLMConfig(
                provider=reflect_provider or provider,  # type: ignore[arg-type]
                model_id=reflect_model_id or model_id,
            ),
        )
        return cls(
            interpret=base_cfg,
            propose=base_cfg,
            implement=base_cfg,
            validate_model=base_cfg,
            tune=tune_cfg,
        )
