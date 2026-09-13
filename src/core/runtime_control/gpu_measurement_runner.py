"""Launch the worker, watch the device, and join the two accounts per phase.

V20 PR C2 / C2-4.

Two independent observers produce a phase measurement and neither is
sufficient alone:

* the **worker** knows where its phases began and ended, and what its own
  allocator saw -- but it is blind to the CUDA context, to workspaces
  outside the caching allocator, and to any child it spawned;
* the **parent** sees driver-visible memory for the whole candidate tree --
  but has no idea which phase was running when.

So the parent samples continuously and the worker marks the boundaries, and
this module joins them **by wall-clock window**. That join is what makes a
requirement phase-specific rather than cumulative: `probe_production.py`
resets its peak once, in `_setup()`, so its figure is a running maximum
over setup + training + inference and can answer neither phase's question
(audit F2).

THE TWO FIGURES STAY IN SEPARATE FIELDS. `driver_tree_peak_mib` and
`allocator_peak_mib` are both recorded, both attributed to their source,
and never merged. The driver figure legitimately exceeds the allocator one
-- CUDA context, workspaces, other owned PIDs -- and averaging or
substituting either would destroy the only cross-check available.

WHEN THE WORKER LEAVES NO REPORT. A killed or reaped worker writes no
report, so there are no windows to join. The append-only journal still
records which phase was in flight, which is the difference between telling
an operator "the candidate OOMed during training" and "something failed".
The samples are retained either way -- raw, timestamped, unattributed.

THIS MODULE DOES NOT CLASSIFY. It reports what happened; deciding which
`PreflightOutcome` that is, and whether any of it carries authority, is
C2-5 reading this record.
"""

from __future__ import annotations

import contextlib
import json
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_control.gpu_accounting import DeviceIdentity, GpuAccountingSnapshot
from core.runtime_control.gpu_accounting import sample as sample_device
from core.runtime_control.gpu_measurement_identity import RealizedCandidateIdentity
from core.runtime_control.gpu_measurement_sampler import GpuTreeSampler, TreeMemorySample
from core.runtime_control.gpu_measurement_spec import (
    GpuMeasurementSpec,
    PhaseCompletion,
    PhaseStatus,
    RealismEvidence,
    WorkerMeasurementReport,
    WorkerStatus,
)
from core.runtime_control.gpu_requirement import (
    CandidateMeasurementRequest,
    MeasuredPhase,
    MeasurementDeadline,
    SamplingCoverage,
)
from core.runtime_control.process_group import (
    process_group_alive,
    signal_group,
    tree_rss_bytes,
)

#: Named so a record says which instrument produced each figure, and so the
#: two can never be read as interchangeable.
DRIVER_SOURCE = "gpu_accounting.sample(nvidia-smi):own_tree_mib"
ALLOCATOR_SOURCE = "torch.cuda.max_memory_allocated(in-worker)"


class ProcessEvidence(BaseModel):
    """How the worker process ended. Facts, not a verdict."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    worker_pid: int = Field(gt=0)
    worker_pgid: int = Field(gt=0)
    exit_code: int | None = None
    signal_number: int | None = None
    term_sent: bool = False
    kill_sent: bool = False
    #: Something in the group outlived the reap. It may still hold the
    #: device, so this is never silently ignored.
    orphans_remaining: bool = False


class HostMemoryBound(BaseModel):
    """What the host-memory ceiling observed -- present either way, so "it
    was fine" is recorded as explicitly as "it was not"."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    limit_bytes: int = Field(gt=0)
    peak_tree_rss_bytes: int = Field(default=0, ge=0)
    exceeded: bool = False

    @property
    def peak_tree_rss_gib(self) -> float:
        return round(self.peak_tree_rss_bytes / 1024**3, 3)


