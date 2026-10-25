"""Resume lineage and no-child proof regressions; science verification is separately gated."""

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from core.native_writer.ownership import acquire
from core.native_writer.resume import (
    adopt_reserved_writer,
    locked_registered_writer,
    reservation_name,
)
from core.runtime_control.process_group import GroupCleanup, GroupObservation
from tools.candidate_operations import read_operation, submit_operation
from tools.candidate_operations.files import encode, publish
from tools.candidate_operations.models import Completion, OperationRecord, OperationStoreConfig
from tools.candidate_operations.native_chain import _fence
from tools.candidate_operations.native_chain_models import (
    NativeChainAdmission,
    NativeChainOperation,
    NativeChainOperationRequest,
    NativeChainTerminal,
)
from tools.candidate_operations.native_resume_execute import execute_native_resume
from tools.candidate_operations.native_resume_models import (
    NativeChainResumeOperation,
    NativeChainResumeRequest,
    NativeResumeAdmission,
    NativeResumeReview,
    reservation_for,
    review_digest,
)
from tools.candidate_operations.process import current_identity, runtime_identity
from tools.candidate_operations.store import claim, digest, locked_store, now
from tools.native_chain.observation import NativeChainCheckpointObservation, NativeChainEvidence
from tools.workspace_sandbox.runner import (
    ExecutionResult,
    ObservedExecutionResult,
    ObservedSpawnFailure,
)


def exited(record, path):
    identity = current_identity(record)
    publish(
        path / "process.json", identity.model_copy(update={"start_ticks": identity.start_ticks + 1})
    )


def terminal(record, path, request, admission, evidence, *, cleanup="absent"):
    result = NativeChainTerminal(
        operation_id=record.submission.request_id,
        request_digest=record.request_digest,
        capture_sha256=request.capture_sha256,
        envelope=request.envelope,
        workspace=admission.workspace,
        runtime_digest=hashlib.sha256(encode(record.runtime)).hexdigest(),
        observation_policy=2,
        evidence=evidence,
        supervision=ObservedExecutionResult(
            execution=ExecutionResult(status="failed", returncode=137, elapsed_seconds=1),
            direct_child_reaped=True,
            cleanup=GroupCleanup(required=True, final=GroupObservation(status=cleanup)),
        ),
    )
    publish(path / "native-chain-terminal.json", result)
    done = Completion(
        operation_id=record.submission.request_id,
        request_digest=record.request_digest,
        outcome="native_chain",
        terminal_digest=hashlib.sha256(encode(result)).hexdigest(),
        reason="native_chain_terminal",
    )
    publish(path / "completion.json", done)
    return done


