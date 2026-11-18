"""Wire-level witnesses for opt-in OpenAI Responses background mode (#1533).

Real pydantic-ai adapters decode mocked HTTP responses; no credentials or
network participate. A fake monotonic clock drives the poll loop.
"""

import asyncio
import json

import httpx2
import pytest
from openai import APIError

import agent.llm_transport.background as background
from agent.llm_bridge import LLMBridge
from agent.llm_transport.background import (
    BackgroundDeadlineExpired,
    BackgroundWaitExpired,
    BackgroundWindowRefused,
)
from agent.llm_transport.client import PydanticClient
from agent.llm_transport.contracts import OpenAIBackgroundConfig, PydanticTransportConfig
from core.execution_deadline import ExecutionDeadlineExceeded, execution_deadline

MODEL = "gpt-6.1-terra"
RESPONSE_ID = "resp_background"


def response(status, *, text=None, usage=False, error=None):
    body = {
        "id": RESPONSE_ID,
        "object": "response",
        "created_at": 1,
        "status": status,
        "background": True,
        "model": MODEL,
        "output": [],
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "service_tier": "default",
    }
    if text is not None:
        body["output"] = [
            {
                "id": "msg_background",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ]
    if usage:
        body["usage"] = {
            "input_tokens": 13,
            "output_tokens": 5,
            "total_tokens": 18,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        }
    if error is not None:
        body["error"] = error
    return body


class Clock:
    """Monotonic time that only advances when the poll loop sleeps."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def wire(monkeypatch):
    requests = []
    responses = []
    original = httpx2.AsyncClient.__init__

    def handle(request):
        requests.append(request)
        assert responses, f"Unexpected extra request: {request.method} {request.url.path}"
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        status, payload = item
        return httpx2.Response(status, json=payload)

    def initialize(self, *args, **kwargs):
        kwargs["transport"] = httpx2.MockTransport(handle)
        kwargs["trust_env"] = False
        original(self, *args, **kwargs)

    clock = Clock()
    monkeypatch.setattr(httpx2.AsyncClient, "__init__", initialize)
    monkeypatch.setattr("agent.llm_bridge.deadline_sleep", lambda *_args: None)
    monkeypatch.setattr(background, "_now", clock.monotonic)
    monkeypatch.setattr(background.asyncio, "sleep", clock.sleep)
    return requests, responses, clock


def bridge(tmp_path, *, window="8h", max_wait=36000.0, **kwargs):
    options = {
        "provider": "openai",
        "model_id": MODEL,
        "api_key": "test-key",
        "transport": PydanticTransportConfig(
            protocol="openai-responses",
            background=OpenAIBackgroundConfig(completion_window=window, max_wait_seconds=max_wait),
        ),
    }
    options.update(kwargs)
    result = LLMBridge(**options)
    result.set_run_context(workspace=tmp_path, iter=0, run_name="bg-test", run_id="bg-test-run")
    return result


def rows(tmp_path):
    return [json.loads(line) for line in (tmp_path / "token_usage.jsonl").read_text().splitlines()]


def creates(requests):
    return [r for r in requests if r.method == "POST" and r.url.path.endswith("/responses")]


def test_background_request_shape_and_ledger_rows(wire, tmp_path):
    """Without these fields the provider bills Standard rates; without the rows,
    an orphaned billed request and its pricing basis are invisible."""
    requests, responses, _ = wire
    responses += [
        (200, response("queued")),
        (200, response("in_progress")),
        (200, response("completed", text="ready", usage=True)),
    ]
    assert bridge(tmp_path).generate_text("S", "U", label="test.bg") == "ready"
    body = json.loads(creates(requests)[0].content)
    assert body["background"] is True
    assert body["service_tier"] == "default"
    assert body["background_options"] == {"completion_window": "8h"}
    assert body.get("stream") in (None, False)
    assert [r.method for r in requests] == ["POST", "GET", "GET"]
    submitted, final = rows(tmp_path)
    assert submitted["label"] == "test.bg.background_submitted"
    assert submitted["tokens"] == {"prompt": None, "completion": None, "total": None}
    assert submitted["extra"]["background_response_id"] == RESPONSE_ID
    assert submitted["extra"]["completion_window"] == "8h"
    assert submitted["extra"]["service_tier_requested"] == "default"
    assert submitted["extra"]["model"] == MODEL
    assert final["label"] == "test.bg"
    assert final["tokens"] == {"prompt": 13, "completion": 5, "total": 18}
    assert final["extra"]["status"] == "ok"
    assert final["extra"]["background_response_id"] == RESPONSE_ID
    assert final["extra"]["service_tier_served"] == "default"
    assert final["extra"]["background_status"] == "completed"


@pytest.mark.parametrize(
    "poll_failure",
    [(500, {"error": {"message": "server", "type": "server_error"}}), httpx2.ReadTimeout("slow")],
    ids=["poll-5xx", "poll-timeout"],
)
def test_poll_failures_never_resubmit_the_accepted_request(wire, tmp_path, poll_failure):
    """A poll error escaping into the bridge retry owner would pay for the request twice."""
    requests, responses, _ = wire
    responses += [
        (200, response("queued")),
        poll_failure,
        poll_failure,
        (200, response("completed", text="ready", usage=True)),
    ]
    assert bridge(tmp_path, max_retries=5).generate_text("S", "U", label="test.bg") == "ready"
    assert len(creates(requests)) == 1
    assert [r.method for r in requests] == ["POST", "GET", "GET", "GET"]


def test_submission_429_keeps_the_unbounded_bridge_retry(wire, tmp_path):
    """Background mode must not shorten the deliberate unbounded 429 submission retry."""
    requests, responses, _ = wire
    rate_limited = (429, {"error": {"message": "slow down", "type": "rate_limit_exceeded"}})
    responses += [
        rate_limited,
        rate_limited,
        rate_limited,
        (200, response("queued")),
        (200, response("completed", text="ready", usage=True)),
    ]
    assert bridge(tmp_path, max_retries=None).generate_text("S", "U", label="test.bg") == "ready"
    assert len(creates(requests)) == 4


@pytest.mark.parametrize(
    ("deadline", "limit"),
    [(None, "max_wait_seconds"), (8000.0, "execution_deadline")],
)
def test_wait_expiry_cancels_once_records_and_raises(wire, tmp_path, monkeypatch, deadline, limit):
    """Without the bound a slow window would block the run indefinitely and keep billing."""
    requests, responses, clock = wire
    responses.append((200, response("queued")))
    responses += [(200, response("in_progress"))] * 400
    responses.append((200, response("cancelled")))
    if deadline is not None:
        # A cooperative deadline visible to the bridge, on the same fake clock.
        expires = clock.now + deadline
        monkeypatch.setattr(background, "remaining_seconds", lambda _b: expires - clock.now)
    cancels = []
    original_cancel = background._cancel

    async def counting_cancel(model, ticket):
        cancels.append(ticket.response_id)
        return await original_cancel(model, ticket)

    monkeypatch.setattr(background, "_cancel", counting_cancel)
    client = bridge(tmp_path, window="2h", max_wait=40000.0 if deadline else 600.0)
    with pytest.raises(BackgroundWaitExpired) as caught:
        client.generate_text("S", "U", label="test.bg")
    error = caught.value
    # Only the deadline-bound case may be read as a deadline verdict by callers.
    assert isinstance(error, ExecutionDeadlineExceeded) is (deadline is not None)
    assert isinstance(error, BackgroundDeadlineExpired) is (deadline is not None)
    assert (error.label, error.response_id, error.completion_window, error.limit) == (
        "test.bg",
        RESPONSE_ID,
        "2h",
        limit,
    )
    assert error.waited_seconds >= (deadline or 600.0)
    assert cancels == [RESPONSE_ID]
    assert sum(r.url.path.endswith("/cancel") for r in requests) == 1
    assert len(creates(requests)) == 1
    final = rows(tmp_path)[-1]
    assert final["label"] == "test.bg"
    assert final["extra"]["background_status"] == "wait_expired"
    assert final["extra"]["status"] == "invalid_provider_response"
    assert final["extra"]["background_waited_seconds"] == pytest.approx(error.waited_seconds)


def test_visible_deadline_shorter_than_window_refuses_before_submission(wire, tmp_path):
    """Submitting a window that cannot finish inside the deadline would bill for nothing."""
    requests, _, _ = wire
    client = bridge(tmp_path, window="2h")
    with execution_deadline(3600), pytest.raises(BackgroundWindowRefused, match="2h"):
        client.generate_text("S", "U", label="test.bg")
    assert requests == []


FAILED_BODY = response("failed", error={"code": "server_error", "message": "model crashed"})


@pytest.mark.parametrize(
    ("poll_reply", "status"),
    [
        ((200, FAILED_BODY), "failed"),
        ((400, {"error": {"message": "bad request", "type": "invalid_request_error"}}), "failed"),
        ((403, {"error": {"message": "forbidden", "type": "permission_error"}}), "failed"),
        (None, "undecodable"),
    ],
    ids=["failed-body", "poll-400", "poll-403", "undecodable"],
)
def test_terminal_poll_outcome_cancels_records_and_refuses(
    wire, tmp_path, monkeypatch, poll_reply, status
):
    """Refusing without a cancel left the accepted job billing while the caller resubmitted."""
    requests, responses, _ = wire
    responses.append((200, response("queued")))
    if poll_reply is None:
        from pydantic_ai.exceptions import UnexpectedModelBehavior

        async def undecodable(*_args):
            raise UnexpectedModelBehavior("adapter could not decode the poll response")

        monkeypatch.setattr("agent.llm_transport.runtime.continue_background", undecodable)
    else:
        responses.append(poll_reply)
    responses.append((200, response("cancelled")))
    with pytest.raises(APIError):
        bridge(tmp_path, max_retries=5).generate_text("S", "U", label="test.bg")
    assert len(creates(requests)) == 1
    assert [r.url.path.rsplit("/", 1)[-1] for r in requests][-1] == "cancel"
    assert sum(r.url.path.endswith("/cancel") for r in requests) == 1
    final = rows(tmp_path)[-1]
    assert final["extra"]["status"] == "invalid_provider_response"
    assert final["extra"]["background_status"] == status
    assert final["extra"]["background_cancel"] == "cancelled"


def test_expired_retention_needs_no_cancel(wire, tmp_path):
    """A 404 means the provider no longer has the job; a cancel would only fail."""
    requests, responses, _ = wire
    gone = (404, {"error": {"message": "not found", "type": "invalid_request_error"}})
    responses += [(200, response("queued")), gone]
    with pytest.raises(APIError, match="no longer retrievable"):
        bridge(tmp_path).generate_text("S", "U", label="test.bg")
    assert not any(r.url.path.endswith("/cancel") for r in requests)


def test_ledger_failure_before_polling_cancels_the_accepted_response(wire, tmp_path, monkeypatch):
    """A failure between acceptance and polling must not orphan a billing job."""
    requests, responses, _ = wire
    responses += [(200, response("queued")), (200, response("cancelled"))]
    client = bridge(tmp_path)

    def broken_marker(**_kwargs):
        raise OSError("ledger unavailable")

    monkeypatch.setattr(client, "emit_marker", broken_marker)
    with pytest.raises(OSError, match="ledger unavailable"):
        client.generate_text("S", "U", label="test.bg")
    assert [r.url.path.rsplit("/", 1)[-1] for r in requests] == ["responses", "cancel"]


def test_in_process_interrupt_cancels_the_accepted_response(wire, tmp_path, monkeypatch):
    """An operator interrupt must not leave an accepted 8h response running and billing."""
    requests, responses, _ = wire
    responses += [(200, response("queued")), (200, response("cancelled"))]

    async def interrupted(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(background.asyncio, "sleep", interrupted)
    with pytest.raises(asyncio.CancelledError):
        bridge(tmp_path).generate_text("S", "U", label="test.bg")
    assert [r.url.path.rsplit("/", 1)[-1] for r in requests] == ["responses", "cancel"]


def test_reflector_does_not_inherit_the_main_background_route(monkeypatch):
    """Background mode is a per-route opt-in; a shared client would silently delay the reflector."""
    monkeypatch.setattr("agent.llm_bridge.load_dotenv", lambda: None)
    shared = LLMBridge(provider="openai", model_id=MODEL, api_key="test-key")
    assert shared.reflect_client is shared.client
    opted = LLMBridge(
        provider="openai",
        model_id=MODEL,
        api_key="test-key",
        transport=PydanticTransportConfig(
            protocol="openai-responses",
            background=OpenAIBackgroundConfig(completion_window="2h", max_wait_seconds=9000),
        ),
    )
    assert isinstance(opted.client, PydanticClient)
    assert not isinstance(opted.reflect_client, PydanticClient)


def test_background_is_refused_for_other_providers():
    """The discount and request fields exist only on the OpenAI Responses API."""
    with pytest.raises(ValueError, match="provider 'openai'"):
        LLMBridge(
            provider="moonshot",
            model_id="fixture",
            api_key="test-key",
            transport=PydanticTransportConfig(
                protocol="openai-responses",
                background=OpenAIBackgroundConfig(completion_window="2h", max_wait_seconds=9000),
            ),
        )


def test_pseudo_bridge_applies_background_window_admission():
    """A pseudo run must surface a deadline shorter than the configured window."""
    from agent.llm_bridge import StubLLMBridge

    stub = StubLLMBridge(
        transport=PydanticTransportConfig(
            protocol="openai-responses",
            background=OpenAIBackgroundConfig(completion_window="2h", max_wait_seconds=9000),
        )
    )
    with execution_deadline(3600), pytest.raises(BackgroundWindowRefused):
        stub.generate_text("S", "U", label="proposer.legacy_reasoning")
    with execution_deadline(3600):
        stub._admit_stub_background("tuner.reflector")  # the reflector did not opt in
