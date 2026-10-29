"""Process side of parallel graph dispatch (B3-4b): start, guard and terminate units.

A parallel unit child is started through the same code-package owner as a serial
unit (``core.local_code.child.prepare_child``) and checked the same way when it
ends (``ChildInvocation.check``), but in its own session, so the scheduler can
terminate exactly its process group. ``TermGate`` turns SIGTERM into
``UnitTerminated`` and holds it while a unit is being registered or while units
are being terminated, so a signal can neither orphan a just-started unit nor
abort the cleanup of the others. Contract: candidate-worker-contract.md,
"Concurrent dispatch (B3-4b)".
"""

import signal
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from core.local_code.child import ChildInvocation, prepare_child
from core.runtime_control.process_group import terminate_observed_group

from . import unit_runner

#: Seconds between polls of running units.
POLL_SECONDS = 0.05
#: TERM-to-KILL grace when terminating a unit's process group.
TERMINATE_GRACE_SECONDS = 1.0


class UnitTerminated(BaseException):
    """SIGTERM reached the worker during parallel dispatch."""


@dataclass
class UnitProcess:
    """One started unit child and the code-package invocation that guards it."""

    process: subprocess.Popen
    invocation: ChildInvocation

    @property
    def pid(self) -> int:
        return self.process.pid

    @property
    def returncode(self) -> int | None:
        return self.process.returncode

    @property
    def args(self):
        return self.process.args

    def poll(self) -> int | None:
        return self.process.poll()

    def wait(self) -> int:
        return self.process.wait()

    def check(self) -> None:
        """Raise the code-package refusal the child published, as the serial owner does."""
        self.invocation.check(self.process.returncode)


def start_unit(invocation_path: Path, env: dict[str, str]) -> UnitProcess:
    """Spawn the unit child in its own session, sharing the worker log."""
    sys.stdout.flush()
    sys.stderr.flush()
    invocation = prepare_child(unit_runner.unit_command(str(invocation_path)), env)
    process = subprocess.Popen(invocation.argv, env=invocation.env, start_new_session=True)
    return UnitProcess(process, invocation)


def terminate(unit: UnitProcess) -> None:
    """TERM, grace, KILL the unit's own process group, then reap it."""
    terminate_observed_group(
        unit.pid,
        grace_seconds=TERMINATE_GRACE_SECONDS,
        poll_seconds=POLL_SECONDS,
        child=unit.process,
    )
    unit.wait()


class TermGate:
    """SIGTERM becomes ``UnitTerminated``, except inside ``held()``, where it waits."""

    def __init__(self) -> None:
        self.depth = 0
        self.pending = False

    def _handler(self, signum: int, frame: object) -> None:
        if self.depth:
            self.pending = True
            return
        raise UnitTerminated(f"signal {signum}")

    @contextmanager
    def installed(self) -> Iterator["TermGate"]:
        if threading.current_thread() is not threading.main_thread():
            yield self
            return
        previous: Callable | int | None = signal.signal(signal.SIGTERM, self._handler)
        try:
            yield self
        finally:
            signal.signal(signal.SIGTERM, previous)

    @contextmanager
    def held(self) -> Iterator[None]:
        """Hold SIGTERM for the block; deliver it once the block completes normally."""
        self.depth += 1
        try:
            yield
        except BaseException:
            self.depth -= 1
            raise
        self.depth -= 1
        if not self.depth and self.pending:
            self.pending = False
            raise UnitTerminated("signal held during a critical section")
