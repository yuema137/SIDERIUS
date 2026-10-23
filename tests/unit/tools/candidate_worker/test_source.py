"""Captured source is validated and published before native dispatch."""

import hashlib
import importlib
from pathlib import Path

import pytest

from tools.candidate_worker import launch_candidate
from tools.candidate_worker.models import CandidateRunRequest, WorkflowSourceSnapshot
from tools.candidate_worker.source import verify_snapshot
from tools.workspace_sandbox.runner import ExecutionResult
from workflows.definition import render_workflow_source


def captured(request):
    source = render_workflow_source(request.preview.document)
    fields = request.model_dump()
    fields["workflow_source"] = WorkflowSourceSnapshot(
        origin_path="/diagnostic/absent.py",
        sha256=hashlib.sha256(source.encode()).hexdigest(),
        source=source,
    )
    return CandidateRunRequest.model_validate(fields)


def test_source_binding_checks_hash_and_full_layout(prepared):
    request = captured(prepared)
    fields = request.model_dump()
    fields["workflow_source"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash mismatch"):
        CandidateRunRequest.model_validate(fields)
    fields = request.model_dump()
    # Layout does not change execution identity, but belongs to exact reviewed capture.
    fields["preview"]["document"]["positions"] = ({"node": "propose", "x": 12.0, "y": 24.0},)
    with pytest.raises(ValueError, match="differs from preview"):
        CandidateRunRequest.model_validate(fields)


def test_snapshot_failure_prevents_dispatch_and_capture_ignores_origin(prepared, monkeypatch):
    launch = importlib.import_module("tools.candidate_worker.launch")
    request = captured(prepared)
    publish = launch.publish_bytes_write_once

    def failing(path, payload):
        if path.endswith("workflow.py.snapshot"):
            raise OSError("snapshot publication failed")
        publish(path, payload)

    monkeypatch.setattr(launch, "publish_bytes_write_once", failing)
    monkeypatch.setattr(
        launch, "run", lambda *a: pytest.fail("native dispatch after snapshot failure")
    )
    receipt = launch_candidate(request)
    assert receipt.status == "failed" and "snapshot publication failed" in receipt.error
    saved = CandidateRunRequest.model_validate_json(
        (Path(receipt.workspace) / "candidate_run/request.json").read_bytes()
    )
    assert saved.workflow_source == request.workflow_source


def test_child_rejects_missing_corrupt_alias_and_fifo_snapshot(prepared, tmp_path):
    request = captured(prepared)
    snapshot = tmp_path / "workflow.py.snapshot"
    with pytest.raises(FileNotFoundError):
        verify_snapshot(request, tmp_path)
    snapshot.write_text("corrupt")
    with pytest.raises(ValueError, match="mismatch"):
        verify_snapshot(request, tmp_path)
    snapshot.unlink()
    snapshot.symlink_to(Path(request.preview.project_root) / "seed.json")
    with pytest.raises(OSError):
        verify_snapshot(request, tmp_path)
    snapshot.unlink()
    import os

    os.mkfifo(snapshot)
    with pytest.raises(ValueError, match="regular file"):
        verify_snapshot(request, tmp_path)


def test_launch_publishes_exact_capture_before_dispatch(prepared, monkeypatch):
    request = captured(prepared)
    launch = importlib.import_module("tools.candidate_worker.launch")

    def dispatched(profile, argv):
        verify_snapshot(request, profile.workspace / "candidate_run")
        return ExecutionResult(status="timed_out", returncode=124, elapsed_seconds=0.0)

    monkeypatch.setattr(launch, "run", dispatched)
    assert launch_candidate(request).status == "timed_out"


def test_child_execute_checks_fixed_snapshot_before_native_binding(prepared, monkeypatch):
    """Removing execute's snapshot check must hit the native-binding sentinel."""
    child = importlib.import_module("tools.candidate_worker.child")
    launch = importlib.import_module("tools.candidate_worker.launch")
    request = captured(prepared)
    monkeypatch.setattr(
        child,
        "bind_generated_library_to_workspace",
        lambda *a: pytest.fail("native binding reached after corrupt source snapshot"),
    )

    def dispatched(profile, argv):
        (profile.workspace / "candidate_run/workflow.py.snapshot").write_text("corrupted capture")
        child.execute(Path(argv[-1]))
        pytest.fail("child accepted a corrupt source snapshot")

    monkeypatch.setattr(launch, "run", dispatched)
    receipt = launch_candidate(request)
    assert (
        receipt.status == "failed"
        and receipt.error == "ValueError: workflow source snapshot mismatch"
    )
