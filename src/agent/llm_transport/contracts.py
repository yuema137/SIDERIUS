"""Private normalized response and opt-in transport configuration contracts.

Importing this module stays SDK-free: inert route settings and workflow
configuration import the transport carrier without loading provider SDKs.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

CompletionWindow = Literal["2h", "8h"]

#: Nominal length of each discounted OpenAI completion window. The provider
#: treats the window as a completion target from acceptance, not a guarantee.
COMPLETION_WINDOW_SECONDS: dict[CompletionWindow, float] = {"2h": 7200.0, "8h": 28800.0}


class OpenAIBackgroundConfig(BaseModel):
    """Opt-in OpenAI Responses background mode with a discounted completion window.

    ``max_wait_seconds`` is the caller's explicit latency budget for one request,
    measured from provider acceptance. It has no default because the window is
    only a provider target; the bridge never infers how long a run may wait.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    completion_window: CompletionWindow
    max_wait_seconds: float = Field(gt=0, allow_inf_nan=False)


class PydanticTransportConfig(BaseModel):
    """Explicit protocol override; new providers also select this backend automatically.

    This is the bridge's single per-route transport carrier. ``background`` is
    omitted from serialization when unset, so existing carriers keep their bytes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    protocol: Literal["anthropic", "openai-chat", "openai-responses"]
    background: OpenAIBackgroundConfig | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def background_requires_responses(self) -> Self:
        if self.background is not None and self.protocol != "openai-responses":
            raise ValueError("background requires protocol='openai-responses'")
        return self


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
    transport_metadata: dict[str, str | int | float | None] = Field(default_factory=dict)


def validate_completion(response: object) -> None:
    """Called after usage accounting, never inside the transport retry loop."""
    if isinstance(response, Completion) and response.failure:
        import httpx2
        from openai import APIError

        raise APIError(
            response.failure,
            request=httpx2.Request("POST", "https://llm-bridge.invalid/response"),
            body=None,
        )
