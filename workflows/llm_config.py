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
from typing import Any, Literal

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
    max_retries: int | None = Field(
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


class LitReviewLLMConfig(BaseModel):
    """
    LLM config for the ml_literature_review node.

    The lit-review node makes three LLM calls per run (compression,
    search-decision, synthesis) but uses two distinct bridges:

      - main   → compression + synthesis (reasoning-heavy paper digestion)
      - search → search-decision (cheap, templated query/escalate/done step)

    Each sub-call is a complete ``NodeLLMConfig``. They can independently
    use different providers and different models — typically the search
    bridge runs on a cheaper model while the main bridge runs on a stronger
    one for the synthesis step. When operators don't need the split, set
    both sub-slots to the same NodeLLMConfig.

    See docs/external_agents_for_proposer.md §6 for the receiving end:
    the lit-review node reads ``llm_provider`` / ``llm_model_id`` for the
    main bridge and ``search_llm_provider`` / ``search_llm_model_id`` for
    the search bridge (the latter pair is optional in the schema; when
    None the search bridge falls back to the main bridge).
    """

    main: NodeLLMConfig = Field(
        default_factory=lambda: NodeLLMConfig(
            provider="deepseek",
            model_id="deepseek-v4-pro",
        ),
        description=(
            "Sub-agent config for the lit-review node's compression + "
            "synthesis calls. Reasoning-heavy — recommend a strong model. "
            "Maps to LiteratureReviewInput.llm_provider / llm_model_id."
        ),
    )
    search: NodeLLMConfig = Field(
        default_factory=lambda: NodeLLMConfig(
            provider="deepseek",
            model_id="deepseek-v4-pro",
        ),
        description=(
            "Sub-agent config for the lit-review node's search-decision "
            "call. Templated query/escalate/done step — can use a cheaper "
            "model. Maps to LiteratureReviewInput.search_llm_provider / "
            "search_llm_model_id."
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
      - The lit-review node uses `LitReviewLLMConfig` (main + search).
      - Single-sub-call agents (interpret, implement, validate) use plain `NodeLLMConfig`.

    Future agents that grow sub-call needs define their own typed config
    class following the same pattern.
    """

    model_config = {"populate_by_name": True}

    interpret: NodeLLMConfig | None = Field(
        default=None,
        description="LLM config for the interpretation agent.",
    )
    propose: ProposalLLMConfig | None = Field(
        default=None,
        description="LLM config for the proposal agent's three-stage pipeline. "
        "Has nested comparison/reasoning/proposing slots, each a full "
        "NodeLLMConfig. None = agent uses its built-in defaults.",
    )
    implement: NodeLLMConfig | None = Field(
        default=None,
        description="LLM config for the implementor agent.",
    )
    validate_model: NodeLLMConfig | None = Field(
        default=None,
        description="LLM config for the validator agent.",
        alias="validate",
    )
    tune: TunerLLMConfig | None = Field(
        default=None,
        description=(
            "LLM config for the tuning agent. Has nested planner/reflector "
            "slots (each a full NodeLLMConfig) so the tuner's two sub-calls "
            "can use different providers and/or different models."
        ),
    )
    lit_review: LitReviewLLMConfig | None = Field(
        default=None,
        description=(
            "LLM config for the ml_literature_review node (Commit 6+). "
            "Has nested main/search slots (each a full NodeLLMConfig) so "
            "the node's three LLM sub-calls split into two bridges: main "
            "drives compression + synthesis, search drives the cheap "
            "search-decision step. When None (default), .get('lit_review') "
            "falls back to the `interpret` slot's main-bridge config (no "
            "search override) — pre-Commit-6 JSON configs leave this key "
            "absent and the fallback path preserves backward-compat "
            "behavior. Design Decision 3, 2026-06-11."
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

        For the lit-review node (main + search sub-calls per Design
        Decision 3, 2026-06-11), the dict flattens to the four fields
        ``LiteratureReviewInput`` consumes:
            {
                "llm_provider":         <main.provider>,
                "llm_model_id":         <main.model_id>,
                "search_llm_provider":  <search.provider>,
                "search_llm_model_id":  <search.model_id>,
            }
        When ``lit_review`` is not configured, falls back to the
        ``interpret`` slot's main-bridge config (with key translation:
        ``provider`` → ``llm_provider``, ``model_id`` → ``llm_model_id``);
        ``search_llm_*`` fields stay absent so the lit-review node uses
        the main bridge for the search-decision call.

        Args:
            node_name: One of "interpret", "propose", "implement",
                       "validate", "tune", "lit_review".

        Returns:
            Flat dict of LLM kwargs, or `{}` if the node is not configured.
        """
        # Handle "validate" alias → stored as validate_model
        attr = "validate_model" if node_name == "validate" else node_name
        config = getattr(self, attr, None)

        # Lit-review fallback (Commit 6, Design Decision 3, 2026-06-11):
        # when not explicitly configured, inherit the main-bridge config
        # from the interpret slot and translate the keys (provider →
        # llm_provider, model_id → llm_model_id). search_llm_* fields stay
        # absent so the lit-review node falls back per-field to the main
        # bridge for the search-decision call. Keeps cost predictable for
        # operators who haven't tuned lit_review yet; pre-Commit-6 JSON
        # configs (which omit the lit_review key) work unchanged.
        if node_name == "lit_review" and config is None:
            if self.interpret is None:
                return {}
            return {
                "llm_provider": self.interpret.provider,
                "llm_model_id": self.interpret.model_id,
            }

        if config is None:
            return {}
        if isinstance(config, TunerLLMConfig):
            # Flatten the nested TunerLLMConfig into the legacy flat keys
            # that HyperparamTuningInput / LLMBridge expect.
            # ``dict[str, Any]`` because the optional ``max_retries`` value is
            # an ``int`` while everything else is a ``str``; the consumer
            # (LLMBridge) reads each key by name, so a heterogeneous-value
            # dict is the honest type here.
            result: dict[str, Any] = {
                "provider": config.planner.provider,
                "model_id": config.planner.model_id,
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
            # ``dict[str, Any]`` for the same reason as the tuner branch:
            # ``max_retries`` is an ``int`` mixed with string-valued keys.
            result: dict[str, Any] = {
                "comparison_provider": config.comparison.provider,
                "comparison_model_id": config.comparison.model_id,
                "reasoning_provider": config.reasoning.provider,
                "reasoning_model_id": config.reasoning.model_id,
                "proposing_provider": config.proposing.provider,
                "proposing_model_id": config.proposing.model_id,
                # Legacy compat: also provide top-level provider/model_id
                # from the reasoning stage (the "main" model for the agent).
                "provider": config.reasoning.provider,
                "model_id": config.reasoning.model_id,
            }
            if config.reasoning.max_retries is not None:
                result["max_retries"] = config.reasoning.max_retries
            return result
        if isinstance(config, LitReviewLLMConfig):
            # Flatten the nested LitReviewLLMConfig into the 4-field shape
            # ``LiteratureReviewInput`` consumes. Always emit all 4 fields
            # explicitly; the node itself falls back per-field to main when
            # a search field is None at runtime, so emitting both pairs is
            # safe and matches Design Decision 3's operator-visible source-
            # of-truth principle.
            return {
                "llm_provider": config.main.provider,
                "llm_model_id": config.main.model_id,
                "search_llm_provider": config.search.provider,
                "search_llm_model_id": config.search.model_id,
            }
        # Plain NodeLLMConfig — single-sub-call agent
        result = {"provider": config.provider, "model_id": config.model_id}
        if config.max_retries is not None:
            result["max_retries"] = config.max_retries
        return result

    @classmethod
    def from_json(cls, path: str) -> WorkflowLLMConfig:
        """Load from a JSON file."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.model_validate(data)

    @classmethod
    def uniform(
        cls,
        provider: str,
        model_id: str,
        reflect_provider: str | None = None,
        reflect_model_id: str | None = None,
    ) -> WorkflowLLMConfig:
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
        - The lit-review node gets a `LitReviewLLMConfig` where both
          main and search sub-slots use the same NodeLLMConfig(provider,
          model_id). Operators wanting a cheaper search bridge override
          construct `LitReviewLLMConfig` explicitly instead of using
          `.uniform()`. (Design Decision 3, 2026-06-11.)

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
        lit_review_cfg = LitReviewLLMConfig(
            main=base_cfg,
            search=base_cfg,
        )
        return cls(
            interpret=base_cfg,
            propose=propose_cfg,
            implement=base_cfg,
            # ``validate`` is the public alias of the ``validate_model``
            # field (set via ``Field(alias="validate")`` + ``populate_by_name=True``).
            # The pyright Pydantic plugin keys construction kwargs off the
            # alias, not the underlying attribute name — using the alias
            # here is the canonical form.
            validate=base_cfg,
            tune=tune_cfg,
            lit_review=lit_review_cfg,
        )
