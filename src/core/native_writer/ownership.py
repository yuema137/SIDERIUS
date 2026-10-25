"""Kernel exclusion and durable registered claims, without liveness-based reclaim."""

from __future__ import annotations

import fcntl
import os
import re
from pathlib import Path
from typing import Literal
from uuid import uuid4

from .models import (
    Claim,
    Inspection,
    Participation,
    Registration,
    Transport,
    Unresolved,
    WriterRefusal,
)
from .state import WriterState, canonical_workspace

TRANSPORT_ENV = "SIDERIUS_NATIVE_WRITER"


def _records(state: WriterState) -> tuple[Registration | None, Claim | None]:
    registration = state.read("registration.json", Registration)
    claim = state.read("claim.json", Claim)
    if registration is not None and registration.workspace != str(state.workspace):
        raise WriterRefusal("writer_registration_changed")
    if claim is not None and (
        registration is None
        or claim.workspace != str(state.workspace)
        or claim.capture_sha256 != registration.capture_sha256
    ):
        raise WriterRefusal("writer_claim_changed")
    return registration, claim


def _has_pending(state: WriterState) -> bool:
    return (
        state.read("iteration.active", Participation) is not None
        or state.read("unresolved", Unresolved) is not None
    )


def _held_description(fd: int, reference_fd: int) -> None:
    supplied, reference = os.fstat(fd), os.fstat(reference_fd)
    if (supplied.st_dev, supplied.st_ino) != (reference.st_dev, reference.st_ino):
        raise WriterRefusal("writer_descriptor_changed")
    # A try-lock would CREATE ownership on a forged unlocked descriptor. fdinfo
    # describes this open file description without changing its lock state.
    with open(f"/proc/self/fdinfo/{fd}", "rb") as stream:
        raw = stream.read(4097)
    if len(raw) > 4096:
        raise WriterRefusal("writer_descriptor_unavailable")
    identity = f"{os.major(supplied.st_dev):02x}:{os.minor(supplied.st_dev):02x}:{supplied.st_ino}"
    pattern = rb"lock:\s+\d+: FLOCK\s+ADVISORY\s+WRITE\s+-?\d+\s+([^ ]+)\s+0 EOF"
    locks = re.findall(pattern, raw)
    if locks != [identity.encode()]:
        raise WriterRefusal("writer_descriptor_not_held")


class WriterLease:
    """One root lease or validated delegation; scientific execution lives elsewhere."""

    def __init__(self, state: WriterState, fd: int, claim: Claim | None, *, delegated: bool):
        self.state, self.fd, self.claim = state, fd, claim
        self.delegated = delegated
        self.unresolved = False
        self.uncertainty_persisted = False

    @property
    def transport(self) -> Transport:
        return Transport(
            fd=self.fd,
            workspace=str(self.state.workspace),
            claim_id=self.claim.claim_id if self.claim else None,
        )

    def mark_unresolved(
        self, reason: Literal["process_cleanup", "participant_exception", "owner_exit"]
    ) -> None:
        # Sticky memory comes first: swallowed I/O failure cannot enable release.
        self.unresolved = True
        if self.claim is not None:
            value = Unresolved(claim_id=self.claim.claim_id, reason=reason)
            prior = self.state.read("unresolved", Unresolved)
            if prior is None:
                self.state.publish("unresolved", value)
            elif prior.claim_id != self.claim.claim_id:
                raise WriterRefusal("writer_claim_changed")
            self.uncertainty_persisted = True

    def close(self, *, clean: bool) -> None:
        try:
            if (
                not self.delegated
                and self.claim is not None
                and clean
                and not self.unresolved
                and not _has_pending(self.state)
            ):
                self.state.remove("claim.json", self.claim)
        finally:
            if not self.delegated:
                os.close(self.fd)
            self.state.close()


def acquire(workspace: str | Path, *, capture_sha256: str | None = None) -> WriterLease:
    state = WriterState(workspace, create=True)
    fd = -1
    try:
        fd = state.open_lock()
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise WriterRefusal("writer_active") from error
        registration, prior = _records(state)
        if prior is not None or _has_pending(state):
            raise WriterRefusal("writer_unresolved")
        if registration is not None and capture_sha256 is None:
            raise WriterRefusal("registered_owner_required")
        claim = None
        if capture_sha256 is not None:
            if state.workspace.exists():
                raise WriterRefusal("writer_registration_requires_fresh_workspace")
            expected = Registration(workspace=str(state.workspace), capture_sha256=capture_sha256)
            if registration is None:
                state.publish("registration.json", expected)
            elif registration != expected:
                raise WriterRefusal("writer_registration_changed")
            claim = Claim(
                claim_id=uuid4(), workspace=str(state.workspace), capture_sha256=capture_sha256
            )
            state.publish("claim.json", claim)
        return WriterLease(state, fd, claim, delegated=False)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        state.close()
        raise


def inherit(workspace: str | Path, payload: str) -> WriterLease:
    if len(payload.encode()) > 4096:
        raise WriterRefusal("writer_transport_limit")
    transport = Transport.model_validate_json(payload)
    if str(canonical_workspace(workspace)) != transport.workspace:
        raise WriterRefusal("writer_workspace_changed")
    state = WriterState(workspace, create=False)
    reference = -1
    try:
        reference = state.open_lock(create=False)
        _held_description(transport.fd, reference)
        registration, claim = _records(state)
        if registration is not None:
            if claim is None or transport.claim_id != claim.claim_id:
                raise WriterRefusal("writer_claim_changed")
        elif claim is not None or transport.claim_id is not None:
            raise WriterRefusal("writer_claim_changed")
        return WriterLease(state, transport.fd, claim, delegated=True)
    except BaseException:
        state.close()
        raise
    finally:
        if reference >= 0:
            os.close(reference)


def inspect_writer(workspace: str | Path) -> Inspection:
    """Read selected ownership only; never create state or reclaim a dead owner."""
    name = str(Path(workspace).expanduser().resolve())
    try:
        state = WriterState(workspace, create=False)
    except FileNotFoundError:
        return Inspection(workspace=name, status="unregistered")
    except (OSError, ValueError, WriterRefusal):
        return Inspection(workspace=name, status="invalid", reason="writer_state_unavailable")
    fd = -1
    try:
        registration, claim = _records(state)
        fd = state.open_lock(create=False)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return Inspection(workspace=name, status="active", registered=registration is not None)
        pending = claim is not None or _has_pending(state)
        return Inspection(
            workspace=name,
            status="unresolved"
            if pending
            else "registered_idle"
            if registration
            else "unregistered",
            registered=registration is not None,
            reason="writer_cleanup_unresolved" if pending else None,
        )
    except (OSError, ValueError, WriterRefusal):
        return Inspection(workspace=name, status="invalid", reason="writer_state_unavailable")
    finally:
        if fd >= 0:
            os.close(fd)
        state.close()
