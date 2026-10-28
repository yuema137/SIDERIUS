"""Liveness evidence for a host reservation: the operation child and its sandbox.

The operation child is a session leader (``start_new_session``). The candidate
sandbox is spawned by that child as a second session leader (``runner.run``
uses ``start_new_session``; ``bwrap --new-session`` starts a third session for
the payload inside the sandbox's PID namespace). The namespace's init is the
forked bwrap, which stays in the sandbox (bwrap) session, and the kernel kills
every process in a PID namespace when its init exits. So the bwrap session
having no live member is evidence that the whole sandbox, including training,
has ended. Contract: candidate-operations-contract.md, "Host reservation ledger".
"""

import os
import shutil
import stat
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field

from tools.workflow_preview.models import PreviewModel

from .files import read_model
from .models import OperationFailure, ProcessIdentity
from .process import observe, session_members

PLACEMENT_FILE = "placement.json"
PROCESS_FILE = "process.json"
SANDBOX_FILE = "sandbox.json"


class SessionEvidence(PreviewModel):
    """One session leader's liveness and the live members of its session."""

    leader: Literal["alive", "exited", "unknown"]
    members: int | None = Field(ge=0)

    @property
    def ended(self) -> bool:
        return self.leader == "exited" and self.members == 0

    @property
    def appears_live(self) -> bool:
        return self.leader == "alive" or bool(self.members)

    @property
    def unobservable(self) -> bool:
        return self.leader == "unknown" and self.members is None


class ReservationEvidence(PreviewModel):
    """``child`` is ``None`` when no identity was bound or published; ``sandbox``
    is ``None`` when the child published no sandbox identity."""

    child: SessionEvidence | None
    sandbox: SessionEvidence | None

    def parts(self) -> tuple[SessionEvidence, ...]:
        return tuple(part for part in (self.child, self.sandbox) if part is not None)

    @property
    def ended(self) -> bool:
        """Safe to release automatically: a positive child exit and no live session.

        A missing sandbox identity is accepted only after the child ended: the
        sandbox is started with ``--die-with-parent``, so it cannot outlive a
        child that died before publishing it.
        """
        return self.child is not None and all(part.ended for part in self.parts())

    @property
    def appears_live(self) -> bool:
        return any(part.appears_live for part in self.parts())

    @property
    def unobservable(self) -> bool:
        return any(part.unobservable for part in self.parts())


def session_evidence(identity: ProcessIdentity, *, may_be_hidden: bool = False) -> SessionEvidence:
    """``may_be_hidden``: an absent leader may be a live process /proc does not show."""
    observation = observe(identity)
    if observation.reason == "different_boot":
        return SessionEvidence(leader="exited", members=0)
    leader = observation.status
    if may_be_hidden and observation.reason == "pid_absent":
        leader = "unknown"
    # Each recorded process is a session leader, so its PID is its session ID.
    return SessionEvidence(leader=leader, members=session_members(identity.pid))


def sandbox_may_be_hidden() -> bool:
    """A setuid-root bwrap under ``/proc`` ``hidepid`` is invisible to this user.

    Such a leader reads as absent, which must not count as a positive exit.
    """
    executable = shutil.which("bwrap")
    try:
        setuid = executable is not None and bool(os.stat(executable).st_mode & stat.S_ISUID)
        mounts = Path("/proc/self/mounts").read_text()
    except OSError:
        return True  # cannot rule it out
    return setuid and any(_hides_pids(line) for line in mounts.splitlines())


def _hides_pids(mount: str) -> bool:
    fields = mount.split()
    if len(fields) < 4 or fields[1] != "/proc" or fields[2] != "proc":
        return False
    for option in fields[3].split(","):
        name, _, value = option.partition("=")
        if name == "hidepid":
            return value not in {"0", "off"}
    return False


def published_identity(
    state_root: str, operation_id: UUID, request_digest: str, name: str
) -> ProcessIdentity | None:
    """An identity the operation child published itself; ``None`` when absent."""
    path = Path(state_root) / "operations" / str(operation_id) / name
    try:
        identity = read_model(path, ProcessIdentity, private_file=True)
    except FileNotFoundError:
        return None
    if identity.operation_id != operation_id or identity.request_digest != request_digest:
        raise OperationFailure("integrity", f"published {name} names another operation")
    return identity


def reservation_evidence(
    state_root: str,
    operation_id: UUID,
    request_digest: str,
    bound: ProcessIdentity | None,
) -> ReservationEvidence:
    """Evidence from the bound child identity (or its own ``process.json``) and sandbox."""
    child = bound or published_identity(state_root, operation_id, request_digest, PROCESS_FILE)
    sandbox = published_identity(state_root, operation_id, request_digest, SANDBOX_FILE)
    return ReservationEvidence(
        child=None if child is None else session_evidence(child),
        sandbox=None
        if sandbox is None
        else session_evidence(sandbox, may_be_hidden=sandbox_may_be_hidden()),
    )
