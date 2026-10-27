"""Construct request-local provider SDKs with SDK retries disabled."""

from typing import TYPE_CHECKING

import httpx2

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from agent.llm_transport.client import PydanticClient


def build_model(client: "PydanticClient", model_id: str, http: httpx2.AsyncClient) -> "Model":
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
    from pydantic_ai.providers.anthropic import AnthropicProvider
    from pydantic_ai.providers.openai import OpenAIProvider

    if client.config.protocol == "anthropic":
        from anthropic import AsyncAnthropic

        sdk = AsyncAnthropic(
            api_key=client.api_key, base_url=client.base_url, http_client=http, max_retries=0
        )
        return AnthropicModel(model_id, provider=AnthropicProvider(anthropic_client=sdk))

    from openai import AsyncOpenAI

    sdk = AsyncOpenAI(
        api_key=client.api_key, base_url=client.base_url, http_client=http, max_retries=0
    )
    provider = OpenAIProvider(openai_client=sdk)
    if client.config.protocol == "openai-responses":
        return OpenAIResponsesModel(model_id, provider=provider)
    if client.provider == "zai":
        from pydantic_ai.models.zai import ZaiModel
        from pydantic_ai.providers.zai import ZaiProvider

        return ZaiModel(model_id, provider=ZaiProvider(openai_client=sdk))
    if client.provider == "moonshot":
        from pydantic_ai.providers.moonshotai import MoonshotAIProvider

        return OpenAIChatModel(model_id, provider=MoonshotAIProvider(openai_client=sdk))
    return OpenAIChatModel(model_id, provider=provider)
