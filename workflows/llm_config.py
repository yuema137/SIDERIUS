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

    provider: Literal["gemini", "openai", "deepseek"] = Field(
        default="gemini",
        description="LLM provider.",
    )
    model_id: str = Field(
        default="gemini-3.1-flash-lite-preview",
        description="Specific model ID passed to the provider.",
    )
    max_retries: Optional[int] = Field(
        default=None,
        description=(
            "Maximum retry attempts for transient API errors (429, 5xx). "
            "None (default) = retry indefinitely (Slurm wall time is the "
            "natural timeout). Set to a positive integer for interactive "
            "use (e.g. 6 for ~77s, 20 for ~15min)."
        ),
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


class ProposalLLMConfig(BaseModel):
    """
    LLM config for the proposal agent's three-stage reasoning pipeline.

    Mirrors TunerLLMConfig's pattern (PR #22): each stage of the pipeline
    is a first-class sub-agent with its own provider and model. The stages
    have different cognitive demands:

      - comparison → data-heavy analysis, can use a cheaper model
      - reasoning  → causal hypothesis, needs strong reasoning
      - proposing  → precise structured JSON, needs strong reasoning

    The pipeline config (stages, model selection, exploration mode) is also
    carried here so the entire proposal agent's behavior is configured in
    one place at the workflow level.

    See docs/adaptive_new_model_proposer.md §2A.
    """

    comparison: NodeLLMConfig = Field(
        default_factory=lambda: NodeLLMConfig(
            provider="gemini",
            model_id="gemini-2.5-flash",
        ),
        description=(
            "Sub-agent config for Stage 1 (comparison). Data-heavy analysis "
            "of past models — can use a cheaper/faster model. Default: gemini-2.5-flash."
        ),
    )
    reasoning: NodeLLMConfig = Field(
        default_factory=lambda: NodeLLMConfig(
            provider="gemini",
            model_id="gemini-3.1-pro-preview",
        ),
        description=(
            "Sub-agent config for Stage 2 (causal reasoning). Needs strong "
            "reasoning ability. Default: gemini-3.1-pro-preview."
        ),
    )
    proposing: NodeLLMConfig = Field(
        default_factory=lambda: NodeLLMConfig(
            provider="gemini",
            model_id="gemini-3.1-pro-preview",
        ),
        description=(
            "Sub-agent config for Stage 3 (architecture design). Needs precise "
            "structured JSON output. Default: gemini-3.1-pro-preview."
        ),
    )


class WorkflowLLMConfig(BaseModel):
    """
    Per-node LLM configuration for a workflow.

    Each field is optional. When None, the corresponding node uses its own
    built-in default (e.g. the implementor defaults to gemini-3.1-pro-preview).

    Agents with multiple sub-calls use nested config classes:
      - The tuner uses `TunerLLMConfig` (planner + reflector).
      - The proposal agent uses `ProposalLLMConfig` (comparison + reasoning + proposing).
      - Single-sub-call agents (interpret, implement, validate) use plain `NodeLLMConfig`.

    Future agents that grow sub-call needs define their own typed config
    class following the same pattern.
    """
    model_config = {"populate_by_name": True}

    interpret: Optional[NodeLLMConfig] = Field(
        default=None,
        description="LLM config for the interpretation agent.",
    )
    propose: Optional[ProposalLLMConfig] = Field(
        default=None,
        description="LLM config for the proposal agent's three-stage pipeline. "
                    "Has nested comparison/reasoning/proposing slots, each a full "
                    "NodeLLMConfig. None = agent uses its built-in defaults.",
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
            result = {
                "provider":         config.planner.provider,
                "model_id":         config.planner.model_id,
                "reflect_provider": config.reflector.provider,
                "reflect_model_id": config.reflector.model_id,
            }
            # The tuner creates one LLMBridge — use the planner's retry config.
            if config.planner.max_retries is not None:
                result["max_retries"] = config.planner.max_retries
            return result
        if isinstance(config, ProposalLLMConfig):
            # Flatten the nested ProposalLLMConfig into per-stage kwargs.
            # The proposal agent reads these to construct per-stage bridges.
            result = {
                "comparison_provider":  config.comparison.provider,
                "comparison_model_id":  config.comparison.model_id,
                "reasoning_provider":   config.reasoning.provider,
                "reasoning_model_id":   config.reasoning.model_id,
                "proposing_provider":   config.proposing.provider,
                "proposing_model_id":   config.proposing.model_id,
                # Legacy compat: also provide top-level provider/model_id
                # from the reasoning stage (the "main" model for the agent).
                "provider":             config.reasoning.provider,
                "model_id":             config.reasoning.model_id,
            }
            if config.reasoning.max_retries is not None:
                result["max_retries"] = config.reasoning.max_retries
            return result
        # Plain NodeLLMConfig — single-sub-call agent
        result = {"provider": config.provider, "model_id": config.model_id}
        if config.max_retries is not None:
            result["max_retries"] = config.max_retries
        return result

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
        propose_cfg = ProposalLLMConfig(
            comparison=base_cfg,
            reasoning=base_cfg,
            proposing=base_cfg,
        )
        tune_cfg = TunerLLMConfig(
            planner=base_cfg,
            reflector=NodeLLMConfig(
                provider=reflect_provider or provider,  # type: ignore[arg-type]
                model_id=reflect_model_id or model_id,
            ),
        )
        return cls(
            interpret=base_cfg,
            propose=propose_cfg,
            implement=base_cfg,
            validate_model=base_cfg,
            tune=tune_cfg,
        )
