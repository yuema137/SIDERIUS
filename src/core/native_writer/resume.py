"""Single-use adoption under the existing writer lock; no scientific decisions."""

import fcntl
import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from .models import Claim, Participation, Registration, Unresolved, WriterRefusal
from .ownership import WriterLease
from .resume_models import ResumeAdoption, ResumeReservation, WriterSnapshot
from .state import WriterState


def reservation_name(predecessor: UUID) -> str:
    return f"successor.{predecessor}.json"


def adoption_name(successor: UUID) -> str:
    return f"adopted.{successor}.json"


def snapshot(state: WriterState, fd: int) -> WriterSnapshot:
    """Parse and hash the very same bounded bytes while the caller holds the lock."""
    registration = state.read_bytes("registration.json")
    claim = state.read_bytes("claim.json")
    participant = state.read_bytes("iteration.active")
    unresolved = state.read_bytes("unresolved")
    if registration is None:
        raise WriterRefusal("registered_owner_required")
    info = os.fstat(fd)
    value = WriterSnapshot(
        registration=Registration.model_validate_json(registration),
        claim=Claim.model_validate_json(claim) if claim is not None else None,
        participant=Participation.model_validate_json(participant)
        if participant is not None
        else None,
        unresolved=Unresolved.model_validate_json(unresolved) if unresolved is not None else None,
        registration_digest=hashlib.sha256(registration).hexdigest(),
        claim_digest=hashlib.sha256(claim).hexdigest() if claim is not None else None,
        participant_digest=hashlib.sha256(participant).hexdigest()
        if participant is not None
        else None,
        unresolved_digest=hashlib.sha256(unresolved).hexdigest()
        if unresolved is not None
        else None,
        lock_device=info.st_dev,
        lock_inode=info.st_ino,
    )
    if value.registration.workspace != str(state.workspace):
        raise WriterRefusal("writer_registration_changed")
    if value.claim is not None and (
        value.claim.workspace != str(state.workspace)
        or value.claim.capture_sha256 != value.registration.capture_sha256
    ):
        raise WriterRefusal("writer_claim_changed")
    for marker in (value.participant, value.unresolved):
        if marker is not None and (value.claim is None or marker.claim_id != value.claim.claim_id):
            raise WriterRefusal("writer_claim_changed")
    return value


class LockedWriter:
    def __init__(self, state: WriterState, fd: int):
        self.state, self.fd = state, fd
        self.transferred = False

    def snapshot(self) -> WriterSnapshot:
        return snapshot(self.state, self.fd)


@contextmanager
def locked_registered_writer(workspace: Path) -> Iterator[LockedWriter]:
    """No creation, durable release, stale-PID reasoning or implicit reclaim."""
    state = WriterState(workspace, create=False)
    fd = -1
    guard = None
    try:
        fd = state.open_lock(create=False)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise WriterRefusal("writer_active") from error
        guard = LockedWriter(state, fd)
        guard.snapshot()
        yield guard
    finally:
        if guard is None or not guard.transferred:
            if fd >= 0:
                os.close(fd)
            state.close()


def adopt_reserved_writer(
    guard: LockedWriter, expected: WriterSnapshot, reservation: ResumeReservation
) -> WriterLease:
    """Caller proves outer cleanup/science; this owner atomically excludes writers."""
    state = guard.state
    if (
        guard.transferred
        or guard.snapshot() != expected
        or hashlib.sha256(expected.model_dump_json().encode()).hexdigest()
        != reservation.snapshot_digest
        or expected.registration.capture_sha256 != reservation.capture_sha256
    ):
        raise WriterRefusal("resume_snapshot_changed")
    raw = state.read_bytes(reservation_name(reservation.predecessor_operation_id))
    if raw is None or ResumeReservation.model_validate_json(raw) != reservation:
        raise WriterRefusal("resume_reservation_changed")
    state.publish(
        adoption_name(reservation.successor_operation_id),
        ResumeAdoption(
            reservation_digest=hashlib.sha256(raw).hexdigest(),
            operation_id=reservation.successor_operation_id,
            claim_id=reservation.claim_id,
        ),
    )
    for name, prior in (
        ("iteration.active", expected.participant),
        ("unresolved", expected.unresolved),
        ("claim.json", expected.claim),
    ):
        if prior is not None:
            state.remove(name, prior)
    claim = Claim(
        claim_id=reservation.claim_id,
        workspace=str(state.workspace),
        capture_sha256=reservation.capture_sha256,
    )
    state.publish("claim.json", claim)
    lease = WriterLease(state, guard.fd, claim, delegated=False)
    guard.transferred = True
    return lease
