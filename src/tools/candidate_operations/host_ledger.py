"""Host-level reservation ledger shared by separate operation stores (B3-5a/5b).

One private directory, serialized by ``flock``, records which candidate operations
hold part of an operator-declared ``HostBudget`` and, in submission order, which
wait for it. Placement arithmetic is ``plan_dispatch``; this module only persists
its decisions, binds each entry to the operation child's process identity and
releases it on evidence (``host_liveness``). Contract:
candidate-operations-contract.md, "Host reservation ledger".
"""

import fcntl
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, NonNegativeInt, ValidationError, model_validator

from core.runtime_control.scheduling import HostBudget, Placement, plan_dispatch
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
    #: The submitting process that wrote this entry (B3-5b review): evidence for
    #: releasing an entry whose submitter died before any child was bound.
    submitter: ProcessIdentity | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def bound_identity(self):
        if self.placement.decision != "placed" or self.placement.unit_id != str(self.operation_id):
            raise ValueError("a reservation holds its own operation's placed unit")
        _require_own_process(self)
        return self

    def evidence(self) -> ReservationEvidence:
        return reservation_evidence(
            self.state_root, self.operation_id, self.request_digest, self.process, self.submitter
        )


class QueuedOperation(PreviewModel):
    """One waiting operation (B3-5b): its queued placement holds a place in line only."""

    operation_id: UUID
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_root: str
    placement: Placement
    process: ProcessIdentity | None = None
    #: The submitting process that wrote this entry (B3-5b review): evidence for
    #: releasing an entry whose submitter died before any child was bound.
    submitter: ProcessIdentity | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def bound_identity(self):
        if self.placement.decision != "queued" or self.placement.unit_id != str(self.operation_id):
            raise ValueError("a queue entry holds its own operation's queued unit")
        _require_own_process(self)
        return self

    def evidence(self) -> ReservationEvidence:
        """The same evidence as a reservation (``reservation_evidence``).

        The child is the bound identity, or else its own ``process.json``; a
        ``sandbox.json`` is read when published, which a waiting child never does.
        """
        return reservation_evidence(
            self.state_root, self.operation_id, self.request_digest, self.process, self.submitter
        )


def _require_own_process(entry: HostReservation | QueuedOperation) -> None:
    for process in (entry.process, entry.submitter):
        if process is not None and (
            process.operation_id != entry.operation_id
            or process.request_digest != entry.request_digest
        ):
            raise ValueError("reservation process identity names another operation")


LedgerEntry = HostReservation | QueuedOperation


class HostLedgerState(PreviewModel):
    """Live reservations and waiting operations against one budget digest.

    ``queued`` is omitted when empty, so a ledger that never queued keeps the
    B3-5a bytes.
    """

    version: Literal[1] = 1
    next_ordinal: NonNegativeInt = 0
    reservations: tuple[HostReservation, ...] = ()
    queued: tuple[QueuedOperation, ...] = Field(default=(), exclude_if=lambda value: not value)

    @model_validator(mode="after")
    def one_budget(self):
        entries = self.entries()
        digests = {r.placement.budget_digest for r in entries}
        ids = [r.operation_id for r in entries]
        if len(digests) > 1 or len(set(ids)) != len(ids):
            raise ValueError("ledger entries must be distinct and share one budget")
        if any(r.placement.dispatch_ordinal >= self.next_ordinal for r in entries):
            raise ValueError("ledger ordinal counter is behind its entries")
        return self

    def entries(self) -> tuple[LedgerEntry, ...]:
        return (*self.reservations, *self.queued)

    @property
    def budget_digest(self) -> str | None:
        entries = self.entries()
        return entries[0].placement.budget_digest if entries else None

    def replacing(self, entries: tuple[LedgerEntry, ...]) -> "HostLedgerState":
        return HostLedgerState(
            next_ordinal=self.next_ordinal,
            reservations=tuple(e for e in entries if isinstance(e, HostReservation)),
            queued=tuple(e for e in entries if isinstance(e, QueuedOperation)),
        )


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
    """The ledger, or a typed ``ledger_format`` refusal for one this revision cannot read.

    That covers a ledger written by an earlier or a newer revision and a corrupt
    or truncated file alike: none of them is parsed, guessed or repaired.

    Every reader (admission, the sweep, the release command) goes through here,
    so an unreadable ledger is refused the same way everywhere and never rewritten.
    """
    path = root / LEDGER_FILE
    try:
        return read_model(path, HostLedgerState, private_file=True)
    except FileNotFoundError:
        return HostLedgerState()
    except ValidationError as error:
        raise OperationFailure(
            "ledger_format",
            f"this host ledger is unreadable by this SIDERIUS revision (written by another "
            f"revision, or corrupt); once the runs it lists have ended, move {path} aside "
            "and retry",
        ) from error


def write_state(root: Path, state: HostLedgerState) -> None:
    publish(root / LEDGER_FILE, state, replace=True)


def _releasable(entry: LedgerEntry) -> bool:
    """Only positive evidence releases; any unreadable or mismatched record keeps it."""
    try:
        return entry.evidence().ended
    except (OSError, ValueError):
        return False


def sweep(root: Path) -> HostLedgerState:
    """Drop entries whose child (and sandbox) sessions have ended; keep the rest.

    A waiting child that died never reaches its sandbox, so its queue entry is
    dropped by the same evidence; otherwise it would hold the head of the line.
    """
    state = read_state(root)
    entries = state.entries()
    live = tuple(r for r in entries if not _releasable(r))
    if live != entries:
        state = state.replacing(live)
        write_state(root, state)
    return state


def promote(state: HostLedgerState, budget: HostBudget) -> HostLedgerState:
    """Place waiting operations in strict submission order wherever the budget allows.

    Every queued entry ``plan_dispatch`` places becomes a reservation now, for
    whichever child it belongs to, so a later waiter can never take the capacity
    an earlier one was given (strict FIFO, decision B3-Q4). Its own child adopts
    it at its next poll.
    """
    if not state.queued:
        return state
    decision = plan_dispatch(
        tuple(entry.placement.reserved for entry in state.queued),
        tuple(r.placement for r in state.reservations),
        budget,
        on_refusal="continue",
    )
    placed = {placement.unit_id: placement for placement in decision.placed}
    if not placed:
        return state
    promoted = (
        HostReservation(
            operation_id=entry.operation_id,
            request_digest=entry.request_digest,
            state_root=entry.state_root,
            placement=placed[str(entry.operation_id)],
            process=entry.process,
            submitter=entry.submitter,
        )
        if str(entry.operation_id) in placed
        else entry
        for entry in state.queued
    )
    return state.replacing((*state.reservations, *promoted))


def without(root: Path, operation_id: UUID) -> None:
    state = read_state(root)
    write_state(
        root,
        state.replacing(tuple(r for r in state.entries() if r.operation_id != operation_id)),
    )


def bind(root: Path, operation_id: UUID, identity: ProcessIdentity) -> None:
    state = read_state(root)
    bound = tuple(
        r.model_copy(update={"process": identity}) if r.operation_id == operation_id else r
        for r in state.entries()
    )
    write_state(root, state.replacing(bound))


def release_reservation(ledger_root: str, operation_id: UUID) -> ReservationRelease:
    """Operator release of a stuck reservation or queue entry; refuses while anything appears live.

    Unlike the automatic sweep, this does not require a positive exit: an
    unbound entry whose child never published an identity is released on
    the operator's word, as is an unknown leader with no visible session member.
    """
    with locked_ledger(ledger_root) as root:
        state = read_state(root)
        match = [r for r in state.entries() if r.operation_id == operation_id]
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
