"""Authored-loop Pause/Resume routes and honest paused/resumed status.

The native owners (``request_loop_pause``, ``review_loop_resume``, ``submit_operation``)
are stubbed at the console service call site except where a real refusal is cheap;
their marker, review and reservation semantics, and the real two-segment status and
per-body results, are witnessed by ``candidate_worker/test_loop_resume.py``.
"""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.unit.tools.candidate_console.test_http import client
from tools.candidate_console import CandidateConsole, PrepareSelection
from tools.candidate_console.models import CredentialReadiness
from tools.candidate_operations import (
    CandidateLoopResumeOperation,
    CandidateLoopResumeRequest,
    OperationHandle,
)
from tools.candidate_operations.models import (
    CandidateOperation,
    OperationFailure,
    OperationSnapshot,
    ProcessObservation,
)
from tools.candidate_worker.loop_models import LoopPause, LoopTrace
from tools.candidate_worker.models import CandidateRunReceipt

SERVICE = "tools.candidate_console.service."
DIGEST = "c" * 64


def _root(final_iteration=3, names=("OPENAI_API_KEY",)):
    loop = SimpleNamespace(final_iteration=final_iteration)
    preview = SimpleNamespace(document=SimpleNamespace(definition=SimpleNamespace(loop=loop)))
    return CandidateOperation.model_construct(
        request_id=uuid4(),
        request=SimpleNamespace(preview=preview, environment_names=names),
    )


def _snapshot(operation_id, kind="candidate", receipt=None, successor=None):
    return OperationSnapshot.model_construct(
        operation_id=operation_id,
        kind=kind,
        request_digest="a" * 64,
        observed_at="2026-10-27T00:00:00Z",
        state="active" if receipt is None else "completed",
        process=ProcessObservation(status="alive" if receipt is None else "exited", reason="x"),
        successor_operation_id=successor,
        finishing=False,
        receipt_available=receipt is not None,
        receipt_digest=None if receipt is None else DIGEST,
        receipt=receipt,
        native_chain=None,
        reason="fixture",
    )


def _paused(attempted=1):
    return CandidateRunReceipt.model_construct(
        run_id="f" * 32, status="paused", loop_trace=LoopTrace(attempted_iterations=attempted)
    )


def _readiness(ready=True):
    return CredentialReadiness(
        required_names=("OPENAI_API_KEY",),
        omitted_names=(),
        unresolved_routes=(),
        present_names=("OPENAI_API_KEY",) if ready else (),
        missing_names=() if ready else ("OPENAI_API_KEY",),
        file_status="readable",
        ready=ready,
        instructions=(),
    )


def test_pause_route_delegates_once_and_acknowledges_only_a_request(console_config, monkeypatch):
    """Fails if Pause skips the owner, calls it twice, takes a body, or claims paused."""
    calls = []

    def pause(config, operation_id):
        calls.append((config, operation_id))
        return LoopPause(run_id="f" * 32, declaration_digest="d" * 64)

    monkeypatch.setattr(SERVICE + "request_loop_pause", pause)
    operation_id = uuid4()
    api = client(console_config)
    url = f"/api/operations/{operation_id}/loop-pause"
    refused = api.post(url, json={"secret": "DO-NOT-ECHO"})
    assert refused.status_code == 422 and "DO-NOT-ECHO" not in refused.text
    assert api.post(url, json={}, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert api.get(url).status_code == 405
    response = api.post(url, json={})
    assert response.status_code == 200, response.text
    assert response.json() == {"operation_id": str(operation_id), "outcome": "requested"}
    assert calls == [(console_config.operation_store, operation_id)]


def test_pause_unknown_operation_is_404_and_non_loop_is_refused(console_config, monkeypatch):
    """Real owner: an absent operation is not a refusal; a prepare operation has no loop."""
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", lambda *args: None)
    selection = PrepareSelection(operation_id=uuid4(), task_id="synthetic", run_name="example")
    CandidateConsole(console_config).prepare(selection)
    api = client(console_config)
    assert api.post(f"/api/operations/{uuid4()}/loop-pause", json={}).status_code == 404
    response = api.post(f"/api/operations/{selection.operation_id}/loop-pause", json={})
    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "kind",
        "message": "Pause is available only for an authored candidate research loop",
    }


