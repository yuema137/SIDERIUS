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
    except OSError:
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
    data_dir: str, file_paths: list[str], *, scoped_bytes: int | None = None
) -> dict[str, Any]:
    """Snapshot the dataset's storage identity (§2.2).

    Args:
        data_dir:     Root directory of the dataset.
        file_paths:   Absolute paths of the files the setup will read.
                      Missing files are counted, not raised — the engine
                      itself decides how to treat absent files.
        scoped_bytes: The bytes the setup will ACTUALLY read (sparse /
                      scoped slices). When provided it becomes
                      ``expected_raw_bytes`` — pre-Gate finding F2:
                      whole-file sizes misclassify a genuinely cold
                      sparse read as warm because the read counter never
                      approaches the full file size. Whole-file sizes
                      stay available as ``total_file_bytes``.

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
        "total_file_bytes": total_bytes,
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


def classify_cache_state(
    bytes_read: int | None,
    expected_bytes: int | None,
    *,
    cold_read_fraction: float = COLD_READ_FRACTION,
) -> CacheState:
    """Classify the cache state of a completed setup read (§2.2).

    The classification is measured, not assumed: ``bytes_read`` is the
    storage-layer read counter delta across the setup window and
    ``expected_bytes`` the on-disk size of what was read. A warm-cache
    measurement must never be presented as a cold-start prediction, so
    any missing counter yields ``"unknown"``.

    Args:
        bytes_read:         Storage-layer bytes read during setup
                            (``read_process_read_bytes`` delta), or
                            ``None`` when the counter was unavailable.
        expected_bytes:     On-disk bytes of the files the setup read,
                            or ``None`` when unknown.
        cold_read_fraction: Fraction of ``expected_bytes`` above which
                            the access counts as cold.
    """
    if bytes_read is None or expected_bytes is None:
        return "unknown"
    if expected_bytes <= 0:
        return "unknown"
    return (
        "cold_first_access"
        if bytes_read >= cold_read_fraction * expected_bytes
        else "warm_page_cache"
    )
