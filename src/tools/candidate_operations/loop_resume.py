"""Operation admission for clean authored checkpoints, never fixed-chain recovery."""

import hashlib
import os
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from uuid import UUID

from core.control_json import encode_control
from core.durable_io import publish_bytes_write_once
from tools.candidate_worker.child import verify_inputs
from tools.candidate_worker.loop_models import LoopContinuation, LoopPause
from tools.candidate_worker.loop_resume import (
    launch_continuation,
    read_continuation,
    require_clean,
    segment_control,
)
from tools.candidate_worker.models import CandidateRunReceipt, CandidateRunRequest
from tools.candidate_worker.preflight import require_credentials
from tools.candidate_worker.records import verify_candidate_records

from .files import directory, read_bytes, read_model
from .models import (
    CandidateLoopResumeOperation,
    CandidateOperation,
    Completion,
    OperationFailure,
    OperationRecord,
    OperationSnapshot,
    OperationStoreConfig,
)
from .process import runtime_identity
from .store import (
    is_authored_loop,
    load_record,
    locked_store,
    native_directory,
    operation_path,
    validate_config,
)


def root_record(record: OperationRecord) -> OperationRecord:
    selected = record
    seen = set()
    while selected.submission.kind == "candidate_loop_resume":
        identity = selected.submission.request_id
        if identity in seen:
            raise OperationFailure("integrity", "loop operation cycle")
        seen.add(identity)
        selected = load_record(record.config, selected.submission.request.predecessor_operation_id)
    if not is_authored_loop(selected):
        raise OperationFailure("kind", "operation is not an authored loop")
    return selected


def loop_root_operation(
    config: OperationStoreConfig, operation_id: UUID
) -> CandidateOperation | None:
    """Read-only: the admitted root candidate of an authored-loop operation or segment.

    Returns ``None`` for any operation that is not an authored loop. A resume segment
    whose root is not an authored loop raises ``OperationFailure`` with kind ``"kind"``
    (reachable only with tampered records). Only immutable operation records are followed
    (``predecessor_operation_id``); no native file, process or credential is read, so
    callers may use it before the worker claims its workspace (declared bound, credential
    names, results root). Predecessor-link cycles raise ``OperationFailure`` with kind
    ``"integrity"``.
    """
    record = load_record(validate_config(config), operation_id)
    if not is_authored_loop(record):
        return None
    root = root_record(record)
    if root.submission.kind != "candidate":
        raise OperationFailure("integrity", "loop root submission is not a candidate")
    return root.submission


def root_inputs(record: OperationRecord):
    root = root_record(record)
    if root.submission.kind != "candidate":
        raise OperationFailure("integrity", "loop root submission is not a candidate")
    control = native_directory(root.submission)
    saved = read_model(control / "request.json", CandidateRunRequest)
    initial = read_model(control / "launch.json", CandidateRunReceipt)
    verify_candidate_records(
        saved,
        initial,
        expected_request=root.submission.request,
        expected_run_id=root.native_id.hex,
        workspace=control.parent,
    )
    if record.runtime != root.runtime or record.inputs != root.inputs:
        raise OperationFailure("integrity", "loop continuation runtime or inputs changed")
    return root, saved, initial


def claimed_inputs(record: OperationRecord):
    """root_inputs for an operation whose root worker must already own its workspace."""
    try:
        return root_inputs(record)
    except FileNotFoundError as error:
        raise OperationFailure(
            "not_ready", "candidate worker has not claimed its workspace"
        ) from error


def selected_control(record: OperationRecord) -> Path:
    root, _, initial = root_inputs(record)
    return segment_control(initial, None if record == root else record.submission.request_id)


