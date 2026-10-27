"""Private normalized response and opt-in transport configuration contracts."""

from typing import Literal

from openai import APIError
from pydantic import BaseModel, ConfigDict, Field


class PydanticTransportConfig(BaseModel):
    """Explicit protocol override; new providers also select this backend automatically."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    protocol: Literal["anthropic", "openai-chat", "openai-responses"]


class FunctionCall(BaseModel):
    name: str
    arguments: str


class ToolCall(BaseModel):
    id: str
    function: FunctionCall


class Message(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


class Choice(BaseModel):
    message: Message


class Usage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class Completion(BaseModel):
    """Bridge consumption shape, without exposing provider library objects to nodes."""

    choices: list[Choice]
    model: str | None = None
    usage: Usage | None = None
    failure: str | None = None
    transport_metadata: dict[str, str | int | None] = Field(default_factory=dict)


def validate_completion(response: object) -> None:
    """Called after usage accounting, never inside the transport retry loop."""
    if isinstance(response, Completion) and response.failure:
        import httpx2

        raise APIError(
            response.failure,
            request=httpx2.Request("POST", "https://llm-bridge.invalid/response"),
            body=None,
        )
