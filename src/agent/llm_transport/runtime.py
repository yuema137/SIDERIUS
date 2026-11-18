"""One asynchronous Direct API request; the bridge owns retries and accounting."""

from collections.abc import Iterator
from contextlib import contextmanager
from importlib.metadata import version
from typing import TYPE_CHECKING, Any

import httpx2
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError
from pydantic_ai.direct import model_request
from pydantic_ai.exceptions import (
    ModelAPIError,
    ModelConnectionError,
    ModelHTTPError,
    ModelTimeoutError,
    UnexpectedModelBehavior,
)
from pydantic_ai.models.openai import OpenAIResponsesModelSettings

from agent.llm_transport.accounting import AccountingCapture
from agent.llm_transport.client import PydanticClient
from agent.llm_transport.contracts import Choice, Completion, Message
from agent.llm_transport.providers import build_model
from agent.llm_transport.requests import translate
from agent.llm_transport.responses import measured_usage, normalize

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelRequest, ModelResponse
    from pydantic_ai.models import Model, ModelRequestParameters

    from agent.llm_transport.background import BackgroundTicket

# Explicit new-route default, not inferred from smoke input length. Callers can
# raise this through workflow max_output_tokens; truncated output is refused.
DEFAULT_ANTHROPIC_OUTPUT_TOKENS = 8192


def _settings(
    client: PydanticClient, kwargs: dict[str, Any]
) -> tuple[OpenAIResponsesModelSettings, int | None]:
    timeout = kwargs.get("timeout", client.timeout)
    settings: OpenAIResponsesModelSettings = {"timeout": timeout}
    output_limit = kwargs.get("max_completion_tokens", client.max_output_tokens)
    if client.config.protocol == "anthropic" and output_limit is None:
        output_limit = DEFAULT_ANTHROPIC_OUTPUT_TOKENS
    if output_limit is not None:
        settings["max_tokens"] = output_limit
    if kwargs.get("reasoning_effort") is not None:
        settings["openai_reasoning_effort"] = kwargs["reasoning_effort"]
    return settings, output_limit


def _metadata(
    client: PydanticClient, output_limit: int | None, json_mode: str | None
) -> dict[str, str | int | float | None]:
    return {
        "backend": "pydantic-ai-direct",
        "backend_version": version("pydantic-ai-slim"),
        "protocol": client.config.protocol,
        "max_output_tokens": output_limit,
        "json_output": json_mode,
    }


UNDECODABLE = "Provider response could not be decoded by the model adapter"


def refused_completion(raw: dict[str, Any], message: str) -> Completion:
    """A refusal that still carries whatever usage the provider reported."""
    return Completion(
        choices=[Choice(message=Message())],
        model=raw.get("model") if isinstance(raw.get("model"), str) else None,
        usage=measured_usage(raw),
        failure=message,
    )


@contextmanager
def translated_errors(client: PydanticClient) -> Iterator[None]:
    """Map adapter failures onto the bridge's existing OpenAI error boundary."""
    req = httpx2.Request("POST", client.base_url)
    try:
        yield
    except ModelHTTPError as exc:
        response = httpx2.Response(exc.status_code, request=req, headers=exc.headers)
        raise APIStatusError(
            f"{client.provider} returned HTTP {exc.status_code}", response=response, body=exc.body
        ) from exc
    except (ModelTimeoutError, httpx2.TimeoutException) as exc:
        raise APITimeoutError(request=req) from exc
    except (ModelConnectionError, httpx2.RequestError) as exc:
        raise APIConnectionError(request=req) from exc
    except ModelAPIError as exc:
        raise APIError(f"{client.provider} model API failure", request=req, body=None) from exc


async def _create(
    client: PydanticClient,
    kwargs: dict[str, Any],
    settings: OpenAIResponsesModelSettings,
    capture: AccountingCapture,
) -> "tuple[ModelResponse, list[ModelRequest], ModelRequestParameters, str | None]":
    """Send one create request on a request-local HTTP client."""
    timeout = kwargs.get("timeout", client.timeout)
    with translated_errors(client):
        async with httpx2.AsyncClient(timeout=timeout, event_hooks={"response": [capture]}) as http:
            model = build_model(client, kwargs["model"], http)
            messages, parameters, json_mode = translate(
                kwargs,
                json_object_supported=model.profile.get("supports_json_object_output", False),
            )
            result = await model_request(
                model,
                messages,
                model_settings=settings,
                model_request_parameters=parameters,
                instrument=False,
            )
    return result, messages, parameters, json_mode


def _tool_names(kwargs: dict[str, Any]) -> set[str]:
    return {tool["function"]["name"] for tool in kwargs.get("tools", [])}


async def request(client: PydanticClient, kwargs: dict[str, Any]) -> Completion:
    capture = AccountingCapture()
    settings, output_limit = _settings(client, kwargs)
    try:
        result, _, _, json_mode = await _create(client, kwargs, settings, capture)
    except UnexpectedModelBehavior:
        return refused_completion(capture.raw, UNDECODABLE)
    return normalize(
        result,
        capture.raw,
        json_mode=json_mode,
        tool_names=_tool_names(kwargs),
        metadata=_metadata(client, output_limit, json_mode),
    )


async def submit_background(
    client: PydanticClient, kwargs: dict[str, Any]
) -> "BackgroundTicket | Completion":
    """Create one background response; return a ticket while it is still pending.

    Submission failures use the same error translation as a foreground request,
    so the bridge's submission retry policy (including unbounded 429) applies.
    A response that is already terminal at creation is normalized directly.
    """
    from agent.llm_transport.background import (
        SERVICE_TIER,
        BackgroundTicket,
        background_metadata,
    )

    config = client.config.background
    if config is None:
        raise ValueError("submit_background requires a background transport configuration")
    capture = AccountingCapture()
    settings, output_limit = _settings(client, kwargs)
    settings["openai_background"] = True
    settings["openai_service_tier"] = SERVICE_TIER
    settings["extra_body"] = {"background_options": {"completion_window": config.completion_window}}
    try:
        result, messages, parameters, json_mode = await _create(client, kwargs, settings, capture)
    except UnexpectedModelBehavior:
        return refused_completion(capture.raw, UNDECODABLE)
    metadata = _metadata(client, output_limit, json_mode)
    if result.state == "suspended" and result.provider_response_id:
        return BackgroundTicket(
            client=client,
            config=config,
            model_id=kwargs["model"],
            messages=list(messages),
            suspended=result,
            settings=settings,
            parameters=parameters,
            json_mode=json_mode,
            tool_names=_tool_names(kwargs),
            raw=capture.raw,
            metadata=metadata,
        )
    metadata.update(background_metadata(config, result.provider_response_id, capture.raw))
    return normalize(
        result, capture.raw, json_mode=json_mode, tool_names=_tool_names(kwargs), metadata=metadata
    )


async def continue_background(
    model: "Model", ticket: "BackgroundTicket", timeout: float
) -> "ModelResponse":
    """Retrieve the pending response once; adapter exceptions are left to the poll policy."""
    settings = ticket.settings.copy()
    settings["timeout"] = timeout
    return await model_request(
        model,
        [*ticket.messages, ticket.suspended],
        model_settings=settings,
        model_request_parameters=ticket.parameters,
        instrument=False,
    )