@pytest.fixture
def history(tmp_path, monkeypatch):
    envelope = tmp_path / "envelope"
    envelope.mkdir()
    capture = tmp_path / "capture.json"
    capture.write_text("retained input")
    config = OperationStoreConfig(
        state_root=str(tmp_path / "state"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    request = NativeChainOperationRequest(
        capture_path=str(capture),
        capture_sha256="a" * 64,
        envelope=str(envelope),
        read_only=(),
        network=False,
        devices=(),
        environment_names=(),
        timeout_seconds=30,
        input_max_bytes=4096,
        max_iterations_observed=2,
        max_observation_bytes=1048576,
    )
    submission = NativeChainOperation(request_id=uuid4(), request=request)
    runtime = runtime_identity()
    admission = NativeChainAdmission(
        request_digest=digest(submission),
        capture_sha256=request.capture_sha256,
        workspace=str(envelope / "workspace"),
        final_iteration=2,
        run_name="fixture",
        recipe="native-standard-chain/v1",
        checkout=runtime.source,
        git_directory=runtime.source + "/.git",
        git_common_directory=runtime.source + "/.git",
        required_environment_names=(),
        input_files=(),
    )
    root = OperationRecord(
        native_id=uuid4(),
        submission=submission,
        request_digest=digest(submission),
        config=config,
        runtime=runtime,
        inputs=(),
        admitted_at=now(),
        native_chain_admission=admission,
    )
    with locked_store(config) as store:
        path = claim(store, root)
    _fence(root)
    workspace = Path(admission.workspace)
    lease = acquire(workspace, capture_sha256=request.capture_sha256)
    lease.close(clean=True)
    workspace.mkdir()
    evidence = NativeChainEvidence(
        availability="available",
        token_run_id="fixture-20261025T120000-123",
        token_sidecar_sha256="b" * 64,
        checkpoints=(
            NativeChainCheckpointObservation(
                iteration=1,
                native_status="completed",
                integrity="verified",
                manifest_sha256="c" * 64,
                output_sha256="d" * 64,
                manifest_verified=True,
                artifact_verified=True,
            ),
            NativeChainCheckpointObservation(iteration=2, integrity="missing"),
        ),
    )
    current = [evidence]
    monkeypatch.setattr(
        "tools.candidate_operations.native_resume_read.chain_evidence", lambda *a, **k: current[0]
    )
    exited(root, path)
    done = terminal(root, path, request, admission, evidence)
    with locked_registered_writer(workspace) as guard:
        owner = guard.snapshot()
    admitted = NativeResumeAdmission(
        state_root=config.state_root,
        store_digest=hashlib.sha256(encode(config)).hexdigest(),
        root_operation_id=submission.request_id,
        predecessor_operation_id=submission.request_id,
        predecessor_completion_digest=hashlib.sha256(encode(done)).hexdigest(),
        baseline_operation_id=submission.request_id,
        baseline_terminal_digest=done.terminal_digest,
        root_request=request,
        root_admission=admission,
        owner=owner,
        evidence=evidence,
        start_iteration=2,
    )
    successor = NativeChainResumeOperation(
        request_id=uuid4(),
        request=NativeChainResumeRequest(
            predecessor_operation_id=submission.request_id,
            expected_review_digest=review_digest(admitted),
        ),
    )
    record = OperationRecord(
        native_id=uuid4(),
        submission=successor,
        request_digest=digest(successor),
        config=config,
        runtime=runtime,
        inputs=(),
        admitted_at=now(),
        native_resume_admission=admitted,
    )
    with locked_store(config) as store:
        child_path = claim(store, record)
    exited(record, child_path)
    return root, path, record, child_path, current


def reserve(record, *, adopt=False):
    a = record.native_resume_admission
    value = reservation_for(
        a, record.submission.request_id, record.native_id, record.request_digest
    )
    with locked_registered_writer(Path(a.root_admission.workspace)) as guard:
        guard.state.publish(reservation_name(value.predecessor_operation_id), value)
        if adopt:
            lease = adopt_reserved_writer(guard, a.owner, value)
            lease.close(clean=True)


def test_reserved_without_adoption_never_authorizes_new_science(history):
    root, _, record, _, current = history
    reserve(record)
    current[0] = current[0].model_copy(
        update={
            "checkpoints": (
                current[0].checkpoints[0],
                current[0].checkpoints[0].model_copy(update={"iteration": 2}),
            )
        }
    )
    snapshot = read_operation(root.config, root.submission.request_id)
    assert snapshot.native_chain.evidence.availability == "integrity_failure"
    assert snapshot.native_chain.terminal.evidence.checkpoints[1].integrity == "missing"


def test_adopted_suffix_is_current_but_old_terminal_and_prefix_are_immutable(history):
    root, path, record, child_path, current = history
    original = (path / "native-chain-terminal.json").read_bytes()
    reserve(record, adopt=True)
    current[0] = current[0].model_copy(
        update={
            "checkpoints": (
                current[0].checkpoints[0],
                current[0].checkpoints[0].model_copy(update={"iteration": 2}),
            )
        }
    )
    admitted = record.native_resume_admission
    terminal(record, child_path, admitted.root_request, admitted.root_admission, current[0])
    snapshot = read_operation(root.config, root.submission.request_id)
    assert snapshot.native_chain.evidence == current[0]
    assert snapshot.native_chain.terminal.evidence.checkpoints[1].integrity == "missing"
    assert snapshot.native_chain.continuation.head_operation_id == record.submission.request_id
    assert (path / "native-chain-terminal.json").read_bytes() == original
    current[0] = current[0].model_copy(update={"token_sidecar_sha256": "e" * 64})
    assert (
        read_operation(root.config, root.submission.request_id).native_chain.evidence.availability
        == "integrity_failure"
    )


@pytest.mark.parametrize("failure", ["known_no_child", "uncertain"])
def test_only_observed_spawn_failure_gets_no_child_closure(history, monkeypatch, failure):
    _, _, record, path, _ = history
    admitted = record.native_resume_admission
    monkeypatch.setattr(
        "tools.candidate_operations.native_resume_execute.review_locked",
        lambda *a, **k: NativeResumeReview(
            eligibility="ready", review_digest=review_digest(admitted), admission=admitted
        ),
    )
    monkeypatch.setattr(
        "tools.candidate_operations.native_resume_execute.sandbox_profile", lambda *a: None
    )
    monkeypatch.setattr(
        "tools.candidate_operations.native_resume_execute.verify_baseline", lambda *a: None
    )

    def failed(*a):
        raise ObservedSpawnFailure("known") if failure == "known_no_child" else OSError("uncertain")

    monkeypatch.setattr("tools.candidate_operations.native_resume_execute.run_observed", failed)
    done = execute_native_resume(record, path)
    assert done.reason == (
        "native_resume_spawn_failed"
        if failure == "known_no_child"
        else "native_resume_supervision_unresolved"
    )
    assert done.outcome == ("pre_dispatch_failure" if failure == "known_no_child" else "unknown")
    assert not (path / "native-chain-terminal.json").exists()
    publish(path / "completion.json", done)
    Path(admitted.root_request.capture_path).unlink()
    monkeypatch.setattr(
        "tools.candidate_operations.submit.review_native_chain_resume",
        lambda *a, **k: pytest.fail("same UUID re-admitted"),
    )
    monkeypatch.setattr(
        "tools.candidate_operations.submit.spawn",
        lambda *a, **k: pytest.fail("same UUID respawned"),
    )
    assert (
        submit_operation(record.config, record.submission, launch_environment={}).observation
        == "existing"
    )
    assert read_operation(record.config, record.submission.request_id).state == (
        "operation_failed" if failure == "known_no_child" else "unknown"
    )


def test_new_terminal_cannot_launder_prior_checkpoint_mutation(history):
    root, _, record, path, current = history
    reserve(record, adopt=True)
    row = current[0].checkpoints[0].model_copy(update={"manifest_sha256": "f" * 64})
    current[0] = current[0].model_copy(update={"checkpoints": (row, current[0].checkpoints[1])})
    a = record.native_resume_admission
    terminal(record, path, a.root_request, a.root_admission, current[0])
    # Current == newest terminal is insufficient: its protected prefix changed.
    assert (
        read_operation(root.config, root.submission.request_id).native_chain.evidence.availability
        == "integrity_failure"
    )


@pytest.mark.parametrize(
    "reason",
    [
        "STOP",
        "chain_stopped.json",
        ".chain_halted",
        "partial_slot",
        "no_completed",
        "failed_prefix",
    ],
)
def test_append_boundary_refuses_unsupported_recovery(history, reason):
    from tools.native_chain.resume_checks import append_boundary

    _, _, record, _, current = history
    workspace = Path(record.native_resume_admission.root_admission.workspace)
    (workspace / "iter_001").mkdir()
    evidence = current[0]
    if reason == "partial_slot":
        (workspace / "iter_002").mkdir()
    elif reason in {"no_completed", "failed_prefix"}:
        row = evidence.checkpoints[0].model_copy(
            update={"native_status": "no_records" if reason == "no_completed" else "failed"}
        )
        evidence = evidence.model_copy(update={"checkpoints": (row, evidence.checkpoints[1])})
    else:
        (workspace / reason).touch()
    with pytest.raises(ValueError):
        append_boundary(workspace, evidence, 2)


def test_control_budget_rejects_before_reading_oversized_payload(tmp_path, monkeypatch):
    import tools.candidate_operations.native_resume_lineage as lineage

    path = tmp_path / "control.json"
    path.write_bytes(b"1234")
    path.chmod(0o600)
    budget = lineage.ControlBudget()
    budget.remaining = 3
    monkeypatch.setattr(lineage.os, "read", lambda *a: pytest.fail("read beyond aggregate budget"))
    with pytest.raises(ValueError, match="resume_control_limit"):
        budget.read(path)


@pytest.mark.parametrize("status", ["alive", "unknown"])
def test_closed_science_does_not_authorize_live_or_unknown_wrapper(history, status):
    from dataclasses import replace

    from tools.candidate_operations.models import ProcessObservation
    from tools.candidate_operations.native_resume_lineage import read_lineage, require_closed

    root, _, _, _, _ = history
    node = read_lineage(root).head
    with pytest.raises(ValueError, match="active_or_unknown"):
        require_closed(
            replace(node, process=ProcessObservation(status=status, reason="fixture")), None
        )


def test_concurrent_stores_cannot_both_reserve_same_physical_predecessor(history, monkeypatch):
    """Actual flock/write-once publication arbitrates competing host adapters."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    _, _, first, path, _ = history
    alternate = first.config.model_copy(update={"state_root": first.config.state_root + "-other"})
    admitted = first.native_resume_admission.model_copy(
        update={
            "state_root": alternate.state_root,
            "store_digest": hashlib.sha256(encode(alternate)).hexdigest(),
        }
    )
    submission = NativeChainResumeOperation(
        request_id=uuid4(),
        request=NativeChainResumeRequest(
            predecessor_operation_id=admitted.predecessor_operation_id,
            expected_review_digest=review_digest(admitted),
        ),
    )
    second = first.model_copy(
        update={
            "native_id": uuid4(),
            "config": alternate,
            "submission": submission,
            "request_digest": digest(submission),
            "native_resume_admission": admitted,
        }
    )
    by_store = {r.config.state_root: r.native_resume_admission for r in (first, second)}
    monkeypatch.setattr(
        "tools.candidate_operations.native_resume_execute.review_locked",
        lambda config, *a, **k: NativeResumeReview(
            eligibility="ready",
            review_digest=review_digest(by_store[config.state_root]),
            admission=by_store[config.state_root],
        ),
    )
    monkeypatch.setattr(
        "tools.candidate_operations.native_resume_execute.sandbox_profile", lambda *a: None
    )
    monkeypatch.setattr(
        "tools.candidate_operations.native_resume_execute.verify_baseline", lambda *a: None
    )
    calls = []

    def failed(*a):
        calls.append(1)
        raise ObservedSpawnFailure("no child")

    monkeypatch.setattr("tools.candidate_operations.native_resume_execute.run_observed", failed)
    barrier = Barrier(2)

    def compete(record):
        barrier.wait(timeout=5)
        return execute_native_resume(record, path)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, (first, second)))
    assert len(calls) == 1
    assert sorted(result.reason for result in results) == [
        "native_resume_admission_failed",
        "native_resume_spawn_failed",
    ]
    assert not (path / "native-chain-terminal.json").exists()


def test_copied_predecessor_in_another_store_cannot_import_successor(history):
    """Ancestry must bind the admitted store, not merely matching operation UUIDs."""
    import shutil

    from tools.candidate_operations.native_resume_lineage import read_lineage

    root, root_path, child, _, _ = history
    reserve(child)
    config = root.config.model_copy(update={"state_root": root.config.state_root + "-copy"})
    copied = root.model_copy(update={"config": config})
    with locked_store(config) as store:
        path = claim(store, copied)
    for name in ("process.json", "completion.json", "native-chain-terminal.json"):
        shutil.copyfile(root_path / name, path / name)
        (path / name).chmod(0o600)
    # Even a complete, internally consistent copied child cannot retarget the
    # already-published physical reservation to this other store.
    admission = child.native_resume_admission.model_copy(
        update={
            "state_root": config.state_root,
            "store_digest": hashlib.sha256(encode(config)).hexdigest(),
        }
    )
    submission = child.submission.model_copy(
        update={
            "request": child.submission.request.model_copy(
                update={"expected_review_digest": review_digest(admission)}
            )
        }
    )
    copied_child = child.model_copy(
        update={
            "config": config,
            "submission": submission,
            "request_digest": digest(submission),
            "native_resume_admission": admission,
        }
    )
    with locked_store(config) as store:
        child_path = claim(store, copied_child)
    exited(copied_child, child_path)
    with pytest.raises(ValueError, match="resume_link_changed"):
        read_lineage(copied)


def test_reservation_publication_error_never_becomes_no_child_permission(history, monkeypatch):
    from core.native_writer.state import WriterState

    _, _, record, path, _ = history
    admitted = record.native_resume_admission
    monkeypatch.setattr(
        "tools.candidate_operations.native_resume_execute.review_locked",
        lambda *a, **k: NativeResumeReview(
            eligibility="ready", review_digest=review_digest(admitted), admission=admitted
        ),
    )
    publish_state = WriterState.publish

    def uncertain(state, name, value):
        publish_state(state, name, value)
        if name.startswith("successor."):
            raise OSError("publication acknowledgement lost")

    monkeypatch.setattr(WriterState, "publish", uncertain)
    monkeypatch.setattr(
        "tools.candidate_operations.native_resume_execute.run_observed",
        lambda *a: pytest.fail("dispatched after uncertain publication"),
    )
    done = execute_native_resume(record, path)
    assert done.outcome == "unknown" and done.reason == "native_resume_supervision_unresolved"
    publish(path / "completion.json", done)
    assert read_operation(record.config, record.submission.request_id).state == "unknown"


def test_stale_review_refuses_before_persisting_another_request(history, monkeypatch):
    from tools.candidate_operations.models import OperationFailure

    _, _, record, path, _ = history
    publish(
        path / "completion.json",
        Completion(
            operation_id=record.submission.request_id,
            request_digest=record.request_digest,
            outcome="pre_dispatch_failure",
            reason="native_resume_admission_failed",
        ),
    )
    a = record.native_resume_admission
    monkeypatch.setattr(
        "tools.candidate_operations.submit.review_native_chain_resume",
        lambda *args, **kw: NativeResumeReview(
            eligibility="ready", review_digest=review_digest(a), admission=a
        ),
    )
    new = NativeChainResumeOperation(
        request_id=uuid4(),
        request=NativeChainResumeRequest(
            predecessor_operation_id=a.predecessor_operation_id, expected_review_digest="0" * 64
        ),
    )
    with pytest.raises(OperationFailure, match="reviewed state changed"):
        submit_operation(record.config, new, launch_environment={})
    assert not (Path(record.config.state_root) / "operations" / str(new.request_id)).exists()


@pytest.mark.parametrize("cleanup", ["present", "unknown"])
def test_terminal_without_absent_cleanup_cannot_continue(history, cleanup):
    from dataclasses import replace

    from tools.candidate_operations.native_resume_lineage import read_lineage, require_closed

    root, _, _, _, _ = history
    node = read_lineage(root).head
    supervision = node.terminal.supervision.model_copy(
        update={"cleanup": GroupCleanup(required=True, final=GroupObservation(status=cleanup))}
    )
    changed = node.terminal.model_copy(update={"supervision": supervision})
    with pytest.raises(ValueError, match="cleanup_unresolved"):
        require_closed(replace(node, terminal=changed), None)
