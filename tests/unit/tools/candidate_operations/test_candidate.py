"""Candidate-specific outer admission and native launch/receipt identity projection."""

from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from tests.unit.tools.candidate_worker.conftest import prepared
from tools.candidate_operations import (
    CandidateOperation,
    OperationStoreConfig,
    read_operation,
    submit_operation,
)
from tools.candidate_operations.files import JSON_LIMIT
from tools.candidate_operations.models import OperationFailure, OperationRecord
from tools.candidate_operations.process import runtime_identity
from tools.candidate_operations.store import claim, digest, locked_store, now
from tools.candidate_worker.launch import publish as native_publish
from tools.candidate_worker.models import CandidateRunReceipt


def test_oversized_candidate_refuses_before_claim_and_leaves_store_available(
    prepared, tmp_path, monkeypatch
):
    """#804: size refusal must not leave an empty claim blocking the next submission."""
    config = OperationStoreConfig(
        state_root=str(tmp_path / "state"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    spawn = Mock(side_effect=OSError("no child started"))
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", spawn)
    oversized = CandidateOperation(
        request_id=uuid4(),
        request=prepared.model_copy(update={"implementation_advice": "x" * JSON_LIMIT}),
    )
    with pytest.raises(OperationFailure, match="4 MiB") as failure:
        submit_operation(config, oversized, launch_environment={})
    assert failure.value.detail.code == "record_size"
    root = Path(config.state_root)
    assert not (root / "operations" / str(oversized.request_id)).exists()
    assert not (root / "active.json").exists()
    spawn.assert_not_called()

    supported = CandidateOperation(request_id=uuid4(), request=prepared)
    handle = submit_operation(config, supported, launch_environment={})
    assert handle.operation_id == supported.request_id
    assert handle.observation == "operation_failed"
    spawn.assert_called_once()
    assert (root / "operations" / str(supported.request_id) / "request.json").is_file()


@pytest.mark.parametrize("name", ["PYTHONPATH", "PYTHONHOME", "LD_PRELOAD"])
def test_candidate_reserved_name_rejected_before_outer_claim(prepared, tmp_path, name):
    config = OperationStoreConfig(
        state_root=str(tmp_path / "state"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    candidate = CandidateOperation(
        request_id=uuid4(), request=prepared.model_copy(update={"environment_names": (name,)})
    )
    with pytest.raises(ValueError, match="reserved"):
        submit_operation(config, candidate, launch_environment={name: "sentinel"})
    assert not Path(config.state_root).exists()
    assert not Path(prepared.preview.document.definition.task.workspace).exists()


def test_rejected_receipt_remains_rejected_and_launch_mismatch_is_unknown(prepared, tmp_path):
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
        claim(root, record)
    workspace = Path(prepared.preview.document.definition.task.workspace)
    control = workspace / "candidate_run"
    control.mkdir(parents=True)
    initial = CandidateRunReceipt(
        run_id=record.native_id.hex,
        run_name=prepared.run_name,
        workspace=str(workspace),
        declaration_digest=prepared.declaration_digest,
        status="launched",
        node_ids=tuple(node.id for node in prepared.preview.document.definition.nodes),
        selected_constructor_routes=prepared.selected_constructor_routes,
        ledger_path=str(workspace / "token_usage.jsonl"),
        log_path=str(control / "worker.log"),
    )
    native_publish(control / "request.json", prepared)
    native_publish(control / "launch.json", initial)
    rejected = initial.model_copy(update={"status": "rejected", "validation_passed": False})
    native_publish(control / "receipt.json", rejected)
    snapshot = read_operation(config, submission.request_id)
    assert snapshot.state == "completed" and snapshot.receipt.status == "rejected"
    (control / "receipt.json").write_text(
        rejected.model_copy(update={"run_id": "forged"}).model_dump_json()
    )
    assert read_operation(config, submission.request_id).state == "unknown"


@pytest.mark.parametrize("kind", ["prepare", "candidate"])
@pytest.mark.parametrize("explicit", [False, True])
def test_native_identity_binding_preserves_default_and_validates_before_effects(
    selection, prepared, monkeypatch, kind, explicit
):
    """Native UUID ownership/default formatting persists; invalid injection cannot claim paths."""
    import importlib

    from tools.workspace_sandbox.runner import ExecutionResult

    module = importlib.import_module(
        f"tools.candidate_{'prepare' if kind == 'prepare' else 'worker'}.launch"
    )
    request = selection if kind == "prepare" else prepared
    invoke = module.prepare_candidate if kind == "prepare" else module.launch_candidate
    destination = Path(
        selection.output_dir
        if kind == "prepare"
        else prepared.preview.document.definition.task.workspace
    )
    with pytest.raises(ValueError):
        invoke(request, invocation_id="not-a-UUID")
    assert not destination.exists()
    identity = uuid4()

    def generated():
        assert not explicit, "explicit native identity must not regenerate"
        return identity

    monkeypatch.setattr(module, "uuid4", generated)
    monkeypatch.setattr(
        module,
        "run",
        lambda *_: ExecutionResult(status="timed_out", returncode=124, elapsed_seconds=0.1),
    )
    receipt = invoke(request, **({"invocation_id": identity} if explicit else {}))
    assert receipt.status == "timed_out"
    assert (receipt.preparation_id if kind == "prepare" else receipt.run_id) == (
        identity if kind == "prepare" else identity.hex
    )
