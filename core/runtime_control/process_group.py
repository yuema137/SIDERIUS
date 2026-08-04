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

import os


def tree_rss_bytes(pgid: int) -> int:
    """Resident memory of every process in `pgid`, in bytes.

    Resident, not address space. Importing torch and touching CUDA reserves
    ~19.0 GiB of VIRTUAL address space while holding ~0.65 GiB resident
    (measured 2026-07-31, SHA d83f397), so bounding one with the other is
    the same error as using wall time to bound memory.

    A process that exits mid-walk is a dropped row, not an error.
    """
    total = 0
    try:
        entries = os.listdir("/proc")
    except OSError:
        return 0
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            if os.getpgid(int(entry)) != pgid:
                continue
            with open(f"/proc/{entry}/statm") as handle:
                total += int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ProcessLookupError, PermissionError, IndexError, ValueError):
            continue
    return total


def process_group_alive(pgid: int) -> bool:
    """Whether anything in the group is still running.

    Used after reaping to report orphans: a worker that spawned children
    can leave them holding the device after the parent has moved on.
    """
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def signal_group(pgid: int, sig: int) -> bool:
    """Signal the whole group; `False` when there was nothing to signal.

    The group, not the process: a worker's children hold the GPU too, and
    signalling only the leader leaves them behind.
    """
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        return False
    return True
