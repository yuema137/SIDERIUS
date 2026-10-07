"""Effective settings must be inspectable without an SDK or credential effects."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from agent.llm_settings import resolve_main_transport, resolve_reflect_transport


def test_fresh_process_can_resolve_without_importing_effectful_modules(tmp_path: Path) -> None:
    """Import isolation catches accidental bridge/dotenv/SDK reuse in inspection."""
    source = """
import os
import sys
from unittest.mock import patch
from agent.llm_settings import resolve_main_transport, resolve_reflect_transport
assert "agent.llm_bridge" not in sys.modules
assert "dotenv" not in sys.modules
assert "openai" not in sys.modules
with patch.object(os, "getenv", side_effect=AssertionError("credential read")):
    main = resolve_main_transport(provider="OPENAI", reasoning_effort="high")
    reflect = resolve_reflect_transport(main, provider="gemini")
assert main.model_id == "gpt-4o"
assert main.base_url is None
assert reflect.model_id == "gpt-4o"
assert reflect.reasoning_effort is None
assert not reflect.reuse_main_client
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", source],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("reflect_provider", [None, "OPENAI", "gemini"])
def test_reported_settings_match_clients_used_by_execution(monkeypatch, reflect_provider) -> None:
    """A split between displayed transport and instantiated clients must fail."""
    from agent import llm_bridge

    constructor = Mock(side_effect=lambda **kwargs: object())
    monkeypatch.setattr(llm_bridge, "OpenAI", constructor)
    monkeypatch.setattr(llm_bridge, "load_dotenv", lambda: None)
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-key")
    main = resolve_main_transport(
        provider="OPENAI",
        model_id="chosen-model",
        base_url="https://example.invalid/v1",
        reasoning_effort="high",
        request_timeout=37,
        timeout_retries=2,
    )
    reflect = resolve_reflect_transport(main, provider=reflect_provider, model_id="reflect-model")
    bridge = llm_bridge.LLMBridge(
        provider="OPENAI",
        model_id="chosen-model",
        base_url="https://example.invalid/v1",
        reasoning_effort="high",
        request_timeout=37,
        timeout_retries=2,
        reflect_provider=reflect_provider,
        reflect_model_id="reflect-model",
        api_key="fixture-key",
    )
    assert constructor.call_args_list[0].kwargs == {
        "api_key": "fixture-key",
        "max_retries": 0,
        "timeout": main.request_timeout,
        "base_url": main.base_url,
    }
    assert bridge.model_name == main.model_id
    assert bridge.reflect_model_name == reflect.model_id
    assert bridge.reflect_reasoning_effort == reflect.reasoning_effort
    assert (bridge.client is bridge.reflect_client) == reflect.reuse_main_client
    assert constructor.call_count == (1 if reflect.reuse_main_client else 2)
    if not reflect.reuse_main_client:
        assert constructor.call_args_list[1].kwargs["base_url"] == reflect.base_url


def test_invalid_reflector_still_refuses_after_main_client_construction(monkeypatch) -> None:
    """Extraction must not move a later refusal before main client setup."""
    from agent import llm_bridge

    constructor = Mock()
    monkeypatch.setattr(llm_bridge, "OpenAI", constructor)
    monkeypatch.setattr(llm_bridge, "load_dotenv", lambda: None)
    with pytest.raises(ValueError, match="Unknown reflect_provider"):
        llm_bridge.LLMBridge(provider="openai", api_key="fixture", reflect_provider="unknown")
    assert constructor.call_count == 1
