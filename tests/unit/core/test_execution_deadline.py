"""Regression: a continuing allocation must survive request and retry boundaries."""

from types import SimpleNamespace

import httpx
import pytest

from agent.llm_bridge import LLMBridge
from core.execution_deadline import (
    ExecutionDeadlineExceeded,
    deadline_sleep,
    execution_deadline,
    remaining_seconds,
)


def test_nested_deadline_cannot_refresh_parent_and_scope_is_restored(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("core.execution_deadline.time.monotonic", lambda: now[0])
    with execution_deadline(10):
        now[0] = 7
        with execution_deadline(100):
            assert remaining_seconds("nested") == 3
        assert remaining_seconds("parent") == 3
        with pytest.raises(ExecutionDeadlineExceeded, match="retry wait"):
            deadline_sleep(4, "retry")
    assert remaining_seconds("outside") is None


def test_gateway_caps_request_timeout_without_mutating_client(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("core.execution_deadline.time.monotonic", lambda: now[0])
    observed = []
    client = SimpleNamespace(
        timeout=httpx.Timeout(20, connect=2),
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: observed.append(kw))),
    )
    with execution_deadline(10):
        now[0] = 7
        LLMBridge._create_completion(client, reasoning_effort=None, model="synthetic")
    assert observed[0]["timeout"].read == 3
    assert observed[0]["timeout"].connect == 2
    assert client.timeout.read == 20
    LLMBridge._create_completion(client, reasoning_effort=None, model="synthetic")
    assert "timeout" not in observed[1]


def test_gateway_rejects_a_late_success_and_does_not_retry(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("core.execution_deadline.time.monotonic", lambda: now[0])
    bridge = object.__new__(LLMBridge)

    def late():
        now[0] = 11
        return "too late"

    with execution_deadline(10), pytest.raises(ExecutionDeadlineExceeded):
        bridge._call_with_retry(late, label="late")
