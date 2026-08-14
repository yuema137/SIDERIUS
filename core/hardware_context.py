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
import os
import platform as _platform_mod
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import torch
from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)


_SAFETY_FRACTION: float = 0.80  # §3.9.1: single source of truth for the cap
_CPU_DEVICE_NAME: str = "cpu"  # stable marker for ``device_available=False``
_PROBE_TIMEOUT_S: float = 5.0  # O1a: bound on every external probe


class GpuDeviceProvenance(BaseModel):
    """Per-visible-device provenance (V19 O1a). Ordered by logical index —
    under ``CUDA_VISIBLE_DEVICES`` the logical indices are the mapped
    subset; the raw env value is recorded on the parent context so the
    physical identity stays recoverable."""

    model_config = ConfigDict(frozen=True)

    logical_index: int
    name: str
    total_memory_bytes: int
    compute_capability: tuple[int, int]

    # --- V20 B-C2b device identity (optional; old manifests load unchanged) ---
    #: Stable GPU UUID, normalized to the driver's ``GPU-<hex>`` form.
    #: The identity primary key: a device name is not one, because two
    #: cards of the same model are indistinguishable by it.
    uuid: str | None = None
    #: Index as the *driver* reports it, which under
    #: ``CUDA_VISIBLE_DEVICES`` is not the logical index above. Resolved
    #: by matching UUIDs, never by assuming the two orders agree.
    physical_index: int | None = None


class HardwareContext(BaseModel):
    """Discovered physical facts about the active device.

    Immutable (``frozen=True``). If the hardware changes (workspace moved
    between servers, GPU swapped), produce a NEW ``HardwareContext`` via
    ``discover()`` — do not mutate an existing one.

    V19 O1a extends the manifest with optional run-level runtime
    provenance (multi-GPU enumeration, driver version, environment
    facts). All new fields are best-effort and defaulted: old manifests
    load unchanged, collection failures are recorded in
    ``collection_errors`` instead of aborting, and the
    ``get_or_create`` mismatch check still keys ONLY on ``device_name``
    + ``hostname`` — new fields never trigger regeneration.
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

    # --- V19 O1a runtime provenance (optional, best-effort, recording-only) ---
    platform: str | None = None  # platform.platform()
    python_version: str | None = None
    cuda_visible_devices: str | None = Field(
        default=None,
        description="Raw CUDA_VISIBLE_DEVICES value at discovery; None when unset.",
    )
    visible_device_count: int | None = None
    devices: list[GpuDeviceProvenance] = Field(
        default_factory=list,
        description="ALL visible CUDA devices in deterministic logical-index order.",
    )
    # --- V20 B-C2b (FU-A-13): identity of the ACTIVE device ---
    #: UUID of the device this context describes. ``None`` on CPU-only
    #: hosts, on older manifests, and whenever discovery could not read
    #: it — in which case identity is *degraded*, never fabricated.
    active_device_uuid: str | None = None
    #: 1 = legacy, identity keyed on ``device_name``. 2 = UUID-keyed.
    #: Versioned rather than replaced in place: old records have no UUID,
    #: and silently changing what identity means would invalidate
    #: existing measurements and resume state for no stated reason.
    hardware_fingerprint_version: int = Field(default=1, ge=1)

    driver_version: str | None = Field(
        default=None,
        description="NVIDIA driver version via bounded nvidia-smi probe; None on any failure.",
    )
    repo_commit: str | None = Field(
        default=None,
        description="git rev-parse HEAD of the running checkout; None outside a repo.",
    )
    collection_errors: list[str] = Field(
        default_factory=list,
        description="Explicit per-probe failures ('probe: error'); provenance gaps are "
        "recorded as gaps, never fabricated.",
    )

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

    def effective_cap_gb(self, vram_budget_gb: float | None) -> float:
        """The ceiling an architecture must actually fit under, in GB.

        The three regimes the proposer's ``[HARDWARE CONTEXT]`` block names
        collapse to one expression, because in each of them the binding
        ceiling is whichever of the two is smaller:

        =================================  ==============================
        regime                             effective cap
        =================================  ==============================
        PHYSICAL (no operator budget)      ``usable_cap_gb``
        BUDGET (budget <= usable)          ``vram_budget_gb``
        PHYSICAL VETO (budget > usable)    ``usable_cap_gb``
        =================================  ==============================

        Extracted (Step 04a) so the implementor's capacity prose and the
        proposer's block cannot disagree about the number they quote. Two
        copies of this rule would be two authorities, and the divergence
        would be invisible: both render plausible GB values.
        """
        if vram_budget_gb is None:
            return self.usable_cap_gb
        return min(vram_budget_gb, self.usable_cap_gb)


def _probe_driver_version(errors: list[str]) -> str | None:
    """NVIDIA driver version via a bounded ``nvidia-smi`` call (O1a).

    Best-effort by design: a missing binary, timeout, nonzero exit, or
    malformed output records one ``collection_errors`` entry and yields
    ``None`` — never a blocking dependency, never a fabricated value.
    Multi-GPU hosts return one line per device; the first line is taken
    (drivers are host-wide).
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_S,
        )
        if result.returncode != 0:
            errors.append(f"driver_version: nvidia-smi exit {result.returncode}")
            return None
        first = result.stdout.strip().splitlines()
        if not first or not first[0].strip():
            errors.append("driver_version: empty nvidia-smi output")
            return None
        return first[0].strip()
    except (OSError, subprocess.TimeoutExpired) as err:
        errors.append(f"driver_version: {type(err).__name__}: {err}")
        return None


