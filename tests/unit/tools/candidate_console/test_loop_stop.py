"""Authored-loop Stop route and honest loop state in StatusView.

The native owner (``request_loop_stop``) is stubbed at the console service call
site except where a real refusal is cheap to reach; its marker and worker
semantics are witnessed by ``candidate_worker/test_finite_loop.py``.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.unit.tools.candidate_console.test_http import client
from tools.candidate_console import CandidateConsole, PrepareSelection
from tools.candidate_operations.models import (
    CandidateOperation,
    OperationFailure,
    OperationSnapshot,
    ProcessObservation,
)
from tools.candidate_worker.loop_models import LoopStop, LoopTrace
from tools.candidate_worker.models import CandidateRunReceipt
from workflows.definition import AuthoredLoop, LoopFeedback, ResultSource


def _stop_calls(monkeypatch, failure=None):
    calls = []

    def stop(config, operation_id):
        calls.append((config, operation_id))
        if failure is not None:
            raise failure
        return LoopStop(run_id="f" * 32, declaration_digest="d" * 64)

    monkeypatch.setattr("tools.candidate_console.service.request_loop_stop", stop)
    return calls


def test_stop_route_delegates_once_and_acknowledges_only_a_request(console_config, monkeypatch):
    """Fails if the route skips the owner, calls it twice, or claims termination."""
    calls = _stop_calls(monkeypatch)
    operation_id = uuid4()
    response = client(console_config).post(f"/api/operations/{operation_id}/loop-stop", json={})
    assert response.status_code == 200, response.text
    assert response.json() == {"operation_id": str(operation_id), "outcome": "requested"}
    assert calls == [(console_config.operation_store, operation_id)]


def test_stop_route_admission_precedes_the_owner(console_config, monkeypatch):
    """Fails if Stop is reachable without the mutation boundary or with a free-form body."""
    calls = _stop_calls(monkeypatch)
    api = client(console_config)
    url = f"/api/operations/{uuid4()}/loop-stop"
    for headers, expected in (
        ({"Authorization": ""}, 401),
        ({"Authorization": "Bearer wrong"}, 401),
        ({"Origin": ""}, 403),
        ({"Origin": "null"}, 403),
        ({"Host": "evil.invalid"}, 403),
    ):
        assert api.post(url, json={}, headers=headers).status_code == expected
    assert api.post(url, content="{}", headers={"Content-Type": "text/plain"}).status_code == 415
    refused = api.post(url, json={"secret": "DO-NOT-ECHO"})
    assert refused.status_code == 422 and "DO-NOT-ECHO" not in refused.text
    assert api.post("/api/operations/DO-NOT-ECHO/loop-stop", json={}).status_code == 422
    assert api.get(url).status_code == 405
    assert calls == []


def test_unknown_operation_is_404_and_non_loop_is_refused(console_config, monkeypatch):
    """Real owner: an absent operation is not a refusal; a prepare operation has no loop."""
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", lambda *args: None)
    service = CandidateConsole(console_config)
    selection = PrepareSelection(operation_id=uuid4(), task_id="synthetic", run_name="example")
    service.prepare(selection)
    api = client(console_config)
    assert api.post(f"/api/operations/{uuid4()}/loop-stop", json={}).status_code == 404
    response = api.post(f"/api/operations/{selection.operation_id}/loop-stop", json={})
    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "kind",
        "message": "Stop is available only for an authored candidate research loop",
    }


@pytest.mark.parametrize(
    ("code", "message"),
    (
        (
            "not_running",
            "candidate loop is terminal or not confirmed running; Stop was not recorded",
        ),
        ("not_ready", "candidate loop has not claimed its workspace yet; read status and retry"),
        ("integrity", "native operation could not be verified"),
    ),
)
def test_finished_or_unclaimed_loop_refusals_are_409_without_echo(
    console_config, monkeypatch, code, message
):
    """Fails if a terminal/unclaimed loop reads as acknowledged or native text leaks."""
    _stop_calls(monkeypatch, OperationFailure(code, "/secret/path DO-NOT-ECHO"))
    response = client(console_config).post(f"/api/operations/{uuid4()}/loop-stop", json={})
    assert response.status_code == 409
    assert response.json()["error"] == {"code": code, "message": message}
    assert "DO-NOT-ECHO" not in response.text and "/secret" not in response.text


def _loop_submission(operation_id, final_iteration):
    loop = (
        None
        if final_iteration is None
        else AuthoredLoop(
            final_iteration=final_iteration,
            feedback=LoopFeedback(
                source=ResultSource(node="train"),
                target="interpret",
                protocol="tuning-to-interpretation",
                history="native-research/v1",
            ),
        )
    )
    preview = SimpleNamespace(document=SimpleNamespace(definition=SimpleNamespace(loop=loop)))
    return CandidateOperation.model_construct(
        request_id=operation_id, request=SimpleNamespace(preview=preview)
    )


def _snapshot(operation_id, receipt):
    return OperationSnapshot.model_construct(
        operation_id=operation_id,
        kind="candidate",
        request_digest="a" * 64,
        observed_at="2026-10-27T00:00:00Z",
        state="active" if receipt is None else "completed",
        process=ProcessObservation(status="alive" if receipt is None else "exited", reason="x"),
        finishing=False,
        receipt_available=receipt is not None,
        receipt_digest=None,
        receipt=receipt,
        native_chain=None,
        reason="fixture",
    )


@pytest.mark.parametrize(
    ("final_iteration", "receipt", "expected"),
    (
        (3, None, {"final_iteration": 3, "attempted_iterations": None}),
        (
            3,
            CandidateRunReceipt.model_construct(
                run_id="f" * 32, status="stopped", loop_trace=LoopTrace(attempted_iterations=1)
            ),
            {"final_iteration": 3, "attempted_iterations": 1},
        ),
        (None, None, None),
    ),
    ids=("active-loop-no-body-count", "stopped-receipt-body-count", "fixed-candidate"),
)
def test_status_loop_bound_from_submission_and_bodies_only_from_receipt(
    console_config, monkeypatch, final_iteration, receipt, expected
):
    """Fails if an active loop loses its declared bound, or a body count is guessed."""
    operation_id = uuid4()
    monkeypatch.setattr(
        "tools.candidate_console.service.read_operation",
        lambda config, value: _snapshot(value, receipt),
    )
    monkeypatch.setattr(
        "tools.candidate_console.service.lookup_operation_request",
        lambda config, value: _loop_submission(value, final_iteration),
    )
    status = client(console_config).get(f"/api/operations/{operation_id}").json()
    assert status.get("loop") == expected
