"""Queued host placement (B3-5b): the claimed operation child waits for its place.

A submission that fits the declared budget but not the current ledger is claimed,
spawned and recorded in the ledger's queue (``host_ledger.QueuedOperation``). Its
child polls here, before any native dispatch: each poll takes the ledger lock,
sweeps ended entries and promotes waiting operations in strict submission order
(``host_ledger.promote``). When its own entry has become a reservation the child
publishes ``placement.json`` and runs as a placed operation. A recorded cancel
removes the entry instead, so the operation never runs. Contract:
candidate-operations-contract.md, "Queued operations".
"""

import os
import time
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from core.runtime_control.scheduling import HostBudget, Placement
from core.subprocess_env import CUDA_VISIBLE_DEVICES_ENV_VAR
from tools.workflow_preview.models import PreviewModel

from .files import publish, read_model
from .host_ledger import locked_ledger, promote, sweep, without, write_state
from .host_liveness import PLACEMENT_FILE
from .models import OperationFailure

#: Written write-once by admission beside a queued operation's record.
QUEUE_FILE = "queued.json"
#: Seconds between a waiting child's ledger polls (decision B3-5 D2).
QUEUE_POLL_SECONDS = 1.0


class HostQueueTicket(PreviewModel):
    """What a waiting child needs to place itself: the ledger, its budget, its decision."""

    ledger_root: str
    budget: HostBudget
    placement: Placement


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
    held = [r.placement for r in state.reservations if r.operation_id == operation_id]
    if held:
        return held[0]
    if not any(entry.operation_id == operation_id for entry in state.queued):
        raise OperationFailure("host_queue", "queued operation left the host ledger")
    return None
