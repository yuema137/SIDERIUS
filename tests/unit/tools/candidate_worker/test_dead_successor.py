"""Issue #1206: a verified dead successor must not strand its paused predecessor."""

import importlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.unit.tools.candidate_prepare.conftest import selection as selection
from tools.candidate_operations import (
    CandidateLoopResumeOperation,
    CandidateLoopResumeRequest,
    CandidateOperation,
    OperationStoreConfig,
    read_operation,
    request_loop_pause,
    request_loop_stop,
    review_loop_resume,
    submit_operation,
)
from tools.candidate_operations.files import publish
from tools.candidate_operations.models import ActiveOperation, OperationFailure, ProcessIdentity
from tools.candidate_operations.read import releasable
from tools.candidate_operations.store import load_record, locked_store, require_available
from tools.candidate_worker import training

from .test_finite_loop import loop_request
from .test_finite_loop import loop_tuner as loop_tuner
from .test_interpretation import interpretation_provider as interpretation_provider
from .test_loop_resume import process_segments as process_segments
from .test_native import native_runner as native_runner
from .test_training import training_runner as training_runner


@pytest.mark.parametrize("death", ["absent", "reused", "zombie"])
def test_dead_successor_can_end_without_reusing_reservation(
    prepared, loop_tuner, interpretation_provider, process_segments, monkeypatch, tmp_path, death
):
    """Without the fix, dead readback stays unknown and the store and End remain blocked.

    Exercise real pause/resume admission and native verification. Fake only the
    successor spawn and Linux liveness, including live/unknown sandbox safeguards.
    """
    config = OperationStoreConfig(
        state_root=str(tmp_path / "operations"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    first_id, next_id = uuid4(), uuid4()
    real_tune = training.HyperparamTuningAgent.run

    def pause(self, value):
        result = real_tune(self, value)
        request_loop_pause(config, first_id)
        return result

    monkeypatch.setattr(training.HyperparamTuningAgent, "run", pause)
    submit_operation(
        config,
        CandidateOperation(request_id=first_id, request=loop_request(prepared, final_iteration=3)),
        launch_environment={"OPENAI_API_KEY": "offline-stub"},
    )
    process_segments()
    review = review_loop_resume(config, first_id)
    assert review.receipt_digest is not None
    submission = CandidateLoopResumeOperation(
        request_id=next_id,
        request=CandidateLoopResumeRequest(
            predecessor_operation_id=first_id, expected_receipt_digest=review.receipt_digest
        ),
    )
    fake_pid = 2000000000

    def spawn(path, env):
        record = load_record(config, next_id)
        publish(
            path / "process.json",
            ProcessIdentity(
                operation_id=next_id,
                request_digest=record.request_digest,
                boot_id="fixture-boot",
                pid=fake_pid,
                start_ticks=100,
            ),
        )
        return SimpleNamespace(pid=fake_pid)

    monkeypatch.setattr("tools.candidate_operations.submit.spawn", spawn)
    submit_operation(config, submission, launch_environment={"OPENAI_API_KEY": "offline-stub"})
    process = importlib.import_module("tools.candidate_operations.process")
    real_stat, real_boot = process._stat, process._boot_id()
    identity_path = Path(config.state_root) / "operations" / str(next_id) / "process.json"
    identity = ProcessIdentity.model_validate_json(identity_path.read_bytes())
    identity = identity.model_copy(update={"boot_id": real_boot})
    publish(identity_path, identity, replace=True)

    def stat(pid):
        if pid != fake_pid:
            return real_stat(pid)
        if death == "absent":
            raise FileNotFoundError()
        return ("Z", 100) if death == "zombie" else ("S", 101)

    monkeypatch.setattr(process, "_stat", stat)
    monkeypatch.setattr("tools.candidate_operations.host_liveness.session_members", lambda _: 0)
    failed = read_operation(config, next_id)
    assert failed.state == "operation_failed", failed
    assert failed.reason == "loop_process_exited"
    assert (
        failed.process.reason
        == {"absent": "pid_absent", "reused": "pid_reused", "zombie": "zombie_or_dead"}[death]
    )
    assert not failed.receipt_available
    assert releasable(config, next_id)
    predecessor = read_operation(config, first_id)
    assert predecessor.reason == "loop_successor_failed"
    assert predecessor.successor_operation_id == next_id
    assert predecessor.receipt_digest == review.receipt_digest

    # A surviving or unobservable session prevents release and End, even with a dead leader.
    for members in (1, None):
        with monkeypatch.context() as patch:
            patch.setattr(
                "tools.candidate_operations.host_liveness.session_members",
                lambda _, observed=members: observed,
            )
            assert not releasable(config, next_id)
            assert read_operation(config, first_id).reason == "native_terminal"
            with pytest.raises(OperationFailure, match="already has a successor"):
                request_loop_stop(config, first_id)

    # An unrelated live sandbox remains a writer after the operation wrapper dies.
    sandbox = identity.model_copy(update={"pid": 2000000001})
    publish(identity_path.parent / "sandbox.json", sandbox)
    with monkeypatch.context() as patch:
        patch.setattr(process, "_stat", lambda pid: ("S", 100) if pid == sandbox.pid else stat(pid))
        assert not releasable(config, next_id)
        with pytest.raises(OperationFailure, match="already has a successor"):
            request_loop_stop(config, first_id)
    (identity_path.parent / "sandbox.json").unlink()

    # Unobservable wrapper identity remains unknown; it never authorizes recovery.
    with monkeypatch.context() as patch:

        def denied(pid):
            if pid == fake_pid:
                raise PermissionError()
            return real_stat(pid)

        patch.setattr(process, "_stat", denied)
        assert read_operation(config, next_id).state == "unknown"
        assert not releasable(config, next_id)

    # No native evidence is rewritten, and a partial next body is never re-executed.
    assert review.receipt is not None
    control = Path(review.receipt.workspace) / "candidate_run"
    reservation = (control / "successor.json").read_bytes()
    (control / "iteration_002").mkdir()
    with pytest.raises(OperationFailure, match="already has a successor"):
        review_loop_resume(config, first_id)
    assert submit_operation(config, submission, launch_environment={}).observation == "existing"
    active = Path(config.state_root) / "active.json"
    with locked_store(config) as root:
        require_available(root, lambda operation_id: releasable(config, operation_id))
    assert not active.exists()
    publish(active, ActiveOperation(operation_id=next_id))
    # The first Stop snapshot can precede session exit; the locked review then
    # proves recovery. Pointer release must use admission, not stale display text.
    recovery = importlib.import_module("tools.candidate_operations.loop_recovery")
    real_failed_successor = recovery.failed_successor
    observations = 0

    def successor_after_first_read(record):
        nonlocal observations
        observations += 1
        return None if observations == 1 else real_failed_successor(record)

    monkeypatch.setattr(recovery, "failed_successor", successor_after_first_read)
    marker = request_loop_stop(config, first_id)
    assert not active.exists()
    assert request_loop_stop(config, first_id) == marker
    assert (control / "successor.json").read_bytes() == reservation
    assert read_operation(config, first_id).receipt_digest == review.receipt_digest
    assert not (identity_path.parent / "completion.json").exists()


def test_dead_loop_root_releases_admission_for_new_prepare(
    prepared, selection, monkeypatch, tmp_path
):
    """Second #1206 witness: Prepare must get past a dead loop root, but not unknown liveness."""
    from tools.candidate_operations import PrepareOperation
    from tools.candidate_operations.process import current_identity

    config = OperationStoreConfig(
        state_root=str(tmp_path / "operations"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    root_id = uuid4()
    spawned = []

    def spawn(path, env):
        spawned.append(path.name)
        record = load_record(config, root_id)
        publish(path / "process.json", current_identity(record))
        return SimpleNamespace(pid=123)

    monkeypatch.setattr("tools.candidate_operations.submit.spawn", spawn)
    submit_operation(
        config,
        CandidateOperation(request_id=root_id, request=loop_request(prepared, final_iteration=2)),
        launch_environment={"OPENAI_API_KEY": "offline-stub"},
    )
    process = importlib.import_module("tools.candidate_operations.process")
    request = PrepareOperation(request_id=uuid4(), request=selection)
    active = Path(config.state_root) / "active.json"
    with monkeypatch.context() as patch:

        def denied(_):
            raise PermissionError()

        patch.setattr(process, "_stat", denied)
        with pytest.raises(OperationFailure, match="active or unresolved"):
            submit_operation(config, request, launch_environment={})
        assert ActiveOperation.model_validate_json(active.read_bytes()).operation_id == root_id
    monkeypatch.setattr(process, "_stat", lambda _: ("Z", 0))
    monkeypatch.setattr("tools.candidate_operations.host_liveness.session_members", lambda _: 0)
    assert read_operation(config, root_id).reason == "loop_process_exited"
    monkeypatch.setattr(
        "tools.candidate_operations.submit.spawn",
        lambda path, env: spawned.append(path.name) or SimpleNamespace(pid=124),
    )
    handle = submit_operation(config, request, launch_environment={})
    assert handle.observation == "starting"
    assert spawned == [str(root_id), str(request.request_id)]
    assert (
        ActiveOperation.model_validate_json(active.read_bytes()).operation_id == request.request_id
    )


@pytest.fixture
def dead_loop_observation(prepared, monkeypatch, tmp_path):
    """Admit a root without dispatch, then simulate same-boot wrapper exit."""
    from tools.candidate_operations.process import current_identity

    config = OperationStoreConfig(
        state_root=str(tmp_path / "operations"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    operation_id = uuid4()
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", lambda *_: None)
    submit_operation(
        config,
        CandidateOperation(
            request_id=operation_id, request=loop_request(prepared, final_iteration=2)
        ),
        launch_environment={"OPENAI_API_KEY": "offline-stub"},
    )
    record = load_record(config, operation_id)
    path = Path(config.state_root) / "operations" / str(operation_id)
    identity = current_identity(record).model_copy(update={"pid": 2000000000})
    publish(path / "process.json", identity)

    def absent(_):
        raise FileNotFoundError()

    monkeypatch.setattr("tools.candidate_operations.process._stat", absent)
    monkeypatch.setattr("tools.candidate_operations.host_liveness.session_members", lambda _: 0)
    return config, record, path, identity


@pytest.mark.parametrize("sandbox_state", ["alive", "unknown"])
def test_dead_wrapper_is_not_failed_while_sandbox_is_unresolved(
    dead_loop_observation, monkeypatch, sandbox_state
):
    """N1: terminal failure must not be displayed while another writer may survive."""
    config, record, path, identity = dead_loop_observation
    sandbox = identity.model_copy(update={"pid": identity.pid + 1})
    publish(path / "sandbox.json", sandbox)

    def stat(pid):
        if pid == identity.pid:
            raise FileNotFoundError()
        if sandbox_state == "unknown":
            raise PermissionError()
        return "S", sandbox.start_ticks

    monkeypatch.setattr("tools.candidate_operations.process._stat", stat)
    monkeypatch.setattr(
        "tools.candidate_operations.host_liveness.session_members",
        lambda pid: 0 if pid == identity.pid else 1 if sandbox_state == "alive" else None,
    )
    snapshot = read_operation(config, record.submission.request_id)
    assert snapshot.state == "unknown"
    assert snapshot.reason == "loop_process_exiting"
    assert snapshot.process.status == "exited"
    assert not snapshot.receipt_available
    assert not releasable(config, record.submission.request_id)


@pytest.mark.parametrize("read_kind", ["snapshot", "release"])
def test_completion_published_before_observed_exit_is_not_missed(
    dead_loop_observation, monkeypatch, read_kind
):
    """N3: a completion published during observation must govern that same read."""
    from tools.candidate_operations.models import Completion, ProcessObservation

    config, record, path, _ = dead_loop_observation

    def exit_after_completion(_):
        publish(
            path / "completion.json",
            Completion(
                operation_id=record.submission.request_id,
                request_digest=record.request_digest,
                outcome="unknown",
                reason="native_outcome_unresolved",
            ),
        )
        return ProcessObservation(status="exited", reason="pid_absent")

    monkeypatch.setattr("tools.candidate_operations.read.observe", exit_after_completion)
    if read_kind == "release":
        assert not releasable(config, record.submission.request_id)
    else:
        snapshot = read_operation(config, record.submission.request_id)
        assert snapshot.state == "unknown"
        assert snapshot.reason == "native_outcome_unresolved"
