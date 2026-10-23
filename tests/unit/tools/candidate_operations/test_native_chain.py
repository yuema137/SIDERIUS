"""Chain recovery and release trust boundaries, independent of scientific outcomes."""

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

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
from tools.candidate_operations.process import current_identity, runtime_identity
from tools.candidate_operations.read import releasable
from tools.candidate_operations.store import claim, digest, locked_store, now
from tools.workspace_sandbox.runner import ExecutionResult, ObservedExecutionResult


@pytest.fixture
def chain(tmp_path):
    envelope = tmp_path / "envelope"
    envelope.mkdir()
    source = tmp_path / "capture.json"
    source.write_text("original removed after admission")
    config = OperationStoreConfig(
        state_root=str(tmp_path / "state"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    submission = NativeChainOperation(
        request_id=uuid4(),
        request=NativeChainOperationRequest(
            capture_path=str(source),
            capture_sha256="a" * 64,
            envelope=str(envelope),
            read_only=(),
            network=False,
            devices=(),
            environment_names=("OPENAI_API_KEY",),
            timeout_seconds=10,
            input_max_bytes=16777216,
            max_iterations_observed=2,
            max_observation_bytes=1048576,
        ),
    )
    runtime = runtime_identity()
    admission = NativeChainAdmission(
        request_digest=digest(submission),
        capture_sha256="a" * 64,
        workspace=str(envelope / "workspace"),
        final_iteration=2,
        run_name="native_test",
        recipe="native-standard-chain/v1",
        checkout=runtime.source,
        git_directory=runtime.source + "/.git",
        git_common_directory=runtime.source + "/.git",
        required_environment_names=("OPENAI_API_KEY",),
        input_files=(),
    )
    record = OperationRecord(
        native_id=uuid4(),
        submission=submission,
        request_digest=digest(submission),
        config=config,
        runtime=runtime,
        inputs=(),
        admitted_at=now(),
        native_chain_admission=admission,
    )
    with locked_store(config) as root:
        path = claim(root, record)
    marker = current_identity(record)
    publish(
        path / "process.json", marker.model_copy(update={"start_ticks": marker.start_ticks + 1})
    )
    return record, path


def test_recovery_never_reopens_capture_or_requires_keys(chain, monkeypatch):
    """Deleting fresh inputs must not trigger a second launch or lose stored identity."""
    record, _ = chain
    Path(record.submission.request.capture_path).unlink()
    Path(record.native_chain_admission.workspace).mkdir()

    def forbidden(*args, **kwargs):
        pytest.fail("fresh admission/spawn during recovery")

    monkeypatch.setattr(
        "tools.candidate_operations.submit.review_native_chain_operation", forbidden
    )
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", forbidden)
    assert (
        submit_operation(record.config, record.submission, launch_environment={}).observation
        == "existing"
    )
    snapshot = read_operation(record.config, record.submission.request_id)
    assert snapshot.state == "unknown"
    assert snapshot.native_chain.admission.final_iteration == 2
    assert snapshot.native_chain.admission.run_name == "native_test"
    assert snapshot.native_chain.admission.recipe == "native-standard-chain/v1"


def test_cross_store_fence_is_exclusive_and_not_reused(chain):
    """Two persisted stores cannot both acquire a fresh envelope, even same content."""
    record, _ = chain
    _fence(record)
    other = record.model_copy(
        update={"submission": record.submission.model_copy(update={"request_id": uuid4()})}
    )
    with pytest.raises((OSError, ValueError)):
        _fence(other)
    assert not Path(record.native_chain_admission.workspace).exists()


@pytest.mark.parametrize("cleanup", ["absent", "present", "unknown"])
@pytest.mark.parametrize("status", ["completed", "failed", "timed_out"])
def test_release_requires_cleanup_not_shell_success(chain, cleanup, status):
    """Unknown/late-present cleanup must block even exit zero; known failure can release."""
    record, path = chain
    terminal = NativeChainTerminal(
        operation_id=record.submission.request_id,
        request_digest=record.request_digest,
        capture_sha256="a" * 64,
        envelope=record.submission.request.envelope,
        workspace=record.native_chain_admission.workspace,
        runtime_digest=hashlib.sha256(encode(record.runtime)).hexdigest(),
        supervision=ObservedExecutionResult(
            execution=ExecutionResult(
                status=status, returncode=0 if status == "completed" else 124, elapsed_seconds=1
            ),
            cleanup=GroupCleanup(required=False, final=GroupObservation(status=cleanup)),
            direct_child_reaped=True,
        ),
    )
    publish(path / "native-chain-terminal.json", terminal)
    publish(
        path / "completion.json",
        Completion(
            operation_id=record.submission.request_id,
            request_digest=record.request_digest,
            outcome="native_chain",
            terminal_digest=hashlib.sha256(encode(terminal)).hexdigest(),
            reason="native_chain_terminal",
        ),
    )
    snapshot = read_operation(record.config, record.submission.request_id)
    assert snapshot.state == ("completed" if cleanup == "absent" else "unknown")
    assert snapshot.native_chain.terminal.supervision.execution.status == status
    assert not snapshot.receipt_available
    assert releasable(record.config, record.submission.request_id) == (cleanup == "absent")
    (path / "native-chain-terminal.json").write_bytes(encode(terminal) + b" ")
    assert read_operation(record.config, record.submission.request_id).reason == "integrity_failure"
    assert not releasable(record.config, record.submission.request_id)


def test_predispatch_completion_cannot_override_terminal(chain):
    record, path = chain
    (path / "native-chain-terminal.json").write_text("terminal exists, even if malformed")
    publish(
        path / "completion.json",
        Completion(
            operation_id=record.submission.request_id,
            request_digest=record.request_digest,
            outcome="pre_dispatch_failure",
            reason="refused",
        ),
    )
    assert read_operation(record.config, record.submission.request_id).reason == "integrity_failure"
    assert not releasable(record.config, record.submission.request_id)


@pytest.mark.parametrize("failure", ["pre_spawn", "post_spawn"])
def test_dispatch_classifies_only_proven_pre_spawn_failure(chain, monkeypatch, failure):
    from tools.candidate_operations.native_chain import execute_native_chain
    from tools.workspace_sandbox.runner import ObservedSpawnFailure

    record, path = chain
    monkeypatch.setattr(
        "tools.candidate_operations.native_chain.review_native_chain_operation",
        lambda *a, **k: record.native_chain_admission,
    )
    monkeypatch.setattr("tools.candidate_operations.native_chain.captured", lambda *a: None)
    monkeypatch.setattr("tools.candidate_operations.native_chain.sandbox_profile", lambda *a: None)
    monkeypatch.setattr("tools.candidate_operations.native_chain.shell_arguments", lambda *a: ())

    def failed(*args):
        raise (
            ObservedSpawnFailure("not created")
            if failure == "pre_spawn"
            else OSError("after spawn")
        )

    monkeypatch.setattr("tools.candidate_operations.native_chain.run_observed", failed)
    completion = execute_native_chain(record, path)
    assert completion.outcome == ("pre_dispatch_failure" if failure == "pre_spawn" else "unknown")


@pytest.mark.parametrize("timeout", [False, True])
def test_review_cli_bounds_subprocess_failures(chain, monkeypatch, capsys, timeout):
    import subprocess

    from tools.candidate_operations.__main__ import main

    record, path = chain
    config_path = path / "cli-config.json"
    request_path = path / "cli-request.json"
    config_path.write_text(record.config.model_dump_json())
    request_path.write_text(record.submission.model_dump_json())

    def failed(*args, **kwargs):
        if timeout:
            raise subprocess.TimeoutExpired(["private-scientific-argv"], 1)
        raise subprocess.CalledProcessError(78, ["private-scientific-argv"])

    monkeypatch.setattr(
        "tools.candidate_operations.native_chain._review_native_chain_operation", failed
    )
    monkeypatch.setattr(
        "sys.argv",
        ["operation", "review", "--store-config", str(config_path), "--request", str(request_path)],
    )
    assert main() == 2
    error = capsys.readouterr().err
    assert (
        "native_chain_admission" in error
        and "private-scientific-argv" not in error
        and "Traceback" not in error
    )
