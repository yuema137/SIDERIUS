"""Bounded process-group primitives for supervising a worker tree.

Generic runtime infrastructure: this module knows about PIDs, process
groups and `/proc`, and nothing about models, phases or tasks.

**Why it exists.** `agent/skills/evaluate_vram_skill/isolated_probe.py` and
`core/runtime_control/probe_subprocess.py` each grew their own identical
`_process_group_alive` / `_signal_group`, and V20 PR C2's pre-phase
measurement runner needs the same three helpers plus the tree-RSS read. A
third and fourth copy of a kill path is not a maintenance annoyance, it is
four places where a supervision bug can be fixed in one and survive in the
others.

`isolated_probe` now delegates here. `probe_subprocess` deliberately does
not: it sits on C1's just-validated duration path, and moving it is a
separate in-passing change rather than something to do while landing a
measurement producer.

**Read `/proc` directly, import nothing heavy.** The supervision loop's job
is to survive whatever the worker does to the host, so the monitor must not
itself become the memory problem.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict


def tree_rss_bytes(pgid: int) -> int:
    """Resident memory of every process in `pgid`, in bytes.

    Resident, not address space. Importing torch and touching CUDA reserves
    ~19.0 GiB of VIRTUAL address space while holding ~0.65 GiB resident
    (measured 2026-07-31, SHA d83f397), so bounding one with the other is
    the same error as using wall time to bound memory.

    A process that exits mid-walk is a dropped row, not an error.
    """
    return observe_tree_rss(pgid).sampled_bytes


def process_group_alive(pgid: int) -> bool:
    """Whether anything in the group is still running.

    Used after reaping to report orphans: a worker that spawned children
    can leave them holding the device after the parent has moved on.
    """
    return observe_group(pgid).status == "present"


def signal_group(pgid: int, sig: int) -> bool:
    """Signal the whole group; `False` when there was nothing to signal.

    The group, not the process: a worker's children hold the GPU too, and
    signalling only the leader leaves them behind.
    """
    return observe_signal(pgid, sig).status == "delivered"


class RssObservation(BaseModel):
    """A sampled total; incomplete/unavailable is never an authoritative zero."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["complete", "incomplete", "unavailable"]
    sampled_bytes: int = 0
    errors: tuple[str, ...] = ()


class GroupObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["present", "absent", "unknown"]
    error: str | None = None


class SignalObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["delivered", "absent", "unavailable"]
    error: str | None = None


class GroupCleanup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    required: bool
    term: SignalObservation | None = None
    kill: SignalObservation | None = None
    final: GroupObservation


def observe_group(pgid: int) -> GroupObservation:
    """Permission failure cannot prove absence."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return GroupObservation(status="absent")
    except OSError as exc:
        return GroupObservation(status="unknown", error=f"{type(exc).__name__}: {exc}")
    return GroupObservation(status="present")


def observe_signal(pgid: int, sig: int) -> SignalObservation:
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        return SignalObservation(status="absent")
    except OSError as exc:
        return SignalObservation(status="unavailable", error=f"{type(exc).__name__}: {exc}")
    return SignalObservation(status="delivered")


def observe_tree_rss(pgid: int) -> RssObservation:
    """Read group membership and resident bytes without hiding missing evidence.

    A vanished PID is a normal race. Inaccessible membership is incomplete even
    when we cannot determine whether that PID belongs to the requested group.
    This is sampled Linux /proc evidence, not an atomic memory reservation.
    """
    try:
        entries = os.listdir("/proc")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError) as exc:
        return RssObservation(status="unavailable", errors=(f"{type(exc).__name__}: {exc}",))
    total = 0
    errors: list[str] = []
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            if os.getpgid(int(entry)) != pgid:
                continue
            with open(f"/proc/{entry}/statm") as handle:
                resident = int(handle.read().split()[1])
            total += resident * page_size
            if resident < 0:
                errors.append(f"pid {entry}: negative resident page count")
        except (ProcessLookupError, FileNotFoundError):
            continue
        except (OSError, IndexError, ValueError) as exc:
            errors.append(f"pid {entry}: {type(exc).__name__}: {exc}")
    return RssObservation(
        status="incomplete" if errors else "complete", sampled_bytes=total, errors=tuple(errors)
    )


def terminate_observed_group(
    pgid: int,
    *,
    grace_seconds: float,
    poll_seconds: float,
    child: subprocess.Popen | None = None,
    retain_unknown: bool = True,
) -> GroupCleanup:
    """One TERM/grace/KILL owner, including after the group leader exits.

    Only pass a group created by the caller. Polling the direct child reaps its
    zombie; grandchildren remain their parent's/reaper's responsibility. Legacy
    wrappers retain their historical unknown-as-absent conversion explicitly.
    """

    def sample() -> GroupObservation:
        if child is not None:
            child.poll()
        observation = observe_group(pgid)
        if not retain_unknown and observation.status == "unknown":
            return GroupObservation(status="absent")
        return observation

    current = sample()
    if current.status == "absent":
        return GroupCleanup(required=False, final=current)
    term = observe_signal(pgid, signal.SIGTERM)
    until = time.monotonic() + grace_seconds
    current = sample()
    while current.status != "absent" and time.monotonic() < until:
        interval = min(poll_seconds, max(0.0, until - time.monotonic()))
        wait_started = time.monotonic()
        if child is not None:
            # SIGTERM handlers may flush more than a pipe buffer before exit.
            # Reaping alone would block that graceful path and force SIGKILL.
            with contextlib.suppress(subprocess.TimeoutExpired):
                child.communicate(timeout=interval)
        current = sample()
        if current.status != "absent":
            time.sleep(max(0.0, interval - (time.monotonic() - wait_started)))
    kill = None
    if current.status != "absent":
        kill = observe_signal(pgid, signal.SIGKILL)
    return GroupCleanup(required=True, term=term, kill=kill, final=sample())


def terminate_remaining_group(
    pgid: int,
    *,
    grace_seconds: float,
    poll_seconds: float,
) -> tuple[bool, bool]:
    """Compatibility projection for existing supervision callers."""
    cleanup = terminate_observed_group(
        pgid, grace_seconds=grace_seconds, poll_seconds=poll_seconds, retain_unknown=False
    )
    return (
        cleanup.term is not None and cleanup.term.status == "delivered",
        cleanup.kill is not None and cleanup.kill.status == "delivered",
    )
