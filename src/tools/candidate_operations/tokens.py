"""Bind reported-token reads to admitted requests, native nonce and integrity verdict."""

from pathlib import Path
from uuid import UUID

from tools.candidate_worker import (
    CandidateTokenReadRequest,
    CandidateTokenSnapshot,
    read_candidate_tokens,
)
from tools.candidate_worker.models import CandidateRunReceipt, CandidateRunRequest
from tools.candidate_worker.records import verify_candidate_records

from .files import read_model
from .models import OperationFailure, OperationStoreConfig
from .read import read_operation
from .store import load_record, native_directory, validate_config


def read_operation_tokens(
    config: OperationStoreConfig, operation_id: UUID
) -> CandidateTokenSnapshot:
    """Read known operations without a task-choice match, new credentials or dispatch."""
    config = validate_config(config)
    snapshot = read_operation(config, operation_id)
    if snapshot.reason == "integrity_failure":
        raise OperationFailure("integrity", "operation evidence could not be verified")
    record = load_record(config, operation_id)
    if record.submission.kind == "native_chain" or record.submission.kind == "native_chain_resume":
        raise OperationFailure("not_supported", "native chain token aggregation is not supported")
    if record.submission.kind == "prepare" or record.submission.kind == "prepare_reusable":
        return CandidateTokenSnapshot(
            observed_at=snapshot.observed_at,
            availability="not_applicable",
            reason="preparation_not_applicable",
        )
    control = native_directory(record.submission)
    workspace = control.parent
    root = next(
        Path(value)
        for value in config.candidate_roots
        if workspace != Path(value) and workspace.is_relative_to(Path(value))
    )
    try:
        try:
            saved = read_model(control / "request.json", CandidateRunRequest)
            initial = read_model(control / "launch.json", CandidateRunReceipt)
        except FileNotFoundError:
            return CandidateTokenSnapshot(
                run_id=record.native_id.hex,
                run_name=record.submission.request.run_name,
                observed_at=snapshot.observed_at,
                availability="unavailable",
                reason="native_evidence_unavailable",
            )
        verify_candidate_records(
            saved,
            initial,
            expected_request=record.submission.request,
            expected_run_id=record.native_id.hex,
            workspace=workspace,
        )
        return read_candidate_tokens(
            CandidateTokenReadRequest(
                allowed_workspace_root=str(root),
                workspace=str(workspace),
                expected_run_id=record.native_id.hex,
            )
        )
    except (OSError, ValueError) as error:
        raise OperationFailure(
            "integrity", "native token evidence could not be verified"
        ) from error
