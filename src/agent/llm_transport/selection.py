"""Bridge-owned backend selection without importing optional SDKs on legacy routes."""

import os

from agent.llm_settings import OPTIONAL_PROVIDERS
from agent.llm_transport.client import PydanticClient
from agent.llm_transport.contracts import PydanticTransportConfig


def validate_output_limit(value: int | None, *, field: str = "max_output_tokens") -> None:
    """Validate explicit output ceilings independently of backend/client reuse."""
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value <= 0):
        raise ValueError(f"{field} must be a positive integer")


def optional_client(
    *,
    provider: str,
    model_id: str | None,
    base_url: str | None,
    api_key: str | None,
    timeout: float,
    max_output_tokens: int | None,
    config: PydanticTransportConfig | None = None,
) -> PydanticClient | None:
    """Return None for every existing default route; never infer a new model ID."""
    validate_output_limit(max_output_tokens)
    metadata = OPTIONAL_PROVIDERS.get(provider)
    if metadata is None and config is None:
        return None
    if not model_id:
        raise ValueError("An explicit model_id is required for the optional LLM transport")
    config = (
        PydanticTransportConfig.model_validate(config)
        if config is not None
        else (
            PydanticTransportConfig(
                protocol="anthropic" if provider == "anthropic" else "openai-chat"
            )
        )
    )
    if metadata:
        api_key = api_key if api_key is not None else os.getenv(metadata["api_key_env"])
        base_url = base_url or metadata["base_url"]
    if not api_key:
        raise ValueError(f"Missing credentials for provider {provider!r}; no foreign key fallback")
    if not base_url:
        if provider == "openai" and config.protocol.startswith("openai-"):
            base_url = "https://api.openai.com/v1"
        else:
            raise ValueError("An explicit base_url is required for this transport")
    return PydanticClient(
        config=config,
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_output_tokens=max_output_tokens,
    )
