"""Candidate-specific outer admission and native launch/receipt identity projection."""

from pathlib import Path
from uuid import uuid4

import pytest

from tests.unit.tools.candidate_worker.conftest import prepared
from tools.candidate_operations import (
    CandidateOperation,
    OperationStoreConfig,
    read_operation,
    submit_operation,
)
from tools.candidate_operations.models import OperationRecord
from tools.candidate_operations.process import runtime_identity
from tools.candidate_operations.store import claim, digest, locked_store, now
from tools.candidate_worker.launch import publish as native_publish
from tools.candidate_worker.models import CandidateRunReceipt


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
        run_id="native-id",
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
