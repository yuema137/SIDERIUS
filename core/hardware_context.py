"""Hardware discovery and per-run manifest (Phase 6.6 §3.9).

Single source of truth for every physical-device lookup in SIDERIUS.
No other file in the codebase should call ``torch.cuda.get_device_properties``
or embed a device-specific literal (e.g. ``"32 GB"``, ``"RTX 5090"``,
``"A100"``). Principle 5 of the Phase 6.6 design doc ("Universal Hardware
Awareness") is realised here and enforced by ``test_no_hardcoded_device_literals``.

Public surface
--------------
- ``HardwareContext`` — Pydantic schema. Holds every discovered physical fact
  about the active CUDA device (or a CPU-mode stub when CUDA is unavailable).
  Exposes ``usable_cap_bytes`` = ``0.80 × total_memory_bytes`` as the single
  canonical VRAM cap used by the estimator, the batch resolver, and the
  Memory Killer verdict.
- ``discover()`` — builds a ``HardwareContext`` from the current process's
  view of ``torch.cuda``. Always cheap (no kernel launch; only property reads).
- ``write_manifest(ctx, path)`` / ``load_manifest(path)`` — JSON round-trip.
- ``get_or_create(workspace, run_name)`` — per-run lifecycle. On a fresh
  workspace, discovers + persists. On an existing workspace, validates the
  stored manifest against the current host and regenerates on mismatch
  (workspace moved between servers).

Cross-process consistency
-------------------------
``sandbox_executor`` launches training and inference as isolated subprocesses;
those children cannot inherit an in-memory ``HardwareContext`` from the
parent. The manifest file at ``{workspace}/{run_name}_hardware.json`` is the
IPC: children ``load_manifest`` it instead of re-probing, so the whole run
shares one cap and one device identity.
"""

from __future__ import annotations

import json
import logging
import socket
from datetime import UTC, datetime
from pathlib import Path

import torch
from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)


_SAFETY_FRACTION: float = 0.80  # §3.9.1: single source of truth for the cap
_CPU_DEVICE_NAME: str = "cpu"  # stable marker for ``device_available=False``


class HardwareContext(BaseModel):
    """Discovered physical facts about the active device.

    Immutable (``frozen=True``). If the hardware changes (workspace moved
    between servers, GPU swapped), produce a NEW ``HardwareContext`` via
    ``discover()`` — do not mutate an existing one.
    """

    model_config = ConfigDict(frozen=True)

    device_name: str
    total_memory_bytes: int
    compute_capability: tuple[int, int]  # (major, minor)
    multiprocessor_count: int
    cuda_runtime_version: str | None = None  # None on CPU-only hosts
    torch_version: str
    hostname: str
    device_available: bool
    discovered_at: datetime = Field(description="UTC timestamp of discover() invocation.")

    @property
    def usable_cap_bytes(self) -> int:
        """``0.80 × total_memory_bytes``. Single source of truth for the cap.

        Changing the safety fraction is a one-line edit to ``_SAFETY_FRACTION``
        at module scope plus a regression test update — not a runtime knob.
        """
        return int(_SAFETY_FRACTION * self.total_memory_bytes)

    @property
    def total_memory_gb(self) -> float:
        return self.total_memory_bytes / (1024**3)

    @property
    def usable_cap_gb(self) -> float:
        return self.usable_cap_bytes / (1024**3)


def discover() -> HardwareContext:
    """Build a ``HardwareContext`` from the current process's CUDA view.

    On GPU hosts: reads ``torch.cuda.get_device_properties(0)`` and populates
    every field. On CPU-only hosts (or ``torch.cuda.is_available()==False``):
    returns a stub with ``device_available=False`` and ``total_memory_bytes=0``.
    Consumers that require GPU must check ``device_available`` and early-return
    a CPU-mode verdict — the VRAM estimator does this today.
    """
    now = datetime.now(UTC)
    hostname = socket.gethostname()
    torch_version = torch.__version__

    if not torch.cuda.is_available():
        return HardwareContext(
            device_name=_CPU_DEVICE_NAME,
            total_memory_bytes=0,
            compute_capability=(0, 0),
            multiprocessor_count=0,
            cuda_runtime_version=None,
            torch_version=torch_version,
            hostname=hostname,
            device_available=False,
            discovered_at=now,
        )

    props = torch.cuda.get_device_properties(0)
    return HardwareContext(
        device_name=props.name,
        total_memory_bytes=int(props.total_memory),
        compute_capability=(int(props.major), int(props.minor)),
        multiprocessor_count=int(props.multi_processor_count),
        cuda_runtime_version=torch.version.cuda,
        torch_version=torch_version,
        hostname=hostname,
        device_available=True,
        discovered_at=now,
    )


def write_manifest(ctx: HardwareContext, path: Path) -> None:
    """Serialize ``ctx`` to ``path`` as indented JSON with trailing newline.

    ``path.parent`` is created with ``parents=True, exist_ok=True``. Datetimes
    are written in ISO-8601 (Pydantic default). Tuples serialise as JSON
    arrays and are converted back to tuples on load.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # ``mode="json"`` makes Pydantic emit JSON-native types (ISO strings for
    # datetimes, lists for tuples) — required for stable round-trip.
    payload = ctx.model_dump(mode="json")
    path.write_text(json.dumps(payload, indent=2) + "\n")


def load_manifest(path: Path) -> HardwareContext:
    """Read a manifest written by ``write_manifest``. Raises ``ValidationError``
    on a corrupt or schema-mismatched file (do not silently regenerate from
    ``load_manifest`` — let ``get_or_create`` own that recovery path)."""
    path = Path(path)
    raw = json.loads(path.read_text())
    return HardwareContext.model_validate(raw)


def _manifest_path(workspace: Path, run_name: str) -> Path:
    return Path(workspace) / f"{run_name}_hardware.json"


def get_or_create(workspace: Path, run_name: str) -> HardwareContext:
    """Per-run lifecycle.

    1. Manifest path = ``{workspace}/{run_name}_hardware.json``.
    2. If missing → ``discover() + write_manifest()``, return.
    3. If present → ``load_manifest()``, compare ``device_name`` + ``hostname``
       against a fresh ``discover()``. On match → return the stored manifest
       (no write). On mismatch → log warning, regenerate, overwrite, return
       the fresh one. A corrupt manifest (``ValidationError``) triggers the
       same regeneration path.
    """
    path = _manifest_path(workspace, run_name)

    if not path.exists():
        fresh = discover()
        write_manifest(fresh, path)
        return fresh

    try:
        stored = load_manifest(path)
    except (ValidationError, json.JSONDecodeError) as err:
        logger.warning(
            "hardware_context: manifest at %s is corrupt (%s); regenerating.",
            path,
            err,
        )
        fresh = discover()
        write_manifest(fresh, path)
        return fresh

    fresh = discover()
    if stored.device_name == fresh.device_name and stored.hostname == fresh.hostname:
        return stored

    logger.warning(
        "hardware_context: stored manifest at %s describes device=%r host=%r "
        "but current environment is device=%r host=%r. Regenerating.",
        path,
        stored.device_name,
        stored.hostname,
        fresh.device_name,
        fresh.hostname,
    )
    write_manifest(fresh, path)
    return fresh