@pytest.mark.parametrize(
    ("code", "message"),
    (
        (
            "not_running",
            "loop segment is terminal or not confirmed running; Pause was not recorded",
        ),
        ("not_ready", "candidate loop has not claimed its workspace yet; read status and retry"),
        ("integrity", "native operation could not be verified"),
    ),
)
def test_pause_refusals_are_409_without_echo(console_config, monkeypatch, code, message):
    """Fails if a terminal/unclaimed segment reads as acknowledged or native text leaks."""

    def refuse(*_):
        raise OperationFailure(code, "/secret/path DO-NOT-ECHO")

    monkeypatch.setattr(SERVICE + "request_loop_pause", refuse)
    response = client(console_config).post(f"/api/operations/{uuid4()}/loop-pause", json={})
    assert response.status_code == 409
    assert response.json()["error"] == {"code": code, "message": message}
    assert "DO-NOT-ECHO" not in response.text and "/secret" not in response.text


def test_resume_review_returns_owner_digest_bound_and_name_only_readiness(
    console_config, monkeypatch
):
    """Fails if the review invents a digest, drops the root bound, or reads another request."""
    operation_id, root = uuid4(), _root(final_iteration=4)
    seen = []
    monkeypatch.setattr(
        SERVICE + "review_loop_resume",
        lambda config, value: _snapshot(value, receipt=_paused(attempted=2)),
    )
    monkeypatch.setattr(SERVICE + "loop_root_operation", lambda config, value: root)

    def readiness(request, path):
        seen.append((request, path))
        return _readiness()

    monkeypatch.setattr(SERVICE + "credential_readiness", readiness)
    response = client(console_config).get(f"/api/operations/{operation_id}/loop-resume-review")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["predecessor_operation_id"] == str(operation_id)
    assert body["expected_receipt_digest"] == DIGEST
    assert (body["completed_iterations"], body["final_iteration"]) == (2, 4)
    assert body["credential_readiness"]["ready"] is True
    assert seen == [(root.request, console_config.credential_file)]


@pytest.mark.parametrize("code", ("loop_resume", "kind", "not_ready"))
def test_resume_refusals_are_fixed_409_on_review_and_submit(console_config, monkeypatch, code):
    """Fails if a non-resumable or stale paused segment is accepted or native text leaks."""

    def refuse(*_args, **_kwargs):
        raise OperationFailure(code, "/secret/path DO-NOT-ECHO")

    monkeypatch.setattr(SERVICE + "review_loop_resume", refuse)
    monkeypatch.setattr(SERVICE + "loop_root_operation", lambda *_: _root(names=()))
    monkeypatch.setattr(SERVICE + "submit_operation", refuse)
    api = client(console_config)
    reviewed = api.get(f"/api/operations/{uuid4()}/loop-resume-review")
    submitted = api.post(
        "/api/loop-resumes",
        json={
            "request_id": str(uuid4()),
            "predecessor_operation_id": str(uuid4()),
            "expected_receipt_digest": DIGEST,
        },
    )
    for response in (reviewed, submitted):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == code
        assert "DO-NOT-ECHO" not in response.text and "/secret" not in response.text


def _handle(operation_id, observation):
    return OperationHandle(
        operation_id=operation_id,
        kind="candidate_loop_resume",
        request_digest="b" * 64,
        observed_at="2026-10-27T00:00:00Z",
        observation=observation,
    )


def _credentials(config, text):
    secret = Path(config.auth_token_file).with_name("credentials")
    secret.write_text(text)
    secret.chmod(0o600)
    return config.model_copy(update={"credential_file": str(secret)})


