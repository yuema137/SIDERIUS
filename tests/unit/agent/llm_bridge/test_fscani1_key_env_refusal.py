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

**F-8 (v0.1.0 blinded review) — the same defect on the sibling path.** The
refusal above guarded the MAIN client only. ``LLMBridge`` builds a SECOND
client whenever ``reflect_provider`` differs from ``provider``, and that
branch read the reflect provider's key env with no ``None`` check at all, so
``--reflect_provider gemini`` with ``GEMINI_API_KEY`` unset reproduced the
leak one argument over. Re-verified by construction before the fix::

    GEMINI_API_KEY unset, OPENAI_API_KEY="sk-SENTINEL-openai-key"
    LLMBridge(provider="openai", reflect_provider="gemini")
    bridge.reflect_client.api_key  -> "sk-SENTINEL-openai-key"
    bridge.reflect_client.base_url -> https://generativelanguage.googleapis.com/...

Both clients now resolve through ``_provider_credential_or_refuse``, so the
rule is written once and the two paths cannot drift apart again.
"""

from __future__ import annotations

from unittest.mock import patch

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


class TestTheReflectClientCannotLeaveWithTheWrongCredentialEither:
    """F-8 — the second client the bridge builds is the same hazard.

    ``reflect_provider`` is a whole client, with its own ``base_url`` and its
    own key env. The main-path refusal above says nothing about it, so these
    cases fail the moment the reflect branch stops asking
    ``_provider_credential_or_refuse``.
    """

    def test_construction_refuses_when_the_reflect_providers_key_env_is_unset(
        self, only_openai_key
    ):
        """RED before the fix: construction SUCCEEDED and bound the sentinel
        to Google's endpoint."""
        with pytest.raises(LLMBridgeContextError) as excinfo:
            LLMBridge(provider="openai", model_id="gpt-4o-mini", reflect_provider="gemini")

        message = str(excinfo.value)
        assert "GEMINI_API_KEY" in message, "the refusal must NAME the missing variable"
        assert "gemini" in message, "and the provider it belongs to"

    def test_no_second_client_is_ever_constructed(self, only_openai_key):
        """The refusal happens BEFORE the second client exists.

        The main client legitimately exists by this point (it was built with
        its own key); what must not exist is a client bound to the OTHER
        provider's endpoint holding this one's credential. Counting the
        constructor calls is the only way to see that from outside — the
        bridge is never assigned, so there is no object to inspect.
        """
        with patch("agent.llm_bridge.OpenAI") as mock_openai:
            with pytest.raises(LLMBridgeContextError):
                LLMBridge(provider="openai", model_id="gpt-4o-mini", reflect_provider="gemini")

        assert mock_openai.call_count == 1, (
            "exactly one client (the main one) may be constructed before the "
            f"reflect refusal; saw {mock_openai.call_count}"
        )

    def test_the_sentinel_never_reaches_the_reflect_endpoint(self, only_openai_key, monkeypatch):
        """The property, stated positively: when a reflect client for a
        non-OpenAI provider DOES get built, its key is that provider's own."""
        monkeypatch.setenv("GEMINI_API_KEY", "gm-real-key")
        bridge = LLMBridge(provider="openai", model_id="gpt-4o-mini", reflect_provider="gemini")

        assert "googleapis" in str(bridge.reflect_client.base_url)
        assert bridge.reflect_client.api_key == "gm-real-key"
        assert bridge.reflect_client.api_key != SENTINEL
        # ...and the main client is untouched by the reflect resolution.
        assert bridge.client.api_key == SENTINEL

    def test_every_reflect_provider_whose_key_env_differs_is_covered(self, monkeypatch):
        """The same census as the main path, over the reflect argument.

        Derived from the provider table so a provider added later is covered
        on BOTH paths without editing this test — which is the property that
        was missing when the main path was fixed alone.
        """
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
                LLMBridge(
                    provider="openai",
                    model_id="gpt-4o-mini",
                    reflect_provider=name,
                    reflect_model_id=_KNOWN_PROVIDERS[name]["default_model"],
                )

    def test_an_openai_reflect_provider_is_left_to_the_sdk(self, monkeypatch):
        """Scoped exactly like the main path: the SDK's fallback variable IS
        openai's own key env, so no foreign credential can be substituted and
        pre-empting the SDK's error here would be dishonest."""
        monkeypatch.setenv("GEMINI_API_KEY", "gm-real-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(Exception) as excinfo:
            LLMBridge(
                provider="gemini",
                model_id="gemini-3.1-flash-lite-preview",
                reflect_provider="openai",
            )
        assert not isinstance(excinfo.value, LLMBridgeContextError), (
            "an openai reflect provider must be left to the SDK's own error"
        )


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