class PhaseMeasurement(BaseModel):
    """One phase, as both observers saw it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    phase: MeasuredPhase
    status: PhaseStatus
    started_at: float = Field(ge=0.0)
    ended_at: float = Field(ge=0.0)
    elapsed_seconds: float = Field(ge=0.0)

    #: The authority candidate. `None` means unobserved, not empty.
    driver_tree_peak_mib: int | None = Field(default=None, ge=0)
    driver_source: str = DRIVER_SOURCE
    #: Diagnostics. Per-process and allocator-visible; never the authority.
    allocator_peak_mib: int | None = Field(default=None, ge=0)
    allocator_reserved_peak_mib: int | None = Field(default=None, ge=0)
    allocator_source: str = ALLOCATOR_SOURCE

    coverage: SamplingCoverage
    own_pids: tuple[int, ...] = ()
    #: >1 proves a single-process figure would have under-read this phase.
    max_concurrent_own_processes: int = Field(default=0, ge=0)

    units_executed: int = Field(default=0, ge=0)
    units_requested: int = Field(default=0, ge=0)

    # ── observation evidence (D-C2-13/14) ────────────────────────────────
    # Carried through the TYPED result. Attempt 3 could only recover these
    # by reading the worker's private journal after the fact, which means
    # the artifact was incomplete and the result could not carry authority.
    repetitions: int = Field(default=1, ge=0)
    required_samples: int = Field(default=0, ge=0)
    observed_in_phase_samples: int = Field(default=0, ge=0)
    completion_reason: PhaseCompletion = "single_pass"
    max_phase_seconds: float | None = Field(default=None, gt=0.0)
    observation_bound_reached: bool = False
    sampler_ready: bool = True
    sampler_ready_at: float | None = Field(default=None, ge=0.0)
    detail: str = ""


class PrephaseMeasurementRun(BaseModel):
    """Everything one bounded pre-phase measurement established.

    Deliberately a record, not a verdict: C2-5 classifies it and C2-1
    decides authority. Keeping those apart is what lets an operator see the
    evidence that produced a refusal rather than only the refusal.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    request: CandidateMeasurementRequest

    #: `None` when the worker produced no structured report at all.
    worker_status: WorkerStatus | None = None
    report_present: bool = False
    observed_device_uuid: str | None = None
    device_name: str | None = None
    realism: RealismEvidence = Field(default_factory=RealismEvidence)
    #: What the worker actually built (D-C2-7). `None` when it never got
    #: far enough to say -- an unverified subject, not a smaller figure.
    realized_identity: RealizedCandidateIdentity | None = None
    #: The nonce the worker echoed. Compared against the request, so a
    #: stale or misrouted result cannot answer for this one.
    reported_request_id: str | None = None

    phases: tuple[PhaseMeasurement, ...] = ()
    #: From the journal, when the worker died without reporting: which
    #: phase was running. Distinguishes "OOMed during training" from
    #: "something failed".
    in_flight_phase: MeasuredPhase | None = None

    deadline: MeasurementDeadline
    #: The worker's own budget, carried so the classifier can report the
    #: deadline that ACTUALLY fired. A clean worker-side stop happens
    #: below the parent's deadline by construction, so reporting the
    #: parent's budget would produce a timeout claim whose elapsed time
    #: never reached it -- exactly the mislabelling C2-1's validator
    #: refuses.
    soft_deadline_seconds: float | None = Field(default=None, gt=0.0)
    host_memory: HostMemoryBound
    process: ProcessEvidence

    #: The raw series, retained. A peak with no samples behind it cannot be
    #: audited.
    samples: tuple[TreeMemorySample, ...] = ()
    journal: tuple[dict[str, Any], ...] = ()
    detail: str = ""

    def phase(self, phase: MeasuredPhase) -> PhaseMeasurement | None:
        return next((p for p in self.phases if p.phase == phase), None)

    @property
    def target(self) -> PhaseMeasurement | None:
        """The phase this run was asked to measure."""
        return self.phase(self.request.phase)


