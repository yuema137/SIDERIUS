"""Admit complete one-shot results and retain measured provider usage."""

import json
from typing import Any

from pydantic_ai.messages import ModelResponse, TextPart, ThinkingPart, ToolCallPart

from agent.llm_transport.contracts import Choice, Completion, FunctionCall, Message, ToolCall, Usage
from agent.llm_transport.requests import JSON_TOOL


def strict_arguments(call: ToolCallPart) -> dict[str, Any]:
    """Do not use the library's partial-JSON parser for execution arguments."""
    payload = json.loads(call.args) if isinstance(call.args, str) else call.args
    if not isinstance(payload, dict):
        raise ValueError("Tool arguments must be a complete JSON object")
    return payload


def measured_usage(raw: dict[str, Any]) -> Usage | None:
    counts = raw.get("usage")
    if not isinstance(counts, dict):
        return None
    prompt = counts.get("prompt_tokens", counts.get("input_tokens"))
    if "input_tokens" in counts and isinstance(prompt, int):
        # Anthropic reports cached input separately; OpenAI prompt_tokens already
        # includes it. Count all input tokens without changing legacy accounting.
        for key in ("cache_creation_input_tokens", "cache_read_input_tokens"):
            cached = counts.get(key, 0)
            if isinstance(cached, int):
                prompt += cached
    completion = counts.get("completion_tokens", counts.get("output_tokens"))
    total = counts.get("total_tokens")
    if total is None and isinstance(prompt, int) and isinstance(completion, int):
        total = prompt + completion
    return Usage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)


def normalize(
    result: ModelResponse,
    raw: dict[str, Any],
    *,
    json_mode: str | None,
    tool_names: set[str],
    metadata: dict[str, str | int | None],
) -> Completion:
    """Refuse lossy results AFTER returning usage to the bridge's accounting owner."""
    texts = [part.content for part in result.parts if isinstance(part, TextPart)]
    calls = [part for part in result.parts if isinstance(part, ToolCallPart)]
    failure = None
    if result.finish_reason not in ("stop", "tool_call"):
        failure = f"Incomplete provider response: {result.finish_reason!r}"
    if any(not isinstance(part, (TextPart, ThinkingPart, ToolCallPart)) for part in result.parts):
        failure = "Unsupported provider response content for the one-shot bridge contract"
    content = "".join(texts) or None
    tools = []
    if json_mode == "tool":
        if len(calls) != 1 or calls[0].tool_name != JSON_TOOL:
            failure = "JSON output requires exactly one declared result tool"
        else:
            try:
                payload = strict_arguments(calls[0])
                if set(payload) != {"value"} or not isinstance(payload["value"], (dict, list)):
                    raise ValueError("Expected JSON object or array in value")
                content = json.dumps(payload["value"], ensure_ascii=False)
            except (ValueError, TypeError) as exc:
                failure = f"Invalid JSON result tool: {type(exc).__name__}"
    elif json_mode == "object":
        if calls or not content:
            failure = "Expected JSON text without tool calls"
    elif tool_names:
        if len(calls) != 1:
            failure = "The one-shot bridge requires exactly one tool call"
        else:
            call = calls[0]
            try:
                args = strict_arguments(call)
                if (
                    call.tool_name not in tool_names
                    or not call.tool_call_id
                    or not isinstance(args, dict)
                ):
                    raise ValueError("Unknown tool or missing call identity/object arguments")
                tools = [
                    ToolCall(
                        id=call.tool_call_id,
                        function=FunctionCall(
                            name=call.tool_name, arguments=json.dumps(args, ensure_ascii=False)
                        ),
                    )
                ]
            except (ValueError, TypeError) as exc:
                failure = f"Invalid tool call: {type(exc).__name__}"
    elif calls or not content:
        failure = "Expected nonempty text without tool calls"
    return Completion(
        choices=[Choice(message=Message(content=content, tool_calls=tools))],
        model=raw.get("model") if isinstance(raw.get("model"), str) else None,
        usage=measured_usage(raw),
        failure=failure,
        transport_metadata=metadata,
    )
