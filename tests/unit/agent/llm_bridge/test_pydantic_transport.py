"""Wire-level regression witnesses for the opt-in Direct API transport.

Real provider adapters decode mocked HTTP responses. No provider credentials,
network, Agent retry loop or tool execution participate in these tests.
"""

import json

import httpx2
import pytest
from openai import APIError, APIStatusError, APITimeoutError

from agent.llm_bridge import LLMBridge
from agent.llm_transport.contracts import PydanticTransportConfig

MODEL = "claude-sonnet-4-20250514"
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "inspect",
            "description": "Inspect a candidate without executing training.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    }
]


def anthropic_response(content=None, *, stop="end_turn"):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": MODEL,
        "content": content if content is not None else [{"type": "text", "text": "ready"}],
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": 13, "output_tokens": 5},
    }


def tool_block(name="inspect", arguments=None, call_id="tool_1"):
    return {
        "type": "tool_use",
        "id": call_id,
        "name": name,
        "input": {"name": "candidate"} if arguments is None else arguments,
    }


def chat_response(*, finish="stop", usage=True, calls=None):
    message = {"role": "assistant", "content": "ready"}
    if calls is not None:
        message["content"] = None
        message["tool_calls"] = calls
    response = {
        "id": "chat_test",
        "object": "chat.completion",
        "created": 1,
        "model": "served-test",
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish,
            }
        ],
    }
    if usage:
        response["usage"] = {"prompt_tokens": 13, "completion_tokens": 5, "total_tokens": 18}
    return response


@pytest.fixture
def wire(monkeypatch):
    """Keep runtime event hooks intact while replacing only the HTTP transport."""
    requests = []
    responses = []
    original = httpx2.AsyncClient.__init__

    def handle(request):
        requests.append(request)
        assert responses, "Unexpected extra request: SDK/content retry escaped the bridge budget"
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, httpx2.Response):
            return response
        status, payload = response
        return httpx2.Response(status, json=payload)

    def initialize(self, *args, **kwargs):
        kwargs["transport"] = httpx2.MockTransport(handle)
        kwargs["trust_env"] = False
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx2.AsyncClient, "__init__", initialize)
    monkeypatch.setattr("agent.llm_bridge.deadline_sleep", lambda *_args: None)
    return requests, responses


def bridge(tmp_path, **kwargs):
    options = {"provider": "anthropic", "model_id": MODEL, "api_key": "test-key", "max_retries": 2}
    options.update(kwargs)
    result = LLMBridge(**options)
    result.set_run_context(
        workspace=tmp_path, iter=0, run_name="adapter-test", run_id="adapter-test-run"
    )
    return result


def rows(tmp_path):
    return [json.loads(line) for line in (tmp_path / "token_usage.jsonl").read_text().splitlines()]


def test_anthropic_large_prompt_and_explicit_output_cap_survive_translation(wire, tmp_path):
    requests, responses = wire
    responses.append((200, anthropic_response()))
    client = bridge(tmp_path, max_output_tokens=12000)
    prompt = "scientific evidence\n" * 6000
    assert client.generate_text("system contract", prompt, label="test.text") == "ready"
    payload = json.loads(requests[0].content)
    assert payload["max_tokens"] == 12000
    assert payload["messages"][0]["content"][0]["text"] == prompt
    assert requests[0].headers["authorization"] == "Bearer test-key"
    record = rows(tmp_path)[0]
    assert record["tokens"] == {"prompt": 13, "completion": 5, "total": 18}
    assert record["served_model"] == MODEL
    assert record["chars"]["user"] == len(prompt)


def test_anthropic_json_uses_constrained_output_tool_and_unwraps_value(wire, tmp_path):
    requests, responses = wire
    responses.append(
        (
            200,
            anthropic_response(
                [
                    tool_block("siderius_json_result", {"value": {"decision": "run"}}),
                ],
                stop="tool_use",
            ),
        )
    )
    assert bridge(tmp_path).generate("Return JSON", "Evaluate", label="test.json") == {
        "decision": "run"
    }
    payload = json.loads(requests[0].content)
    assert payload["tools"][0]["name"] == "siderius_json_result"
    assert "value" in payload["tools"][0]["input_schema"]["properties"]
    assert len(requests) == 1


def test_anthropic_tool_call_retains_name_arguments_and_id(wire, tmp_path):
    _, responses = wire
    responses.append((200, anthropic_response([tool_block()], stop="tool_use")))
    result = bridge(tmp_path).tool_call("Select tool", "Inspect", TOOLS, label="test.tool")
    assert (result.name, result.arguments, result.call_id) == (
        "inspect",
        {"name": "candidate"},
        "tool_1",
    )


