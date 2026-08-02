"""Driver-visible GPU occupancy, per device, attributed to a process tree.

V20 PR B, commit B-C1. Generic runtime infrastructure: this module knows
about processes and devices, and nothing about TIDMAD, denoising,
models, batches or training phases. It must never import a task module.

**Why a new primitive rather than reuse.** Two nearby helpers exist and
neither answers this question:

``probe.py:capture_contention_snapshot`` samples the device total and
the compute-app *PIDs*, but not their memory, so it cannot attribute
occupancy to anyone. It also takes ``.splitlines()[0]`` of the device
query, which silently means "the first GPU" on a multi-GPU host, and it
names a GiB quantity ``gpu_memory_used_gb``.

``probe_subprocess.py:sample_worker_vram_gb`` does read per-PID memory,
but keys ownership on the process *group* — which misses a child started
with ``start_new_session=True``, exactly what the pre-flight worker is
(``isolated_probe.py``) — and returns ``None`` when the total is zero,
collapsing "held nothing" with "could not measure". For a memory guard
those must stay distinguishable.

So the sampling shape is borrowed (one bounded subprocess call, any
failure becomes an explicit gap) and the accounting is new.

**Units.** Every quantity is MiB and every field says so. A ``_gb`` field
holding GiB is how the existing code reads today, and unit-lying names
in a memory-safety module are worth one extra character to avoid.

**A gap is never a zero.** When telemetry fails, quantities are ``None``
and ``telemetry_available`` is ``False``. A caller that treats a failed
sample as "nothing is held" would admit work onto a full device.
"""

from __future__ import annotations

import subprocess
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: How far up the ppid chain ownership is traced. Deep enough for the
#: parent -> executor -> child shapes here, bounded so a cycle or a
#: pathological tree cannot spin.
_MAX_ANCESTRY_HOPS = 24

#: Bounds the nvidia-smi call so a hung driver query cannot delay a
#: phase launch. The caller is on the critical path.
_QUERY_TIMEOUT_S = 10.0


class DeviceIdentity(BaseModel):
    """Which accelerator a sample is about.

    Required rather than optional, and UUID-keyed rather than
    index-keyed, because an index is not a stable name for a device: a
    logical index under ``CUDA_VISIBLE_DEVICES`` need not be the
    physical one, and "device 0" means different hardware on different
    hosts. A snapshot that cannot say which device it describes cannot
    be compared with another one.
    """

    model_config = ConfigDict(frozen=True)

    #: Primary key. Stable across reboots and independent of ordering.
    uuid: str = Field(min_length=1)
    #: Physical index as the driver reports it.
    physical_index: int = Field(ge=0)
    #: Index inside ``CUDA_VISIBLE_DEVICES``, when the caller is running
    #: under one. ``None`` when the mapping is not known to the caller.
    logical_index: int | None = Field(default=None, ge=0)
    #: The variable as this process sees it, captured verbatim so a
    #: later reader can reconstruct the mapping.
    cuda_visible_devices: str | None = None
    #: Which telemetry produced the sample. ``nvidia-smi`` availability
    #: is a discovered fact, not a property of the framework.
    telemetry_backend: str = Field(default="nvidia-smi", min_length=1)


class ProcessOccupancy(BaseModel):
    """One compute process's driver-visible memory on one device."""

    model_config = ConfigDict(frozen=True)

    pid: int = Field(gt=0)
    used_mib: int = Field(ge=0)


