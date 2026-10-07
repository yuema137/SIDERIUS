"""
core/runtime_control/provenance.py

Environment / storage / process-IO provenance capture for runtime
observations (RT2-B).

Design: docs/design/runtime_estimation_and_watchdog.md §2.2 — every
setup measurement records where it ran and what it read, with the
outcome measured rather than labeled ("no ambiguous labels"). All
capture functions are best-effort and degrade to explicit ``None`` /
``"unknown"`` on non-Linux hosts or missing ``/proc`` entries — a
provenance gap is recorded as a gap, never fabricated.

Task-agnostic: callers (the production engines) pass explicit file
paths; nothing here knows about dataset naming conventions.
"""

from __future__ import annotations

import os
import platform
import socket
import sys
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

ProcessReadBytesScope = Literal["complete", "incomplete", "unknown"]

CacheState = Literal["cold_first_access", "warm_page_cache", "already_materialized", "unknown"]

#: Fraction of the expected bytes that must be read from storage for the
#: access to count as cold. Well under 1.0 on purpose: filesystem
#: read-ahead and partial page-cache hits make a truly cold read land
#: below the raw file size, while a warm read lands near zero.
COLD_READ_FRACTION = 0.5


def capture_environment_provenance() -> dict[str, Any]:
    """Snapshot the execution environment (§2.2).

    Returns:
        Dict with hostname, platform, Python/torch/CUDA versions, GPU
        name, and a wall-clock timestamp. Torch/GPU fields are ``None``
        when torch is unavailable or no CUDA device is visible.
    """
    prov: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": sys.version.split()[0],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "torch_version": None,
        "cuda_version": None,
        "gpu_name": None,
    }
    try:
        import torch

        prov["torch_version"] = torch.__version__
        prov["cuda_version"] = torch.version.cuda
        if torch.cuda.is_available():
            prov["gpu_name"] = torch.cuda.get_device_name(0)
    except Exception:
        pass
    return prov


def capture_software_stack() -> dict[str, Any]:
    """The software stack that backs a calibration observation's identity.

    This is the *drift anchor*: `stack_identity` (`calibration_policy.py`)
    content-hashes the returned dict, so the KEY NAMES are part of the
    bucket key. Two producers emitting the same facts under different key
    names would fork the bucket for one machine, which is why this lives in
    one place rather than at each call site.

    The shape is `{"torch": ..., "cuda": ...}`, matching what
    `runtime_bootstrap` already wrote, so records produced by the bootstrap
    CLI and by the tuner describe the same stack with the same identity.

    Returns:
        Both keys, always. A value is ``None`` when torch is unavailable, or
        when `torch.version.cuda` is None on a CPU-only build.

    An absent stack is deliberately **not** ``{}``. An empty dict is what a
    caller passes when it never looked, and `stack_identity({})` is a
    constant digest shared by every such record — that is exactly the state
    this helper exists to end. ``{"torch": None, "cuda": None}`` says "we
    looked and there was nothing to find", which is a different fact.
    """
    stack: dict[str, Any] = {"torch": None, "cuda": None}
    try:
        import torch

        stack["torch"] = torch.__version__
        stack["cuda"] = torch.version.cuda
    except Exception:
        pass
    return stack


def read_process_read_bytes() -> int | None:
    """Bytes this process has read from the storage layer (``/proc/self/io``).

    Returns ``None`` when the counter is unavailable (non-Linux,
    restricted /proc). ``read_bytes`` counts actual storage-layer reads,
    so page-cache hits do NOT increment it — exactly the property the
    cold/warm classification needs.
    """
    try:
        with open("/proc/self/io") as f:
            for line in f:
                if line.startswith("read_bytes:"):
                    return int(line.split(":", 1)[1].strip())
    except (OSError, ValueError):
        return None
    return None


def read_process_rss_bytes() -> int | None:
    """Resident set size of this process (``/proc/self/status`` VmRSS).

    Returns ``None`` when unavailable.
    """
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024  # kB → bytes
    except (OSError, ValueError, IndexError):
        return None
    return None


