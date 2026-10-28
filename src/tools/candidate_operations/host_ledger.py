"""Host-level reservation ledger shared by separate operation stores (B3-5a).

One private directory, serialized by ``flock``, records which candidate operations
hold part of an operator-declared ``HostBudget``. Placement arithmetic is
``plan_dispatch``; this module only persists its placements, binds each one to the
operation child's process identity and releases it on evidence. Contract:
candidate-operations-contract.md, "Host reservation ledger".
"""

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, NonNegativeInt, model_validator

from core.runtime_control.scheduling import HostBudget, Placement
from tools.workflow_preview.models import PreviewModel
from tools.workspace_sandbox.profile import runtime_roots

from .files import canonical, directory, overlap, private, private_directory, publish, read_model
from .models import OperationFailure, ProcessIdentity
from .process import observe, session_members

LEDGER_FILE = "ledger.json"
LOCK_FILE = "ledger.lock"


class HostScheduling(PreviewModel):
    """Caller selection: a ledger directory and, for budgeted launches, its budget."""

    ledger_root: str
    budget: HostBudget | None = None


class HostReservation(PreviewModel):
    """One placed operation's reservation; ``process`` is bound right after spawn."""

    operation_id: UUID
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_root: str
    placement: Placement
    time_budgeted: bool
    process: ProcessIdentity | None = None

    @model_validator(mode="after")
    def bound_identity(self):
        if self.placement.decision != "placed" or self.placement.unit_id != str(self.operation_id):
            raise ValueError("a reservation holds its own operation's placed unit")
        process = self.process
        if process is not None and (
            process.operation_id != self.operation_id
            or process.request_digest != self.request_digest
        ):
            raise ValueError("reservation process identity names another operation")
        return self


class HostLedgerState(PreviewModel):
    """Live reservations against one budget digest, plus the next submission ordinal."""

    version: Literal[1] = 1
    next_ordinal: NonNegativeInt = 0
    reservations: tuple[HostReservation, ...] = ()

    @model_validator(mode="after")
    def one_budget(self):
        digests = {r.placement.budget_digest for r in self.reservations}
        ids = [r.operation_id for r in self.reservations]
        if len(digests) > 1 or len(set(ids)) != len(ids):
            raise ValueError("ledger reservations must be distinct and share one budget")
        if any(r.placement.dispatch_ordinal >= self.next_ordinal for r in self.reservations):
            raise ValueError("ledger ordinal counter is behind its reservations")
        return self

    @property
    def budget_digest(self) -> str | None:
        return self.reservations[0].placement.budget_digest if self.reservations else None


class SessionEvidence(PreviewModel):
    """Liveness of a reservation's operation child and of its whole session."""

    leader: Literal["alive", "exited", "unknown"]
    members: int | None = Field(ge=0)

    @property
    def ended(self) -> bool:
        """Positive exit and no surviving session member: safe to release automatically."""
        return self.leader == "exited" and self.members == 0

    @property
    def appears_live(self) -> bool:
        return self.leader == "alive" or bool(self.members)


class ReservationRelease(PreviewModel):
    operation_id: UUID
    evidence: SessionEvidence | None
    released: Literal[True] = True


def session_evidence(identity: ProcessIdentity) -> SessionEvidence:
    observation = observe(identity)
    if observation.reason == "different_boot":
        return SessionEvidence(leader="exited", members=0)
    # The child is a session leader (start_new_session), so its PID is the session ID.
    return SessionEvidence(leader=observation.status, members=session_members(identity.pid))


def ledger_directory(ledger_root: str) -> Path:
    root = canonical(ledger_root)
    if any(overlap(root, runtime) for runtime in runtime_roots()):
        raise OperationFailure("path", "host ledger overlaps runtime/source")
    return root


@contextmanager
def locked_ledger(ledger_root: str, *, create: bool = True) -> Iterator[Path]:
    root = ledger_directory(ledger_root)
    private_directory(root, create=create)
    with directory(root) as descriptor:
        lock = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
    try:
        private(os.fstat(lock), directory=False)
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield root
    finally:
        os.close(lock)


def read_state(root: Path) -> HostLedgerState:
    try:
        return read_model(root / LEDGER_FILE, HostLedgerState, private_file=True)
    except FileNotFoundError:
        return HostLedgerState()


def write_state(root: Path, state: HostLedgerState) -> None:
    publish(root / LEDGER_FILE, state, replace=True)


def sweep(root: Path) -> HostLedgerState:
    """Drop reservations whose child exited and whose session ended; keep everything else."""
    state = read_state(root)
    live = tuple(
        r for r in state.reservations if r.process is None or not session_evidence(r.process).ended
    )
    if live != state.reservations:
        state = state.model_copy(update={"reservations": live})
        write_state(root, state)
    return state


def without(root: Path, operation_id: UUID) -> None:
    state = read_state(root)
    kept = tuple(r for r in state.reservations if r.operation_id != operation_id)
    write_state(root, state.model_copy(update={"reservations": kept}))


def bind(root: Path, operation_id: UUID, identity: ProcessIdentity) -> None:
    state = read_state(root)
    bound = tuple(
        r.model_copy(update={"process": identity}) if r.operation_id == operation_id else r
        for r in state.reservations
    )
    write_state(root, HostLedgerState(next_ordinal=state.next_ordinal, reservations=bound))


def published_identity(reservation: HostReservation) -> ProcessIdentity | None:
    """An unbound reservation's identity as the child published it, if it did."""
    path = Path(reservation.state_root) / "operations" / str(reservation.operation_id)
    try:
        identity = read_model(path / "process.json", ProcessIdentity, private_file=True)
    except FileNotFoundError:
        return None
    if (
        identity.operation_id != reservation.operation_id
        or identity.request_digest != reservation.request_digest
    ):
        raise OperationFailure("integrity", "published process identity names another operation")
    return identity


def release_reservation(ledger_root: str, operation_id: UUID) -> ReservationRelease:
    """Operator release of a stuck reservation; refuses while its session appears live.

    Unlike the automatic sweep, this does not require a positive exit: an
    unobservable leader with no visible session member, or an unbound reservation
    whose child never published an identity, is released on the operator's word.
    """
    with locked_ledger(ledger_root, create=False) as root:
        state = read_state(root)
        match = [r for r in state.reservations if r.operation_id == operation_id]
        if not match:
            raise OperationFailure("not_reserved", "operation holds no host reservation")
        identity = match[0].process or published_identity(match[0])
        evidence = None if identity is None else session_evidence(identity)
        if evidence is not None and evidence.appears_live:
            raise OperationFailure("session_live", "operation session still appears live")
        if evidence is not None and evidence.leader == "unknown" and evidence.members is None:
            raise OperationFailure("liveness_unobservable", "cannot observe the operation session")
        without(root, operation_id)
        return ReservationRelease(operation_id=operation_id, evidence=evidence)
