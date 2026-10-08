"""Bounded GPU evidence around one phase (V20 PR B, B-C2b).

Generic runtime infrastructure. It knows about a device, a child PID and
a clock, and nothing about TIDMAD, denoising, models or what a "phase"
means — the caller names the phase, this module never does.

**Why sampling has to happen while the child is alive.** The obvious
implementation takes one snapshot after a failure is observed. By then
the child has exited and the driver has reclaimed its memory, so the
candidate's own occupancy — the quantity attribution most depends on —
is already gone, and what remains is whatever the *other* side holds.
Every OOM would look like contention. So the observer samples during the
child's life and keeps four fixed slots, never a growing series.

**What it deliberately does not do.** No attribution (B-C3), no
admission (B-C4), no promotion of a successful run's measurement to
reusable evidence (that is PR C, per D-B5). It produces evidence and
stops.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_control.gpu_accounting import (
    DeviceBaselineSnapshot,
    DeviceIdentity,
    GpuAccountingSnapshot,
    sample,
    sample_device_baseline,
)

if TYPE_CHECKING:
    from core.runtime_control.gpu_protection import (
        GpuProtectionBinding,
        GpuProtectionReceipt,
        GpuRuntimeProtectionPolicy,
        TimedGpuObservation,
    )
    from core.runtime_control.process_control import (
        ProcessControlDecision,
        ProcessControlPolicy,
        ProcessLiveness,
    )


class GpuObservationPolicy(BaseModel):
    """How often to look, and how long to wait for the observer to stop.

    Typed configuration rather than constants inside the runner, per
    §1.4: cadence is *observation* policy. It is not admission policy and
    must not be co-located with the per-attempt or pair ceilings — those
    are a different category of value with different authority.

    The defaults are compatibility defaults, chosen from measurement: A5's
    training phase ran 8.0 s, so a fast opening window keeps a short
    phase from being described by a handful of samples, while a long
    phase does not go on paying that rate.
    """

    model_config = ConfigDict(frozen=True)

    #: Opening cadence — ~5 Hz.
    fast_interval_ms: int = Field(default=200, gt=0)
    #: How long the opening cadence lasts.
    fast_window_ms: int = Field(default=15_000, ge=0)
    #: Cadence thereafter — ~1 Hz.
    steady_interval_ms: int = Field(default=1_000, gt=0)
    #: How long the runner waits for the observer thread to stop. Bounded
    #: so telemetry can never hold up child cleanup.
    join_timeout_ms: int = Field(default=2_000, gt=0)

    def interval_ms_at(self, elapsed_ms: float) -> int:
        return (
            self.fast_interval_ms if elapsed_ms < self.fast_window_ms else self.steady_interval_ms
        )


class GpuEvidenceBundle(BaseModel):
    """Four snapshots and their coverage. Fixed size, whatever the runtime.

    ``observed_peak`` is the whole snapshot taken at maximum
    ``own_tree_mib`` — never a per-field maximum, which would compose a
    state the machine was never in and then reason about it.
    """

    model_config = ConfigDict(frozen=True)

    device: DeviceIdentity | None = None
    sampling_policy: GpuObservationPolicy | None = None

    baseline_before_spawn: DeviceBaselineSnapshot | None = None
    observed_peak: GpuAccountingSnapshot | None = None
    last_while_alive: GpuAccountingSnapshot | None = None
    post_failure: GpuAccountingSnapshot | None = None

    valid_sample_count: int = Field(default=0, ge=0)
    failed_sample_count: int = Field(default=0, ge=0)
    child_runtime_ms: float | None = Field(default=None, ge=0.0)
    first_valid_offset_ms: float | None = Field(default=None, ge=0.0)
    last_valid_offset_ms: float | None = Field(default=None, ge=0.0)

    #: Set when the observer thread did not stop within the join timeout.
    #: Recorded as a telemetry failure rather than allowed to delay the
    #: child's cleanup.
    observer_join_timed_out: bool = False
    #: Set when the observer itself raised. The child's own result is
    #: never affected by it — telemetry must not be able to fail the
    #: science it is watching.
    observer_error: str | None = None

    @property
    def coverage_is_thin(self) -> bool:
        """True when there is too little here to convict a candidate.

        ``observed_peak`` is a sampled lower bound, so B-C3 must not
        treat a thin bundle as authoritative demand — it yields
        ``unknown``, never candidate blame.
        """
        return self.valid_sample_count < 2 or self.observed_peak is None


class GpuPhaseObserver:
    """Samples one device on behalf of one child process.

    Not a general scheduler: it starts when the caller has a PID, stops
    when told, and holds four slots.
    """

    def __init__(
        self,
        device: DeviceIdentity | None,
        *,
        policy: GpuObservationPolicy | None = None,
        sampler: Any = None,
        baseline_sampler: Any = None,
        clock: Any = None,
        protection_policy: GpuRuntimeProtectionPolicy | None = None,
        protection_binding: GpuProtectionBinding | None = None,
        initial_observation: TimedGpuObservation | None = None,
    ) -> None:
        self._device = device
        self._policy = policy or GpuObservationPolicy()
        self._sample = sampler or sample
        self._sample_baseline = baseline_sampler or sample_device_baseline
        self._clock = clock or time.monotonic
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

        self._baseline: DeviceBaselineSnapshot | None = None
        self._peak: GpuAccountingSnapshot | None = None
        self._last_alive: GpuAccountingSnapshot | None = None
        self._post_failure: GpuAccountingSnapshot | None = None
        self._valid = 0
        self._failed = 0
        self._started_at: float | None = None
        self._first_offset: float | None = None
        self._last_offset: float | None = None
        self._runtime_ms: float | None = None
        self._join_timed_out = False
        self._error: str | None = None
        self._protection = None
        if any(
            value is not None
            for value in (protection_policy, protection_binding, initial_observation)
        ):
            if (
                protection_policy is None
                or protection_binding is None
                or initial_observation is None
            ):
                raise ValueError(
                    "protected observation requires policy, binding and initial observation"
                )
            if device is None or device != protection_binding.device:
                raise ValueError("observer device must match the protection binding")
            if policy is not None and policy != protection_policy.observation:
                raise ValueError("protected observation has one cadence policy")
            from core.runtime_control.gpu_protection_state import ProtectedGpuObservation

            self._policy = protection_policy.observation
            self._protection = ProtectedGpuObservation(
                protection_binding, protection_policy, initial_observation, self._clock
            )

    @property
    def enabled(self) -> bool:
        """False when no device identity was supplied.

        A missing identity means telemetry is unavailable, not that a
        device should be discovered — rediscovery here is how "GPU 0"
        gets assumed.
        """
        return self._device is not None

    def capture_baseline(self) -> None:
        """Before ``Popen``. Claims nothing about the candidate."""
        if self._protection is not None:
            if self._protection.receipt().effective_control is None:
                self._protection.abort("protected observation requires supervisor control")
                raise ValueError("protected observation requires the same observer as control")
            self.check_control()
            return
        device = self._device
        if device is None:
            return
        try:
            self._baseline = self._sample_baseline(device)
        except Exception as exc:  # pragma: no cover - defensive
            self._error = f"{type(exc).__name__}: {exc}"

    def start(self, child_pid: int) -> None:
        """After ``Popen``, once the child's PID exists."""
        if self._protection is not None:
            self._protection.start(child_pid)
        if not self.enabled or self._thread is not None:
            return
        self._started_at = self._clock()
        self._thread = threading.Thread(
            target=self._loop, args=(child_pid,), name="gpu-phase-observer", daemon=True
        )
        self._thread.start()

    def _record(self, snap: GpuAccountingSnapshot) -> None:
        if not snap.telemetry_available:
            self._failed += 1
            return
        self._valid += 1
        offset = (self._clock() - (self._started_at or 0.0)) * 1000.0
        if self._first_offset is None:
            self._first_offset = offset
        self._last_offset = offset
        self._last_alive = snap
        current = self._peak.own_tree_mib if self._peak else None
        if current is None or (snap.own_tree_mib or 0) > current:
            # The WHOLE snapshot at the maximum, not a per-field max.
            self._peak = snap

    def _loop(self, child_pid: int) -> None:
        device = self._device
        if device is None:  # pragma: no cover - start() never runs without one
            return
        try:
            while not self._stop.is_set():
                try:
                    if self._protection is not None:
                        self._protection.sample_once(self._sample)
                    else:
                        self._record(self._sample(child_pid, device))
                except Exception as exc:
                    if self._protection is not None:
                        self._protection.failed(f"GPU observer failed: {type(exc).__name__}: {exc}")
                        break
                    self._failed += 1
                elapsed_ms = (self._clock() - (self._started_at or 0.0)) * 1000.0
                interval = self._policy.interval_ms_at(elapsed_ms) / 1000.0
                if self._stop.wait(interval):
                    break
        except BaseException as exc:  # pragma: no cover - defensive
            self._error = f"{type(exc).__name__}: {exc}"
            if self._protection is not None:
                self._protection.failed(self._error)

    def stop(self, *, child_pid: int | None = None, failed: bool = False) -> None:
        """Stop sampling with a bounded join; a pending driver call may outlive it.

        A join timeout is recorded as a telemetry failure rather than
        waited out: the child's cleanup must not be held up by the thread
        watching it.
        """
        if self._protection is not None:
            self._protection.end()
            self._stop.set()
            thread = self._thread
            try:
                if thread is not None and thread.ident is not None:
                    thread.join(timeout=self._policy.join_timeout_ms / 1000.0)
            finally:
                self._protection.finish(join_timed_out=bool(thread and thread.is_alive()))
            return
        if self._started_at is not None:
            self._runtime_ms = (self._clock() - self._started_at) * 1000.0
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=self._policy.join_timeout_ms / 1000.0)
            if thread.is_alive():
                self._join_timed_out = True
        device = self._device
        if failed and device is not None and child_pid is not None:
            try:
                self._post_failure = self._sample(child_pid, device)
            except Exception as exc:
                self._error = self._error or f"{type(exc).__name__}: {exc}"

    def bundle(self) -> GpuEvidenceBundle:
        return GpuEvidenceBundle(
            device=self._device,
            sampling_policy=self._policy if self.enabled else None,
            baseline_before_spawn=self._baseline,
            observed_peak=self._peak,
            last_while_alive=self._last_alive,
            post_failure=self._post_failure,
            valid_sample_count=self._valid,
            failed_sample_count=self._failed,
            child_runtime_ms=self._runtime_ms,
            first_valid_offset_ms=self._first_offset,
            last_valid_offset_ms=self._last_offset,
            observer_join_timed_out=self._join_timed_out,
            observer_error=self._error,
        )

    def _protected(self):
        if self._protection is None:
            raise ValueError("observer has no explicitly selected GPU protection policy")
        return self._protection

    @property
    def control_policy(self) -> ProcessControlPolicy:
        return self._protected().policy.control

    def configure_control(self, effective: ProcessControlPolicy) -> None:
        self._protected().configure(effective)

    def check_control(self) -> ProcessControlDecision:
        thread = self._thread
        return self._protected().check(thread_alive=bool(thread and thread.is_alive()))

    def attach_process(self, process: ProcessLiveness) -> None:
        self._protected().attach(process)

    def mark_process_end(self) -> None:
        self.check_control()
        self._protected().end()
        self._stop.set()

    def abort_control(self, reason: str) -> None:
        self._protected().abort(reason)
        self._stop.set()

    def protection_receipt(self) -> GpuProtectionReceipt:
        return self._protected().receipt()
