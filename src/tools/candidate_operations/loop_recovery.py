"""Abandoned loop segments: preserve reservations and require ended sessions."""

from uuid import UUID

from .host_liveness import reservation_evidence
from .models import OperationFailure, OperationRecord


def sessions_ended(record: OperationRecord) -> bool:
    """Wrapper exit alone does not prove that its sandbox has stopped writing."""
    try:
        evidence = reservation_evidence(
            record.config.state_root,
            record.submission.request_id,
            record.request_digest,
            None,
        )
        return evidence.child is not None and evidence.ended
    except (OSError, ValueError):
        return False


def failed_successor(record: OperationRecord) -> UUID | None:
    """Read one bound successor without recursively projecting its descendants."""
    from .loop_resume import successor_id
    from .read import _read_record
    from .store import load_record

    successor = successor_id(record)
    if successor is None:
        return None
    child = load_record(record.config, successor)
    submission = child.submission
    if (
        submission.kind != "candidate_loop_resume"
        or submission.request.predecessor_operation_id != record.submission.request_id
    ):
        raise OperationFailure("integrity", "successor operation names another predecessor")
    snapshot = _read_record(record.config, child, successor, project_successor_recovery=False)
    if snapshot.reason == "loop_process_exited" and sessions_ended(child):
        return successor
    return None
