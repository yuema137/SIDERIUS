"""Host-level reservation ledger shared by separate operation stores (B3-5a).

One private directory, serialized by ``flock``, records which candidate operations
hold part of an operator-declared ``HostBudget``. Placement arithmetic is
``plan_dispatch``; this module only persists its placements, binds each one to the
operation child's process identity and releases it on evidence
(``host_liveness``). Contract: candidate-operations-contract.md, "Host
reservation ledger".
"""

import fcntl
import os
import time
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
from .host_liveness import ReservationEvidence, reservation_evidence
from .models import OperationFailure, ProcessIdentity

LEDGER_FILE = "ledger.json"
LOCK_FILE = "ledger.lock"
#: Longest a caller waits for another submission's admission/spawn to finish.
LEDGER_LOCK_WAIT_SECONDS = 30.0
_LOCK_POLL_SECONDS = 0.05


class HostScheduling(PreviewModel):
    """Caller selection: an existing ledger directory and the budget it enforces."""

    ledger_root: str
    budget: HostBudget


class HostReservation(PreviewModel):
    """One placed operation's reservation; ``process`` is bound right after spawn."""

    operation_id: UUID
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_root: str
    placement: Placement
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

    def evidence(self) -> ReservationEvidence:
        return reservation_evidence(
            self.state_root, self.operation_id, self.request_digest, self.process
        )


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

    def replacing(self, reservations: tuple[HostReservation, ...]) -> "HostLedgerState":
        return HostLedgerState(next_ordinal=self.next_ordinal, reservations=reservations)


class ReservationRelease(PreviewModel):
    operation_id: UUID
    evidence: ReservationEvidence
    released: Literal[True] = True


def ledger_directory(ledger_root: str) -> Path:
    """The canonical, already existing private ledger directory; never created here."""
    root = canonical(ledger_root)
    if any(overlap(root, runtime) for runtime in runtime_roots()):
        raise OperationFailure("path", "host ledger overlaps runtime/source")
    try:
        private_directory(root)
    except FileNotFoundError as error:
        raise OperationFailure(
            "path", "host ledger directory must already exist with owned mode 0700"
        ) from error
    return root


@contextmanager
def locked_ledger(ledger_root: str) -> Iterator[Path]:
    root = ledger_directory(ledger_root)
    with directory(root) as descriptor:
        lock = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
    try:
        private(os.fstat(lock), directory=False)
        _acquire(lock)
        yield root
    finally:
        os.close(lock)


def _acquire(lock: int) -> None:
    deadline = time.monotonic() + LEDGER_LOCK_WAIT_SECONDS
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise OperationFailure(
                    "ledger_busy",
                    f"host ledger stayed locked for {LEDGER_LOCK_WAIT_SECONDS:g} s; retry later",
                ) from None
            time.sleep(_LOCK_POLL_SECONDS)


def read_state(root: Path) -> HostLedgerState:
    try:
        return read_model(root / LEDGER_FILE, HostLedgerState, private_file=True)
    except FileNotFoundError:
        return HostLedgerState()


def write_state(root: Path, state: HostLedgerState) -> None:
    publish(root / LEDGER_FILE, state, replace=True)


def _releasable(reservation: HostReservation) -> bool:
    """Only positive evidence releases; any unreadable or mismatched record keeps it."""
    try:
        return reservation.evidence().ended
    except (OSError, ValueError):
        return False


def sweep(root: Path) -> HostLedgerState:
    """Drop reservations whose child and sandbox sessions have ended; keep the rest."""
    state = read_state(root)
    live = tuple(r for r in state.reservations if not _releasable(r))
    if live != state.reservations:
        state = state.replacing(live)
        write_state(root, state)
    return state


def without(root: Path, operation_id: UUID) -> None:
    state = read_state(root)
    write_state(
        root,
        state.replacing(tuple(r for r in state.reservations if r.operation_id != operation_id)),
    )


def bind(root: Path, operation_id: UUID, identity: ProcessIdentity) -> None:
    state = read_state(root)
    bound = tuple(
        r.model_copy(update={"process": identity}) if r.operation_id == operation_id else r
        for r in state.reservations
    )
    write_state(root, state.replacing(bound))


def release_reservation(ledger_root: str, operation_id: UUID) -> ReservationRelease:
    """Operator release of a stuck reservation; refuses while anything appears live.

    Unlike the automatic sweep, this does not require a positive exit: an
    unbound reservation whose child never published an identity is released on
    the operator's word, as is an unknown leader with no visible session member.
    """
    with locked_ledger(ledger_root) as root:
        state = read_state(root)
        match = [r for r in state.reservations if r.operation_id == operation_id]
        if not match:
            raise OperationFailure("not_reserved", "operation holds no host reservation")
        evidence = match[0].evidence()
        if evidence.appears_live:
            raise OperationFailure(
                "session_live", "operation child or sandbox session still appears live"
            )
        if evidence.unobservable:
            raise OperationFailure(
                "liveness_unobservable", "cannot observe the operation child or sandbox"
            )
        without(root, operation_id)
        return ReservationRelease(operation_id=operation_id, evidence=evidence)
