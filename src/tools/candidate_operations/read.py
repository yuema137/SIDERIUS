"""Project validated native outcomes without inventing a second workflow state."""

import hashlib
import os
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ValidationError

from tools.candidate_prepare.models import CandidatePreparationReceipt, PreparationControl
from tools.candidate_worker.models import CandidateRunReceipt, CandidateRunRequest
from tools.candidate_worker.records import verify_candidate_records

from .files import read_bytes, read_model
from .models import (
    Completion,
    NativeReceipt,
    OperationFailure,
    OperationRecord,
    OperationSnapshot,
    OperationStoreConfig,
    OperationSubmission,
    ProcessIdentity,
    ProcessObservation,
    SpawnFailure,
)
from .process import observe
from .store import load_record, native_directory, now, operation_path, validate_config


def optional[Model: BaseModel](path: Path, model: type[Model]) -> Model | None:
    try:
        return read_model(path, model, private_file=True)
    except FileNotFoundError:
        return None


def bound(record: OperationRecord, marker: ProcessIdentity | Completion | SpawnFailure) -> None:
    if (
        marker.operation_id != record.submission.request_id
        or marker.request_digest != record.request_digest
    ):
        raise OperationFailure("integrity", "operation marker identity mismatch")


def native_receipt(record: OperationRecord) -> tuple[NativeReceipt, str] | None:
    submission = record.submission
    control = native_directory(submission)
    try:
        payload = read_bytes(control / "receipt.json")
    except FileNotFoundError:
        return None
    if submission.kind == "prepare":
        receipt = CandidatePreparationReceipt.model_validate_json(payload)
        saved = read_model(control / "request.json", PreparationControl)
        if (
            saved.request != submission.request
            or saved.preparation_id != record.native_id
            or saved.preparation_id != receipt.preparation_id
            or receipt.output_dir != str(control.parent)
            or receipt.request_path != str(control / "request.json")
            or receipt.log_path != str(control / "worker.log")
            or receipt.source_observations != saved.sources
            or saved.sources != record.inputs
        ):
            raise OperationFailure("integrity", "native preparation identity mismatch")
    else:
        receipt = CandidateRunReceipt.model_validate_json(payload)
        initial = read_model(control / "launch.json", CandidateRunReceipt)
        saved = read_model(control / "request.json", CandidateRunRequest)
        verify_candidate_records(
            saved,
            initial,
            expected_request=submission.request,
            expected_run_id=record.native_id.hex,
            workspace=control.parent,
            receipt=receipt,
        )
    return receipt, hashlib.sha256(payload).hexdigest()


def read_operation(config: OperationStoreConfig, operation_id: UUID) -> OperationSnapshot:
    config = validate_config(config)
    record = load_record(config, operation_id)
    path = operation_path(config, operation_id)
    process = ProcessObservation(status="unknown", reason="missing_identity")
    observed_at = now()
    try:
        identity = optional(path / "process.json", ProcessIdentity)
        failure = optional(path / "spawn_failure.json", SpawnFailure)
        completion = optional(path / "completion.json", Completion)
        for marker in (identity, failure, completion):
            if marker is not None:
                bound(record, marker)
        if identity is not None:
            process = observe(identity)
        if failure is not None:
            if identity is not None or completion is not None:
                raise OperationFailure("integrity", "spawn failure contradicts child evidence")
            return OperationSnapshot(
                operation_id=operation_id,
                kind=record.submission.kind,
                request_digest=record.request_digest,
                observed_at=observed_at,
                state="operation_failed",
                process=process,
                reason="spawn_failed",
            )
        native = native_receipt(record)
        if (
            completion is not None
            and completion.outcome == "native"
            and (native is None or completion.receipt_digest != native[1])
        ):
            raise OperationFailure("integrity", "completed native receipt changed or vanished")
        if native is not None:
            if completion is not None and completion.outcome == "pre_dispatch_failure":
                raise OperationFailure(
                    "integrity", "pre-dispatch failure contradicts native receipt"
                )
            return OperationSnapshot(
                operation_id=operation_id,
                kind=record.submission.kind,
                request_digest=record.request_digest,
                observed_at=observed_at,
                state="completed",
                process=process,
                finishing=process.status == "alive",
                receipt_available=True,
                receipt=native[0],
                receipt_digest=native[1],
                reason="native_terminal",
            )
        if completion is not None:
            return OperationSnapshot(
                operation_id=operation_id,
                kind=record.submission.kind,
                request_digest=record.request_digest,
                observed_at=observed_at,
                state="operation_failed"
                if completion.outcome == "pre_dispatch_failure"
                else "unknown",
                process=process,
                reason=completion.reason,
            )
        return OperationSnapshot(
            operation_id=operation_id,
            kind=record.submission.kind,
            request_digest=record.request_digest,
            observed_at=observed_at,
            state="active" if process.status == "alive" else "unknown",
            process=process,
            reason="observed_wrapper" if process.status == "alive" else "outcome_unresolved",
        )
    except (OSError, ValueError, ValidationError):
        return OperationSnapshot(
            operation_id=operation_id,
            kind=record.submission.kind,
            request_digest=record.request_digest,
            observed_at=observed_at,
            state="unknown",
            process=process,
            reason="integrity_failure",
        )


def releasable(config: OperationStoreConfig, operation_id: UUID) -> bool:
    try:
        snapshot = read_operation(config, operation_id)
    except (OSError, ValueError):
        return False
    return (snapshot.state == "operation_failed" and snapshot.reason == "spawn_failed") or (
        snapshot.state in {"completed", "operation_failed"} and snapshot.process.status == "exited"
    )


def lookup_operation_request(
    config: OperationStoreConfig, operation_id: UUID
) -> OperationSubmission | None:
    """Return a verified admission, or None only when its directory is absent."""
    config = validate_config(config)
    path = Path(config.state_root) / "operations" / str(operation_id)
    if not os.path.lexists(path):
        return None
    return load_record(config, operation_id).submission
