"""Stop run route: one owner call, typed refusals without echo, and honest status projection.

The cancel owner (``request_cancel``) is stubbed at the service call site except where a
real refusal is cheap to reach; its store and child semantics are witnessed by
``candidate_operations/test_cancel.py``.
"""

from uuid import uuid4

import pytest

from tests.unit.tools.candidate_console.test_http import client
from tests.unit.tools.candidate_console.test_loop_stop import _snapshot
from tools.candidate_console import CandidateConsole, PrepareSelection
from tools.candidate_operations.models import CancelRequest, OperationFailure


def _cancel_calls(monkeypatch, failure=None):
    calls = []

    def cancel(config, operation_id):
        calls.append((config, operation_id))
        if failure is not None:
            raise failure
        return CancelRequest(operation_id=operation_id, request_digest="a" * 64, requested_at="t")

    monkeypatch.setattr("tools.candidate_console.service.request_cancel", cancel)
    return calls


def test_cancel_route_delegates_once_and_acknowledges_only_a_request(console_config, monkeypatch):
    """Fails if the route skips the owner, calls it twice, or claims the run stopped."""
    calls = _cancel_calls(monkeypatch)
    operation_id = uuid4()
    response = client(console_config).post(f"/api/operations/{operation_id}/cancel", json={})
    assert response.status_code == 200, response.text
    assert response.json() == {"operation_id": str(operation_id), "outcome": "requested"}
    assert calls == [(console_config.operation_store, operation_id)]


def test_cancel_route_admission_precedes_the_owner(console_config, monkeypatch):
    """Fails if a destructive cancel is reachable without the mutation boundary."""
    calls = _cancel_calls(monkeypatch)
    api = client(console_config)
    url = f"/api/operations/{uuid4()}/cancel"
    for headers, expected in (
        ({"Authorization": "Bearer wrong"}, 401),
        ({"Origin": "null"}, 403),
        ({"Host": "evil.invalid"}, 403),
    ):
        assert api.post(url, json={}, headers=headers).status_code == expected
    refused = api.post(url, json={"secret": "DO-NOT-ECHO"})
    assert refused.status_code == 422 and "DO-NOT-ECHO" not in refused.text
    assert api.get(url).status_code == 405
    assert calls == []


@pytest.mark.parametrize(
    ("code", "message"),
    (
        ("terminal", "this run has already finished; nothing was stopped"),
        ("starting", "the run is still starting; try again in a moment"),
        ("not_running", "the run's process is no longer running; nothing to stop"),
        ("integrity", "native operation could not be verified"),
    ),
)
def test_refusals_are_409_with_fixed_text(console_config, monkeypatch, code, message):
    """Fails if a finished run reads as stopped or a native diagnostic leaks to the page."""
    _cancel_calls(monkeypatch, OperationFailure(code, "/secret/path DO-NOT-ECHO"))
    response = client(console_config).post(f"/api/operations/{uuid4()}/cancel", json={})
    assert response.status_code == 409
    assert response.json()["error"] == {"code": code, "message": message}
    assert "DO-NOT-ECHO" not in response.text


def test_unknown_operation_is_404_and_prepare_is_refused(console_config, monkeypatch):
    """Real owner: an absent operation is not a refusal; a preparation has no Stop run."""
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", lambda *args: None)
    selection = PrepareSelection(operation_id=uuid4(), task_id="synthetic", run_name="example")
    CandidateConsole(console_config).prepare(selection)
    api = client(console_config)
    assert api.post(f"/api/operations/{uuid4()}/cancel", json={}).status_code == 404
    response = api.post(f"/api/operations/{selection.operation_id}/cancel", json={})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "kind"


@pytest.mark.parametrize("field", ["cancel_requested", "cancellable"])
@pytest.mark.parametrize("value", [False, True])
def test_status_projects_cancel_facts(console_config, monkeypatch, field, value):
    """Fails if the page cannot tell "Stopping" from running, loses the server's single
    cancellable verdict, or if an operation without them gains new status keys (existing
    status bytes must stay unchanged)."""
    operation_id = uuid4()
    snapshot = _snapshot(operation_id, None).model_copy(update={field: value})
    monkeypatch.setattr(
        "tools.candidate_console.service.read_operation", lambda config, value: snapshot
    )
    monkeypatch.setattr(
        "tools.candidate_console.service.loop_root_operation", lambda config, value: None
    )
    monkeypatch.setattr(
        "tools.candidate_console.service.operation_admitted", lambda config, value: True
    )
    status = client(console_config).get(f"/api/operations/{operation_id}").json()
    assert status.get(field, "absent") == (True if value else "absent")
