"""Preserve selected terminal history while verifying authorized append-only progress."""

import os
from pathlib import Path

from core.native_writer.resume import reservation_name
from tools.native_chain.observation import NativeChainEvidence

from .models import OperationRecord, OperationSnapshot
from .native_chain_models import NativeChainContinuation, NativeChainObservation
from .native_chain_read import chain_context, chain_evidence, chain_state
from .native_resume_lineage import ChainLineage, read_lineage
from .store import now


def has_continuation(record: OperationRecord) -> bool:
    if record.submission.kind == "native_chain_resume":
        return True
    _, admission = chain_context(record)
    workspace = Path(admission.workspace)
    return os.path.lexists(
        workspace.parent
        / f".{workspace.name}.siderius-writer"
        / reservation_name(record.submission.request_id)
    )


def prefix_equal(baseline: NativeChainEvidence, current: NativeChainEvidence, start: int) -> bool:
    return (
        baseline.availability == current.availability == "available"
        and not baseline.anomalies
        and not current.anomalies
        and baseline.token_run_id == current.token_run_id
        and baseline.token_sidecar_sha256 == current.token_sidecar_sha256
        and tuple(row for row in baseline.checkpoints if row.iteration < start)
        == tuple(row for row in current.checkpoints if row.iteration < start)
    )


def verified_current(lineage: ChainLineage) -> NativeChainEvidence:
    current = chain_evidence(lineage.head.record)
    for index, reservation in enumerate(lineage.reservations):
        child = lineage.nodes[index + 1]
        admitted = child.record.native_resume_admission
        assert admitted is not None
        if not prefix_equal(admitted.evidence, current, reservation.start_iteration):
            raise ValueError("resume_preserved_prefix_changed")
        # A reservation alone never permits even a new suffix. No-child links
        # can precede later adopted successors, whose own baseline is checked.
        if lineage.adoptions[index] is None:
            # An earlier missing adoption cannot borrow authority from a later
            # link. Genuine no-child links retain their unchanged baseline.
            if child.terminal is not None:
                boundary = child.terminal.evidence
            elif index + 1 < len(lineage.reservations):
                following = lineage.nodes[index + 2].record.native_resume_admission
                assert following is not None
                boundary = following.evidence
            else:
                boundary = current
            if boundary != admitted.evidence:
                raise ValueError("resume_unadopted_science_changed")
        if child.terminal is not None and not prefix_equal(
            admitted.evidence, child.terminal.evidence, reservation.start_iteration
        ):
            raise ValueError("resume_terminal_changed_prefix")
    tail = lineage.head
    if tail.terminal is not None and current != tail.terminal.evidence:
        raise ValueError("changed_after_terminal")
    return current


def read_resume_chain(record: OperationRecord) -> OperationSnapshot:
    lineage = read_lineage(record, allow_unlinked=True)
    selected = lineage.selected
    if selected.spawn_failure is not None:
        if selected.id in {node.id for node in lineage.nodes}:
            raise ValueError("resume_linked_spawn_failure")
        return OperationSnapshot(
            operation_id=selected.id,
            kind=record.submission.kind,
            request_digest=record.request_digest,
            observed_at=now(),
            state="operation_failed",
            process=selected.process,
            reason="spawn_failed",
        )
    if selected.id not in {node.id for node in lineage.nodes}:
        if selected.terminal is not None or (
            selected.completion is not None
            and selected.completion.outcome != "pre_dispatch_failure"
        ):
            raise ValueError("resume_unlinked_outcome")
        state, reason = chain_state(selected.process, selected.completion, selected.terminal)
        return OperationSnapshot(
            operation_id=selected.id,
            kind=record.submission.kind,
            request_digest=record.request_digest,
            observed_at=now(),
            state=state,
            process=selected.process,
            reason=reason,
        )
    state, reason = chain_state(selected.process, selected.completion, selected.terminal)
    try:
        evidence = verified_current(lineage)
    except ValueError:
        evidence = NativeChainEvidence(
            availability="integrity_failure", anomalies=("changed_after_terminal",)
        )
    head_state, _ = chain_state(
        lineage.head.process, lineage.head.completion, lineage.head.terminal
    )
    head = lineage.head
    lifecycle = (
        "terminal"
        if head.terminal is not None
        else "adopted"
        if lineage.adoptions and lineage.adoptions[-1] is not None
        else "no_child"
        if head.completion is not None and head.completion.reason == "native_resume_spawn_failed"
        else "reserved"
    )
    return OperationSnapshot(
        operation_id=selected.id,
        kind=record.submission.kind,
        request_digest=record.request_digest,
        observed_at=now(),
        state=state,
        process=selected.process,
        reason=reason,
        finishing=state == "completed" and selected.process.status == "alive",
        native_chain=NativeChainObservation(
            admission=chain_context(record)[1],
            terminal=selected.terminal,
            evidence=evidence,
            continuation=NativeChainContinuation(
                root_operation_id=lineage.nodes[0].id,
                head_operation_id=head.id,
                head_state=head_state,
                lifecycle=lifecycle,
            ),
        ),
    )