def capture_storage_provenance(
    data_dir: str,
    file_paths: list[str],
    *,
    scoped_bytes: int | None = None,
    process_read_bytes_scope: ProcessReadBytesScope = "unknown",
    process_read_bytes_reason: str | None = None,
) -> dict[str, Any]:
    """Snapshot the dataset's storage identity (§2.2).

    Args:
        data_dir:     Root directory of the dataset.
        file_paths:   Absolute paths of the files the setup will read.
                      Missing files are counted, not raised — the engine
                      itself decides how to treat absent files.
        scoped_bytes: On-disk bytes the setup will read (sparse /
                      scoped slices). When provided it becomes
                      ``expected_raw_bytes`` — pre-Gate finding F2:
                      whole-file sizes misclassify a genuinely cold
                      sparse read as warm because the read counter never
                      approaches the full file size. Whole-file sizes
                      stay available as ``total_file_bytes``.
        process_read_bytes_scope: Whether this process's counter covers the
                      setup reads, including the storage backend. Merely having
                      a readable counter is not evidence of complete coverage.
        process_read_bytes_reason: Task-owned explanation of incomplete or
                      unknown coverage, preserved in the observation.

    Returns:
        Dict with dataset root, file counts, expected raw bytes (scoped
        when known, else on-disk file sizes), total on-disk file bytes,
        and the filesystem type of the best-matching mount point
        (``"unknown"`` when undeterminable).
    """
    existing = [p for p in file_paths if os.path.exists(p)]
    total_bytes = sum(os.stat(p).st_size for p in existing)
    return {
        "dataset_root": os.path.abspath(data_dir),
        "file_count": len(file_paths),
        "files_present": len(existing),
        "expected_raw_bytes": scoped_bytes if scoped_bytes is not None else total_bytes,
        "expected_on_disk_bytes": scoped_bytes if scoped_bytes is not None else total_bytes,
        "total_file_bytes": total_bytes,
        "process_read_bytes_scope": process_read_bytes_scope,
        "process_read_bytes_reason": process_read_bytes_reason,
        "filesystem_type": _filesystem_type(os.path.abspath(data_dir)),
    }


def _filesystem_type(path: str) -> str:
    """Filesystem type of the mount point covering ``path`` (Linux).

    Longest-prefix match over ``/proc/mounts``; ``"unknown"`` on any
    failure.
    """
    try:
        best_len, best_type = -1, "unknown"
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mount_point, fs_type = parts[1], parts[2]
                if path.startswith(mount_point) and len(mount_point) > best_len:
                    best_len, best_type = len(mount_point), fs_type
        return best_type
    except OSError:
        return "unknown"


class CacheStateAssessment(BaseModel):
    """Cache classification and the reason evidence could not support one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: CacheState
    unknown_reason: str | None = None


def assess_cache_state(
    bytes_read: int | None,
    expected_bytes: int | None,
    *,
    process_read_bytes_scope: ProcessReadBytesScope = "unknown",
    process_read_bytes_reason: str | None = None,
    cold_read_fraction: float = COLD_READ_FRACTION,
) -> CacheStateAssessment:
    """Compare physical bytes only when process-counter coverage is declared.

    Filesystem names cannot prove counter coverage: loaders may delegate reads
    to workers or services on any filesystem. Tasks declare coverage through
    their public storage capability. Unknown coverage never implies warm cache.
    """
    if process_read_bytes_scope != "complete":
        reason = process_read_bytes_reason or f"process_counter_coverage_{process_read_bytes_scope}"
    elif bytes_read is None:
        reason = "process_read_counter_unavailable"
    elif bytes_read < 0:
        reason = "process_read_counter_decreased"
    elif expected_bytes is None or expected_bytes <= 0:
        reason = "scoped_on_disk_bytes_unavailable"
    else:
        return CacheStateAssessment(
            state=(
                "cold_first_access"
                if bytes_read >= cold_read_fraction * expected_bytes
                else "warm_page_cache"
            )
        )
    return CacheStateAssessment(state="unknown", unknown_reason=reason)


def classify_cache_state(
    bytes_read: int | None,
    expected_bytes: int | None,
    *,
    cold_read_fraction: float = COLD_READ_FRACTION,
    filesystem_type: str | None = None,
    process_read_bytes_scope: ProcessReadBytesScope = "unknown",
) -> CacheState:
    """Return the cache state; use ``assess_cache_state`` to preserve the reason.

    ``filesystem_type`` remains an accepted compatibility keyword, but is
    descriptive metadata only. Complete counter coverage must be declared;
    a filesystem name alone cannot establish it. ``expected_bytes`` is scoped
    on-disk bytes, never the decoded size. The cold threshold remains 0.5.
    """
    return assess_cache_state(
        bytes_read,
        expected_bytes,
        cold_read_fraction=cold_read_fraction,
        process_read_bytes_scope=process_read_bytes_scope,
    ).state
