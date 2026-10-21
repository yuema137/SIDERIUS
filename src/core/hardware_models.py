"""Pure hardware evidence schemas; importing these never discovers devices.

Runtime discovery and manifest I/O remain in core.hardware_context, which
re-exports these classes for existing callers. JSON fields and cap arithmetic
are shared, not duplicated in offline setup review.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_SAFETY_FRACTION: float = 0.80
TorchGpuBackend = Literal["cuda", "rocm", "none"]


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


class GpuRuntimeFacts(BaseModel):
    """Fresh observation plus implemented capabilities, never launch permission."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    installed_backend: TorchGpuBackend
    runtime_version: str | None
    hardware: HardwareContext
    implemented_accounting_adapter: Literal["nvidia-smi"] | None
    limitations: tuple[str, ...]
