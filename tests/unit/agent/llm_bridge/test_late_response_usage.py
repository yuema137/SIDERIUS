"""Late provider receipts must survive refusal without admitting results or retrying."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import APIStatusError

from agent.llm_bridge import LLMBridge
from agent.schemas.llm_retry import RetryPolicy
from agent.schemas.telemetry import LLMBridgeContextError
from core.execution_deadline import ExecutionDeadlineExceeded, execution_deadline
from tests.helpers.metric_fixtures import accuracy_like_spec


@pytest.fixture
def call_context(monkeypatch, tmp_path):
    now = [0.0]
    monkeypatch.setattr("core.execution_deadline.time.monotonic", lambda: now[0])
    monkeypatch.setattr("agent.llm_bridge.load_dotenv", lambda: None)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-fixture")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-reflector-fixture")
    client = Mock(timeout=httpx.Timeout(600))
    monkeypatch.setattr("agent.llm_bridge.OpenAI", Mock(return_value=client))
    bridge = LLMBridge(
        provider="openai",
        model_id="main-fixture",
        reflect_provider="deepseek",
        reflect_model_id="reflect-fixture",
        max_retries=5,
    )
    bridge.set_run_context(workspace=tmp_path, iter=1, run_name="fixture", run_id="fixture")
    return bridge, client.chat.completions.create, now, tmp_path / "token_usage.jsonl"


def response(*, usage=True, content='{"ok": true}'):
    return SimpleNamespace(
        model="served-fixture",
        usage=SimpleNamespace(prompt_tokens=17, completion_tokens=9, total_tokens=26)
        if usage
        else None,
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=None))],
    )


def invoke(bridge, route):
    if route == "reflect":
        return bridge.reflect(
            exp_id="fixture",
            hypothesis="private-hypothesis",
            actual_results={"score": 0.1},
            metric_spec=accuracy_like_spec(),
        )
    if route == "tools":
        return bridge.tool_call("private-system", "private-user", [], label="fixture.tools")
    if route == "text":
        return bridge.generate_text("private-system", "private-user", label="fixture.text")
    return bridge.generate("private-system", "private-user", label="fixture.json")


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.mark.parametrize("route", ["json", "reflect", "text", "tools"])
@pytest.mark.parametrize("has_usage", [True, False])
def test_late_success_records_known_usage_once_then_refuses(call_context, route, has_usage, capsys):
    """All successful response paths used to lose their receipt before classification."""
    bridge, create, now, path = call_context

    def late(**kwargs):
        now[0] = 11
        return response(usage=has_usage, content="private-response")

    create.side_effect = late
    with execution_deadline(10), pytest.raises(ExecutionDeadlineExceeded) as caught:
        invoke(bridge, route)
    assert create.call_count == 1
    recorded = rows(path)
    assert len(recorded) == 1
    row = recorded[0]
    assert row["extra"] == {"attempt": 0, "status": "deadline_exceeded"}
    assert row["tokens"] == (
        {"prompt": 17, "completion": 9, "total": 26}
        if has_usage
        else {"prompt": None, "completion": None, "total": None}
    )
    assert row["served_model"] == "served-fixture"
    assert row["provider"] == ("deepseek" if route == "reflect" else "openai")
    assert row["model"] == ("reflect-fixture" if route == "reflect" else "main-fixture")
    assert row["label"] == ("tuner.reflector" if route == "reflect" else f"fixture.{route}")
    log = path.read_text() + str(caught.value) + repr(caught.value)
    captured = capsys.readouterr()
    log += captured.out + captured.err
    for private in ("private-response", "private-system", "private-user", "private-hypothesis"):
        assert private not in log


def test_content_repair_keeps_earlier_receipt_and_late_attempt_index(call_context, monkeypatch):
    """Recording late work must neither relabel nor duplicate an earlier invalid JSON reply."""
    bridge, create, now, path = call_context
    monkeypatch.setattr("core.execution_deadline.time.sleep", lambda seconds: None)

    def replies(**kwargs):
        if create.call_count == 1:
            now[0] = 1
            return response(content="not json")
        now[0] = 11
        return response()

    create.side_effect = replies
    with execution_deadline(10), pytest.raises(ExecutionDeadlineExceeded):
        invoke(bridge, "json")
    assert create.call_count == 2
    assert [row["extra"] for row in rows(path)] == [
        {"attempt": 0, "status": "json_decode_error"},
        {"attempt": 1, "status": "deadline_exceeded"},
    ]


@pytest.mark.parametrize("boundary", ["before_dispatch", "transport_wait", "content_wait"])
def test_deadline_without_returned_late_response_never_invents_usage(call_context, boundary):
    """Only an actual returned response can create a receipt; waits cannot buy a fresh budget."""
    bridge, create, now, path = call_context

    def cannot_continue(**kwargs):
        now[0] = 9
        if boundary == "content_wait":
            return response(content="not json")
        request = httpx.Request("POST", "https://example.invalid")
        raise APIStatusError("fixture", response=httpx.Response(503, request=request), body=None)

    create.side_effect = cannot_continue
    with execution_deadline(10), pytest.raises(ExecutionDeadlineExceeded):
        if boundary == "before_dispatch":
            now[0] = 11
        invoke(bridge, "json")
    assert create.call_count == (0 if boundary == "before_dispatch" else 1)
    if boundary == "content_wait":
        assert [row["extra"] for row in rows(path)] == [
            {"attempt": 0, "status": "json_decode_error"}
        ]
    else:
        assert not path.exists()


@pytest.mark.parametrize("context", ["unset", "backwards_iteration", "missing_directory"])
def test_unavailable_usage_context_never_accepts_late_result(call_context, context):
    """Unbound context stays a no-op; structural telemetry errors remain fatal."""
    bridge, create, now, path = call_context
    if context == "unset":
        bridge._token_usage_path = None
    elif context == "backwards_iteration":
        bridge._last_logged_iter = 2
    else:
        bridge._token_usage_path = path.parent / "missing-directory" / "token_usage.jsonl"

    def late(**kwargs):
        now[0] = 11
        return response()

    create.side_effect = late
    exception = {
        "unset": ExecutionDeadlineExceeded,
        "backwards_iteration": LLMBridgeContextError,
        "missing_directory": OSError,
    }[context]
    with execution_deadline(10), pytest.raises(exception):
        invoke(bridge, "json")
    assert create.call_count == 1
    assert not path.exists()


def test_late_receipt_failure_cannot_restart_transport(call_context, monkeypatch):
    """An unexpected recorder error must stay outside the provider retry handler."""
    bridge, create, now, path = call_context
    request = httpx.Request("POST", "https://example.invalid")
    recorder_error = APIStatusError(
        "recorder fixture", response=httpx.Response(503, request=request), body=None
    )
    recorder = Mock(side_effect=recorder_error)
    monkeypatch.setattr(bridge, "_record_usage", recorder)

    def late(**kwargs):
        now[0] = 11
        return response()

    create.side_effect = late
    with execution_deadline(10), pytest.raises(APIStatusError) as caught:
        invoke(bridge, "json")
    assert caught.value is recorder_error
    assert create.call_count == recorder.call_count == 1
    assert not path.exists()


@pytest.mark.parametrize("reflector_limit", [1, 2])
def test_reflector_retry_override_and_late_receipt_work_together(
    call_context, monkeypatch, reflector_limit
):
    """The two fixes must preserve both call-specific limits and late usage."""
    bridge, create, now, path = call_context
    bridge.max_retries = 1
    bridge.reflect_retry_policy = RetryPolicy(max_retries=reflector_limit)
    monkeypatch.setattr("agent.llm_bridge.deadline_sleep", lambda *args: None)
    request = httpx.Request("POST", "https://example.invalid")
    transient = APIStatusError("fixture", response=httpx.Response(503, request=request), body=None)

    def replies(**kwargs):
        if create.call_count == 1:
            raise transient
        now[0] = 11
        return response()

    create.side_effect = replies
    expected = APIStatusError if reflector_limit == 1 else ExecutionDeadlineExceeded
    with execution_deadline(10), pytest.raises(expected):
        invoke(bridge, "reflect")
    assert create.call_count == reflector_limit
    assert bridge.max_retries == 1
    if reflector_limit == 1:
        assert not path.exists()
    else:
        recorded = rows(path)
        assert len(recorded) == 1
        assert recorded[0]["label"] == "tuner.reflector"
        assert recorded[0]["extra"]["status"] == "deadline_exceeded"
        assert recorded[0]["tokens"]["total"] == 26