def test_resume_submits_reviewed_digest_with_root_credential_names(console_config, monkeypatch):
    """Fails if Resume forgets the root's names, alters the reviewed digest, or echoes values."""
    config = _credentials(console_config, '{"OPENAI_API_KEY":"private-value","OTHER":"x"}')
    predecessor, request_id = uuid4(), uuid4()
    roots, submitted = [], []

    def root(store, value):
        roots.append(value)
        return _root()

    def submit(store, submission, launch_environment):
        submitted.append((store, submission, launch_environment))
        return _handle(submission.request_id, "starting")

    monkeypatch.setattr(SERVICE + "loop_root_operation", root)
    monkeypatch.setattr(SERVICE + "submit_operation", submit)
    response = client(config).post(
        "/api/loop-resumes",
        json={
            "request_id": str(request_id),
            "predecessor_operation_id": str(predecessor),
            "expected_receipt_digest": DIGEST,
        },
    )
    assert response.status_code == 202, response.text
    assert response.json()["operation_id"] == str(request_id)
    assert "private-value" not in response.text
    assert roots == [predecessor]
    [(store, submission, environment)] = submitted
    assert store == config.operation_store
    assert isinstance(submission, CandidateLoopResumeOperation)
    assert submission.request_id == request_id
    assert submission.request.predecessor_operation_id == predecessor
    assert submission.request.expected_receipt_digest == DIGEST
    assert environment == {"OPENAI_API_KEY": "private-value"}


def test_resume_missing_credentials_refuses_with_names_only(console_config, monkeypatch):
    """Fails if Resume dispatches without a root credential or the refusal leaks a value."""
    config = _credentials(console_config, '{"OTHER":"private-value"}')
    monkeypatch.setattr(SERVICE + "loop_root_operation", lambda *_: _root())
    monkeypatch.setattr(
        SERVICE + "submit_operation", lambda *_a, **_k: pytest.fail("submitted without names")
    )
    response = client(config).post(
        "/api/loop-resumes",
        json={
            "request_id": str(uuid4()),
            "predecessor_operation_id": str(uuid4()),
            "expected_receipt_digest": DIGEST,
        },
    )
    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "credentials",
        "message": "missing credentials: OPENAI_API_KEY",
    }
    assert "private-value" not in response.text


def test_repeated_resume_request_replays_before_credential_reads(console_config, monkeypatch):
    """Fails if a retry of an admitted request UUID needs credentials again (outcome replay)."""
    request_id, predecessor = uuid4(), uuid4()
    existing = CandidateLoopResumeOperation(
        request_id=request_id,
        request=CandidateLoopResumeRequest(
            predecessor_operation_id=predecessor, expected_receipt_digest=DIGEST
        ),
    )
    submitted = []
    monkeypatch.setattr(SERVICE + "lookup_operation_request", lambda *_: existing)
    monkeypatch.setattr(
        SERVICE + "loop_root_operation", lambda *_: pytest.fail("root/credentials read on replay")
    )

    def submit(store, submission, launch_environment):
        submitted.append((submission, launch_environment))
        return _handle(submission.request_id, "existing")

    monkeypatch.setattr(SERVICE + "submit_operation", submit)
    api = client(console_config)
    payload = {
        "request_id": str(request_id),
        "predecessor_operation_id": str(predecessor),
        "expected_receipt_digest": DIGEST,
    }
    for _ in range(2):
        response = api.post("/api/loop-resumes", json=payload)
        assert response.status_code == 202, response.text
        assert response.json()["observation"] == "existing"
    assert submitted == [(existing, {}), (existing, {})]


@pytest.mark.parametrize(
    ("kind", "receipt", "successor", "expected_loop"),
    (
        ("candidate_loop_resume", None, None, {"final_iteration": 3, "attempted_iterations": None}),
        ("candidate", _paused(1), uuid4(), {"final_iteration": 3, "attempted_iterations": 1}),
    ),
    ids=("active-resume-segment", "paused-root-with-successor"),
)
def test_status_projects_resume_segment_bound_and_successor(
    console_config, monkeypatch, kind, receipt, successor, expected_loop
):
    """Fails if a resume segment loses its root bound (hiding Stop/Pause) or the
    successor link is dropped or breaks the strict status view."""
    operation_id = uuid4()
    monkeypatch.setattr(SERVICE + "operation_admitted", lambda config, value: True)
    monkeypatch.setattr(
        SERVICE + "read_operation",
        lambda config, value: _snapshot(value, kind=kind, receipt=receipt, successor=successor),
    )
    monkeypatch.setattr(SERVICE + "loop_root_operation", lambda config, value: _root())
    response = client(console_config).get(f"/api/operations/{operation_id}")
    assert response.status_code == 200, response.text
    status = response.json()
    assert status["kind"] == kind
    assert status["loop"] == expected_loop
    assert status.get("successor_operation_id") == (None if successor is None else str(successor))
