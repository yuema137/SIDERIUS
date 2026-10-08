"""Fixed-size protected observation state; no signalling or second sampler."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Literal

from core.runtime_control.gpu_accounting import GpuAccountingSnapshot
from core.runtime_control.gpu_protection import (
    GpuProtectionBinding,
    GpuProtectionReceipt,
    GpuRuntimeProtectionPolicy,
    TimedGpuObservation,
    observation_refusal,
    protection_mechanism_digest,
)
from core.runtime_control.process_control import (
    ProcessControlDecision,
    ProcessControlPolicy,
    ProcessLiveness,
)


class ProtectedGpuObservation:
    """The observer's protected state. All blocking work stays outside its lock."""

    def __init__(
        self,
        binding: GpuProtectionBinding,
        policy: GpuRuntimeProtectionPolicy,
        initial: TimedGpuObservation,
        clock: Callable[[], float],
    ) -> None:
        self.binding, self.policy, self.initial = binding, policy, initial
        self.clock = clock
        self._digest = protection_mechanism_digest()
        self._lock = threading.Lock()
        self._state: Literal["prepared", "running", "stopping", "frozen"] = "prepared"
        self._effective: ProcessControlPolicy | None = None
        self._process: ProcessLiveness | None = None
        self._pid: int | None = None
        self._started: float | None = None
        self._ended: float | None = None
        self._latest: TimedGpuObservation | None = None
        self._live: TimedGpuObservation | None = None
        self._stop_observation: TimedGpuObservation | None = None
        self._decision = ProcessControlDecision(
            status="continue",
            binding_token=binding.attempt_token,
            sequence=initial.sequence,
            reason="GPU observation is usable",
        )
        self._count = 0
        self._valid = 0
        self._join_timeout = False
        self._check_coverage(clock())

    def _latch(self, reason: str, observation: TimedGpuObservation | None = None) -> None:
        if self._decision.status == "stop":
            return
        self._decision = ProcessControlDecision(
            status="stop",
            binding_token=self.binding.attempt_token,
            sequence=observation.sequence if observation else self.initial.sequence + self._count,
            reason=reason,
        )
        self._stop_observation = observation

    def _check_coverage(self, now: float) -> None:
        observation = self._live or self.initial
        reason = observation_refusal(observation, self.binding, self.policy, now=now)
        if reason:
            self._latch(reason, observation)

    def configure(self, effective: ProcessControlPolicy) -> None:
        with self._lock:
            if self._state != "prepared" or self._effective is not None:
                raise ValueError("protected observer is single-use")
            self._effective = effective

    def attach(self, process: ProcessLiveness) -> None:
        pid = process.pid
        with self._lock:
            if self._state != "prepared" or self._process is not None:
                raise ValueError("protected observer is single-use")
            self._process, self._pid = process, pid

    def start(self, pid: int) -> None:
        now = self.clock()
        with self._lock:
            if self._state != "prepared" or self._process is None or pid != self._pid:
                raise ValueError("protected observer requires its supervisor's actual child")
            self._state, self._started = "running", now

    def check(self, *, thread_alive: bool) -> ProcessControlDecision:
        with self._lock:
            # Read the local monotonic clock with the slot: a sample published
            # while this thread awaited the lock must not look future-dated.
            now = self.clock()
            if self._state != "frozen":
                self._check_coverage(self._ended if self._ended is not None else now)
                if self._state == "running" and not thread_alive:
                    self._latch("GPU observation thread is not running")
            return self._decision

    def end(self) -> None:
        with self._lock:
            now = self.clock()
            if self._state in {"frozen", "stopping"}:
                return
            self._ended = now
            self._state = "stopping"
            self._check_coverage(now)

    def abort(self, reason: str) -> None:
        """Pre-spawn/package failure: freeze without pretending a child existed."""
        with self._lock:
            if self._state == "frozen":
                return
            self._latch(reason)
            self._state = "frozen"

    def finish(self, *, join_timed_out: bool) -> None:
        with self._lock:
            if self._state == "frozen":
                return
            if not self._valid:
                self._latch("no successful GPU observation was bracketed by a live child")
            if join_timed_out:
                self._join_timeout = True
                self._latch("GPU observer did not join within its selected bound")
            self._state = "frozen"

    def failed(self, reason: str) -> None:
        with self._lock:
            if self._state != "frozen":
                self._latch(reason)

    def sample_once(self, sampler: Callable[..., GpuAccountingSnapshot]) -> None:
        with self._lock:
            if self._state != "running":
                return
            process = self._process
            sequence = self.initial.sequence + self._count + 1
        assert process is not None
        started = self.clock()
        # No lock across liveness, driver calls, or user-injected test samplers.
        live_before = process.poll() is None
        if not live_before:
            self.end()
            return
        try:
            snapshot = sampler(process.pid, self.binding.device)
            error = None
        except Exception as exc:
            snapshot, error = None, f"{type(exc).__name__}: {exc}"
        completed = self.clock()
        live_after = process.poll() is None
        observation = TimedGpuObservation(
            sequence=sequence,
            query_started_at=started,
            query_completed_at=completed,
            snapshot=snapshot,
            sampling_error=error,
        )
        with self._lock:
            if self._state == "frozen":
                return
            # Publication can wait behind another state operation. Use the
            # actual commit time, not a timestamp captured before that wait.
            now = self.clock()
            if not live_after and self._ended is None:
                self._ended, self._state = now, "stopping"
            # Check OLD accepted coverage before renewal, including delayed threads.
            self._check_coverage(self._ended if self._ended is not None else now)
            self._count += 1
            self._latest = observation
            reason = observation_refusal(
                observation, self.binding, self.policy, now=now, coverage_ends_at=self._ended
            )
            if reason:
                self._latch(reason, observation)
            elif live_after and self._state == "running":
                self._live = observation
                self._valid += 1

    def receipt(self) -> GpuProtectionReceipt:
        with self._lock:
            return GpuProtectionReceipt(
                binding=self.binding,
                policy=self.policy,
                effective_control=self._effective,
                mechanism_sha256=self._digest,
                state=self._state,
                initial=self.initial,
                latest=self._latest,
                last_live=self._live,
                first_stop_observation=self._stop_observation,
                decision=self._decision,
                valid_live_samples=self._valid,
                observations=self._count,
                child_pid=self._pid,
                started_at=self._started,
                ended_at=self._ended,
                join_timed_out=self._join_timeout,
            )