def read_segment(record: OperationRecord) -> tuple[CandidateRunReceipt, str] | None:
    try:
        root, saved, initial = root_inputs(record)
    except FileNotFoundError:
        if record.submission.kind == "candidate":
            return None
        raise
    segment_id = None if record == root else record.submission.request_id
    control = segment_control(initial, segment_id)
    if segment_id is not None:
        binding = read_continuation(initial, segment_id)
        assert record.submission.kind == "candidate_loop_resume"
        previous = load_record(record.config, record.submission.request.predecessor_operation_id)
        expected_segment = (
            None if previous.submission.kind == "candidate" else previous.submission.request_id
        )
        if (
            binding.predecessor_segment != expected_segment
            or binding.predecessor_receipt_digest
            != record.submission.request.expected_receipt_digest
        ):
            raise OperationFailure("integrity", "resume request disagrees with native binding")
    try:
        payload = read_bytes(control / "receipt.json")
    except FileNotFoundError:
        return None
    receipt = CandidateRunReceipt.model_validate_json(payload)
    if receipt.loop_trace is not None and receipt.loop_trace.segment_id != segment_id:
        raise OperationFailure("integrity", "receipt belongs to another loop segment")
    verify_candidate_records(
        saved,
        initial,
        expected_request=saved,
        expected_run_id=root.native_id.hex,
        workspace=Path(initial.workspace),
        receipt=receipt,
    )
    return receipt, hashlib.sha256(payload).hexdigest()


def successor_id(record: OperationRecord) -> UUID | None:
    try:
        binding = read_model(selected_control(record) / "successor.json", LoopContinuation)
    except FileNotFoundError:
        return None
    _, _, initial = root_inputs(record)
    if read_continuation(initial, binding.operation_id) != binding:
        raise OperationFailure("integrity", "loop successor changed")
    return binding.operation_id


def review_locked(config: OperationStoreConfig, operation_id: UUID) -> OperationSnapshot:
    from tools.candidate_worker.loop import stop_requested
    from tools.candidate_worker.loop_evidence import require_unused_next

    from .read import bound, optional, read_operation

    record = load_record(config, operation_id)
    _, request, initial = claimed_inputs(record)
    snapshot = read_operation(config, operation_id)
    receipt = snapshot.receipt
    if (
        snapshot.process.status != "exited"
        or not isinstance(receipt, CandidateRunReceipt)
        or receipt.status != "paused"
        or receipt.loop_trace is None
        or not snapshot.receipt_digest
    ):
        raise OperationFailure("loop_resume", "resume requires an exited, verified paused segment")
    completion = optional(operation_path(config, operation_id) / "completion.json", Completion)
    if completion is None:
        raise OperationFailure("loop_resume", "paused operation has no bound completion")
    bound(record, completion)
    if completion.outcome != "native" or completion.receipt_digest != snapshot.receipt_digest:
        raise OperationFailure("loop_resume", "paused completion identity disagrees")
    try:
        require_clean(selected_control(record))
    except (OSError, ValueError) as error:
        # Missing, unknown or unclean supervision is never resume authorization.
        raise OperationFailure("loop_resume", "paused segment lacks clean supervision") from error
    if successor_id(record) is not None:
        raise OperationFailure("loop_resume", "paused segment already has a successor")
    loop = request.preview.document.definition.loop
    assert loop is not None
    if receipt.loop_trace.attempted_iterations >= loop.final_iteration or stop_requested(initial):
        raise OperationFailure("loop_resume", "loop is terminal")
    # Deliberately redundant with the paused readback above: defense in depth.
    try:
        require_unused_next(request, initial, receipt.loop_trace.attempted_iterations)
    except ValueError as error:
        raise OperationFailure("loop_resume", "next body slot is not unused") from error
    return snapshot


def review_loop_resume(config: OperationStoreConfig, operation_id: UUID) -> OperationSnapshot:
    """Review one exited paused segment; its receipt_digest is the resume request's expectation."""
    config = validate_config(config)
    with locked_store(config, create=False):
        return review_locked(config, operation_id)