@pytest.mark.parametrize(
    "content,stop",
    [
        ([tool_block(), tool_block(call_id="tool_2")], "tool_use"),
        ([tool_block("unknown")], "tool_use"),
        ([{"type": "text", "text": "no tool"}], "end_turn"),
        ([tool_block()], "max_tokens"),
    ],
)
def test_unusable_tool_results_are_accounted_then_refused(wire, tmp_path, content, stop):
    requests, responses = wire
    responses.append((200, anthropic_response(content, stop=stop)))
    with pytest.raises((APIError, ValueError)):
        bridge(tmp_path).tool_call("Select tool", "Inspect", TOOLS, label="test.invalid")
    assert len(requests) == 1
    assert len(rows(tmp_path)) == 1
    assert rows(tmp_path)[0]["tokens"]["completion"] == 5


@pytest.mark.parametrize("provider,host", [("moonshot", "api.moonshot.ai"), ("zai", "api.z.ai")])
def test_provider_credentials_and_endpoints_are_isolated(
    wire, tmp_path, monkeypatch, provider, host
):
    requests, responses = wire
    responses.append((200, chat_response()))
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    client = bridge(tmp_path, provider=provider, model_id="explicit-model")
    assert client.generate_text("System", "User", label="test.route") == "ready"
    assert requests[0].url.host == host
    assert requests[0].headers["authorization"] == "Bearer test-key"
    assert rows(tmp_path)[0]["served_model"] == "served-test"


def test_absent_wire_usage_remains_unknown_instead_of_library_default_zero(wire, tmp_path):
    _, responses = wire
    responses.append((200, chat_response(usage=False)))
    bridge(tmp_path, provider="moonshot", model_id="explicit").generate_text(
        "S", "U", label="test.usage"
    )
    assert rows(tmp_path)[0]["tokens"] == {"prompt": None, "completion": None, "total": None}


@pytest.mark.parametrize("finish", ["length", "content_filter"])
def test_incomplete_text_is_not_admitted_as_success(wire, tmp_path, finish):
    requests, responses = wire
    responses.append((200, chat_response(finish=finish)))
    client = bridge(tmp_path, provider="moonshot", model_id="explicit")
    with pytest.raises(APIError):
        client.generate_text("S", "U", label="test.incomplete")
    assert len(requests) == 1
    assert rows(tmp_path)[0]["tokens"]["completion"] == 5


def test_transient_http_status_is_retried_only_by_bridge(wire, tmp_path):
    requests, responses = wire
    responses.extend(
        [
            (429, {"type": "error", "error": {"type": "rate_limit_error", "message": "retry"}}),
            (200, anthropic_response()),
        ]
    )
    assert bridge(tmp_path).generate_text("S", "U", label="test.retry") == "ready"
    assert len(requests) == 2
    assert len(rows(tmp_path)) == 1


def test_authentication_failure_keeps_public_transport_error_contract(wire, tmp_path):
    requests, responses = wire
    responses.append(
        (401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid"}})
    )
    with pytest.raises(APIStatusError) as caught:
        bridge(tmp_path).generate_text("S", "U", label="test.auth")
    assert caught.value.status_code == 401
    assert len(requests) == 1


def test_network_timeout_obeys_bounded_budget_without_sdk_retries(wire, tmp_path):
    requests, responses = wire
    responses.extend([httpx2.ReadTimeout("timeout"), httpx2.ReadTimeout("timeout")])
    with pytest.raises(APITimeoutError):
        bridge(tmp_path, timeout_retries=2).generate_text("S", "U", label="test.timeout")
    assert len(requests) == 2


def test_explicit_chat_protocol_uses_new_transport_without_changing_provider(wire, tmp_path):
    requests, responses = wire
    responses.append((200, chat_response()))
    client = bridge(
        tmp_path,
        provider="openai",
        model_id="explicit",
        transport=PydanticTransportConfig(protocol="openai-chat"),
    )
    assert client.generate_text("S", "U", label="test.optin") == "ready"
    assert requests[0].url.path.endswith("/chat/completions")


def test_responses_protocol_keeps_output_cap_and_observed_model(wire, tmp_path):
    requests, responses = wire
    responses.append(
        (
            200,
            {
                "id": "resp_test",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "served-responses-model",
                "output": [
                    {
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": "ready", "annotations": []},
                        ],
                    }
                ],
                "usage": {"input_tokens": 13, "output_tokens": 5, "total_tokens": 18},
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
            },
        )
    )
    client = bridge(
        tmp_path,
        provider="openai",
        model_id="gpt-5",
        max_output_tokens=15000,
        transport=PydanticTransportConfig(protocol="openai-responses"),
    )
    assert client.generate_text("S", "U", label="test.responses") == "ready"
    assert requests[0].url.path.endswith("/responses")
    assert json.loads(requests[0].content)["max_output_tokens"] == 15000
    assert rows(tmp_path)[0]["served_model"] == "served-responses-model"


