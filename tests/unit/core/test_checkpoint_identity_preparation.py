"""CPU identity transport, mutation refusal and preparation-budget regressions."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from core.runtime_control import checkpoint_identity_runner as runner
from core.runtime_control import checkpoint_identity_worker_main as worker
from core.runtime_control import observed_subprocess as supervision
from core.runtime_control.checkpoint_identity import (
    CheckpointIdentityReceipt,
    CheckpointIdentityRequest,
)
from core.runtime_control.inference_checkpoint_reference import InferenceCheckpointReference
from core.runtime_control.observed_subprocess import (
    ObservedProcessResult,
    ProcessLifecycle,
    ProcessLimits,
    ProcessSupervisionError,
)
from core.runtime_control.process_group import (
    GroupCleanup,
    GroupObservation,
    RssObservation,
    SignalObservation,
)
from core.sandbox_layout import training_checkpoint_path


def fixture(tmp_path, *, seconds=5):
    path = training_checkpoint_path(tmp_path, "native", "attempt")
    path.write_bytes(b"known tiny checkpoint bytes\x00\xff")
    (tmp_path / "_OK_attempt").touch()
    request = CheckpointIdentityRequest(
        checkpoint_path=str(path),
        model_type="native",
        experiment_id="attempt",
        request_nonce="explicit-request-7",
        cooperative_seconds=seconds,
    )
    limits = ProcessLimits(
        deadline_seconds=seconds,
        rss_limit_bytes=256 * 1024**2,
        poll_seconds=0.01,
        grace_seconds=0.05,
        reap_seconds=0.1,
    )
    return request, limits


def reference(request):
    return InferenceCheckpointReference(
        checkpoint_path=request.checkpoint_path,
        experiment_id=request.experiment_id,
        checkpoint_sha256=hashlib.sha256(b"known tiny checkpoint bytes\x00\xff").hexdigest(),
        checkpoint_byte_size=29,
    )


def observed(request, *, receipt=None, lifecycle=None):
    receipt = receipt or CheckpointIdentityReceipt(
        request_nonce=request.request_nonce, child_pid=12345, reference=reference(request)
    )
    return ObservedProcessResult(
        completed=subprocess.CompletedProcess([], 0, stdout=receipt.model_dump_json(), stderr=""),
        lifecycle=lifecycle
        or ProcessLifecycle(
            child_pid=12345,
            owned_pgid=12345,
            elapsed_seconds=0,
            child_reaped=True,
            returncode=0,
            group_cleanup=GroupCleanup(required=False, final=GroupObservation(status="absent")),
        ),
    )


def prepare(request, limits, tmp_path):
    return runner.prepare_checkpoint_identity(
        request, limits=limits, request_directory=tmp_path, env=dict(os.environ)
    )


def test_real_cpu_worker_returns_known_bytes_and_owns_cleanup(tmp_path):
    request, limits = fixture(tmp_path)
    outcome = prepare(request, limits, tmp_path)
    assert outcome.status == "available", outcome.detail
    assert outcome.reference == reference(request)
    assert outcome.worker_receipt.child_pid == outcome.lifecycle.child_pid
    assert outcome.lifecycle.owned_pgid == outcome.lifecycle.child_pid
    assert outcome.lifecycle.child_reaped
    assert outcome.lifecycle.group_cleanup.final.status == "absent"
    assert not list(tmp_path.glob("checkpoint-identity-*"))
    assert outcome.timing.elapsed_seconds == pytest.approx(
        outcome.timing.request_seconds
        + outcome.timing.supervised_seconds
        + outcome.timing.finalization_seconds,
        abs=0.002,
    )


def test_fixed_worker_import_does_not_load_model_or_torch():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import core.runtime_control.checkpoint_identity_worker_main; "
            "assert 'torch' not in sys.modules; assert 'ml_models.models_sandbox' not in sys.modules; "
            "assert 'core.sandbox_executor' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("kind", ["missing_marker", "symlink", "fifo", "directory", "missing_file"])
def test_unavailable_native_artifact_never_produces_reference(tmp_path, kind):
    request, limits = fixture(tmp_path)
    path = Path(request.checkpoint_path)
    if kind == "missing_marker":
        (tmp_path / "_OK_attempt").unlink()
    else:
        path.unlink()
        if kind == "symlink":
            target = tmp_path / "other"
            target.write_bytes(b"other")
            path.symlink_to(target)
        elif kind == "fifo":
            os.mkfifo(path)
        elif kind == "directory":
            path.mkdir()
    outcome = prepare(request, limits, tmp_path)
    assert outcome.status == "unavailable"
    assert outcome.reference is None
    assert outcome.worker_receipt.unavailable_reason
    assert outcome.lifecycle.child_reaped


@pytest.mark.parametrize("mutation", ["same_size", "grow", "shrink", "replace"])
def test_same_fd_identity_refuses_mutation_between_stream_checks(tmp_path, monkeypatch, mutation):
    request, _ = fixture(tmp_path)
    path = Path(request.checkpoint_path)
    original = worker.stream_file_identity
    calls = 0

    def mutate(handle, **kwargs):
        nonlocal calls
        result = original(handle, **kwargs)
        calls += 1
        if calls == 1:
            if mutation == "replace":
                replacement = tmp_path / "replacement"
                replacement.write_bytes(path.read_bytes())
                replacement.replace(path)
            else:
                path.write_bytes(
                    {"same_size": b"X" * 29, "grow": b"X" * 30, "shrink": b"X"}[mutation]
                )
        return result

    monkeypatch.setattr(worker, "stream_file_identity", mutate)
    with pytest.raises(ValueError, match=r"changed|declared"):
        worker.identify_checkpoint(request)


def test_cooperative_deadline_is_checked_inside_stream(tmp_path):
    request, _ = fixture(tmp_path)
    ticks = iter([0, 0, 6])
    with pytest.raises(TimeoutError):
        worker.identify_checkpoint(request, clock=lambda: next(ticks))


class Clock:
    value = 0.0

    def __call__(self):
        return self.value


def test_ten_minus_request_three_minus_package_two_gives_worker_five(tmp_path, monkeypatch):
    from core.local_code import child

    request, limits = fixture(tmp_path, seconds=10)
    clock = Clock()
    monkeypatch.setattr(supervision.time, "perf_counter", clock)
    write = Path.write_text

    def slow_write(path, *args, **kwargs):
        clock.value += 3
        return write(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", slow_write)

    def packaging(argv, env):
        clock.value += 2
        return child.ChildInvocation(argv, env)

    monkeypatch.setattr(child, "prepare_child", packaging)
    seen = []

    def supervised(*args, **kwargs):
        seen.append(kwargs["limits"].deadline_seconds)
        return observed(request)

    monkeypatch.setattr(supervision, "supervise_process", supervised)
    result = prepare(request, limits, tmp_path)
    assert result.status == "available"
    assert seen == [5]
    assert result.timing.request_seconds == 3
    assert result.timing.supervised_seconds == 2
    assert result.timing.elapsed_seconds == 5


@pytest.mark.parametrize("stage", ["request", "package", "monitor"])
def test_expired_preparation_refuses_before_any_spawn(tmp_path, monkeypatch, stage):
    from core.local_code import child

    request, limits = fixture(tmp_path)
    clock = Clock()
    monkeypatch.setattr(supervision.time, "perf_counter", clock)
    if stage == "request":
        original = Path.write_text

        def slow_write(path, *args, **kwargs):
            clock.value = 6
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", slow_write)
    elif stage == "package":

        def packaging(argv, env):
            clock.value = 6
            return child.ChildInvocation(argv, env)

        monkeypatch.setattr(child, "prepare_child", packaging)
    else:

        def monitoring(pgid):
            clock.value = 6
            return RssObservation(status="complete")

        monkeypatch.setattr(supervision, "observe_tree_rss", monitoring)
    with patch.object(
        subprocess, "Popen", side_effect=AssertionError("expired work must not launch")
    ):
        outcome = prepare(request, limits, tmp_path)
    assert outcome.status == "unavailable"
    assert "allowance" in outcome.detail
    assert not list(tmp_path.glob("checkpoint-identity-*"))


@pytest.mark.parametrize("stage", ["receipt", "cleanup"])
def test_late_valid_receipt_is_unavailable_after_final_checks(tmp_path, monkeypatch, stage):
    request, limits = fixture(tmp_path)
    clock = Clock()
    monkeypatch.setattr(supervision.time, "perf_counter", clock)
    monkeypatch.setattr(runner, "supervise_subprocess", lambda *args, **kwargs: observed(request))
    if stage == "receipt":
        original = runner._validate_receipt

        def late(*args):
            clock.value = 6
            return original(*args)

        monkeypatch.setattr(runner, "_validate_receipt", late)
    else:
        original = runner.tempfile.TemporaryDirectory.cleanup

        def late_cleanup(self):
            clock.value = 6
            return original(self)

        monkeypatch.setattr(runner.tempfile.TemporaryDirectory, "cleanup", late_cleanup)
    outcome = prepare(request, limits, tmp_path)
    assert outcome.status == "unavailable"
    assert outcome.reference is None
    assert outcome.worker_receipt.reference == reference(request)
    assert outcome.timing.elapsed_seconds == 6


@pytest.mark.parametrize(
    "mismatch",
    ["nonce", "pid", "path", "required_cleanup", "unknown_group", "unreaped", "timeout", "signal"],
)
def test_receipt_or_lifecycle_mismatch_cannot_authorize_identity(tmp_path, monkeypatch, mismatch):
    request, limits = fixture(tmp_path)
    result = observed(request)
    receipt = CheckpointIdentityReceipt.model_validate_json(result.completed.stdout)
    if mismatch in {"nonce", "pid", "path"}:
        if mismatch == "nonce":
            receipt = receipt.model_copy(update={"request_nonce": "stale"})
        elif mismatch == "pid":
            receipt = receipt.model_copy(update={"child_pid": 99999})
        else:
            receipt = receipt.model_copy(
                update={
                    "reference": receipt.reference.model_copy(
                        update={
                            "checkpoint_path": str(
                                tmp_path / "elsewhere" / Path(request.checkpoint_path).name
                            )
                        }
                    )
                }
            )
        result = observed(request, receipt=receipt)
    elif mismatch == "timeout":
        result = result.model_copy(update={"timeout": {"deadline_s": 1}})
    else:
        lifecycle = result.lifecycle
        if mismatch == "unreaped":
            lifecycle = lifecycle.model_copy(update={"child_reaped": False})
        else:
            group = lifecycle.group_cleanup.model_copy(
                update={
                    "required": mismatch == "required_cleanup",
                    "final": GroupObservation(
                        status="unknown" if mismatch == "unknown_group" else "absent"
                    ),
                }
            )
            if mismatch == "signal":
                group = group.model_copy(update={"term": SignalObservation(status="delivered")})
            lifecycle = lifecycle.model_copy(update={"group_cleanup": group})
        result = observed(request, lifecycle=lifecycle)
    monkeypatch.setattr(runner, "supervise_subprocess", lambda *args, **kwargs: result)
    assert prepare(request, limits, tmp_path).status == "unavailable"


@pytest.mark.parametrize("intact", [True, False])
def test_identity_adapter_uses_actual_package_guard_and_preserves_refusal(
    tmp_path, monkeypatch, intact
):
    from core.local_code import bind_code_package
    from core.subprocess_env import subprocess_env
    from tests.unit.core.test_local_code_failure import package_and_env

    request, limits = fixture(tmp_path)
    package = package_and_env(tmp_path, monkeypatch)
    seen = []
    original = subprocess.Popen

    def spawn(argv, **kwargs):
        seen.append(argv)
        return original(argv, **kwargs)

    if not intact:
        (tmp_path / "helper.py").write_text("VALUE = 4\n")
    with bind_code_package(package), patch.object(subprocess, "Popen", spawn):
        outcome = runner.prepare_checkpoint_identity(
            request, limits=limits, request_directory=tmp_path, env=subprocess_env()
        )
    assert seen[0][1:4] == ["-m", "core.local_code.child", "module"]
    assert seen[0][4] == "core.runtime_control.checkpoint_identity_worker_main"
    if intact:
        assert outcome.status == "available", outcome.detail
    else:
        assert outcome.status == "unavailable"
        assert "LocalCodeError" in outcome.detail
        assert "digest mismatch" in outcome.detail
        assert outcome.reference is None
    assert outcome.lifecycle.child_reaped


def test_cold_package_wrapped_worker_path_never_imports_torch_or_models(tmp_path, monkeypatch):
    from core.local_code import bind_code_package
    from core.subprocess_env import subprocess_env
    from tests.unit.core.test_local_code_failure import package_and_env

    request, limits = fixture(tmp_path)
    package = package_and_env(tmp_path, monkeypatch)
    request_path = tmp_path / "input.json"
    request_path.write_text(request.model_dump_json())
    witness = tmp_path / "cold_worker.py"
    witness.write_text(
        "import sys\n"
        "from core.runtime_control.checkpoint_identity_worker_main import main\n"
        "assert 'torch' not in sys.modules\n"
        "assert 'ml_models.models_sandbox' not in sys.modules\n"
        "assert 'core.sandbox_executor' not in sys.modules\n"
        "status=main(sys.argv[1:])\n"
        "assert 'torch' not in sys.modules\n"
        "assert 'ml_models.models_sandbox' not in sys.modules\n"
        "raise SystemExit(status)\n"
    )
    with bind_code_package(package):
        result = supervision.supervise_subprocess(
            [sys.executable, str(witness), str(request_path)],
            env=subprocess_env(),
            preexec_fn=None,
            capture_stdout=True,
            limits=limits,
        )
    assert CheckpointIdentityReceipt.model_validate_json(
        result.completed.stdout
    ).reference == reference(request)
    assert result.lifecycle.child_reaped


def test_blocked_worker_read_is_stopped_by_parent_cpu_deadline(tmp_path):
    request, limits = fixture(tmp_path, seconds=0.8)
    request_path = tmp_path / "input.json"
    request_path.write_text(request.model_dump_json())
    entered = tmp_path / "read_started"
    code = (
        "import time; from pathlib import Path; "
        "from core.runtime_control import checkpoint_identity_worker_main as worker\n"
        "def blocked(*args, **kwargs):\n"
        f"    Path({str(entered)!r}).touch()\n"
        "    time.sleep(20)\n"
        "worker.stream_file_identity=blocked\n"
        f"worker.main([{str(request_path)!r}])\n"
    )
    with pytest.raises(ProcessSupervisionError) as caught:
        supervision.supervise_subprocess(
            [sys.executable, "-c", code],
            env=dict(os.environ),
            preexec_fn=None,
            capture_stdout=True,
            limits=limits,
        )
    assert entered.exists(), "deadline fired before reaching the injected blocking read"
    assert caught.value.lifecycle.stop_reason == "work_deadline_exceeded"
    assert caught.value.lifecycle.child_reaped
    assert caught.value.lifecycle.group_cleanup.final.status == "absent"


@pytest.mark.parametrize("payload", ["", "{}", "{broken", "duplicate", "two_objects"])
def test_missing_or_conflicting_protocol_output_is_unavailable(tmp_path, monkeypatch, payload):
    request, limits = fixture(tmp_path)
    result = observed(request)
    if payload == "duplicate":
        payload = result.completed.stdout.replace("{", '{"request_nonce":"stale",', 1)
    elif payload == "two_objects":
        payload = result.completed.stdout + result.completed.stdout
    result.completed.stdout = payload
    monkeypatch.setattr(runner, "supervise_subprocess", lambda *args, **kwargs: result)
    outcome = prepare(request, limits, tmp_path)
    assert outcome.status == "unavailable"
    assert outcome.reference is None
    assert outcome.lifecycle.child_reaped


def test_unavailable_monitoring_preserves_raw_lifecycle_in_adapter(tmp_path, monkeypatch):
    request, limits = fixture(tmp_path)
    monkeypatch.setattr(
        supervision,
        "observe_tree_rss",
        lambda pgid: RssObservation(status="unavailable", errors=("proc unreadable",)),
    )
    with patch.object(subprocess, "Popen", side_effect=AssertionError("monitoring missing")):
        result = prepare(request, limits, tmp_path)
    assert result.status == "unavailable"
    assert result.lifecycle.last_rss_observation.errors == ("proc unreadable",)
    assert result.reference is None


def test_request_cleanup_failure_cannot_publish_valid_reference(tmp_path, monkeypatch):
    request, limits = fixture(tmp_path)
    monkeypatch.setattr(runner, "supervise_subprocess", lambda *args, **kwargs: observed(request))
    original = runner.tempfile.TemporaryDirectory.cleanup

    def fail_after_cleanup(self):
        original(self)
        raise OSError("cleanup receipt failure")

    monkeypatch.setattr(runner.tempfile.TemporaryDirectory, "cleanup", fail_after_cleanup)
    result = prepare(request, limits, tmp_path)
    assert result.status == "unavailable"
    assert result.reference is None
    assert result.worker_receipt.reference == reference(request)
    assert "cleanup receipt failure" in result.detail
