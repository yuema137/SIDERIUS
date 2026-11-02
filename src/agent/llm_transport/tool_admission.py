"""Shared complete single-tool admission, independent of the optional backend."""

import json
from typing import Any

from openai.types.chat import ChatCompletion

from agent.llm_transport.contracts import Completion, ToolCall


def require_single_call(count: int, finish_reason: str | None) -> None:
    """Check a canonical finish reason before selecting any returned call."""
    if finish_reason not in ("stop", "tool_call"):
        raise ValueError(f"Incomplete provider response: {finish_reason!r}")
    if count != 1:
        raise ValueError("The one-shot bridge requires exactly one tool call")


def object_arguments(arguments: object) -> dict[str, Any]:
    """Execution arguments require complete JSON, never partial-JSON recovery."""
    payload = json.loads(arguments) if isinstance(arguments, str) else arguments
    if not isinstance(payload, dict):
        raise ValueError("Tool arguments must be a complete JSON object")
    return payload


def declared_arguments(
    name: str, call_id: str, arguments: object, tool_names: set[str]
) -> dict[str, Any]:
    """Admit only an identified call to a function declared in this request."""
    if name not in tool_names or not call_id:
        raise ValueError("Unknown tool or missing call identity")
    return object_arguments(arguments)


def admit_tool_response(
    response: ChatCompletion | Completion, tools: list[dict[str, Any]]
) -> tuple[str, dict[str, Any], str]:
    """Adapt SDK envelopes after accounting and normalized-failure handling."""
    if len(response.choices) != 1:
        raise ValueError("Tool selection requires exactly one response choice")
    choice = response.choices[0]
    message = choice.message
    finish_reason = "tool_call"
    if not isinstance(response, Completion):
        sdk_choice = response.choices[0]
        finish_reason = sdk_choice.finish_reason
        if finish_reason == "tool_calls":
            finish_reason = "tool_call"
        if sdk_choice.message.refusal:
            raise ValueError("Provider refused tool selection")
    if not message.tool_calls:
        raise ValueError("[LLMBridge.tool_call] Model did not return a tool call")
    require_single_call(len(message.tool_calls), finish_reason)
    call = message.tool_calls[0]
    if not isinstance(call, ToolCall) and call.type != "function":
        raise ValueError("Tool selection requires a function call")
    names = {tool["function"]["name"] for tool in tools if tool.get("type") == "function"}
    args = declared_arguments(call.function.name, call.id, call.function.arguments, names)
    return call.function.name, args, call.id