def _probe_repo_commit(errors: list[str]) -> str | None:
    """``git rev-parse HEAD`` of the checkout containing this module (O1a)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_S,
            cwd=Path(__file__).resolve().parent,
        )
        if result.returncode != 0:
            errors.append(f"repo_commit: git exit {result.returncode}")
            return None
        commit = result.stdout.strip()
        return commit or None
    except (OSError, subprocess.TimeoutExpired) as err:
        errors.append(f"repo_commit: {type(err).__name__}: {err}")
        return None


def _normalize_uuid(raw: object) -> str | None:
    """Driver form ``GPU-<hex>``. torch reports the bare hex; nvidia-smi
    prefixes it. Normalizing here means the two sources compare equal
    instead of silently never matching."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return text if text.startswith(("GPU-", "MIG-")) else f"GPU-{text}"


def _physical_index_by_uuid(errors: list[str]) -> dict[str, int]:
    """UUID -> driver index, from ``nvidia-smi``.

    ``torch``'s index is the *logical* one: under
    ``CUDA_VISIBLE_DEVICES=2`` torch calls that device 0. The two orders
    are related only through the UUID, so the mapping is resolved by
    matching identities and never by assuming the orders agree.
    """
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_S,
            check=True,
        ).stdout
    except Exception as err:
        errors.append(f"physical_index_map: {type(err).__name__}: {err}")
        return {}
    mapping: dict[str, int] = {}
    for line in out.splitlines():
        parts = [c.strip() for c in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            idx = int(parts[0])
        except ValueError:
            continue
        uuid = _normalize_uuid(parts[1])
        if uuid:
            mapping[uuid] = idx
    return mapping


def _probe_devices(errors: list[str]) -> tuple[int | None, list[GpuDeviceProvenance]]:
    """Enumerate ALL visible CUDA devices in logical-index order (O1a)."""
    try:
        count = int(torch.cuda.device_count())
    except Exception as err:  # any torch failure is a recorded gap, never an abort
        errors.append(f"devices: device_count: {type(err).__name__}: {err}")
        return None, []
    devices: list[GpuDeviceProvenance] = []
    physical_by_uuid = _physical_index_by_uuid(errors) if count else {}
    for idx in range(count):
        try:
            props = torch.cuda.get_device_properties(idx)
            uuid = _normalize_uuid(getattr(props, "uuid", None))
            devices.append(
                GpuDeviceProvenance(
                    logical_index=idx,
                    name=props.name,
                    total_memory_bytes=int(props.total_memory),
                    compute_capability=(int(props.major), int(props.minor)),
                    uuid=uuid,
                    physical_index=physical_by_uuid.get(uuid) if uuid else None,
                )
            )
        except Exception as err:
            errors.append(f"devices[{idx}]: {type(err).__name__}: {err}")
    return count, devices


def discover() -> HardwareContext:
    """Build a ``HardwareContext`` from the current process's CUDA view.

    On GPU hosts: reads ``torch.cuda.get_device_properties(0)`` and populates
    every field. On CPU-only hosts (or ``torch.cuda.is_available()==False``):
    returns a stub with ``device_available=False`` and ``total_memory_bytes=0``.
    Consumers that require GPU must check ``device_available`` and early-return
    a CPU-mode verdict — the VRAM estimator does this today.

    O1a provenance fields are collected once here (no repeated probing —
    ``get_or_create`` reuses the stored manifest); every probe is
    individually wrapped so a failure records a ``collection_errors``
    entry instead of aborting.
    """
    now = datetime.now(UTC)
    hostname = socket.gethostname()
    torch_version = torch.__version__

    errors: list[str] = []
    plat = _platform_mod.platform()
    python_version = sys.version.split()[0]
    cuda_visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    repo_commit = _probe_repo_commit(errors)

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
            platform=plat,
            python_version=python_version,
            cuda_visible_devices=cuda_visible,
            visible_device_count=0,
            devices=[],
            driver_version=None,  # not probed on CPU-only hosts (no fabrication)
            repo_commit=repo_commit,
            collection_errors=errors,
        )

    props = torch.cuda.get_device_properties(0)
    visible_count, devices = _probe_devices(errors)
    driver_version = _probe_driver_version(errors)
    # Identity of the ACTIVE device (logical 0). Absent on hosts where the
    # driver or torch cannot report it — degraded, never fabricated.
    active_uuid = next((d.uuid for d in devices if d.logical_index == 0), None) or _normalize_uuid(
        getattr(props, "uuid", None)
    )
    return HardwareContext(
        active_device_uuid=active_uuid,
        hardware_fingerprint_version=2 if active_uuid else 1,
        device_name=props.name,
        total_memory_bytes=int(props.total_memory),
        compute_capability=(int(props.major), int(props.minor)),
        multiprocessor_count=int(props.multi_processor_count),
        cuda_runtime_version=torch.version.cuda,
        torch_version=torch_version,
        hostname=hostname,
        device_available=True,
        discovered_at=now,
        platform=plat,
        python_version=python_version,
        cuda_visible_devices=cuda_visible,
        visible_device_count=visible_count,
        devices=devices,
        driver_version=driver_version,
        repo_commit=repo_commit,
        collection_errors=errors,
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
