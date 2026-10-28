"""Admit one submission against the host reservation ledger, around claim and spawn.

``host_slot`` is entered under the store lock, before the claim, and holds the
ledger lock until the child is spawned and bound. Without a ``HostScheduling``
selection it is a no-op, so the serial path is unchanged. A submission that fits
the budget but not the current ledger is queued (B3-5b): claimed and spawned, its
child then waits in ``host_queue``. Decisions B3-5 D1-D6.
"""

import subprocess
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from core.runtime_control.scheduling import HostBudget, Placement, plan_dispatch
from core.subprocess_env import CUDA_VISIBLE_DEVICES_ENV_VAR
from tools.candidate_worker.models import CandidateRunRequest

from .files import canonical, overlap, publish
from .host_ledger import (
    HostLedgerState,
    HostReservation,
    HostScheduling,
    QueuedOperation,
    bind,
    ledger_directory,
    locked_ledger,
    promote,
    sweep,
    without,
    write_state,
)
from .host_liveness import PLACEMENT_FILE
from .host_queue import QUEUE_FILE, HostQueueTicket
from .models import (
    CandidateOperation,
    OperationFailure,
    OperationRecord,
    OperationResources,
    OperationStoreConfig,
    OperationSubmission,
)
from .process import identity_of
from .store import load_record, native_directory

#: Names a placed GPU run must declare so its sandbox receives the placement.
GPU_PLACEMENT_NAMES = (CUDA_VISIBLE_DEVICES_ENV_VAR,)


class HostSlot:
    """Serial default: no ledger, no reservation, environment unchanged."""

    observation: Literal["starting", "queued"] = "starting"

    def launch_environment(self, source: Mapping[str, str]) -> Mapping[str, str]:
        return source

    def deferred_names(self) -> tuple[str, ...]:
        """Declared names the child receives only once it is placed."""
        return ()

    def reserve(self, path: Path, record: OperationRecord) -> None:
        pass

    def spawned(self, record: OperationRecord, child: subprocess.Popen) -> None:
        pass

    def spawn_failed(self, operation_id: UUID) -> None:
        pass


@dataclass(frozen=True)
class Admitted:
    """A placed or queued decision that passed every ledger rule.

    ``state`` is the swept ledger with earlier waiters already promoted; the
    reservation or queue entry for this submission is added to it after the claim.
    """

    placement: Placement
    state: HostLedgerState
    resources: OperationResources


class LedgerSlot(HostSlot):
    """A reservation or queue entry, written after the claim and bound after the spawn."""

    def __init__(self, root: Path, host: HostScheduling, admitted: Admitted):
        self.root = root
        self.host = host
        self.admitted = admitted
        self.observation = "queued" if admitted.placement.decision == "queued" else "starting"

    def launch_environment(self, source: Mapping[str, str]) -> Mapping[str, str]:
        """Overlay the placed GPU so every later name check and the child see it.

        The slot UUID replaces any inherited ``CUDA_VISIBLE_DEVICES``. The declared
        ``vram_gib`` is the ledger's accounting only; the run's own admission does
        not yet enforce it (#1018). A CPU-only unit binds no device node
        (admission), so it needs no selector. A queued unit has no slot yet.
        """
        if self.admitted.placement.gpu_uuid is None:
            return source
        return {**source, CUDA_VISIBLE_DEVICES_ENV_VAR: self.admitted.placement.gpu_uuid}

    def deferred_names(self) -> tuple[str, ...]:
        """A queued GPU unit's child sets the selector itself once placed."""
        placement = self.admitted.placement
        if placement.decision == "queued" and placement.reserved.gpu_count == 1:
            return GPU_PLACEMENT_NAMES
        return ()

    def reserve(self, path: Path, record: OperationRecord) -> None:
        placement = self.admitted.placement
        identity = {
            "operation_id": record.submission.request_id,
            "request_digest": record.request_digest,
            "state_root": record.config.state_root,
            "placement": placement,
        }
        entry = (
            QueuedOperation(**identity)
            if placement.decision == "queued"
            else HostReservation(**identity)
        )
        prior = self.admitted.state
        state = HostLedgerState(
            next_ordinal=prior.next_ordinal + 1,
            reservations=prior.reservations,
            queued=prior.queued,
        ).replacing((*prior.entries(), entry))
        # Fail closed: the entry exists before any child can.
        write_state(self.root, state)
        if placement.decision == "queued":
            ticket = HostQueueTicket(
                ledger_root=self.host.ledger_root, budget=self.host.budget, placement=placement
            )
            publish(path / QUEUE_FILE, ticket)
        else:
            publish(path / PLACEMENT_FILE, placement)

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
    root_operation, resources = _declared(config, submission)
    _require_disjoint(host.ledger_root, config, root_operation)
    with locked_ledger(host.ledger_root) as root:
        state = sweep(root)
        admitted = admit(
            state, host.budget, submission.request_id, root_operation.request, resources
        )
        yield LedgerSlot(root, host, admitted)


def _declared(
    config: OperationStoreConfig, submission: OperationSubmission
) -> tuple[CandidateOperation, OperationResources]:
    """The candidate whose request and declaration the ledger reserves for.

    A loop resume inherits its root candidate's declaration and launch request:
    the segment runs that request again in the same workspace.
    """
    operation = submission
    if submission.kind == "candidate_loop_resume":
        from .loop_resume import root_record

        root = root_record(load_record(config, submission.request.predecessor_operation_id))
        operation = root.submission
    if not isinstance(operation, CandidateOperation) or operation.resources is None:
        raise OperationFailure(
            "resources_required",
            "a budgeted launch requires a candidate (or the loop root of a resume) with a "
            "resources declaration",
        )
    return operation, operation.resources


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
    operation_id: UUID,
    request: CandidateRunRequest,
    resources: OperationResources,
) -> Admitted:
    """Return the placed or queued decision to record, or refuse with a typed reason.

    Earlier waiters are promoted first, so this submission is planned behind
    them in strict submission order and is placed only when all of them are.
    """
    if state.budget_digest not in (None, budget.digest):
        raise OperationFailure(
            "budget_mismatch",
            f"live ledger entries hold budget {state.budget_digest}; got {budget.digest}",
        )
    _require_reachable(request, resources)
    unit = resources.request(
        unit_id=str(operation_id),
        dispatch_ordinal=state.next_ordinal,
        wall_seconds=request.timeout_seconds,
    )
    state = promote(state, budget)
    waiting = tuple(entry.placement.reserved for entry in state.queued)
    running = tuple(r.placement for r in state.reservations)
    decision = plan_dispatch((*waiting, unit), running, budget, on_refusal="continue")
    own = [p for p in decision.placements + decision.refused if p.unit_id == str(operation_id)]
    if own[0].decision == "refused":
        raise OperationFailure("resource_refused", "; ".join(own[0].reasons))
    return Admitted(placement=own[0], state=state, resources=resources)


def _require_reachable(request: CandidateRunRequest, resources: OperationResources) -> None:
    """The child must actually receive the placement the ledger reserves."""
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
