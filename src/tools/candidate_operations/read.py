"""Project validated native outcomes without inventing a second workflow state."""

import hashlib
import os
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ValidationError

from tools.candidate_prepare.models import CandidatePreparationReceipt, PreparationControl
from tools.candidate_prepare.reusable_models import ReusablePreparationObservations
from tools.candidate_prepare.reusable_terminal import read_reusable_terminal
from tools.candidate_worker.models import CandidateRunReceipt, CandidateRunRequest
from tools.candidate_worker.records import verify_candidate_records

from .expectation import compare_reusable_expectation
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
    ReusablePreparationExpectation,
    SpawnFailure,
)
from .native_chain_read import read_native_chain_operation
from .native_resume_read import has_continuation, read_resume_chain
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
    if submission.kind == "native_chain" or submission.kind == "native_chain_resume":
        raise OperationFailure("kind", "chain has no native scientific receipt")
    if submission.kind == "candidate_loop_resume" or (
        submission.kind == "candidate"
        and submission.request.preview.document.definition.loop is not None
    ):
        from .loop_resume import read_segment

        return read_segment(record)
    if submission.kind == "prepare_reusable":
        return read_reusable_terminal(
            submission.request,
            ReusablePreparationObservations.from_inputs(record.inputs),
            record.native_id,
        )
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
        # Continuation owns one bounded read of all markers. Do not read them
        # here first and then silently reset its aggregate budget.
        if record.submission.kind in {"native_chain", "native_chain_resume"} and has_continuation(
            record
        ):
            return read_resume_chain(record)
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
        if record.submission.kind in {"native_chain", "native_chain_resume"}:
            return read_native_chain_operation(record, process, completion)
        native = native_receipt(record)
        if (
            completion is not None
            and completion.outcome == "native"
            and (native is None or completion.receipt_digest != native[1])
        ):
            raise OperationFailure("integrity", "completed native receipt changed or vanished")
        if native is not None:
            successor = None
            if record.submission.kind == "candidate_loop_resume" or (
                record.submission.kind == "candidate"
                and record.submission.request.preview.document.definition.loop is not None
            ):
                from .loop_resume import successor_id

                successor = successor_id(record)
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
                successor_operation_id=successor,
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


def recover_reusable_preparation(
    config: OperationStoreConfig,
    operation_id: UUID,
    expected: ReusablePreparationExpectation,
) -> OperationSubmission | None:
    """Recover admitted identity before mutable-source/credential reads; never dispatch."""
    config = validate_config(config)
    path = Path(config.state_root) / "operations" / str(operation_id)
    if not os.path.lexists(path):
        return None
    record = load_record(config, operation_id)
    compare_reusable_expectation(record, expected)
    return record.submission
