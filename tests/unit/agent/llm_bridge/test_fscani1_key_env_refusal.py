"""F-SCANI-1 — a credential must not be able to leave for the wrong endpoint.

**The defect, verified by construction rather than by reading.** With the
resolved provider's key env unset, ``LLMBridge`` resolved ``api_key`` to
``None`` and passed it to the SDK. The SDK falls back to ``OPENAI_API_KEY``
(``openai/_client.py``). Combined with the provider's ``base_url``, the
OpenAI credential is bound to *the other provider's endpoint* and transmitted
as a Bearer header. The only symptom is an opaque 401 — raised **after** the
key has left the machine.

Reproduced before the fix, with a sentinel::

    GEMINI_API_KEY unset, OPENAI_API_KEY="sk-SENTINEL-openai-key"
    bridge.api_key        -> None
    bridge.client.api_key -> "sk-SENTINEL-openai-key"
    bridge.client.base_url-> https://generativelanguage.googleapis.com/...

**Reachable by omission, not misconfiguration.** Several launch paths default
the provider to gemini, so a user with only ``OPENAI_API_KEY`` set and no
explicit provider argument reaches this with nothing wrong in their command.
That is what makes it a security defect rather than a usability one: the
failure mode is silent egress, and the user did nothing unusual.
"""

from __future__ import annotations

import pytest

from agent.llm_bridge import LLMBridge
from agent.schemas.telemetry import LLMBridgeContextError

SENTINEL = "sk-SENTINEL-openai-key"


@pytest.fixture
def only_openai_key(monkeypatch):
    """The exact environment that produced the leak."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", SENTINEL)


class TestTheCredentialCannotLeave:
    def test_construction_refuses_when_the_providers_key_env_is_unset(self, only_openai_key):
        """RED before the fix: construction SUCCEEDED and bound the sentinel."""
        with pytest.raises(LLMBridgeContextError) as excinfo:
            LLMBridge(provider="gemini", model_id="gemini-3.1-flash-lite-preview")

        message = str(excinfo.value)
        assert "GEMINI_API_KEY" in message, "the refusal must NAME the missing variable"
        assert "gemini" in message, "and the provider it belongs to"

    def test_no_client_exists_to_carry_the_key(self, only_openai_key):
        """The refusal is at CONSTRUCTION, before a client exists.

        Asserting the exception alone would not distinguish 'refused before
        building a client' from 'built one, then complained' — and only the
        first makes egress impossible.
        """
        with pytest.raises(LLMBridgeContextError):
            bridge = LLMBridge(provider="gemini", model_id="gemini-3.1-flash-lite-preview")
            assert not hasattr(bridge, "client"), "a client was constructed before refusing"

    def test_the_sentinel_never_reaches_a_non_openai_endpoint(self, only_openai_key, monkeypatch):
        """The property, stated positively: whenever a client for a non-OpenAI
        provider DOES get built, its key is that provider's own."""
        monkeypatch.setenv("GEMINI_API_KEY", "gm-real-key")
        bridge = LLMBridge(provider="gemini", model_id="gemini-3.1-flash-lite-preview")

        assert "googleapis" in str(bridge.client.base_url)
        assert bridge.client.api_key == "gm-real-key"
        assert bridge.client.api_key != SENTINEL


class TestTheRefusalIsScopedToTheActualHazard:
    """It fires for a CROSS-PROVIDER substitution, and only there."""

    def test_openai_with_its_own_key_unset_is_left_to_the_sdk(self, monkeypatch):
        """NOT refused here, deliberately.

        The SDK's fallback variable IS openai's own key env, so no foreign
        credential can be substituted and nothing can be sent to another
        provider's endpoint. The SDK raises its own error for the missing
        key. Refusing here as well would duplicate that with a message this
        code cannot honestly make: "this provider's endpoint would receive
        that credential" is false when the credential is the endpoint's own.
        """
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(Exception) as excinfo:
            LLMBridge(provider="openai", model_id="gpt-4o-mini")
        assert not isinstance(excinfo.value, LLMBridgeContextError), (
            "openai must be left to the SDK's own error, not pre-empted by "
            "a cross-provider refusal that does not apply to it"
        )

    def test_every_provider_whose_key_env_differs_is_covered(self, monkeypatch):
        """Census, not a roster: derived from the provider table, so a new
        provider added later is covered without editing this test."""
        from agent.llm_bridge import _KNOWN_PROVIDERS, _SDK_FALLBACK_KEY_ENV

        at_risk = [
            name
            for name, cfg in _KNOWN_PROVIDERS.items()
            if cfg["api_key_env"] != _SDK_FALLBACK_KEY_ENV
        ]
        assert at_risk, "vacuity guard: the census must find providers to check"

        monkeypatch.setenv(_SDK_FALLBACK_KEY_ENV, SENTINEL)
        for name in at_risk:
            monkeypatch.delenv(_KNOWN_PROVIDERS[name]["api_key_env"], raising=False)
            with pytest.raises(LLMBridgeContextError):
                LLMBridge(provider=name, model_id=_KNOWN_PROVIDERS[name]["default_model"])


class TestTheFixChangesNothingElse:
    def test_a_provider_with_its_key_set_is_unaffected(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "oa-real-key")
        bridge = LLMBridge(provider="openai", model_id="gpt-4o-mini")
        assert bridge.client.api_key == "oa-real-key"

    def test_an_explicit_api_key_still_wins_over_the_environment(self, only_openai_key):
        """The documented precedence is explicit arg > env > (now) refusal.

        A caller passing a key must not be refused for an unset env var — that
        would break the one path that never consults the environment at all.
        """
        bridge = LLMBridge(
            provider="gemini", model_id="gemini-3.1-flash-lite-preview", api_key="gm-explicit"
        )
        assert bridge.client.api_key == "gm-explicit"


def test_the_refusal_is_not_accompanied_by_endpoint_validation(only_openai_key, monkeypatch):
    """SCOPE PIN — a deliberate omission, pinned so implementing it fails here.

    The ruling asked for the SMALLEST repair: refuse when the key is unset.
    It explicitly did NOT ask for provenance-vs-endpoint validation — checking
    that a key's *issuer* matches the endpoint it is being sent to is a larger
    change with its own design questions.

    So a deliberately mismatched-looking key must still be accepted: this
    constructs a gemini client whose key is shaped like an OpenAI one, and
    asserts it is allowed through. If someone later adds issuer validation
    here, this fails and says the omission was a decision rather than an
    oversight.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "sk-looks-like-an-openai-key")
    bridge = LLMBridge(provider="gemini", model_id="gemini-3.1-flash-lite-preview")
    assert bridge.client.api_key == "sk-looks-like-an-openai-key"
