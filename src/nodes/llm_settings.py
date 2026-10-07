"""Inert node constructor defaults and bridge arguments.

The execution classes import these defaults; inspection need not import their
package initializers, which eagerly load implementations. These are constructor
defaults, not WorkflowLLMConfig defaults or decisions to enable a capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NodeLLMDefaults[ModelId: (str, None)]:
    provider: str
    model_id: ModelId
    max_retries: int | None = None
    reasoning_effort: str | None = None


INTERPRET = NodeLLMDefaults("gemini", "gemini-3.1-flash-lite-preview")
IMPLEMENT = NodeLLMDefaults("gemini", "gemini-3.1-pro-preview")
VALIDATE = NodeLLMDefaults("gemini", "gemini-3.1-flash-lite-preview")
ANALYZE = NodeLLMDefaults("gemini", None)
PROPOSE = NodeLLMDefaults("gemini", "gemini-3.1-flash-lite-preview")


def node_bridge_kwargs(
    *,
    provider: str,
    model_id: str | None,
    max_retries: int | None,
    reasoning_effort: str | None,
    omit_unset_retries: bool = False,
) -> dict[str, Any]:
    """Preserve existing node keyword omission, including DA's retry policy."""
    result: dict[str, Any] = {"provider": provider, "model_id": model_id}
    if max_retries is not None or not omit_unset_retries:
        result["max_retries"] = max_retries
    if reasoning_effort is not None:
        result["reasoning_effort"] = reasoning_effort
    return result


@dataclass(frozen=True)
class LiteratureBridgeArguments:
    """A missing search dictionary means reuse the actual main client."""

    main: dict[str, Any]
    search: dict[str, Any] | None


def literature_bridge_arguments(
    *,
    provider: str,
    model_id: str,
    reasoning_effort: str | None,
    search_provider: str | None,
    search_model_id: str | None,
    search_reasoning_effort: str | None,
) -> LiteratureBridgeArguments:
    """Project validated literature input; main routing has no default here."""
    main = node_bridge_kwargs(
        provider=provider,
        model_id=model_id,
        max_retries=None,
        reasoning_effort=reasoning_effort,
        omit_unset_retries=True,
    )
    search = None
    if search_provider or search_model_id or search_reasoning_effort:
        search = node_bridge_kwargs(
            provider=search_provider or provider,
            model_id=search_model_id or model_id,
            max_retries=None,
            reasoning_effort=search_reasoning_effort,
            omit_unset_retries=True,
        )
    return LiteratureBridgeArguments(main, search)
