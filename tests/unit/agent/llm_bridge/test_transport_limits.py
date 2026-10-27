"""Explicit limits must survive shared-client selection and deadline clipping."""

from unittest.mock import Mock

import httpx
import httpx2
import pytest

from agent.llm_bridge import LLMBridge
from core.execution_deadline import execution_deadline


@pytest.mark.parametrize("field", ["max_output_tokens", "reflect_max_output_tokens"])
@pytest.mark.parametrize("invalid", [0, -1, True, 1.5, "1024"])
@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_invalid_output_limit_refused_before_client_creation(monkeypatch, field, invalid, provider):
    """Reflector reuse previously bypassed validation and sent invalid provider limits."""
    sdk = Mock()
    adapter = Mock()
    monkeypatch.setattr("agent.llm_bridge.OpenAI", sdk)
    monkeypatch.setattr("agent.llm_bridge.optional_client", adapter)
    with pytest.raises(ValueError, match=field):
        LLMBridge(provider=provider, model_id="fixture", api_key="offline", **{field: invalid})
    sdk.assert_not_called()
    adapter.assert_not_called()


@pytest.mark.parametrize("timeout_class", [httpx.Timeout, httpx2.Timeout])
def test_deadline_clipping_retains_explicit_zero_phase_timeout(monkeypatch, timeout_class):
    """Zero means immediate timeout, not an omitted phase allowance."""
    monkeypatch.setattr("core.execution_deadline.time.monotonic", lambda: 0.0)
    original = timeout_class(connect=0, read=None, write=40, pool=2)
    client = Mock(timeout=original)
    with execution_deadline(10):
        LLMBridge._create_completion(client, reasoning_effort=None, model="fixture", messages=[])
    sent = client.chat.completions.create.call_args.kwargs["timeout"]
    assert type(sent) is timeout_class
    assert sent.connect == 0
    assert sent.read == 10
    assert sent.write == 10
    assert sent.pool == 2
    assert original.read is None
    assert original.write == 40


def test_omitted_output_limits_preserve_legacy_request_and_shared_client(monkeypatch):
    """The new validation must not materialize default caps on existing routes."""
    monkeypatch.setattr("agent.llm_bridge.load_dotenv", lambda: None)
    client = Mock(timeout=600)
    client.chat.completions.create.return_value = Mock(
        choices=[Mock(message=Mock(content="ready"))], usage=None, model="fixture"
    )
    monkeypatch.setattr("agent.llm_bridge.OpenAI", Mock(return_value=client))
    bridge = LLMBridge(provider="openai", model_id="fixture", api_key="offline")
    assert bridge.reflect_client is bridge.client
    assert bridge.generate_text("system", "user", label="test.limits") == "ready"
    sent = client.chat.completions.create.call_args.kwargs
    assert "max_completion_tokens" not in sent
    assert "max_tokens" not in sent