def test_malformed_tool_arguments_do_not_trigger_hidden_content_retry(wire, tmp_path):
    requests, responses = wire
    responses.append(
        (
            200,
            chat_response(
                finish="tool_calls",
                calls=[
                    {
                        "id": "tool_bad",
                        "type": "function",
                        "function": {"name": "inspect", "arguments": "{invalid"},
                    }
                ],
            ),
        )
    )
    client = bridge(tmp_path, provider="moonshot", model_id="explicit")
    with pytest.raises((APIError, ValueError)):
        client.tool_call("S", "U", TOOLS, label="test.malformed")
    assert len(requests) == 1
    assert rows(tmp_path)[0]["tokens"]["total"] == 18


def test_expired_execution_deadline_prevents_provider_request(wire, tmp_path, monkeypatch):
    from core.execution_deadline import ExecutionDeadlineExceeded, execution_deadline

    requests, _ = wire
    clock = [0.0]
    monkeypatch.setattr("core.execution_deadline.time.monotonic", lambda: clock[0])
    client = bridge(tmp_path)
    with execution_deadline(1):
        clock[0] = 2.0
        with pytest.raises(ExecutionDeadlineExceeded):
            client.generate_text("S", "U", label="test.deadline")
    assert requests == []


def test_explicit_reasoning_none_survives_wire_translation(wire, tmp_path):
    requests, responses = wire
    responses.append((200, chat_response()))
    client = bridge(
        tmp_path,
        provider="openai",
        model_id="gpt-5",
        reasoning_effort="none",
        transport=PydanticTransportConfig(protocol="openai-chat"),
    )
    assert client.generate_text("S", "U", label="test.reasoning") == "ready"
    assert json.loads(requests[0].content)["reasoning_effort"] == "none"


def test_deadline_clamps_each_native_httpx2_timeout_component(wire, tmp_path, monkeypatch):
    requests, responses = wire
    responses.append((200, anthropic_response()))
    client = bridge(tmp_path)
    client.client.timeout = httpx2.Timeout(connect=1, read=60, write=2, pool=40)
    monkeypatch.setattr("agent.llm_bridge.remaining_seconds", lambda *_args: 3.0)
    assert client.generate_text("S", "U", label="test.timeout_clamp") == "ready"
    assert requests[0].extensions["timeout"] == {"connect": 1, "read": 3, "write": 2, "pool": 3}


def test_missing_served_model_is_not_filled_from_requested_identity(wire, tmp_path):
    _, responses = wire
    payload = chat_response()
    del payload["model"]
    responses.append((200, payload))
    client = bridge(tmp_path, provider="moonshot", model_id="requested-model")
    with pytest.raises(APIError):
        client.generate_text("S", "U", label="test.identity")
    record = rows(tmp_path)[0]
    assert record["model"] == "requested-model"
    assert record["served_model"] is None


def test_partial_usage_does_not_invent_missing_counts(wire, tmp_path):
    _, responses = wire
    payload = chat_response()
    payload["usage"] = {"prompt_tokens": 0}
    responses.append((200, payload))
    with pytest.raises(APIError):
        bridge(tmp_path, provider="moonshot", model_id="explicit").generate_text(
            "S", "U", label="test.partial_usage"
        )
    assert rows(tmp_path)[0]["tokens"] == {"prompt": 0, "completion": None, "total": None}


@pytest.mark.parametrize("provider,model_id", [("moonshot", "kimi-k2.5"), ("zai", "glm-4.7")])
def test_provider_native_json_mode_does_not_force_synthetic_tools(
    wire, tmp_path, provider, model_id
):
    requests, responses = wire
    payload = chat_response()
    payload["choices"][0]["message"]["content"] = '{"decision":"run"}'
    responses.append((200, payload))
    client = bridge(tmp_path, provider=provider, model_id=model_id)
    assert client.generate("Return JSON", "Evaluate", label="test.native_json") == {
        "decision": "run"
    }
    request = json.loads(requests[0].content)
    assert request["response_format"] == {"type": "json_object"}
    assert not request.get("tools")
    assert request["messages"] == [
        {"role": "system", "content": "Return JSON"},
        {"role": "user", "content": "Evaluate"},
    ]
    assert len(requests) == 1


