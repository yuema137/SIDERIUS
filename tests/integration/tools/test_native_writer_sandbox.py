"""Real bubblewrap witness: a sandboxed native loop entry owns the host writer lock.

Regression for ``writer_state_refused``: the candidate worker's loop child calls
``iteration_owner(workspace)`` inside the sandbox, whose workspace parent is
read-only, so the sibling ``.<name>.siderius-writer`` directory could not be
created. The fix prepares that directory outside the sandbox
(``candidate_worker.launch.loop_writer_state``) and binds exactly it writable.

Ownership acquired inside must be the host's: while the child holds it, host
``inspect_writer`` reports ``active``. This also rules out a directory created on a
sandbox-private tmpfs (for example when ``--basetemp`` is under ``/tmp``).

Hardening (#1525): the directory is bound read-only with only the host
pre-created ``writer.lock`` bound writable on top (NFS/SMB flock needs O_RDWR), so
while it holds ownership the sandboxed child cannot unlink, rename or replace the
lock, chmod the directory or create files beside it; the host inode stays the same
and the lock stays lockable. Writing to or chmodding the lock file itself is within
the same-uid trust boundary and not attempted here. Skips when bubblewrap cannot
create user namespaces on this host.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from core.native_writer import inspect_writer, iteration_owner
from tools.candidate_worker.launch import loop_writer_state
from tools.workspace_sandbox.command import build_command
from tools.workspace_sandbox.profile import SandboxProfile

_CHILD = """
import os, sys, time
from pathlib import Path
from core.native_writer import iteration_owner
workspace = Path(sys.argv[1])
state = workspace.parent / f".{workspace.name}.siderius-writer"
lock = state / "writer.lock"
try:
    (workspace.parent / "escape").write_text("x")
except OSError:
    pass
attacks = {
    "unlink": lambda: os.unlink(lock),
    "rename": lambda: os.rename(lock, state / "moved"),
    "create": lambda: (state / "forged").write_text("x"),
    "replace": lambda: os.replace(workspace / "forged", lock),
    "chmod_state": lambda: os.chmod(state, 0o777),
}
try:
    with iteration_owner(str(workspace)):
        (workspace / "forged").write_text("x")
        succeeded = []
        for name, attack in attacks.items():
            try:
                attack()
                succeeded.append(name)
            except OSError:
                pass
        (workspace / "attacks").write_text(",".join(succeeded))
        (workspace / "held").write_text("1")
        deadline = time.monotonic() + 60
        while not (workspace / "release").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
except Exception as error:
    (workspace / "error").write_text(f"{type(error).__name__}: {error}")
    raise SystemExit(3)
"""


def _require_bwrap() -> None:
    if sys.platform != "linux" or shutil.which("bwrap") is None:
        pytest.skip("real sandbox witness requires Linux with bubblewrap (bwrap) on PATH")
    probe = subprocess.run(
        ["bwrap", "--unshare-all", "--ro-bind", "/", "/", "true"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip(f"bubblewrap cannot create user namespaces here: {probe.stderr.strip()}")


def _run(workspace: Path, writer_state: Path | None) -> tuple[str, int]:
    """Return (host inspection while the child holds or failed, child exit code)."""
    profile = SandboxProfile(
        workspace=workspace, writer_state=writer_state, network=False, timeout_seconds=60
    )
    command, env = build_command(profile, [sys.executable, "-c", _CHILD, str(workspace)])
    child = subprocess.Popen(command, env=env)
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and child.poll() is None:
            if (workspace / "held").exists():
                break
            time.sleep(0.05)
        observed = inspect_writer(workspace).status if (workspace / "held").exists() else "none"
        (workspace / "release").write_text("1")
        return observed, child.wait(timeout=60)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_sandboxed_loop_entry_holds_the_host_writer_lock(tmp_path):
    _require_bwrap()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = loop_writer_state(workspace)
    lock = (state / "writer.lock").stat()
    observed, code = _run(workspace, state)
    error = (workspace / "error").read_text() if (workspace / "error").exists() else None
    assert (observed, code, error) == ("active", 0, None)
    # #1525: every attempt to change the lock or its directory was refused.
    assert (workspace / "attacks").read_text() == ""
    after = (state / "writer.lock").stat()
    assert (after.st_dev, after.st_ino, after.st_mode) == (lock.st_dev, lock.st_ino, lock.st_mode)
    assert sorted(path.name for path in state.iterdir()) == ["writer.lock"]
    assert oct(state.stat().st_mode & 0o777) == oct(0o700)
    # The lock is still the lockable host inode: a new owner acquires and releases it.
    with iteration_owner(str(workspace)) as lease:
        assert lease is not None and os.fstat(lease.fd).st_ino == lock.st_ino
    # Released cleanly; the parent stayed read-only apart from the bound directory.
    assert inspect_writer(workspace).status == "unregistered"
    assert not (tmp_path / "escape").exists()


def test_without_the_bound_state_the_sandbox_cannot_hold_host_ownership(tmp_path):
    # Discriminating control for the test above: the pre-fix profile.
    _require_bwrap()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    observed, code = _run(workspace, None)
    assert observed != "active"
    if not str(tmp_path).startswith("/tmp/"):
        # Outside the sandbox's private /tmp this is the reported production failure.
        assert code == 3
        assert "writer_state_refused" in (workspace / "error").read_text()
