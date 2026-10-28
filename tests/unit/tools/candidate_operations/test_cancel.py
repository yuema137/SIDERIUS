"""Operator cancel of a live candidate operation: durable intent, child enforcement, readback.

The store and reader run for real against private tmp_path state. The end-to-end
case runs the operation child's ``execute`` in this process with the sandbox
command replaced by a long-running shell group, so the runner's real group
cleanup terminates real processes.
"""

import os
import subprocess
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest

from core.runtime_control.process_group import observe_group
from tests.unit.tools.candidate_worker.conftest import prepared
from tools.candidate_operations import (
    CandidateOperation,
    OperationStoreConfig,
    read_operation,
    request_cancel,
)
from tools.candidate_operations.cancel import CANCEL_FILE
from tools.candidate_operations.child import execute
from tools.candidate_operations.files import publish
from tools.candidate_operations.models import CancelRequest, OperationFailure, OperationRecord
from tools.candidate_operations.process import current_identity, identity_of, runtime_identity
from tools.candidate_operations.store import claim, digest, locked_store, now
from tools.candidate_worker.launch import publish as native_publish
from tools.candidate_worker.models import CandidateRunReceipt


@pytest.fixture
def claimed(prepared, tmp_path):
    """One admitted candidate claim; no process or native records yet."""
    config = OperationStoreConfig(
        state_root=str(tmp_path / "state"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    submission = CandidateOperation(request_id=uuid4(), request=prepared)
    record = OperationRecord(
        native_id=uuid4(),
        submission=submission,
        request_digest=digest(submission),
        config=config,
        runtime=runtime_identity(),
        inputs=prepared.files,
        admitted_at=now(),
    )
    with locked_store(config) as root:
        path = claim(root, record)
    return config, record, path


def alive(record: OperationRecord, path: Path) -> None:
    """This test process stands in for a live operation child."""
    publish(path / "process.json", current_identity(record))


def native_records(record: OperationRecord, status: str | None) -> Path:
    request = record.submission.request
    workspace = Path(request.preview.document.definition.task.workspace)
    control = workspace / "candidate_run"
    control.mkdir(parents=True)
    initial = CandidateRunReceipt(
        run_id=record.native_id.hex,
        run_name=request.run_name,
        workspace=str(workspace),
        declaration_digest=request.declaration_digest,
        status="launched",
        node_ids=tuple(node.id for node in request.preview.document.definition.nodes),
        selected_constructor_routes=request.selected_constructor_routes,
        ledger_path=str(workspace / "token_usage.jsonl"),
        log_path=str(control / "worker.log"),
    )
    native_publish(control / "request.json", request)
    native_publish(control / "launch.json", initial)
    if status is not None:
        native_publish(control / "receipt.json", initial.model_copy(update={"status": status}))
    return control


def test_cancel_is_durable_write_once_and_idempotent(claimed):
    """Fails if a repeated cancel rewrites the intent (a new timestamp or digest) instead of
    returning the first, or if the snapshot does not report the recorded intent."""
    config, record, path = claimed
    alive(record, path)
    before = read_operation(config, record.submission.request_id)
    assert before.state == "active" and "cancel_requested" not in before.model_dump_json()
    assert before.cancellable
    first = request_cancel(config, record.submission.request_id)
    payload = (path / CANCEL_FILE).read_bytes()
    assert (first.operation_id, first.request_digest) == (
        record.submission.request_id,
        record.request_digest,
    )
    time.sleep(0.01)
    assert request_cancel(config, record.submission.request_id) == first
    assert (path / CANCEL_FILE).read_bytes() == payload
    snapshot = read_operation(config, record.submission.request_id)
    assert snapshot.state == "active" and snapshot.cancel_requested
    assert not snapshot.cancellable, "a recorded cancel must not be offered again"


def test_terminal_and_unconfirmed_operations_refuse_without_recording(claimed):
    """Fails if cancel records intent for a run that already finished or is not confirmed
    alive (a later recorded intent would misreport that run as cancelled), or if the
    launch window and a vanished wrapper share one refusal (one is retryable, one never)."""
    config, record, path = claimed
    operation_id = record.submission.request_id
    with pytest.raises(OperationFailure) as refused:
        request_cancel(config, operation_id)
    assert refused.value.detail.code == "starting"
    assert not read_operation(config, operation_id).cancellable
    gone = subprocess.Popen(["/bin/sleep", "30"])
    try:
        identity = identity_of(record, gone.pid)
    finally:
        gone.kill()
        gone.wait()
    publish(path / "process.json", identity)
    with pytest.raises(OperationFailure) as refused:
        request_cancel(config, operation_id)
    assert refused.value.detail.code == "not_running"
    native_records(record, "accepted")
    with pytest.raises(OperationFailure) as refused:
        request_cancel(config, operation_id)
    assert refused.value.detail.code == "terminal"
    assert not (path / CANCEL_FILE).exists()


def test_non_candidate_kind_is_refused(admitted):
    """Fails if cancel accepts an operation whose child has no cancel probe (it would
    acknowledge a request nothing will honour)."""
    config, _, record = admitted
    with locked_store(config) as root:
        claim(root, record)
    with pytest.raises(OperationFailure) as refused:
        request_cancel(config, record.submission.request_id)
    assert refused.value.detail.code == "kind"


def test_cancelled_receipt_requires_recorded_intent(claimed):
    """Fails if a ``cancelled`` receipt without an operator request reads as a verified
    terminal (a forged or misattributed cancellation)."""
    config, record, path = claimed
    alive(record, path)
    native_records(record, "cancelled")
    forged = read_operation(config, record.submission.request_id)
    assert (forged.state, forged.reason) == ("unknown", "integrity_failure")
    assert not forged.cancellable
    # A later operator cancel must not launder the forged receipt into a verified one.
    with pytest.raises(OperationFailure) as refused:
        request_cancel(config, record.submission.request_id)
    assert refused.value.detail.code == "integrity"
    assert not (path / CANCEL_FILE).exists()
    relaunder = read_operation(config, record.submission.request_id)
    assert (relaunder.state, relaunder.reason) == ("unknown", "integrity_failure")
    # Only an intent recorded while the run was live (written directly here) vouches for it.
    publish(
        path / CANCEL_FILE,
        CancelRequest(
            operation_id=record.submission.request_id,
            request_digest=record.request_digest,
            requested_at=now(),
        ),
    )
    genuine = read_operation(config, record.submission.request_id)
    assert genuine.state == "completed" and genuine.receipt.status == "cancelled"
    assert genuine.cancel_requested


def test_child_terminates_live_sandbox_group_and_records_cancelled(claimed, monkeypatch, tmp_path):
    """End to end: Fails if the child never polls the intent (the 600 s group runs on), if
    termination misses the grandchildren, or if the outcome is failed/unknown instead of a
    verified ``cancelled`` receipt with launch records left readable."""
    from tools.workspace_sandbox import runner

    config, record, path = claimed
    leader = tmp_path / "sandbox-leader"
    monkeypatch.setattr(
        runner,
        "build_command",
        lambda profile, argv: (
            ["/bin/sh", "-c", f"echo $$ > {leader}; sleep 600 & sleep 600 & wait"],
            {"PATH": "/usr/bin:/bin"},
        ),
    )
    monkeypatch.setattr(runner, "CANCEL_POLL_SECONDS", 0.05)
    outcome: list[object] = []

    def operator():
        try:
            deadline = time.monotonic() + 60
            while not (leader.exists() and leader.read_text().strip()):
                if time.monotonic() > deadline:
                    raise TimeoutError("sandbox group never started")
                time.sleep(0.02)
            outcome.append(request_cancel(config, record.submission.request_id))
        except BaseException as error:
            outcome.append(error)

    thread = threading.Thread(target=operator)
    thread.start()
    started = time.monotonic()
    status = execute(path)
    thread.join(timeout=60)
    assert not isinstance(outcome[0], BaseException), outcome
    assert status == 0 and time.monotonic() - started < 60
    assert observe_group(int(leader.read_text())).status == "absent"
    snapshot = read_operation(config, record.submission.request_id)
    assert snapshot.state == "completed" and snapshot.cancel_requested
    assert snapshot.receipt is not None and snapshot.receipt.status == "cancelled"
    control = Path(record.submission.request.preview.document.definition.task.workspace)
    assert (control / "candidate_run" / "launch.json").is_file()
    assert os.path.isfile(path / "completion.json")
