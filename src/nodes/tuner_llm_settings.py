"""Pure projection of validated tuner input into bridge arguments."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.schemas.llm_retry import RetryPolicy

if TYPE_CHECKING:
    from agent.schemas.hyperparam_tuning import HyperparamTuningInput


def tuner_bridge_arguments(agent_input: HyperparamTuningInput) -> dict[str, Any]:
    """Keep optional LLM transport out of the tuner execution loop."""
    return tuner_bridge_kwargs(
        llm_provider=agent_input.llm_provider,
        llm_model_id=agent_input.llm_model_id,
        reflect_provider=agent_input.reflect_provider,
        reflect_model_id=agent_input.reflect_model_id,
        max_retries=agent_input.max_retries,
        reasoning_effort=agent_input.reasoning_effort,
        reflect_reasoning_effort=agent_input.reflect_reasoning_effort,
        reflect_retry_policy=agent_input.reflect_retry_policy,
    )


def tuner_bridge_kwargs(
    *,
    llm_provider: str,
    llm_model_id: str,
    reflect_provider: str | None,
    reflect_model_id: str | None,
    max_retries: int | None,
    reasoning_effort: str | None,
    reflect_reasoning_effort: str | None,
    reflect_retry_policy: RetryPolicy | None = None,
) -> dict[str, Any]:
    """Project already-resolved settings without fabricating a full tuner input."""
    kwargs: dict[str, Any] = {
        "provider": llm_provider,
        "model_id": llm_model_id,
        "reflect_provider": reflect_provider,
        "reflect_model_id": reflect_model_id,
        "max_retries": max_retries,
    }
    if reasoning_effort is not None:
        kwargs["reasoning_effort"] = reasoning_effort
    if reflect_reasoning_effort is not None:
        kwargs["reflect_reasoning_effort"] = reflect_reasoning_effort
    if reflect_retry_policy is not None:
        kwargs["reflect_retry_policy"] = reflect_retry_policy
    return kwargs