@pytest.mark.parametrize("provider,model_id", [("moonshot", "kimi-k2.5"), ("zai", "glm-4.7")])
def test_provider_tools_work_inside_an_existing_async_caller(wire, tmp_path, provider, model_id):
    import asyncio

    requests, responses = wire
    responses.append(
        (
            200,
            chat_response(
                finish="tool_calls",
                calls=[
                    {
                        "id": "call_inspect",
                        "type": "function",
                        "function": {"name": "inspect", "arguments": '{"name":"candidate"}'},
                    }
                ],
            ),
        )
    )
    client = bridge(tmp_path, provider=provider, model_id=model_id)

    async def call():
        return client.tool_call("Select tool", "Inspect", TOOLS, label="test.async_caller")

    result = asyncio.run(call())
    assert (result.name, result.arguments, result.call_id) == (
        "inspect",
        {"name": "candidate"},
        "call_inspect",
    )
    request = json.loads(requests[0].content)
    assert request["tools"][0]["function"]["name"] == "inspect"
    assert request["tool_choice"] == "auto"
    assert len(requests) == 1
    assert rows(tmp_path)[0]["tokens"]["total"] == 18


def event_stream(events):
    body = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)
    return httpx2.Response(200, text=body, headers={"content-type": "text/event-stream"})


def test_anthropic_stream_fallback_retains_cached_input_and_final_output(
    wire, tmp_path, monkeypatch
):
    from anthropic.resources.beta.messages import AsyncMessages

    requests, responses = wire
    original = AsyncMessages.create

    async def require_stream(self, *args, **kwargs):
        if not kwargs.get("stream"):
            raise ValueError("Streaming is required")
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(AsyncMessages, "create", require_stream)
    message = anthropic_response([], stop=None)
    message["usage"] = {
        "input_tokens": 10,
        "output_tokens": 0,
        "cache_creation_input_tokens": 20,
        "cache_read_input_tokens": 30,
    }
    responses.append(
        event_stream(
            [
                {"type": "message_start", "message": message},
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "ready"},
                },
                {"type": "content_block_stop", "index": 0},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 7},
                },
                {"type": "message_stop"},
            ]
        )
    )
    assert (
        bridge(tmp_path, max_output_tokens=64000).generate_text("S", "U", label="test.stream")
        == "ready"
    )
    assert json.loads(requests[0].content)["stream"] is True
    assert rows(tmp_path)[0]["tokens"] == {"prompt": 60, "completion": 7, "total": 67}
    assert rows(tmp_path)[0]["served_model"] == MODEL


def test_responses_completed_stream_captures_only_reported_usage():
    import asyncio

    from agent.llm_transport.accounting import AccountingCapture
    from agent.llm_transport.responses import measured_usage

    capture = AccountingCapture()
    response = event_stream(
        [
            {"type": "response.created", "response": {"model": "served", "usage": None}},
            {
                "type": "response.completed",
                "response": {"model": "served", "usage": {"input_tokens": 0}},
            },
        ]
    )
    asyncio.run(capture(response))
    assert capture.raw == {"model": "served", "usage": {"input_tokens": 0}}
    usage = measured_usage(capture.raw)
    assert usage is not None
    assert usage.model_dump() == {
        "prompt_tokens": 0,
        "completion_tokens": None,
        "total_tokens": None,
    }
    assert "response.completed" in response.text  # Capture did not consume the SDK's stream.


def test_cross_provider_reflector_uses_own_key_and_cap(wire, tmp_path, monkeypatch):
    requests, responses = wire
    monkeypatch.setenv("MOONSHOT_API_KEY", "reflect-only-key")
    responses.append((200, anthropic_response()))
    payload = chat_response()
    payload["choices"][0]["message"]["content"] = '{"reflection":"retain"}'
    responses.append((200, payload))
    client = bridge(
        tmp_path,
        max_output_tokens=9000,
        reflect_provider="moonshot",
        reflect_model_id="kimi-k2.5",
        reflect_max_output_tokens=13000,
    )
    assert client.generate_text("S", "U", label="test.main") == "ready"
    assert client._chat_json(
        client.reflect_client,
        client.reflect_model_name,
        "Return JSON",
        "Reflect",
        label="tuner.reflector",
        provider=client.reflect_provider,
    ) == {"reflection": "retain"}
    assert requests[0].headers["authorization"] == "Bearer test-key"
    assert requests[1].headers["authorization"] == "Bearer reflect-only-key"
    assert requests[1].url.host == "api.moonshot.ai"
    assert json.loads(requests[0].content)["max_tokens"] == 9000
    assert json.loads(requests[1].content)["max_completion_tokens"] == 13000
    assert [record["provider"] for record in rows(tmp_path)] == ["anthropic", "moonshot"]
