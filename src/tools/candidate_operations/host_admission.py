"""Admit one submission against the host reservation ledger, around claim and spawn.

``host_slot`` is entered under the store lock, before the claim, and holds the
ledger lock until the child is spawned and bound. Without a ``HostScheduling``
selection it is a no-op, so the serial path is unchanged. Decisions B3-5 D1-D6.
"""

import subprocess
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from core.runtime_control.scheduling import HostBudget, Placement, plan_dispatch
from core.subprocess_env import CUDA_VISIBLE_DEVICES_ENV_VAR

from .files import publish
from .host_ledger import (
    HostLedgerState,
    HostReservation,
    HostScheduling,
    bind,
    locked_ledger,
    sweep,
    without,
    write_state,
)
from .models import CandidateOperation, OperationFailure, OperationRecord, OperationSubmission
from .process import identity_of

PLACEMENT_FILE = "placement.json"


class HostSlot:
    """Serial default: no ledger, no reservation, environment unchanged."""

    def launch_environment(self, source: Mapping[str, str]) -> Mapping[str, str]:
        return source

    def reserve(self, path: Path, record: OperationRecord) -> None:
        pass

    def spawned(self, record: OperationRecord, child: subprocess.Popen) -> None:
        pass

    def spawn_failed(self, operation_id: UUID) -> None:
        pass


class LedgerSlot(HostSlot):
    """A placed reservation, written after the claim and bound after the spawn."""

    def __init__(
        self,
        root: Path,
        state: HostLedgerState,
        placement: Placement,
        submission: CandidateOperation,
    ):
        self.root = root
        self.state = state
        self.placement = placement
        self.submission = submission

    def launch_environment(self, source: Mapping[str, str]) -> Mapping[str, str]:
        """Overlay the placed GPU so every later name check and the child see it.

        The slot UUID replaces any inherited value. A CPU-only unit binds no device
        node (admission), so it needs no selector.
        """
        if self.placement.gpu_uuid is None:
            return source
        return {**source, CUDA_VISIBLE_DEVICES_ENV_VAR: self.placement.gpu_uuid}

    def reserve(self, path: Path, record: OperationRecord) -> None:
        assert self.submission.resources is not None
        reservation = HostReservation(
            operation_id=self.submission.request_id,
            request_digest=record.request_digest,
            state_root=record.config.state_root,
            placement=self.placement,
            time_budgeted=self.submission.resources.time_budgeted,
        )
        state = HostLedgerState(
            next_ordinal=self.state.next_ordinal + 1,
            reservations=(*self.state.reservations, reservation),
        )
        # Fail closed: the reservation exists before any child can.
        write_state(self.root, state)
        publish(path / PLACEMENT_FILE, self.placement)

    def spawned(self, record: OperationRecord, child: subprocess.Popen) -> None:
        # The unreaped child pins its PID, so this identity cannot name a reused PID.
        bind(self.root, record.submission.request_id, identity_of(record, child.pid))

    def spawn_failed(self, operation_id: UUID) -> None:
        without(self.root, operation_id)


@contextmanager
def host_slot(host: HostScheduling | None, submission: OperationSubmission) -> Iterator[HostSlot]:
    if host is None:
        yield HostSlot()
        return
    with locked_ledger(host.ledger_root) as root:
        state = sweep(root)
        placement = admit(state, host.budget, submission)
        if placement is None:
            yield HostSlot()
            return
        assert isinstance(submission, CandidateOperation)
        yield LedgerSlot(root, state, placement, submission)


def admit(
    state: HostLedgerState, budget: HostBudget | None, submission: OperationSubmission
) -> Placement | None:
    """Return the placement to reserve, ``None`` for an admitted unbudgeted launch, or refuse."""
    if budget is None:
        if state.reservations:
            raise OperationFailure(
                "host_reserved",
                f"{len(state.reservations)} live host reservation(s); "
                "an unbudgeted launch would bypass the ledger",
            )
        return None
    if submission.kind != "candidate" or submission.resources is None:
        raise OperationFailure(
            "resources_required", "a budgeted launch requires a candidate resource declaration"
        )
    if state.budget_digest not in (None, budget.digest):
        raise OperationFailure(
            "budget_mismatch",
            f"live reservations hold budget {state.budget_digest}; got {budget.digest}",
        )
    _require_reachable(submission)
    unit = submission.resources.request(
        unit_id=str(submission.request_id),
        dispatch_ordinal=state.next_ordinal,
        wall_seconds=submission.request.timeout_seconds,
    )
    running = tuple(r.placement for r in state.reservations)
    decision = plan_dispatch((unit,), running, budget, on_refusal="continue")
    if decision.refused:
        raise OperationFailure("resource_refused", "; ".join(decision.refused[0].reasons))
    placement = decision.placements[0]
    if placement.decision == "queued":
        raise OperationFailure(
            "host_capacity", "cannot be placed now: " + "; ".join(placement.reasons)
        )
    _require_time_budget_acknowledged(state, placement, submission, budget)
    return placement


def _require_reachable(submission: CandidateOperation) -> None:
    """The child must actually receive the placement the ledger reserves."""
    assert submission.resources is not None
    request = submission.request
    if submission.resources.gpu_count == 1:
        if CUDA_VISIBLE_DEVICES_ENV_VAR not in request.environment_names:
            raise OperationFailure(
                "placement_unreachable",
                f"a GPU reservation requires {CUDA_VISIBLE_DEVICES_ENV_VAR} in environment_names "
                "so the sandbox receives the placed device",
            )
    elif request.devices:
        raise OperationFailure(
            "placement_unreachable", "a CPU-only reservation must not bind device nodes"
        )


def _require_time_budget_acknowledged(
    state: HostLedgerState,
    placement: Placement,
    submission: CandidateOperation,
    budget: HostBudget,
) -> None:
    """Decision B3-Q6: contention on a shared GPU changes measured-time admission."""
    assert submission.resources is not None
    if placement.gpu_uuid is None or budget.acknowledge_shared_gpu_time_budget:
        return
    sharing = [r for r in state.reservations if r.placement.gpu_uuid == placement.gpu_uuid]
    if sharing and (submission.resources.time_budgeted or any(r.time_budgeted for r in sharing)):
        raise OperationFailure(
            "shared_gpu_time_budget",
            f"a time-budgeted run would share {placement.gpu_uuid}; set "
            "acknowledge_shared_gpu_time_budget in the budget file to accept contention",
        )
