"""Evidence-only control of one owned child; signalling belongs to supervision."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ProcessControlPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    poll_seconds: float = Field(gt=0, allow_inf_nan=False, strict=True)
    grace_seconds: float = Field(ge=0, allow_inf_nan=False, strict=True)
    reap_seconds: float = Field(gt=0, allow_inf_nan=False, strict=True)


class ProcessControlDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["continue", "stop"]
    binding_token: str = Field(min_length=1)
    sequence: int = Field(ge=0, strict=True)
    reason: str = Field(min_length=1)


class ProcessLiveness(Protocol):
    @property
    def pid(self) -> int: ...
    def poll(self) -> int | None: ...


class ProcessControl(Protocol):
    """Bounded state operations, never sampling, blocking IO or signalling."""

    @property
    def control_policy(self) -> ProcessControlPolicy: ...
    def configure_control(self, effective: ProcessControlPolicy) -> None: ...
    def check_control(self) -> ProcessControlDecision: ...
    def attach_process(self, process: ProcessLiveness) -> None: ...
    def mark_process_end(self) -> None: ...
    def abort_control(self, reason: str) -> None: ...


def effective_control_policy(
    selected: ProcessControlPolicy,
    *,
    existing_poll: float | None,
    existing_grace: float | None,
    existing_reap: float | None,
) -> ProcessControlPolicy:
    """Intersect active bounds; legacy poll=0 is not a protected cadence."""
    import math

    for value in (existing_poll, existing_grace, existing_reap):
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ValueError("active process bounds must be nonnegative and finite")
    return ProcessControlPolicy(
        poll_seconds=min(selected.poll_seconds, existing_poll)
        if existing_poll is not None and existing_poll > 0
        else selected.poll_seconds,
        grace_seconds=min(selected.grace_seconds, existing_grace)
        if existing_grace is not None
        else selected.grace_seconds,
        reap_seconds=min(selected.reap_seconds, existing_reap)
        if existing_reap is not None
        else selected.reap_seconds,
    )
