"""One operation process: publish identity, invoke native owner, record references."""

import os
import sys
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from core.runtime_control.scheduling import Placement
from core.seeding import MissingRunSeed
from tools.candidate_prepare import prepare_candidate, prepare_reusable_candidate
from tools.candidate_prepare.reusable_models import ReusablePreparationObservations
from tools.candidate_worker import launch_candidate

from .cancel import cancel_probe
from .files import canonical, publish, read_model
from .host_liveness import PLACEMENT_FILE, SANDBOX_FILE, published_identity
from .host_queue import is_queued, wait_for_placement
from .models import (
    SEEDED_SUBMISSIONS,
    Completion,
    HostPlacementEvidence,
    OperationRecord,
)
from .native_chain import execute_native_chain
from .native_resume_execute import execute_native_resume
from .process import current_identity, identity_of, runtime_identity
from .read import native_receipt
from .reusable import verify_reusable_operation
from .store import load_record


def execute(path: Path) -> int:
    canonical(str(path))
    # No caller-selected executable or callable; the directory UUID binds the record.
    seed = read_model(path / "request.json", OperationRecord, private_file=True)
    record = load_record(seed.config, UUID(path.name))
    expected = Path(record.config.state_root) / "operations" / str(record.submission.request_id)
    if path != expected:
        raise ValueError("operation directory disagrees with request")
    publish(path / "process.json", current_identity(record))
    entered = False
    pre_dispatch_reason = "runtime_binding_failed"
    try:
        if runtime_identity() != record.runtime:
            raise ValueError("operation runtime binding changed")
        if is_queued(path):
            pre_dispatch_reason = "host_queue_failed"
            cancel = cancel_probe(path, record)
            if wait_for_placement(path, record.submission.request_id, cancel) is None:
                pre_dispatch_reason = "cancelled_while_queued"
                raise _LeftQueue
        if (
            record.submission.kind == "candidate"
            and record.submission.reusable_preparation is not None
        ):
            pre_dispatch_reason = "reusable_preparation_failed"
            verify_reusable_operation(record.config, record.submission)
        if record.submission.kind == "native_chain":
            completion = execute_native_chain(record, path)
            publish(path / "completion.json", completion)
            return 0 if completion.outcome == "native_chain" else 1
        if record.submission.kind == "native_chain_resume":
            completion = execute_native_resume(record, path)
            publish(path / "completion.json", completion)
            return 0 if completion.outcome == "native_chain" else 1
        if isinstance(record.submission, SEEDED_SUBMISSIONS) and record.run_seed is None:
            # Only admission binds a seed; the child never generates a second one.
            raise MissingRunSeed("operation record has no admitted run seed")
        entered = True
        if record.submission.kind == "prepare":
            prepare_candidate(
                record.submission.request,
                invocation_id=record.native_id,
                run_seed=record.run_seed,
            )
        elif record.submission.kind == "prepare_reusable":
            prepare_reusable_candidate(
                record.submission.request,
                invocation_id=record.native_id,
                expected_observations=ReusablePreparationObservations.from_inputs(record.inputs),
                run_seed=record.run_seed,
            )
        elif record.submission.kind == "candidate_loop_resume":
            from .loop_resume import execute_resume

            execute_resume(
                record,
                cancel_requested=cancel_probe(path, record),
                **sandbox_observer(record, path),
            )
        else:
            launch_candidate(
                record.submission.request,
                invocation_id=record.native_id,
                run_seed=record.run_seed,
                cancel_requested=cancel_probe(path, record),
                **sandbox_observer(record, path),
            )
        native = native_receipt(record)
        if native is None:
            raise ValueError("native invocation returned without final receipt")
        completion = Completion(
            operation_id=record.submission.request_id,
            request_digest=record.request_digest,
            outcome="native",
            receipt_digest=native[1],
            reason="native_terminal",
        )
    except (Exception, KeyboardInterrupt):
        # Do not serialize exception messages: arbitrary plugins can include credentials.
        completion = Completion(
            operation_id=record.submission.request_id,
            request_digest=record.request_digest,
            outcome="unknown" if entered else "pre_dispatch_failure",
            reason="native_outcome_unresolved" if entered else pre_dispatch_reason,
        )
    try:
        evidence = host_placement_evidence(record, path)
    except (OSError, ValueError):
        evidence = None  # the outcome is still published; placement.json stays readable
    if evidence is not None:
        completion = completion.model_copy(update={"host_placement": evidence})
    publish(path / "completion.json", completion)
    return 0 if completion.outcome == "native" else 1


class _LeftQueue(Exception):
    """A recorded cancel removed the queued operation before it ran."""


def host_placement_evidence(record: OperationRecord, path: Path) -> HostPlacementEvidence | None:
    """The placement and the identities its release depends on; ``None`` when never placed."""
    if not os.path.lexists(path / PLACEMENT_FILE):
        return None
    state_root, operation_id = record.config.state_root, record.submission.request_id
    return HostPlacementEvidence(
        placement=read_model(path / PLACEMENT_FILE, Placement, private_file=True),
        process=current_identity(record),
        sandbox=published_identity(state_root, operation_id, record.request_digest, SANDBOX_FILE),
    )


def sandbox_observer(record: OperationRecord, path: Path) -> dict[str, Callable[[int], None]]:
    """A placed (host-ledger) operation publishes its sandbox identity for release.

    The sandbox runs in its own session, outside this process's, so the ledger
    must observe it separately. Serial operations have no ``placement.json`` and
    launch exactly as before. Called after any queue wait, so a queued operation
    that was placed publishes it too.
    """
    if not os.path.lexists(path / PLACEMENT_FILE):
        return {}

    def publish_sandbox(pid: int) -> None:
        publish(path / SANDBOX_FILE, identity_of(record, pid))

    return {"on_sandbox_spawn": publish_sandbox}


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    try:
        return execute(Path(sys.argv[1]))
    except (Exception, KeyboardInterrupt):
        print("operation wrapper could not publish a trusted outcome", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