def run_prephase_measurement(
    spec: GpuMeasurementSpec,
    *,
    device: DeviceIdentity,
    poll_seconds: float = 0.05,
    grace_seconds: float = 10.0,
    command: list[str] | None = None,
    device_sampler: Callable[..., GpuAccountingSnapshot] = sample_device,
    clock: Callable[[], float] = time.time,
    elapsed_clock: Callable[[], float] = time.monotonic,
) -> PrephaseMeasurementRun:
    """Run one bounded measurement and return what it established.

    `device` is required, not derived from `request.device_uuid`. Building
    one from a UUID alone would mean guessing `physical_index`, and
    `gpu_accounting` is explicit that a degraded identity is never repaired
    by guessing: device 0 would silently conflate two cards of the same
    model, and every measurement attributed to the wrong one would look
    perfectly valid. The caller holds what discovery produced.

    `command` is injectable so tests can drive deterministic fake workers --
    one that reports cleanly, one that never exits, one that dies mid-phase
    -- with no GPU and no torch.

    Never raises for anything it can observe. A launch failure, a hung
    worker and a crashed worker are all recorded outcomes.
    """
    result_path = Path(spec.result_path)
    spec_path = result_path.with_suffix(".spec.json")
    log_path = result_path.with_suffix(".worker.log")
    result_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(spec.model_dump_json(indent=1), encoding="utf-8")

    # `command` is the interpreter prefix only; the spec path is always
    # appended. An injected command that could omit it would be testing a
    # worker with different inputs from the production one.
    # D-C2-13. The worker waits for this before opening a timed phase, and
    # it is touched ONLY after a real driver sample succeeds -- so "sampling
    # is active" is evidence, not a promise. Stale markers from an earlier
    # run would defeat that, so it is removed first.
    ready_path = Path(spec.sampler_ready_path) if spec.sampler_ready_path else None
    if ready_path is not None and ready_path.exists():
        ready_path.unlink()
    # D-C2-14. The parent ends the phase, because the parent is the only
    # component that knows how many valid in-phase samples actually landed.
    complete_path = Path(spec.phase_complete_path) if spec.phase_complete_path else None
    if complete_path is not None and complete_path.exists():
        complete_path.unlink()
    journal_path = Path(spec.journal_path)

    argv = [
        *(command or [sys.executable, "-m", "core.runtime_control.gpu_measurement_worker_main"]),
        str(spec_path),
    ]
    deadline_seconds = spec.request.deadline_seconds
    started = elapsed_clock()
    log_handle = log_path.open("w", encoding="utf-8")
    try:
        # The worker is a CLEAN process: it rebuilds the plugin registry
        # from the transported directories, never from inherited parent
        # memory. Spawning with no `env=` is what made every
        # agent-generated candidate CONFIG_REJECTED in V20 attempt 2 —
        # the parent's own environment carries no SIDERIUS_PLUGIN_DIRS,
        # because that variable is built per-sandbox for its children.
        from core.local_code.child import prepare_child
        from core.subprocess_env import subprocess_env

        invocation = prepare_child(
            argv, subprocess_env(plugin_dir=spec.plugin_dir, loss_dir=spec.loss_dir)
        )
        process = subprocess.Popen(
            invocation.argv,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # own group: a kill reaches descendants
            env=invocation.env,
        )
    except Exception as exc:
        log_handle.close()
        from core.local_code.failure import raise_if_code_package_failure

        raise_if_code_package_failure(exc)
        return _launch_failure(spec, deadline_seconds, exc)

    pgid = process.pid  # session leader, so pgid == pid
    sampler = GpuTreeSampler(
        pgid,
        device,
        interval_seconds=spec.request.sampling_interval_seconds,
        device_sampler=device_sampler,
        clock=clock,
    )
    # No opening `force` here: `poll()` always samples on its first call,
    # so the loop below opens the watch on its first iteration. A forced
    # sample here was redundant, and a mutation proved no test could
    # justify it.
    peak_rss = 0
    host_exceeded = False
    term_sent = kill_sent = False

    while process.poll() is None:
        elapsed = elapsed_clock() - started
        rss = tree_rss_bytes(pgid)
        peak_rss = max(peak_rss, rss)
        taken = sampler.poll()
        if (
            ready_path is not None
            and not ready_path.exists()
            and taken is not None
            and taken.telemetry_available
        ):
            # A SUCCESSFUL sample, not merely an attempted one: a failing
            # driver query proves nothing is being observed.
            ready_path.parent.mkdir(parents=True, exist_ok=True)
            ready_path.touch()

        if complete_path is not None and not complete_path.exists():
            # Count only samples inside the OPEN phase window, read from
            # the journal the worker flushes as it crosses the boundary.
            # Samples before the phase opened describe a different phase.
            opened_at = _phase_opened_at(journal_path, spec.phase)
            if opened_at is not None:
                in_phase = sum(
                    1
                    for s in sampler.samples
                    if s.at >= opened_at and s.telemetry_available and s.own_tree_mib is not None
                )
                if in_phase >= spec.min_authoritative_samples:
                    complete_path.parent.mkdir(parents=True, exist_ok=True)
                    complete_path.touch()

        # RSS is bounded by the parent because the worker cannot bound
        # itself: RLIMIT_AS caps ADDRESS SPACE, and torch plus CUDA reserve
        # ~19 GiB of it while holding under 1 GiB resident.
        if rss >= spec.worker_memory_limit_bytes:
            host_exceeded = True
        if host_exceeded or elapsed >= deadline_seconds:
            term_sent = signal_group(pgid, signal.SIGTERM)
            grace_until = elapsed_clock() + grace_seconds
            while process.poll() is None and elapsed_clock() < grace_until:
                sampler.poll()
                time.sleep(poll_seconds)
            if process.poll() is None:
                kill_sent = signal_group(pgid, signal.SIGKILL)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=grace_seconds)
            break
        time.sleep(poll_seconds)

    # One last look before the tree is gone: memory held at the very end
    # would otherwise fall outside the watch.
    sampler.poll(force=True)
    sampler.stop()
    elapsed = round(elapsed_clock() - started, 3)
    log_handle.close()

    returncode = process.returncode
    invocation.check(returncode)
    report = _load_report(result_path)
    journal = _load_journal(Path(spec.journal_path))

    phases: list[PhaseMeasurement] = []
    if report is not None:
        for phase_report in report.phases:
            window = sampler.measure_window(phase_report.started_at, phase_report.ended_at)
            phases.append(
                PhaseMeasurement(
                    phase=phase_report.phase,
                    status=phase_report.status,
                    started_at=phase_report.started_at,
                    ended_at=phase_report.ended_at,
                    elapsed_seconds=phase_report.elapsed_seconds,
                    driver_tree_peak_mib=window.driver_tree_peak_mib,
                    allocator_peak_mib=phase_report.allocator_peak_mib,
                    allocator_reserved_peak_mib=phase_report.allocator_reserved_peak_mib,
                    coverage=window.coverage,
                    own_pids=window.own_pids,
                    max_concurrent_own_processes=window.max_concurrent_own_processes,
                    units_executed=phase_report.units_executed,
                    units_requested=phase_report.units_requested,
                    repetitions=phase_report.repetitions,
                    required_samples=phase_report.required_samples,
                    observed_in_phase_samples=window.coverage.samples_taken,
                    completion_reason=phase_report.completion_reason,
                    max_phase_seconds=phase_report.max_phase_seconds,
                    observation_bound_reached=phase_report.observation_bound_reached,
                    sampler_ready=phase_report.sampler_ready,
                    sampler_ready_at=phase_report.sampler_ready_at,
                    detail=phase_report.detail,
                )
            )

    return PrephaseMeasurementRun(
        label=spec.label,
        request=spec.request,
        worker_status=report.status if report is not None else None,
        report_present=report is not None,
        observed_device_uuid=report.observed_device_uuid if report is not None else None,
        device_name=report.device_name if report is not None else None,
        realism=report.realism if report is not None else RealismEvidence(),
        realized_identity=report.realized_identity if report is not None else None,
        reported_request_id=(report.request_id or None) if report is not None else None,
        phases=tuple(phases),
        in_flight_phase=_in_flight_phase(journal) if report is None else None,
        deadline=MeasurementDeadline(budget_seconds=deadline_seconds, elapsed_seconds=elapsed),
        soft_deadline_seconds=spec.soft_deadline_seconds,
        host_memory=HostMemoryBound(
            limit_bytes=spec.worker_memory_limit_bytes,
            peak_tree_rss_bytes=peak_rss,
            exceeded=host_exceeded,
        ),
        process=ProcessEvidence(
            worker_pid=process.pid,
            worker_pgid=pgid,
            exit_code=returncode,
            signal_number=-returncode if returncode is not None and returncode < 0 else None,
            term_sent=term_sent,
            kill_sent=kill_sent,
            orphans_remaining=process_group_alive(pgid),
        ),
        samples=sampler.samples,
        journal=journal,
        detail=report.detail if report is not None else _log_tail(log_path),
    )


