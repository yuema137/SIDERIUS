"""Operator cancellation of one live candidate operation (durable intent, child-enforced).

The submitter side only records a write-once ``cancel.json`` in the private
operation directory. The operation child, which created the sandbox process
group, polls it through ``workspace_sandbox.runner`` and terminates that group
through the existing ``terminate_observed_group`` owner. No second kill path
exists: the sandbox runs with ``--die-with-parent``, so a group cannot outlive
an operation child that is gone. Contract: candidate-operations-contract.md,
"Cancel an active candidate operation".
"""

from pathlib import Path
from uuid import UUID

from tools.candidate_worker.models import CandidateRunReceipt
from tools.workspace_sandbox.runner import CancelProbe

from .files import publish, read_model
from .models import CancelRequest, OperationFailure, OperationRecord, OperationStoreConfig
from .store import load_record, locked_store, now, operation_path, validate_config

CANCEL_FILE = "cancel.json"
#: Kinds whose single sandbox the operation child supervises with a cancel probe.
CANCELLABLE_KINDS = frozenset({"candidate", "candidate_loop_resume"})


def read_cancel(path: Path, record: OperationRecord) -> CancelRequest | None:
    """The recorded intent bound to this operation; ``None`` when absent."""
    try:
        marker = read_model(path / CANCEL_FILE, CancelRequest, private_file=True)
    except FileNotFoundError:
        return None
    if (
        marker.operation_id != record.submission.request_id
        or marker.request_digest != record.request_digest
    ):
        raise OperationFailure("integrity", "cancel request names another operation")
    return marker


def cancel_probe(path: Path, record: OperationRecord) -> CancelProbe:
    """Polled by the child; an unreadable or mismatched marker raises (run ends failed)."""
    return lambda: read_cancel(path, record) is not None


def require_cancel_evidence(receipt: CandidateRunReceipt, cancel: CancelRequest | None) -> None:
    """A ``cancelled`` receipt is genuine only beside a recorded operator intent."""
    if receipt.status == "cancelled" and cancel is None:
        raise OperationFailure("integrity", "cancelled receipt has no recorded cancel request")


def request_cancel(config: OperationStoreConfig, operation_id: UUID) -> CancelRequest:
    """Record cancel for one live candidate operation; idempotent, never a termination claim.

    A repeated call returns the first recorded request unchanged. An operation
    with a native receipt or failed admission refuses with ``terminal``; one not
    confirmed alive refuses with ``not_running``. Read ``read_operation`` for the
    outcome: the receipt status becomes ``cancelled`` unless the run finished first.
    """
    from .read import read_operation

    config = validate_config(config)
    with locked_store(config, create=False):
        record = load_record(config, operation_id)
        if record.submission.kind not in CANCELLABLE_KINDS:
            raise OperationFailure("kind", "cancel supports candidate operations only")
        path = operation_path(config, operation_id)
        prior = read_cancel(path, record)
        if prior is not None:
            return prior
        snapshot = read_operation(config, operation_id)
        if snapshot.receipt_available or snapshot.state == "operation_failed":
            raise OperationFailure("terminal", "operation already finished; nothing to cancel")
        if snapshot.process.status != "alive":
            raise OperationFailure("not_running", "operation is not confirmed running")
        marker = CancelRequest(
            operation_id=operation_id, request_digest=record.request_digest, requested_at=now()
        )
        publish(path / CANCEL_FILE, marker)
        return marker
