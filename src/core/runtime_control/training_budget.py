"""Explicit cooperative training allocation, independent of admission authority.

This policy does not monitor loss, choose checkpoints or kill processes. The
caller observes complete train/validation epochs; checkpoint selection belongs
to the trainer and is reported separately from the stopping decision.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.checkpoint_selection import CheckpointSelection


class TrainingBudgetEnvelope(BaseModel):
    """Resolved operator allowance for one attempt on one host.

    The monotonic origin is transmitted to the local training child, never
    reused for another attempt or resumed on another machine. Downstream
    reserve is an explicit allowance, not a fabricated performance estimate.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    budget_seconds: float = Field(gt=0)
    reserve_fraction: float = Field(gt=0, lt=1)
    max_epochs: int = Field(ge=1, le=100)
    max_optimizer_steps: int | None = Field(default=None, gt=0)
    started_monotonic_seconds: float = Field(ge=0)

    @property
    def reserved_seconds(self) -> float:
        return self.budget_seconds * self.reserve_fraction


class TrainingBudgetDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    completed_epochs: int = Field(ge=0)
    elapsed_seconds: float = Field(ge=0)
    remaining_seconds: float
    reserved_seconds: float = Field(gt=0)
    next_epoch_seconds: float | None = Field(default=None, gt=0)
    action: Literal["continue", "stop"]
    reason: Literal["calibration", "fits", "epoch_cap", "time_budget", "step_limit"]


def decide_training_budget(
    envelope: TrainingBudgetEnvelope,
    *,
    elapsed_seconds: float,
    completed_epochs: int,
    observed_epoch_seconds: list[float],
    completed_optimizer_steps: int = 0,
    next_optimizer_steps: int | None = None,
) -> TrainingBudgetDecision:
    """Admit a next complete epoch using the slowest observed complete epoch.

    No additional safety-factor default is invented. The explicit downstream
    reserve supplies headroom; a future unit can still overrun its prediction.
    The first epoch is calibration if any training allowance remains.
    """
    if elapsed_seconds < 0 or completed_epochs != len(observed_epoch_seconds):
        raise ValueError("Training budget requires nonnegative elapsed time and one cost per epoch")
    if any(not (0 < cost < float("inf")) for cost in observed_epoch_seconds):
        raise ValueError("Training budget requires finite, positive complete-epoch costs")
    next_cost = max(observed_epoch_seconds) if observed_epoch_seconds else None
    remaining = envelope.budget_seconds - elapsed_seconds
    reason: Literal["calibration", "fits", "epoch_cap", "time_budget", "step_limit"]
    if completed_epochs >= envelope.max_epochs:
        reason = "epoch_cap"
    elif (
        envelope.max_optimizer_steps is not None
        and next_optimizer_steps is not None
        and completed_optimizer_steps + next_optimizer_steps > envelope.max_optimizer_steps
    ):
        reason = "step_limit"
    elif remaining <= envelope.reserved_seconds or (
        next_cost is not None and next_cost + envelope.reserved_seconds > remaining
    ):
        reason = "time_budget"
    else:
        reason = "calibration" if next_cost is None else "fits"
    return TrainingBudgetDecision(
        completed_epochs=completed_epochs,
        elapsed_seconds=elapsed_seconds,
        remaining_seconds=remaining,
        reserved_seconds=envelope.reserved_seconds,
        next_epoch_seconds=next_cost,
        action="stop" if reason in ("epoch_cap", "time_budget", "step_limit") else "continue",
        reason=reason,
    )


class TrainingBudgetReceipt(BaseModel):
    """Validated trainer-result provenance for an adaptive allocation."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    policy: TrainingBudgetEnvelope
    proposed_epochs: int = Field(ge=1)
    completed_epochs: int = Field(ge=1)
    optimizer_steps: int = Field(ge=1)
    epoch_seconds_including_validation: list[float]
    stop: TrainingBudgetDecision
    checkpoint_selection: CheckpointSelection = "last_completed_epoch"
    scientific_early_stopping: Literal[False] = False
    reserve_source: Literal["operator_allowance"] = "operator_allowance"
    clock_scope: Literal["runtime_policy_resolution_through_training"] = (
        "runtime_policy_resolution_through_training"
    )