def _launch_failure(
    spec: GpuMeasurementSpec, deadline_seconds: float, exc: BaseException
) -> PrephaseMeasurementRun:
    """The worker never started. There is no PID, no tree and no window --
    so the record says exactly that rather than inventing an empty one."""
    return PrephaseMeasurementRun(
        label=spec.label,
        request=spec.request,
        report_present=False,
        deadline=MeasurementDeadline(budget_seconds=deadline_seconds, elapsed_seconds=0.0),
        host_memory=HostMemoryBound(limit_bytes=spec.worker_memory_limit_bytes),
        process=ProcessEvidence(worker_pid=1, worker_pgid=1, exit_code=None),
        detail=f"could not launch the measurement worker: {exc!r}",
    )


def _phase_opened_at(journal_path: Path, phase: str) -> float | None:
    """When the worker opened `phase`, or `None` if it has not yet.

    Read from the append-only journal the worker flushes at every
    boundary, so the parent learns the window start without a second
    channel. A phase that has already ended returns `None`: counting
    samples for a closed window could signal completion after the fact.
    """
    opened: float | None = None
    for entry in _load_journal(journal_path):
        if entry.get("phase") != phase:
            continue
        if entry.get("event") == "phase_start":
            at = entry.get("at")
            opened = float(at) if isinstance(at, (int, float)) else None
        elif entry.get("event") == "phase_end":
            opened = None
    return opened


def _load_report(path: Path) -> WorkerMeasurementReport | None:
    """The worker's report, or `None`. A malformed report is no report:
    half a measurement must never be read as a whole one."""
    try:
        return WorkerMeasurementReport(**json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return None


def _load_journal(path: Path) -> tuple[dict[str, Any], ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    events: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            # A torn final line is what a killed worker leaves behind.
            continue
        if isinstance(entry, dict):
            events.append(entry)
    return tuple(events)


def _in_flight_phase(journal: tuple[dict[str, Any], ...]) -> MeasuredPhase | None:
    """The phase that started and never ended.

    Only meaningful when there is no report. It is the whole reason the
    journal is flushed as it goes.
    """
    open_phase: MeasuredPhase | None = None
    for entry in journal:
        phase = entry.get("phase")
        if phase not in ("setup", "training", "inference"):
            continue
        if entry.get("event") == "phase_start":
            open_phase = phase
        elif entry.get("event") == "phase_end" and open_phase == phase:
            open_phase = None
    return open_phase


def _log_tail(path: Path, limit: int = 400) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()[-limit:]
    except OSError:
        return ""
