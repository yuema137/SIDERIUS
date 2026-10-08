"""Typed runtime GPU protection evidence and its pure sample decision.

This is sampled environment protection, not a physical partition or proof of
unseen peaks. The caller supplies admission's resolved ceiling and device.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.planner_strategy_identity import source_fingerprint
from core.runtime_control.gpu_accounting import (
    DeviceIdentity,
    GpuAccountingSnapshot,
    OccupancyBound,
)
from core.runtime_control.gpu_observer import GpuObservationPolicy
from core.runtime_control.pair_admission import gib_from_mib
from core.runtime_control.process_control import ProcessControlDecision, ProcessControlPolicy


class GpuRuntimeProtectionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    observation: GpuObservationPolicy
    max_sample_age_seconds: float = Field(gt=0, allow_inf_nan=False, strict=True)
    control: ProcessControlPolicy

    @model_validator(mode="after")
    def usable_cadence(self) -> GpuRuntimeProtectionPolicy:
        cadence = max(self.observation.fast_interval_ms, self.observation.steady_interval_ms) / 1000
        if cadence >= self.max_sample_age_seconds:
            raise ValueError("observation cadence must be shorter than maximum sample age")
        if self.control.poll_seconds > self.max_sample_age_seconds:
            raise ValueError("control polling must not exceed maximum sample age")
        return self


class GpuProtectionBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    attempt_token: str = Field(min_length=1)
    phase: str = Field(min_length=1)
    device: DeviceIdentity
    device_total_mib: int = Field(gt=0, strict=True)
    effective_ceiling_gib: float = Field(gt=0, allow_inf_nan=False, strict=True)
    ceiling_origin: str = Field(min_length=1)

    @model_validator(mode="after")
    def physical_ceiling(self) -> GpuProtectionBinding:
        if self.effective_ceiling_gib > gib_from_mib(self.device_total_mib):
            raise ValueError("effective ceiling exceeds supplied physical capacity")
        return self


class TimedGpuObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    sequence: int = Field(ge=0, strict=True)
    query_started_at: float = Field(ge=0, allow_inf_nan=False, strict=True)
    query_completed_at: float = Field(ge=0, allow_inf_nan=False, strict=True)
    snapshot: GpuAccountingSnapshot | None = None
    sampling_error: str | None = None

    @model_validator(mode="after")
    def one_observation(self) -> TimedGpuObservation:
        if self.query_completed_at < self.query_started_at:
            raise ValueError("query completion precedes query start")
        if (self.snapshot is None) == (self.sampling_error is None):
            raise ValueError("provide exactly one snapshot or sampling error")
        return self


class GpuProtectionReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    binding: GpuProtectionBinding
    policy: GpuRuntimeProtectionPolicy
    effective_control: ProcessControlPolicy | None
    mechanism_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["prepared", "running", "stopping", "frozen"]
    initial: TimedGpuObservation
    latest: TimedGpuObservation | None
    last_live: TimedGpuObservation | None
    first_stop_observation: TimedGpuObservation | None
    decision: ProcessControlDecision
    valid_live_samples: int = Field(ge=0)
    observations: int = Field(ge=0)
    child_pid: int | None
    started_at: float | None
    ended_at: float | None
    join_timed_out: bool


def observation_refusal(
    observation: TimedGpuObservation,
    binding: GpuProtectionBinding,
    policy: GpuRuntimeProtectionPolicy,
    *,
    now: float,
    coverage_ends_at: float | None = None,
) -> str | None:
    """One coherent, recent, device-matched total; never add worker demand."""
    if observation.query_completed_at > now:
        return "observation has a future query interval"
    coverage_time = min(now, coverage_ends_at) if coverage_ends_at is not None else now
    if coverage_time - observation.query_started_at > policy.max_sample_age_seconds:
        return "GPU observation coverage expired"
    if observation.sampling_error is not None:
        return f"GPU sampling failed: {observation.sampling_error}"
    snapshot = observation.snapshot
    if snapshot is None or not snapshot.telemetry_available:
        return "GPU telemetry unavailable"
    if snapshot.device.uuid != binding.device.uuid:
        return "GPU observation device UUID changed"
    if snapshot.device_total_mib != binding.device_total_mib:
        return "GPU observation physical capacity changed"
    try:
        bound = OccupancyBound.model_validate(
            snapshot.model_dump(include=set(OccupancyBound.model_fields))
        )
    except ValueError:
        return "GPU accounting is incomplete or inconsistent"
    if gib_from_mib(bound.device_used_mib) > binding.effective_ceiling_gib:
        return "current device occupancy exceeds the resolved GPU ceiling"
    return None


def protection_mechanism_digest() -> str:
    """Named monitoring closure, separate from the measurement estimator."""
    core = Path(__file__).resolve().parents[1]
    names = (
        "runtime_control/gpu_protection.py",
        "runtime_control/gpu_protection_state.py",
        "runtime_control/gpu_observer.py",
        "runtime_control/gpu_accounting.py",
        "runtime_control/process_visibility.py",
        "runtime_control/pair_admission.py",
        "runtime_control/process_control.py",
        "runtime_control/observed_subprocess.py",
        "runtime_control/process_group.py",
        "planner_strategy_identity.py",
    )
    return source_fingerprint({name: (core / name).read_bytes() for name in names})
