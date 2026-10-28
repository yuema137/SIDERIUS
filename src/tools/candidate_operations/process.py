"""Exact-environment spawning and read-only Linux process identity observation."""

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from core.layout import checkout_root, package_root
from tools.workspace_sandbox.profile import SandboxProfile

from .files import directory, private
from .models import (
    OperationFailure,
    OperationRecord,
    ProcessIdentity,
    ProcessObservation,
    RuntimeIdentity,
)


def environment(names: tuple[str, ...], source: Mapping[str, str]) -> dict[str, str]:
    SandboxProfile.environment_keys(names)
    missing = tuple(name for name in names if not source.get(name))
    if missing:
        raise OperationFailure(
            "environment", "missing required environment names: " + ", ".join(missing)
        )
    if any("\0" in source[name] for name in names):
        raise OperationFailure("environment", "environment values must not contain NUL")
    return {
        "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        **{name: source[name] for name in names},
    }


def runtime_identity() -> RuntimeIdentity:
    checkout = checkout_root()
    revision = None
    if checkout is not None:
        result = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            env=environment((), {}),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            revision = result.stdout.strip()
    return RuntimeIdentity(
        executable=sys.executable,
        resolved_executable=str(Path(sys.executable).resolve()),
        environment=str(Path(sys.prefix).resolve()),
        source=str(checkout or package_root()),
        revision=revision,
    )


def _boot_id() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def _stat(pid: int) -> tuple[str, int]:
    payload = Path(f"/proc/{pid}/stat").read_text()
    prefix, fields = payload.rsplit(")", 1)
    if int(prefix.split("(", 1)[0]) != pid:
        raise ValueError("process identity mismatch")
    values = fields.split()
    if len(values) < 20 or len(values[0]) != 1:
        raise ValueError("malformed process stat")
    return values[0], int(values[19])


def current_identity(record: OperationRecord) -> ProcessIdentity:
    return identity_of(record, os.getpid())


def identity_of(record: OperationRecord, pid: int) -> ProcessIdentity:
    """Identity of a process this caller started and has not reaped (so its PID is pinned)."""
    _, ticks = _stat(pid)
    return ProcessIdentity(
        operation_id=record.submission.request_id,
        request_digest=record.request_digest,
        boot_id=_boot_id(),
        pid=pid,
        start_ticks=ticks,
    )


def session_members(session_id: int) -> int | None:
    """Count live (non-zombie) processes in one session; ``None`` when unobservable.

    Linux keeps a session ID allocated while any process still belongs to it, so a
    surviving member of an exited leader's session is counted, never confused with
    an unrelated process that reused the number.
    """
    try:
        names = os.listdir("/proc")
    except OSError:
        return None
    if not Path("/proc/self/stat").is_file():
        return None
    count = 0
    for name in names:
        if not name.isdigit():
            continue
        fields = _scan_fields(name)
        if fields is _UNREADABLE:
            return None
        if fields is not None and fields[0] not in {"Z", "X", "x"} and int(fields[3]) == session_id:
            count += 1
    return count


_UNREADABLE: list[str] = []


def _scan_fields(name: str) -> list[str] | None:
    """Stat fields after the command name; ``None`` to skip, ``_UNREADABLE`` to give up.

    An entry that vanished, or that belongs to another user and cannot be read,
    cannot be a member of this user's operation session and is skipped. An
    unreadable entry owned by this user makes the count unobservable.
    """
    try:
        fields = Path(f"/proc/{name}/stat").read_text().rsplit(")", 1)[1].split()
    except (FileNotFoundError, ProcessLookupError):
        return None
    except (OSError, IndexError):
        try:
            foreign = os.stat(f"/proc/{name}").st_uid != os.getuid()
        except OSError:
            return None  # vanished
        return None if foreign else _UNREADABLE
    return fields if len(fields) >= 4 else _UNREADABLE


def observe(identity: ProcessIdentity) -> ProcessObservation:
    try:
        boot = _boot_id()
    except OSError:
        return ProcessObservation(status="unknown", reason="boot_unobservable")
    try:
        if boot != identity.boot_id:
            return ProcessObservation(status="exited", reason="different_boot")
        state, ticks = _stat(identity.pid)
        if ticks != identity.start_ticks:
            return ProcessObservation(status="exited", reason="pid_reused")
        if state in {"Z", "X", "x"}:
            return ProcessObservation(status="exited", reason="zombie_or_dead")
        return ProcessObservation(status="alive", reason="matching_identity")
    except FileNotFoundError:
        # A missing /proc root is not positive evidence that the process exited.
        if Path("/proc/self/stat").is_file():
            return ProcessObservation(status="exited", reason="pid_absent")
        return ProcessObservation(status="unknown", reason="proc_unavailable")
    except (OSError, ValueError, IndexError):
        return ProcessObservation(status="unknown", reason="identity_unobservable")


def spawn(path: Path, env: dict[str, str]) -> subprocess.Popen:
    with directory(path) as descriptor:
        log = os.open(
            "operation.log",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=descriptor,
        )
    try:
        private(os.fstat(log), directory=False)
        return subprocess.Popen(
            [sys.executable, "-m", "tools.candidate_operations.child", str(path)],
            env=env,
            cwd=str(path),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            close_fds=True,
            start_new_session=True,
        )
    finally:
        os.close(log)
