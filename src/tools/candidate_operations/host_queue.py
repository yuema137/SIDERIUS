"""Queued host placement (B3-5b): the claimed operation child waits for its place.

A submission that fits the declared budget but not the current ledger is claimed,
spawned and recorded in the ledger's queue (``host_ledger.QueuedOperation``). Its
child polls here, before any native dispatch: each poll takes the ledger lock,
sweeps ended entries and promotes waiting operations in strict submission order
(``host_ledger.promote``). When its own entry has become a reservation the child
publishes ``placement.json`` and runs as a placed operation. A recorded cancel
removes the entry instead, so the operation never runs.

A directly placed child confirms its reservation the same way before any work
(``confirm_reservation``): the submitter holds the ledger lock until it has bound
or removed the entry, so a child whose entry was removed (an interrupted spawn)
or released (a submitter that died before the child published itself) never
runs unaccounted. Contract: candidate-operations-contract.md, "Queued
operations" and "Host reservation ledger".
"""

import os
import time
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from pydantic import Field

from core.runtime_control.scheduling import HostBudget, Placement
from core.subprocess_env import CUDA_VISIBLE_DEVICES_ENV_VAR
from tools.candidate_worker.parallel_models import HostGrant
from tools.workflow_preview.models import PreviewModel

from .files import publish, read_model
from .host_ledger import (
    HostLedgerState,
    HostReservation,
    locked_ledger,
    promote,
    read_state,
    sweep,
    without,
    write_state,
)
from .host_liveness import GRANT_FILE, PLACEMENT_FILE
from .models import OperationFailure, OperationRecord

#: Written write-once by admission beside a queued operation's record.
QUEUE_FILE = "queued.json"
#: Written write-once by admission beside a directly placed operation's record.
RESERVATION_FILE = "host_reservation.json"
#: Seconds between a waiting child's ledger polls (decision B3-5 D2).
QUEUE_POLL_SECONDS = 1.0


class HostQueueTicket(PreviewModel):
    """What a waiting child needs to place itself: the ledger, its budget, its decision."""

    ledger_root: str
    budget: HostBudget
    placement: Placement
    #: A parallel run (B3-4a): once placed, the child also publishes its ``HostGrant``.
    grant: bool = Field(default=False, exclude_if=lambda value: not value)


class HostReservationTicket(PreviewModel):
    """The ledger a directly placed child must confirm its reservation in (#1108)."""

    ledger_root: str


def is_queued(path: Path) -> bool:
    return os.path.lexists(path / QUEUE_FILE)


def wait_for_placement(
    path: Path, operation_id: UUID, cancelled: Callable[[], bool]
) -> Placement | None:
    """Block until this operation is placed; ``None`` after a cancel left the queue.

    On placement the child's own environment receives the slot UUID, which the
    sandbox passes on (``CUDA_VISIBLE_DEVICES`` is a required declared name).
    """
    ticket = read_model(path / QUEUE_FILE, HostQueueTicket, private_file=True)
    if ticket.placement.unit_id != str(operation_id):
        raise OperationFailure("integrity", "queue ticket names another operation")
    while True:
        placement = None if cancelled() else _poll(ticket, operation_id)
        # Checked again after a placement: a cancel recorded meanwhile still wins.
        if cancelled():
            _leave(ticket, operation_id)
            return None
        if placement is not None:
            publish(path / PLACEMENT_FILE, placement)
            if ticket.grant:
                publish(path / GRANT_FILE, HostGrant(budget=ticket.budget, placement=placement))
            if placement.gpu_uuid is not None:
                os.environ[CUDA_VISIBLE_DEVICES_ENV_VAR] = placement.gpu_uuid
            return placement
        time.sleep(QUEUE_POLL_SECONDS)


def _leave(ticket: HostQueueTicket, operation_id: UUID) -> None:
    """Nothing has started: the entry, queued or already promoted, leaves the ledger."""
    with locked_ledger(ticket.ledger_root) as root:
        without(root, operation_id)


def _poll(ticket: HostQueueTicket, operation_id: UUID) -> Placement | None:
    try:
        with locked_ledger(ticket.ledger_root) as root:
            swept = sweep(root)
            state = promote(swept, ticket.budget)
            if state != swept:
                write_state(root, state)
    except OperationFailure as error:
        if error.detail.code == "ledger_busy":
            return None  # another submission holds the lock; try again next poll
        raise
    held = _held_reservation(state, operation_id)
    if held is not None:
        return held.placement
    if not any(entry.operation_id == operation_id for entry in state.queued):
        raise OperationFailure("host_queue", "queued operation left the host ledger")
    return None


def confirm_reservation(path: Path, record: OperationRecord) -> None:
    """Refuse to run unless the ledger still holds this child's published placement.

    Read under the ledger lock, which the submitter holds from writing the entry
    until it has bound the child or removed the entry, so this observes its
    final decision. Called after ``process.json`` is published: from then on the
    sweep sees a live child and keeps the entry, so a confirmed entry stays held.
    """
    ticket = read_model(path / RESERVATION_FILE, HostReservationTicket, private_file=True)
    placement = read_model(path / PLACEMENT_FILE, Placement, private_file=True)
    with locked_ledger(ticket.ledger_root) as root:
        state = read_state(root)
    entry = _held_reservation(state, record.submission.request_id)
    if (
        entry is None
        or entry.request_digest != record.request_digest
        or entry.placement != placement
    ):
        raise OperationFailure(
            "host_reservation", "placed operation is not held in the host ledger"
        )


def _held_reservation(state: HostLedgerState, operation_id: UUID) -> HostReservation | None:
    """Locate a child's held entry in a snapshot read under the ledger lock."""
    return next((entry for entry in state.reservations if entry.operation_id == operation_id), None)