class DeviceBaselineSnapshot(BaseModel):
    """Device state **before** a candidate process exists.

    Deliberately a different type from ``GpuAccountingSnapshot``, and
    deliberately without an ``own_tree_mib`` field: before ``Popen``
    there is no child PID, so no ownership split is possible, and a
    model that cannot express candidate ownership cannot accidentally
    claim it.

    The alternative — reusing the attributed snapshot with
    ``own_tree_mib=0`` — would conflate "the candidate holds nothing"
    with "the candidate does not exist yet", which is precisely the
    distinction a later attribution decision rests on.

    Substituting the *parent* PID is equally wrong: the parent has other
    descendants (the pre-flight worker, a concurrent scoring process),
    and counting those as the candidate's would inflate the number
    attribution depends on.
    """

    model_config = ConfigDict(frozen=True)

    device: DeviceIdentity
    telemetry_available: bool
    sampled_at: float = Field(ge=0.0)

    device_used_mib: int | None = Field(default=None, ge=0)
    device_total_mib: int | None = Field(default=None, ge=0)
    #: What the candidate will have to fit into.
    device_free_mib: int | None = Field(default=None, ge=0)
    #: Every compute process already on the device, with its usage.
    processes: tuple[ProcessOccupancy, ...] = ()
    process_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _a_gap_is_not_a_zero(self) -> DeviceBaselineSnapshot:
        if self.telemetry_available:
            return self
        populated = [
            name
            for name in (
                "device_used_mib",
                "device_total_mib",
                "device_free_mib",
                "process_count",
            )
            if getattr(self, name) is not None
        ]
        if populated or self.processes:
            raise ValueError(
                f"telemetry_available=False but {sorted(populated)} are populated. "
                "An unmeasured baseline must stay None: reading it as an empty "
                "device would admit work onto a device nobody looked at."
            )
        return self


class GpuAccountingSnapshot(BaseModel):
    """Driver-visible occupancy on one device at one instant.

    Occupancy is split into *ours* and *everything else*. There is
    deliberately no notion of a named peer: a headroom decision needs to
    know how much is free, not who is holding it, and inferring peer
    identity would require cross-process coordination this module does
    not have (PR B design, D-B1).
    """

    model_config = ConfigDict(frozen=True)

    device: DeviceIdentity
    #: False when the sample could not be taken. Every quantity below is
    #: then ``None``, and the caller must not read that as "nothing".
    telemetry_available: bool

    device_used_mib: int | None = Field(default=None, ge=0)
    device_total_mib: int | None = Field(default=None, ge=0)

    #: Summed over processes whose ancestry reaches ``root_pid``.
    own_tree_mib: int | None = Field(default=None, ge=0)
    own_processes: tuple[ProcessOccupancy, ...] = ()

    #: Everything on this device that is not ours. Clamped at 0 for the
    #: decision; ``accounting_skew_mib`` is where the clamp is visible.
    other_mib: int | None = Field(default=None, ge=0)
    other_process_count: int | None = Field(default=None, ge=0)

    #: Sum over every compute process the driver listed for this device.
    per_pid_total_mib: int | None = Field(default=None, ge=0)
    #: Device usage the per-process listing does not account for —
    #: context overhead, graphics clients, processes owned by another
    #: user. Clamped at 0.
    unattributed_mib: int | None = Field(default=None, ge=0)
    #: ``device_used_mib - per_pid_total_mib``, **signed**. A negative
    #: value is a real transient the driver can report, and clamping it
    #: away would hide the fact that the two accounts disagree.
    accounting_skew_mib: int | None = None

    @model_validator(mode="after")
    def _a_gap_is_not_a_zero(self) -> GpuAccountingSnapshot:
        """Unavailable telemetry may not carry numbers.

        The failure mode this prevents is a snapshot that reports
        ``own_tree_mib=0`` because nothing could be measured, which a
        headroom check would read as an empty device.
        """
        if self.telemetry_available:
            return self
        populated = [
            name
            for name in (
                "device_used_mib",
                "device_total_mib",
                "own_tree_mib",
                "other_mib",
                "other_process_count",
                "per_pid_total_mib",
                "unattributed_mib",
                "accounting_skew_mib",
            )
            if getattr(self, name) is not None
        ]
        if populated or self.own_processes:
            raise ValueError(
                "telemetry_available=False but "
                f"{sorted([*populated, *(['own_processes'] if self.own_processes else [])])} "
                "are populated. An unmeasured quantity must stay None: a "
                "caller that reads a failed sample as zero would admit "
                "work onto a device it never looked at."
            )
        return self


