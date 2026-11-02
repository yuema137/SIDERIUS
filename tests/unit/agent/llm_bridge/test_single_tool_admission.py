"""Legacy SDK responses must not silently lose calls or admit incomplete execution data."""

import json

import httpx
import pytest
from openai import OpenAI

from agent.llm_bridge import LLMBridge
from core.execution_deadline import ExecutionDeadlineExceeded, execution_deadline

TOOLS = [{"type": "function", "function": {"name": "inspect", "parameters": {"type": "object"}}}]


def call(*, name="inspect", arguments='{"value": 7}', identity="call_1"):
    return {"id": identity, "type": "function", "function": {"name": name, "arguments": arguments}}


def response(calls=None, finish="tool_calls", *, choices=1, refusal=None):
    return {
        "id": "reply_1",
        "object": "chat.completion",
        "created": 1,
        "model": "served-fixture",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "refusal": refusal,
                    "tool_calls": [call()] if calls is None else calls,
                },
            }
        ]
        * choices,
        "usage": {"prompt_tokens": 13, "completion_tokens": 5, "total_tokens": 18},
    }


@pytest.fixture
def sdk(monkeypatch, tmp_path):
    requests = []
    replies = []
    now = [0.0]
    monkeypatch.setattr("core.execution_deadline.time.monotonic", lambda: now[0])
    monkeypatch.setattr("agent.llm_bridge.load_dotenv", lambda: None)

    def handle(request):
        requests.append(json.loads(request.content))
        payload, late = replies.pop(0)
        if late:
            now[0] = 11.0
        return httpx.Response(200, json=payload)

    def client(**kwargs):
        return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle)))

    monkeypatch.setattr("agent.llm_bridge.OpenAI", client)
    bridge = LLMBridge(provider="openai", model_id="fixture", api_key="offline-key")
    bridge.set_run_context(workspace=tmp_path, iter=1, run_name="fixture", run_id="fixture")
    return bridge, replies, requests, tmp_path / "token_usage.jsonl"


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(response([call(), call(identity="call_2")]), id="multiple"),
        pytest.param(response([]), id="missing"),
        pytest.param(response(finish="length"), id="length"),
        pytest.param(response(finish="content_filter"), id="content_filter"),
        pytest.param(response(finish=None), id="unknown_finish"),
        pytest.param(response([call(name="not_offered")]), id="undeclared"),
        pytest.param(response([call(identity="")]), id="empty_id"),
        pytest.param(response([call(arguments='{"value":')]), id="malformed"),
        pytest.param(response([call(arguments="[]")]), id="array"),
        pytest.param(response([call(arguments="7")]), id="scalar"),
        pytest.param(response([call(arguments="null")]), id="null"),
        pytest.param(response(choices=0), id="no_choices"),
        pytest.param(response(choices=2), id="extra_choice"),
        pytest.param(
            response(
                [{"type": "custom", "id": "call_1", "custom": {"name": "inspect", "input": "x"}}]
            ),
            id="custom",
        ),
        pytest.param(response(refusal="declined"), id="refusal"),
    ],
)
def test_invalid_single_tool_response_records_usage_once_without_retry(sdk, value):
    bridge, replies, requests, path = sdk
    replies.append((value, False))
    with pytest.raises(ValueError):
        bridge.tool_call("system", "user", TOOLS, label="test.tool")
    assert len(requests) == 1
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["tokens"] == {"prompt": 13, "completion": 5, "total": 18}
    assert rows[0]["served_model"] == "served-fixture"


@pytest.mark.parametrize("finish", ["tool_calls", "stop"])
def test_complete_declared_call_preserves_request_and_result(sdk, finish):
    bridge, replies, requests, _ = sdk
    replies.append((response(finish=finish), False))
    result = bridge.tool_call("system", "user", TOOLS, label="test.tool")
    assert (result.name, result.arguments, result.call_id) == ("inspect", {"value": 7}, "call_1")
    assert requests[0]["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "user"},
    ]
    assert requests[0]["tools"] == TOOLS
    assert requests[0]["tool_choice"] == "auto"


def test_deadline_precedes_invalid_response_admission(sdk):
    bridge, replies, requests, path = sdk
    replies.append((response([call(), call()], finish="length"), True))
    with execution_deadline(10), pytest.raises(ExecutionDeadlineExceeded):
        bridge.tool_call("system", "user", TOOLS, label="test.tool")
    assert len(requests) == 1
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["extra"]["status"] == "deadline_exceeded"
    assert rows[0]["tokens"]["total"] == 18
