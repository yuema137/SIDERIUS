"""Admission races and immutable terminal evidence own separate trust boundaries."""

import hashlib
import importlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from tests.unit.tools.candidate_prepare.test_reusable_preparation import direct_child, reusable
from tools.candidate_prepare import preflight_reusable_candidate, prepare_reusable_candidate
from tools.candidate_prepare.reusable_models import (
    ReusablePreparationObservations,
    ReusablePreparationReceipt,
)
from tools.candidate_prepare.reusable_terminal import read_reusable_terminal
from tools.workspace_sandbox.runner import ExecutionResult


def test_legacy_top_receipt_bytes():
    """Adding invocation identity must not rewrite historical null fields or bytes."""
    path = (
        Path(__file__).resolve().parents[3]
        / "fixtures/candidate_operations/legacy-reusable-receipt.json"
    )
    payload = path.read_bytes()
    assert (
        ReusablePreparationReceipt.model_validate_json(payload).model_dump_json(indent=2) + "\n"
    ).encode() == payload


@pytest.mark.parametrize("field", ["manifest", "config"])
def test_actual_capture_rejects_post_precheck_input_drift(reusable, field):
    """A second capture must not silently replace the admitted manifest/config identity."""
    # Admission treats manifest bytes inertly; never mutate the shared repository fixture.
    source = Path(reusable.source_path)
    original = preflight_reusable_candidate(reusable).binding.request.task_manifest
    manifest = Path(reusable.project_root) / "observed-task.yaml"
    manifest.write_text("inert: admission-only\n")
    source.write_text(source.read_text().replace(original, str(manifest)))
    reusable = reusable.model_copy(
        update={"expected_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    )
    expected = ReusablePreparationObservations.from_binding(
        preflight_reusable_candidate(reusable).binding
    )
    Path(getattr(expected, field).path).write_bytes(
        Path(getattr(expected, field).path).read_bytes() + b"\n"
    )
    with pytest.raises(ValueError, match="actual reusable capture"):
        prepare_reusable_candidate(reusable, expected_observations=expected)
    assert list(Path(reusable.runs_root).iterdir()) == []


def test_failure_before_control_has_bound_terminal_identity(reusable, monkeypatch):
    """A failure after snapshot publication can complete without fabricated native control."""
    launch = importlib.import_module("tools.candidate_prepare.reusable_launch")
    expected = ReusablePreparationObservations.from_binding(
        preflight_reusable_candidate(reusable).binding
    )
    invocation = uuid4()
    monkeypatch.setattr(
        launch, "admit", lambda *a, **k: (_ for _ in ()).throw(ValueError("late refusal"))
    )
    receipt = prepare_reusable_candidate(
        reusable, invocation_id=invocation, expected_observations=expected
    )
    assert receipt.status == "failed" and receipt.preparation_receipt_path is None
    assert read_reusable_terminal(reusable, expected, invocation)[0] == receipt
    Path(reusable.source_path).unlink()
    Path(expected.config.path).unlink()
    assert read_reusable_terminal(reusable, expected, invocation)[0] == receipt


@pytest.mark.parametrize("status", ["timed_out", "interrupted"])
def test_terminal_native_failure_status(reusable, monkeypatch, status):
    """Native timeout/interruption remains terminal failure rather than successful preparation."""
    launch = importlib.import_module("tools.candidate_prepare.reusable_launch")
    expected = ReusablePreparationObservations.from_binding(
        preflight_reusable_candidate(reusable).binding
    )
    invocation = uuid4()

    def outcome(*args, **kwargs):
        if status == "interrupted":
            raise KeyboardInterrupt
        return ExecutionResult(status="timed_out", returncode=-9, elapsed_seconds=1)

    monkeypatch.setattr(launch, "supervise", outcome)
    receipt = prepare_reusable_candidate(reusable, invocation_id=invocation)
    assert read_reusable_terminal(reusable, expected, invocation)[0].status == status
    assert receipt.candidate_request_path is None


@pytest.mark.parametrize(
    "change",
    [
        "top_id",
        "control_id",
        "inner_id",
        "inner_status",
        "inner_error",
        "missing_inner",
        "missing_binding",
        "top_hash",
    ],
)
def test_terminal_rejects_contradictory_evidence(reusable, monkeypatch, change):
    """Terminal projection cannot trust mismatched IDs/statuses or missing referenced evidence."""
    launch = importlib.import_module("tools.candidate_prepare.reusable_launch")
    expected = ReusablePreparationObservations.from_binding(
        preflight_reusable_candidate(reusable).binding
    )
    invocation = uuid4()
    monkeypatch.setattr(
        launch,
        "supervise",
        lambda *a, **k: ExecutionResult(status="failed", returncode=1, elapsed_seconds=0),
    )
    receipt = prepare_reusable_candidate(reusable, invocation_id=invocation)
    envelope = Path(receipt.envelope)
    top_digest = hashlib.sha256((envelope / "receipt.json").read_bytes()).hexdigest()
    if change.startswith("missing"):
        (
            envelope
            / ("binding.json" if change == "missing_binding" else "inputs/preparation/receipt.json")
        ).unlink()
    else:
        target = (
            "receipt.json"
            if change.startswith("top")
            else "inputs/preparation/request.json"
            if change == "control_id"
            else "inputs/preparation/receipt.json"
        )
        path = envelope / target
        value = json.loads(path.read_bytes())
        if change.endswith("id"):
            value["preparation_id"] = str(uuid4())
        elif change == "inner_status":
            value["status"] = "timed_out"
        else:
            value["error"] = "changed"
        path.write_text(json.dumps(value))
    with pytest.raises((ValueError, OSError)):
        read_reusable_terminal(
            reusable,
            expected,
            invocation,
            expected_receipt_sha256=top_digest if change == "top_hash" else None,
        )


def test_success_uses_snapshot_without_mutable_origin(reusable, direct_child):
    """Status is historical identity; source/config removal does not erase completed preparation."""
    expected = ReusablePreparationObservations.from_binding(
        preflight_reusable_candidate(reusable).binding
    )
    invocation = uuid4()
    result = prepare_reusable_candidate(reusable, invocation_id=invocation)
    assert result.status == "prepared", result.error
    Path(reusable.source_path).unlink()
    Path(expected.config.path).unlink()
    assert read_reusable_terminal(reusable, expected, invocation)[0] == result
    (Path(result.envelope) / "receipt.json").unlink()
    assert read_reusable_terminal(reusable, expected, invocation) is None
