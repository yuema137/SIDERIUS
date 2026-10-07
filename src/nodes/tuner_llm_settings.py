"""Pure projection of validated tuner input into bridge arguments."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.schemas.hyperparam_tuning import HyperparamTuningInput


def tuner_bridge_arguments(agent_input: HyperparamTuningInput) -> dict[str, Any]:
    """Keep optional LLM transport out of the tuner execution loop."""

    kwargs: dict[str, Any] = {
        "provider": agent_input.llm_provider,
        "model_id": agent_input.llm_model_id,
        "reflect_provider": agent_input.reflect_provider,
        "reflect_model_id": agent_input.reflect_model_id,
        "max_retries": agent_input.max_retries,
    }
    if agent_input.reasoning_effort is not None:
        kwargs["reasoning_effort"] = agent_input.reasoning_effort
    if agent_input.reflect_reasoning_effort is not None:
        kwargs["reflect_reasoning_effort"] = agent_input.reflect_reasoning_effort
    return kwargs
