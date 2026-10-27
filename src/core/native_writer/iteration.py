"""Native iteration participation and sticky observation of existing cleanup."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager, suppress
from uuid import uuid4

from core.runtime_control.observed_subprocess import ProcessLifecycle, observe_process_lifecycle

from .models import Participation, WriterRefusal
from .ownership import TRANSPORT_ENV, WriterLease, acquire, inherit


def _observe(lease: WriterLease, lifecycle: ProcessLifecycle) -> None:
    group = lifecycle.group_cleanup
    uncertain = (
        not lifecycle.child_reaped
        or bool(lifecycle.cleanup_errors)
        or (group is not None and group.final.status != "absent")
        or (group is None and lifecycle.returncode != 0)
    )
    if uncertain:
        # mark_unresolved sets sticky memory BEFORE potentially failing state I/O.
        lease.mark_unresolved("process_cleanup")


def _poison(lease: WriterLease) -> None:
    # A failed marker write retains active participation and the durable claim.
    with suppress(Exception):
        lease.mark_unresolved("participant_exception")


@contextmanager
def iteration_owner(workspace: str, *, read_only: bool = False):
    """Protect the full native entry, before package/failure-brake mutations.

    Yields the existing lease on Linux; callers may inspect sticky cleanup uncertainty.
    Legacy non-Linux execution remains unchanged and has no guarded-resume claim.
    Registered roots must use their captured chain, never an implicit direct restart.
    """
    if read_only or sys.platform != "linux":
        yield
        return
    payload = os.environ.get(TRANSPORT_ENV)
    try:
        lease = inherit(workspace, payload) if payload is not None else acquire(workspace)
    except (OSError, ValueError) as error:
        raise WriterRefusal("writer_state_refused") from error
    participant = None
    clean = False
    try:
        if lease.claim is not None:
            participant = Participation(claim_id=lease.claim.claim_id, participant_id=uuid4())
            try:
                lease.state.publish("iteration.active", participant)
            except FileExistsError as error:
                raise WriterRefusal("writer_participant_active") from error
        try:
            with observe_process_lifecycle(lambda lifecycle: _observe(lease, lifecycle)):
                yield lease
        except SystemExit as error:
            # Controlled native failures retain existing shell continuation.
            # Cleanup observations, not this exit code, decide ownership safety.
            clean = isinstance(error.code, (int, type(None))) and 0 <= (error.code or 0) < 128
            if not clean:
                _poison(lease)
            raise
        except BaseException:
            _poison(lease)
            raise
        else:
            clean = True
        finally:
            if participant is not None and (not lease.unresolved or lease.uncertainty_persisted):
                lease.state.remove("iteration.active", participant)
    finally:
        lease.close(clean=clean)
