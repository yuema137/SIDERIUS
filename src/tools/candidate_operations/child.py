"""One operation process: publish identity, invoke native owner, record references."""

import os
import sys
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from core.seeding import MissingRunSeed
from tools.candidate_prepare import prepare_candidate, prepare_reusable_candidate
from tools.candidate_prepare.reusable_models import ReusablePreparationObservations
from tools.candidate_worker import launch_candidate

from .files import canonical, publish, read_model
from .host_liveness import PLACEMENT_FILE, SANDBOX_FILE
from .models import SEEDED_SUBMISSIONS, Completion, OperationRecord
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

            execute_resume(record)
        else:
            launch_candidate(
                record.submission.request,
                invocation_id=record.native_id,
                run_seed=record.run_seed,
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
    publish(path / "completion.json", completion)
    return 0 if completion.outcome == "native" else 1


def sandbox_observer(record: OperationRecord, path: Path) -> dict[str, Callable[[int], None]]:
    """A placed (host-ledger) operation publishes its sandbox identity for release.

    The sandbox runs in its own session, outside this process's, so the ledger
    must observe it separately. Serial operations have no ``placement.json`` and
    launch exactly as before.
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
