"""One asynchronous Direct API request; the bridge owns retries and accounting."""

from importlib.metadata import version
from typing import Any

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
from pydantic_ai.models.openai import OpenAIChatModelSettings

from agent.llm_transport.accounting import AccountingCapture
from agent.llm_transport.client import PydanticClient
from agent.llm_transport.contracts import Choice, Completion, Message
from agent.llm_transport.providers import build_model
from agent.llm_transport.requests import translate
from agent.llm_transport.responses import measured_usage, normalize

# Explicit new-route default, not inferred from smoke input length. Callers can
# raise this through workflow max_output_tokens; truncated output is refused.
DEFAULT_ANTHROPIC_OUTPUT_TOKENS = 8192


async def request(client: PydanticClient, kwargs: dict[str, Any]) -> Completion:
    capture = AccountingCapture()
    raw = capture.raw

    timeout = kwargs.get("timeout", client.timeout)
    settings: OpenAIChatModelSettings = {"timeout": timeout}
    output_limit = kwargs.get("max_completion_tokens", client.max_output_tokens)
    if client.config.protocol == "anthropic" and output_limit is None:
        output_limit = DEFAULT_ANTHROPIC_OUTPUT_TOKENS
    if output_limit is not None:
        settings["max_tokens"] = output_limit
    if kwargs.get("reasoning_effort") is not None:
        settings["openai_reasoning_effort"] = kwargs["reasoning_effort"]
    req = httpx2.Request("POST", client.base_url)
    try:
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
    except UnexpectedModelBehavior:
        return Completion(
            choices=[Choice(message=Message())],
            model=raw.get("model") if isinstance(raw.get("model"), str) else None,
            usage=measured_usage(raw),
            failure="Provider response could not be decoded by the model adapter",
        )
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
    return normalize(
        result,
        raw,
        json_mode=json_mode,
        tool_names={tool["function"]["name"] for tool in kwargs.get("tools", [])},
        metadata={
            "backend": "pydantic-ai-direct",
            "backend_version": version("pydantic-ai-slim"),
            "protocol": client.config.protocol,
            "max_output_tokens": output_limit,
            "json_output": json_mode,
        },
    )
