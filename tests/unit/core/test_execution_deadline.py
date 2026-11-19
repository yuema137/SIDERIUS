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
    bridge.max_retries = 1

    def late():
        now[0] = 11
        return "too late"

    with execution_deadline(10), pytest.raises(ExecutionDeadlineExceeded):
        bridge._call_with_retry(late, label="late")


def test_stopped_by_names_only_the_binding_allocation(monkeypatch):
    """Defect #1590: a deadline refusal did not say which allocation refused, so a
    candidate worker could not tell its own budget running out from a shorter nested
    allocation (a Data Analysis wall-time budget). Fails if a refusal by a nested
    allocation clamped to the worker deadline is not attributed to it, if a shorter
    nested allocation's refusal is, if a wrapped refusal is missed, or if a refusal
    created with no deadline is attributed to one."""
    from core.execution_deadline import stopped_by

    now = [0.0]
    monkeypatch.setattr("core.execution_deadline.time.monotonic", lambda: now[0])
    with execution_deadline(10) as worker:
        with execution_deadline(100):  # clamped to the worker's expiry
            now[0] = 11
            with pytest.raises(ExecutionDeadlineExceeded) as clamped:
                remaining_seconds("llm.request")
        now[0] = 5
        with execution_deadline(1):  # shorter: its own expiry binds
            with pytest.raises(ExecutionDeadlineExceeded) as shorter:
                deadline_sleep(2, "llm.retry")
        try:
            raise RuntimeError("node wrapper") from clamped.value
        except RuntimeError as wrapped:
            wrapper = wrapped
    assert stopped_by(clamped.value, worker)
    assert stopped_by(wrapper, worker)
    assert not stopped_by(shorter.value, worker)
    assert not stopped_by(ExecutionDeadlineExceeded("no deadline bound"), worker)


def test_deadline_refusal_subclasses_record_the_active_allocation(monkeypatch):
    """Defect #1590: transport refusals that subclass ExecutionDeadlineExceeded
    (BackgroundWindowRefused, BackgroundDeadlineExpired) are raised by the transport,
    not by the deadline object, so they carried no allocation. Fails if a subclass
    created inside a scope does not record that scope's expiry."""
    from agent.llm_transport.background import BackgroundWindowRefused
    from core.execution_deadline import stopped_by

    monkeypatch.setattr("core.execution_deadline.time.monotonic", lambda: 0.0)
    with execution_deadline(10) as worker:
        refused = BackgroundWindowRefused("window does not fit")
    assert refused.expires_at == worker.expires_at
    assert stopped_by(refused, worker)