def _run_query(fields: str, kind: str, *, runner: Any = None) -> list[list[str]] | None:
    """One bounded nvidia-smi query, or ``None`` if it cannot be taken."""
    run = runner or subprocess.run
    try:
        completed = run(
            ["nvidia-smi", f"--query-{kind}={fields}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT_S,
            check=True,
        )
    except Exception:
        return None
    out = getattr(completed, "stdout", None)
    if not isinstance(out, str):
        return None
    return [[c.strip() for c in line.split(",")] for line in out.splitlines() if line.strip()]


def _ppid_of(pid: int, *, proc_reader: Any = None) -> int | None:
    read = proc_reader or _read_proc_status
    text = read(pid)
    if text is None:
        return None
    for line in text.splitlines():
        if line.startswith("PPid:"):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return None
    return None


def _read_proc_status(pid: int) -> str | None:
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def is_descendant_of(pid: int, root_pid: int, *, proc_reader: Any = None) -> bool:
    """Whether ``root_pid`` appears in ``pid``'s ancestry.

    Ancestry, not session or process group: a child started with
    ``start_new_session=True`` leads its own session, so a session test
    would fail to claim it — and its memory would go uncounted in the
    very total this module exists to produce.

    A PID that exits mid-walk simply stops being claimable; that is a
    dropped row, not an error.
    """
    if pid <= 0 or root_pid <= 0:
        return False
    current = pid
    for _ in range(_MAX_ANCESTRY_HOPS):
        if current == root_pid:
            return True
        if current <= 1:
            return False
        parent = _ppid_of(current, proc_reader=proc_reader)
        if parent is None:
            return False
        current = parent
    return False


def _unavailable(device: DeviceIdentity) -> GpuAccountingSnapshot:
    return GpuAccountingSnapshot(device=device, telemetry_available=False)


def sample(
    root_pid: int,
    device: DeviceIdentity,
    *,
    runner: Any = None,
    proc_reader: Any = None,
) -> GpuAccountingSnapshot:
    """Driver-visible occupancy on ``device``, split by ownership.

    Args:
        root_pid: processes whose ancestry reaches this PID are "ours".
        device: which accelerator to account for. Rows belonging to any
            other device are ignored, never summed in — occupancy on a
            second GPU is not headroom on this one.
        runner: injection seam for ``subprocess.run`` (tests).
        proc_reader: injection seam for reading ``/proc/<pid>/status``.

    Returns:
        A snapshot for exactly one device. If the requested UUID is not
        present in the driver's listing, the result is *unavailable*
        rather than a substituted device — answering about the wrong
        GPU is worse than not answering.
    """
    gpu_rows = _run_query("index,uuid,memory.used,memory.total", "gpu", runner=runner)
    if gpu_rows is None:
        return _unavailable(device)

    matched: list[str] | None = None
    for row in gpu_rows:
        if len(row) >= 4 and row[1] == device.uuid:
            matched = row
            break
    if matched is None:
        # Never fall back to the first row: on a multi-GPU host that is
        # a different device wearing the right shape.
        return _unavailable(device)

    try:
        device_used_mib = int(float(matched[2]))
        device_total_mib = int(float(matched[3]))
    except (ValueError, IndexError):
        return _unavailable(device)

    app_rows = _run_query("pid,used_gpu_memory,gpu_uuid", "compute-apps", runner=runner)
    if app_rows is None:
        return _unavailable(device)

    own: list[ProcessOccupancy] = []
    per_pid_total = 0
    other_total = 0
    other_count = 0
    for row in app_rows:
        if len(row) < 3 or row[2] != device.uuid:
            continue
        try:
            pid = int(row[0])
            used = int(float(row[1]))
        except ValueError:
            continue
        if pid <= 0 or used < 0:
            continue
        per_pid_total += used
        if is_descendant_of(pid, root_pid, proc_reader=proc_reader):
            own.append(ProcessOccupancy(pid=pid, used_mib=used))
        else:
            other_total += used
            other_count += 1

    own_total = sum(p.used_mib for p in own)
    skew = device_used_mib - per_pid_total

    return GpuAccountingSnapshot(
        device=device,
        telemetry_available=True,
        device_used_mib=device_used_mib,
        device_total_mib=device_total_mib,
        own_tree_mib=own_total,
        own_processes=tuple(own),
        other_mib=other_total,
        other_process_count=other_count,
        per_pid_total_mib=per_pid_total,
        unattributed_mib=max(0, skew),
        accounting_skew_mib=skew,
    )


def sample_device_baseline(
    device: DeviceIdentity,
    *,
    runner: Any = None,
    clock: Any = None,
) -> DeviceBaselineSnapshot:
    """Device occupancy before a candidate exists (B-C2b baseline slot).

    Says what is already on the device and how much room is left. Makes
    no claim about the candidate, which has not been started yet.
    """
    import time as _time

    now = float((clock or _time.time)())

    gpu_rows = _run_query("index,uuid,memory.used,memory.total", "gpu", runner=runner)
    if gpu_rows is None:
        return DeviceBaselineSnapshot(device=device, telemetry_available=False, sampled_at=now)

    matched = next((r for r in gpu_rows if len(r) >= 4 and r[1] == device.uuid), None)
    if matched is None:
        # Never fall back to the first row: on a multi-GPU host that is a
        # different device wearing the right shape.
        return DeviceBaselineSnapshot(device=device, telemetry_available=False, sampled_at=now)
    try:
        used = int(float(matched[2]))
        total = int(float(matched[3]))
    except (ValueError, IndexError):
        return DeviceBaselineSnapshot(device=device, telemetry_available=False, sampled_at=now)

    app_rows = _run_query("pid,used_gpu_memory,gpu_uuid", "compute-apps", runner=runner)
    if app_rows is None:
        return DeviceBaselineSnapshot(device=device, telemetry_available=False, sampled_at=now)

    present: list[ProcessOccupancy] = []
    for row in app_rows:
        if len(row) < 3 or row[2] != device.uuid:
            continue
        try:
            pid, mib = int(row[0]), int(float(row[1]))
        except ValueError:
            continue
        if pid > 0 and mib >= 0:
            present.append(ProcessOccupancy(pid=pid, used_mib=mib))

    return DeviceBaselineSnapshot(
        device=device,
        telemetry_available=True,
        sampled_at=now,
        device_used_mib=used,
        device_total_mib=total,
        device_free_mib=max(0, total - used),
        processes=tuple(present),
        process_count=len(present),
    )


def device_identity_from_hardware(hardware: Any) -> DeviceIdentity | None:
    """The one adapter from a discovered hardware record to an identity.

    Deliberately the *only* translation point, so a second GPU identity
    schema cannot appear alongside this one.

    Returns ``None`` — meaning telemetry unavailable — when the record
    carries no UUID: a CPU-only host, a manifest written before UUIDs
    were recorded, or a discovery that could not read one. **A degraded
    identity is never repaired by guessing**: filling in device 0, or
    keying on the device name, would silently conflate two cards of the
    same model, and every measurement attributed to the wrong one would
    look perfectly valid.
    """
    uuid = getattr(hardware, "active_device_uuid", None)
    if not uuid:
        return None

    physical = None
    logical = None
    for dev in getattr(hardware, "devices", None) or ():
        if getattr(dev, "uuid", None) == uuid:
            physical = getattr(dev, "physical_index", None)
            logical = getattr(dev, "logical_index", None)
            break
    if physical is None:
        # The driver index is unknown; the UUID still identifies the
        # device, which is what actually matters. Fall back to the
        # logical index only as a descriptive value.
        physical = logical if logical is not None else 0

    return DeviceIdentity(
        uuid=str(uuid),
        physical_index=int(physical),
        logical_index=int(logical) if logical is not None else None,
        cuda_visible_devices=getattr(hardware, "cuda_visible_devices", None),
    )
