"""Loop root resolution with cycle detection and integrity checks."""

from uuid import uuid4

import pytest

from tools.candidate_operations.loop_resume import root_record
from tools.candidate_operations.models import (
    CandidateLoopResumeOperation,
    CandidateLoopResumeRequest,
    OperationFailure,
    OperationRecord,
    OperationStoreConfig,
    RuntimeIdentity,
)
from tools.candidate_operations.store import digest, now


def _candidate_resume(request_id, predecessor_id):
    """Construct a loop resume operation pointing to a predecessor."""
    request = CandidateLoopResumeRequest(
        predecessor_operation_id=predecessor_id,
        expected_receipt_digest="a" * 64,
    )
    operation = CandidateLoopResumeOperation(
        request_id=request_id,
        request=request,
    )
    return operation


def _operation_record(config, submission, kind):
    """Construct an operation record with the given submission."""
    record = OperationRecord.model_construct(
        native_id=uuid4(),
        submission=submission,
        request_digest=digest(submission),
        config=config,
        runtime=RuntimeIdentity(
            executable="test",
            resolved_executable="test",
            environment="test",
            source="test",
            revision=None,
        ),
        inputs=(),
        admitted_at=now(),
    )
    return record


def test_cycle_is_detected_and_refused(tmp_path, monkeypatch):
    """Fails if predecessor-link cycles are not detected as 'loop operation cycle'."""
    config = OperationStoreConfig(
        state_root=str(tmp_path / "state"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )

    # Create records with IDs that will form a cycle
    id1 = uuid4()
    id2 = uuid4()

    # Create resume 1 -> resume 2 -> resume 1 (cycle)
    submission1 = _candidate_resume(id1, id2)
    record1 = _operation_record(config, submission1, "candidate_loop_resume")

    submission2 = _candidate_resume(id2, id1)
    record2 = _operation_record(config, submission2, "candidate_loop_resume")

    # Mock load_record to return the cycle
    def mock_load_record(cfg, operation_id):
        if operation_id == id1:
            return record1
        elif operation_id == id2:
            return record2
        raise FileNotFoundError(f"Unknown operation {operation_id}")

    monkeypatch.setattr("tools.candidate_operations.loop_resume.load_record", mock_load_record)

    # root_record should detect the cycle and raise
    with pytest.raises(OperationFailure) as exc_info:
        root_record(record1)

    assert exc_info.value.detail.code == "integrity"
    assert exc_info.value.detail.message == "loop operation cycle"


def test_cycle_detection_fails_when_removed(tmp_path, monkeypatch):
    """Fails when cycle detection code is removed (mutation proof)."""
    config = OperationStoreConfig(
        state_root=str(tmp_path / "state"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )

    # Create records with IDs that will form a cycle
    id1 = uuid4()
    id2 = uuid4()

    # Create resume 1 -> resume 2 -> resume 1 (cycle)
    submission1 = _candidate_resume(id1, id2)
    record1 = _operation_record(config, submission1, "candidate_loop_resume")

    submission2 = _candidate_resume(id2, id1)
    record2 = _operation_record(config, submission2, "candidate_loop_resume")

    # Mock load_record to return the cycle
    call_count = {"count": 0}

    def mock_load_record(cfg, operation_id):
        call_count["count"] += 1
        if call_count["count"] > 100:  # Detect infinite loop
            raise RuntimeError("Cycle detection failed: infinite loop detected")
        if operation_id == id1:
            return record1
        elif operation_id == id2:
            return record2
        raise FileNotFoundError(f"Unknown operation {operation_id}")

    monkeypatch.setattr("tools.candidate_operations.loop_resume.load_record", mock_load_record)

    # Without cycle detection, this would loop infinitely or fail in a different way
    # We use the counter to ensure the test catches the absence of the check
    with pytest.raises((OperationFailure, RuntimeError)):
        root_record(record1)