def admit(
    config: OperationStoreConfig,
    submission: CandidateLoopResumeOperation,
    launch_environment: Mapping[str, str],
) -> tuple[str, ...]:
    """Admit one Resume under the store lock; return the root's credential environment names."""
    review = review_locked(config, submission.request.predecessor_operation_id)
    if review.receipt_digest != submission.request.expected_receipt_digest:
        raise OperationFailure("loop_resume", "reviewed paused receipt changed")
    root, saved, initial = root_inputs(
        load_record(config, submission.request.predecessor_operation_id)
    )
    assert root.submission.kind == "candidate"
    try:
        # The same file-identity check the continuation child repeats; refusing here
        # keeps an edited input from consuming the single successor reservation.
        verify_inputs(saved, segment_control(initial, None))
    except (OSError, ValueError) as error:
        raise OperationFailure("loop_resume", "captured loop inputs changed") from error
    if runtime_identity() != root.runtime:
        raise OperationFailure("runtime", "continuation runtime changed")
    try:
        require_credentials(
            root.submission.request.selected_constructor_routes,
            root.submission.request.environment_names,
            launch_environment,
        )
    except ValueError as error:
        raise OperationFailure("credentials", str(error)) from error
    return root.submission.request.environment_names


def reserve(record: OperationRecord) -> None:
    assert record.submission.kind == "candidate_loop_resume"
    previous = load_record(record.config, record.submission.request.predecessor_operation_id)
    _, _, initial = root_inputs(previous)
    native = read_segment(previous)
    if (
        native is None
        or native[0].loop_trace is None
        or native[1] != record.submission.request.expected_receipt_digest
    ):
        raise OperationFailure("integrity", "reviewed checkpoint changed before reservation")
    binding = LoopContinuation(
        run_id=initial.run_id,
        declaration_digest=initial.declaration_digest,
        operation_id=record.submission.request_id,
        predecessor_segment=native[0].loop_trace.segment_id,
        predecessor_receipt_digest=native[1],
        completed_iterations=native[0].loop_trace.attempted_iterations,
    )
    # The private operation claim already exists. Any failed publication stays unresolved.
    control = segment_control(initial, binding.operation_id)
    with directory(segment_control(initial, None)) as descriptor, suppress(FileExistsError):
        os.mkdir("continuations", dir_fd=descriptor)
    with directory(control.parent) as descriptor:
        os.mkdir(control.name, dir_fd=descriptor)
    with directory(control) as descriptor:
        publish_bytes_write_once(
            f"/proc/self/fd/{descriptor}/continuation.json", encode_control(binding)
        )
    with directory(selected_control(previous)) as descriptor:
        publish_bytes_write_once(
            f"/proc/self/fd/{descriptor}/successor.json", encode_control(binding)
        )


def execute_resume(record: OperationRecord) -> None:
    # Read the selected binding against the admitted operation before native dispatch.
    read_segment(record)
    _, request, initial = root_inputs(record)
    binding = read_continuation(initial, record.submission.request_id)
    launch_continuation(request, initial, binding)


def request_loop_pause(config: OperationStoreConfig, operation_id: UUID) -> LoopPause:
    from .read import read_operation

    config = validate_config(config)
    with locked_store(config, create=False):
        record = load_record(config, operation_id)
        root, _, initial = claimed_inputs(record)
        segment_id = None if record == root else record.submission.request_id
        marker = LoopPause(
            run_id=initial.run_id,
            declaration_digest=initial.declaration_digest,
            segment_id=segment_id,
        )
        control = segment_control(initial, segment_id)
        try:
            prior = read_model(control / "pause.json", LoopPause)
        except FileNotFoundError:
            prior = None
        if prior is not None:
            if prior != marker:
                raise OperationFailure("integrity", "Pause identity changed")
            return marker
        snapshot = read_operation(config, operation_id)
        if snapshot.receipt_available or snapshot.process.status != "alive":
            raise OperationFailure("not_running", "candidate is terminal or not confirmed running")
        with directory(control) as descriptor:
            publish_bytes_write_once(
                f"/proc/self/fd/{descriptor}/pause.json", encode_control(marker)
            )
        return marker
