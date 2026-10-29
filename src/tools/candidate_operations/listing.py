"""Read-only enumeration of this store's own admitted operation records.

Only ``{state_root}/operations/<uuid>`` entries are considered; each is loaded
through the same verified ``load_record`` / ``read_operation`` path as a single
read. Nothing is created, claimed, observed for liveness beyond ``read_operation``,
or launched. A record that cannot be verified is counted, never guessed.
"""

import os
from datetime import datetime
from uuid import UUID

from pydantic import ValidationError

from .files import canonical, directory, private_directory
from .models import (
    CandidateLoopResumeOperation,
    OperationFailure,
    OperationListEntry,
    OperationListing,
    OperationRecord,
    OperationStoreConfig,
    PrepareOperation,
    ReusablePrepareOperation,
)
from .native_chain_models import NativeChainOperation
from .native_resume_models import NativeChainResumeOperation
from .read import read_operation
from .store import load_record, validate_config

MAX_LISTED = 200
# Directory entries examined per listing. A store holding more reports itself
# incomplete instead of reading an unbounded number of records per request.
SCAN_LIMIT = 4096
_UNREADABLE = (OSError, ValueError, ValidationError)


def _labels(config: OperationStoreConfig, record: OperationRecord) -> tuple[str | None, str | None]:
    """Run name and setup (editor project) id; generated names and ids only, never paths.

    The id is the recorded ``setup_id`` of a reusable preparation or candidate (a loop
    resume uses its root candidate's), else a reviewed edited run's ``project_id``.
    """
    submission = record.submission
    if isinstance(submission, ReusablePrepareOperation):
        return submission.request.run_name, submission.request.setup_id
    if isinstance(submission, PrepareOperation):
        return submission.request.run_name, None
    if isinstance(submission, NativeChainOperation):
        admission = record.native_chain_admission
        return (admission.run_name if admission else None), None
    if isinstance(submission, NativeChainResumeOperation):
        resume = record.native_resume_admission
        return (resume.root_admission.run_name if resume else None), None
    if isinstance(submission, CandidateLoopResumeOperation):
        from .loop_resume import loop_root_operation

        root = loop_root_operation(config, submission.request_id)
        if root is None:
            return None, None
        candidate = root
    else:
        candidate = submission
    request = candidate.request
    source = request.workflow_source
    context = source.reviewed_context if source else None
    if candidate.setup_id is not None:
        return request.run_name, candidate.setup_id
    return request.run_name, (context.project_id if context else None)


def _admitted(record: OperationRecord) -> datetime:
    return datetime.fromisoformat(record.admitted_at)


def list_operations(
    config: OperationStoreConfig, limit: int = 50, project_id: str | None = None
) -> OperationListing:
    """Most recently admitted operations first, at most ``limit`` (1..MAX_LISTED).

    ``project_id`` keeps only records attributed to that setup; it is applied to
    every verified record before ``limit``, so older matching runs are not lost to
    newer unrelated ones. ``incomplete`` still reports a store beyond ``SCAN_LIMIT``.
    """
    if not 0 < limit <= MAX_LISTED:
        raise OperationFailure("limit", f"limit must be between 1 and {MAX_LISTED}")
    config = validate_config(config)
    root = canonical(config.state_root)
    operations = root / "operations"
    if not os.path.lexists(operations):
        return OperationListing(entries=(), unreadable=0, examined=0, incomplete=False)
    private_directory(root)
    private_directory(operations)
    with directory(operations) as descriptor:
        names = sorted(os.listdir(descriptor))
    incomplete = len(names) > SCAN_LIMIT
    names = names[:SCAN_LIMIT]
    records: list[OperationRecord] = []
    unreadable = 0
    for name in names:
        try:
            operation_id = UUID(name)
            if str(operation_id) != name:
                raise ValueError("non-canonical operation directory name")
            record = load_record(config, operation_id)
            admitted = _admitted(record)
            if admitted.tzinfo is None:
                raise ValueError("admission time has no timezone")
        except _UNREADABLE:
            unreadable += 1
            continue
        records.append(record)
    records.sort(key=lambda r: (_admitted(r), str(r.submission.request_id)), reverse=True)
    labelled: list[tuple[OperationRecord, str | None, str | None]] = []
    # Unfiltered: the newest ``limit`` records, as before. Filtered: newest matches.
    for record in records if project_id is not None else records[:limit]:
        if len(labelled) == limit:
            break
        try:
            run_name, recorded = _labels(config, record)
        except _UNREADABLE:
            unreadable += 1
            continue
        if project_id is None or recorded == project_id:
            labelled.append((record, run_name, recorded))
    entries: list[OperationListEntry] = []
    for record, run_name, recorded in labelled:
        try:
            snapshot = read_operation(config, record.submission.request_id)
        except _UNREADABLE:
            unreadable += 1
            continue
        entries.append(
            OperationListEntry(
                admitted_at=record.admitted_at,
                run_name=run_name,
                project_id=recorded,
                snapshot=snapshot,
            )
        )
    return OperationListing(
        entries=tuple(entries),
        unreadable=unreadable,
        examined=len(names),
        incomplete=incomplete,
    )


__all__ = ["MAX_LISTED", "SCAN_LIMIT", "list_operations"]
