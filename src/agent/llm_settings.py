"""Pure transport configuration shared by LLM execution and setup inspection.

These resolvers preserve the bridge's accepted values and fallback rules. They
never load dotenv, read credentials/environment, instantiate clients or resolve
node-specific routing. A None endpoint delegates to the SDK/environment; it is
not proof of an effective network destination or provider availability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


class ProviderConfig(TypedDict):
    """Static shape of a `_KNOWN_PROVIDERS` entry.

    ``base_url`` is ``None`` for providers that rely on the OpenAI SDK
    default endpoint (currently ``openai``); ``api_key_env`` and
    ``default_model`` are always populated, which lets ``os.getenv`` and
    ``self.model_name`` resolve as ``str`` without a runtime guard.
    """

    base_url: str | None
    api_key_env: str
    default_model: str


KNOWN_PROVIDERS: dict[str, ProviderConfig] = {
    "openai": {
        "base_url": None,  # SDK default
        "api_key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key_env": "GEMINI_API_KEY",
        "default_model": "gemini-3.1-flash-lite-preview",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-v4-pro",
    },
    # Claude via Bedrock/Vertex requires non-standard auth (AWS SigV4 / Google
    # OAuth).  Placeholder entry — wire up when a compatible endpoint is available.
    # "claude": {
    #     "base_url": "https://...",
    #     "api_key_env": "ANTHROPIC_API_KEY",
    #     "default_model": "claude-sonnet-4-20250514",
    # },
}

#: Per-request wall-clock timeout, in seconds, for every provider client.
#:
#: 600 s is the OpenAI SDK's OWN default (`openai._constants.DEFAULT_TIMEOUT`
#: is `Timeout(connect=5.0, read=600, write=600, pool=600)` at v2.26.0,
#: verified locally rather than read from docs). This bridge previously
#: hardcoded 120 s — one fifth of that — with no recorded justification.
#:
#: WHY IT CHANGED (operator decision, 2026-08-17). A real Gate run proved the
#: 120 s bound was killing legitimate work: the implementor's code-generation
#: call against a reasoning model exceeded it TEN consecutive times and the
#: chain never reached training, while an independent probe to the same model
#: with a small prompt returned in 1.3 s. The API was healthy; our own client
#: was the thing hanging up. Long generations are precisely what this system
#: asks an implementor to do, so a bound below the vendor default cannot be
#: the right policy.
DEFAULT_REQUEST_TIMEOUT_SECONDS = 600.0

#: Bounded retry budget for TIMEOUT and CONNECTION errors — total attempts,
#: not additional ones.
#:
#: Kept separate from `max_retries` (which governs 429 / 5xx) because the two
#: failures mean different things. A 503 says "try again shortly" and usually
#: heals. A timeout says "this request did not fit the budget" — and retrying
#: it unchanged reproduces the same outcome. Combined with the old
#: `timeout=120s, max_retries=None`, that produced a genuinely pathological
#: loop: kill at 120 s, back off, kill at 120 s, forever, making no progress
#: and billing every attempt.
DEFAULT_TIMEOUT_RETRIES = 3


@dataclass(frozen=True)
class MainTransportSettings:
    """Resolved public settings; no credentials or client objects."""

    provider: str
    model_id: str | None
    base_url: str | None
    reasoning_effort: str | None
    request_timeout: float
    timeout_retries: int


@dataclass(frozen=True)
class ReflectTransportSettings:
    """Reflector inheritance, including whether the main client is reused."""

    provider: str
    model_id: str | None
    base_url: str | None
    reasoning_effort: str | None
    reuse_main_client: bool


def resolve_main_transport(
    *,
    provider: str,
    model_id: str | None = None,
    base_url: str | None = None,
    reasoning_effort: str | None = None,
    request_timeout: float | None = None,
    timeout_retries: int | None = None,
) -> MainTransportSettings:
    """Resolve the existing bridge defaults without constructing a provider."""
    normalized = provider.lower()
    if reasoning_effort is not None and normalized != "openai":
        raise ValueError("reasoning_effort requires the OpenAI provider")
    timeout = DEFAULT_REQUEST_TIMEOUT_SECONDS if request_timeout is None else float(request_timeout)
    retries = DEFAULT_TIMEOUT_RETRIES if timeout_retries is None else int(timeout_retries)
    known = KNOWN_PROVIDERS.get(normalized)
    if base_url is None and known:
        base_url = known["base_url"]
    if model_id is None and known:
        model_id = known["default_model"]
    return MainTransportSettings(normalized, model_id, base_url, reasoning_effort, timeout, retries)


def resolve_reflect_transport(
    main: MainTransportSettings,
    *,
    provider: str | None = None,
    model_id: str | None = None,
    reasoning_effort: str | None = None,
) -> ReflectTransportSettings:
    """Preserve same-provider inheritance and cross-provider refusal rules.

    Production calls this after constructing its main client. Offline callers
    can resolve both without credentials; this does not test authentication.
    The omitted reflector model inherits the main model even across providers.
    """
    normalized = provider.lower() if provider else main.provider
    if reasoning_effort is not None and normalized != "openai":
        raise ValueError("reflect_reasoning_effort requires the OpenAI provider")
    effort = (
        reasoning_effort
        if reasoning_effort is not None
        else main.reasoning_effort
        if normalized == main.provider
        else None
    )
    reuse = normalized == main.provider
    endpoint = main.base_url
    if not reuse:
        known = KNOWN_PROVIDERS.get(normalized)
        if known is None:
            raise ValueError(
                f"Unknown reflect_provider {normalized!r}. "
                f"Known providers: {list(KNOWN_PROVIDERS.keys())}. "
                f"For ad-hoc providers, instantiate the second client "
                f"manually and assign it to LLMBridge.reflect_client "
                f"after construction."
            )
        endpoint = known["base_url"]
    return ReflectTransportSettings(normalized, model_id or main.model_id, endpoint, effort, reuse)
