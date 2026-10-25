"""Run the existing native shell once under ownership; never schedule its work."""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

from .ownership import TRANSPORT_ENV, WriterLease, acquire


def launch_shell(workspace: Path, argv: Sequence[str], *, capture_sha256: str | None = None) -> int:
    lease = acquire(workspace, capture_sha256=capture_sha256)
    return run_shell_with_lease(lease, argv)


def run_shell_with_lease(lease: WriterLease, argv: Sequence[str]) -> int:
    """Consume an acquired/adopted lease with the unchanged native shell lifecycle."""
    child: subprocess.Popen | None = None
    old_handlers = {}
    clean = False

    def forward(signum, _frame):
        if child is not None:
            with suppress(ProcessLookupError):
                child.send_signal(signum)

    try:
        env = dict(os.environ)
        env[TRANSPORT_ENV] = lease.transport.model_dump_json()
        child = subprocess.Popen(list(argv), env=env, pass_fds=(lease.fd,))
        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            old_handlers[signum] = signal.signal(signum, forward)
        status = child.wait()
        clean = status >= 0
        return status if status >= 0 else 128 - status
    finally:
        for signum, previous in old_handlers.items():
            signal.signal(signum, previous)
        # A pre-spawn failure has no descendants. A killed wrapper never reaches
        # this finally and leaves its already-published durable claim untouched.
        lease.close(clean=clean or child is None)
