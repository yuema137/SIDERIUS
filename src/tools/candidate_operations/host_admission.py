"""Admit one submission against the host reservation ledger, around claim and spawn.

``host_slot`` is entered under the store lock, before the claim, and holds the
ledger lock until the child is spawned and bound. Without a ``HostScheduling``
selection it is a no-op, so the serial path is unchanged. Decisions B3-5 D1-D6.
"""

import subprocess
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from core.runtime_control.scheduling import HostBudget, Placement, plan_dispatch
from core.subprocess_env import CUDA_VISIBLE_DEVICES_ENV_VAR

from .files import canonical, overlap, publish
from .host_ledger import (
    HostLedgerState,
    HostReservation,
    HostScheduling,
    bind,
    ledger_directory,
    locked_ledger,
    sweep,
    without,
    write_state,
)
from .host_liveness import PLACEMENT_FILE
from .models import (
    CandidateOperation,
    OperationFailure,
    OperationRecord,
    OperationResources,
    OperationStoreConfig,
    OperationSubmission,
)
from .process import identity_of
from .store import native_directory

#: Names a placed GPU run must declare so its sandbox receives the placement.
GPU_PLACEMENT_NAMES = (CUDA_VISIBLE_DEVICES_ENV_VAR,)


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


@dataclass(frozen=True)
class Admitted:
    """A placement that passed every ledger rule, with the declaration it reserves."""

    placement: Placement
    operation: CandidateOperation
    resources: OperationResources


class LedgerSlot(HostSlot):
    """A placed reservation, written after the claim and bound after the spawn."""

    def __init__(self, root: Path, state: HostLedgerState, admitted: Admitted):
        self.root = root
        self.state = state
        self.admitted = admitted

    def launch_environment(self, source: Mapping[str, str]) -> Mapping[str, str]:
        """Overlay the placed GPU so every later name check and the child see it.

        The slot UUID replaces any inherited ``CUDA_VISIBLE_DEVICES``. The declared
        ``vram_gib`` is the ledger's accounting only; the run's own admission does
        not yet enforce it (#1018). A CPU-only unit binds no device node
        (admission), so it needs no selector.
        """
        if self.admitted.placement.gpu_uuid is None:
            return source
        return {**source, CUDA_VISIBLE_DEVICES_ENV_VAR: self.admitted.placement.gpu_uuid}

    def reserve(self, path: Path, record: OperationRecord) -> None:
        reservation = HostReservation(
            operation_id=record.submission.request_id,
            request_digest=record.request_digest,
            state_root=record.config.state_root,
            placement=self.admitted.placement,
        )
        state = HostLedgerState(
            next_ordinal=self.state.next_ordinal + 1,
            reservations=(*self.state.reservations, reservation),
        )
        # Fail closed: the reservation exists before any child can.
        write_state(self.root, state)
        publish(path / PLACEMENT_FILE, self.admitted.placement)

    def spawned(self, record: OperationRecord, child: subprocess.Popen) -> None:
        # The unreaped child pins its PID, so this identity cannot name a reused PID.
        bind(self.root, record.submission.request_id, identity_of(record, child.pid))

    def spawn_failed(self, operation_id: UUID) -> None:
        without(self.root, operation_id)


@contextmanager
def host_slot(
    host: HostScheduling | None,
    config: OperationStoreConfig,
    submission: OperationSubmission,
) -> Iterator[HostSlot]:
    if host is None:
        yield HostSlot()
        return
    operation, resources = _declared(submission)
    _require_disjoint(host.ledger_root, config, operation)
    with locked_ledger(host.ledger_root) as root:
        state = sweep(root)
        admitted = admit(state, host.budget, operation, resources)
        yield LedgerSlot(root, state, admitted)


def _declared(submission: OperationSubmission) -> tuple[CandidateOperation, OperationResources]:
    if not isinstance(submission, CandidateOperation) or submission.resources is None:
        raise OperationFailure(
            "resources_required",
            "a budgeted launch requires a candidate submission with a resources declaration",
        )
    return submission, submission.resources


def _require_disjoint(
    ledger_root: str, config: OperationStoreConfig, operation: CandidateOperation
) -> None:
    """The ledger is host state: never inside a store, a workspace or a mounted input."""
    root = ledger_directory(ledger_root)
    owned = (
        canonical(config.state_root),
        native_directory(operation).parent,
        *(canonical(path) for path in operation.request.read_only),
    )
    if any(overlap(root, path) for path in owned):
        raise OperationFailure(
            "path", "host ledger overlaps the store, the workspace or a read-only input"
        )


def admit(
    state: HostLedgerState,
    budget: HostBudget,
    operation: CandidateOperation,
    resources: OperationResources,
) -> Admitted:
    """Return the placement to reserve, or refuse with a typed reason."""
    if state.budget_digest not in (None, budget.digest):
        raise OperationFailure(
            "budget_mismatch",
            f"live reservations hold budget {state.budget_digest}; got {budget.digest}",
        )
    _require_reachable(operation, resources)
    unit = resources.request(
        unit_id=str(operation.request_id),
        dispatch_ordinal=state.next_ordinal,
        wall_seconds=operation.request.timeout_seconds,
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
    return Admitted(placement=placement, operation=operation, resources=resources)


def _require_reachable(operation: CandidateOperation, resources: OperationResources) -> None:
    """The child must actually receive the placement the ledger reserves."""
    request = operation.request
    if resources.gpu_count == 1:
        missing = [name for name in GPU_PLACEMENT_NAMES if name not in request.environment_names]
        if missing:
            raise OperationFailure(
                "placement_unreachable",
                "a GPU reservation requires " + ", ".join(missing) + " in environment_names "
                "so the sandbox receives the placed device",
            )
    elif request.devices:
        raise OperationFailure(
            "placement_unreachable", "a CPU-only reservation must not bind device nodes"
        )
