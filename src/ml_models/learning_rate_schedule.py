"""Explicit epoch schedules; no task-specific strategy or numerical defaults."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class CosineLearningRateSchedule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["cosine"]
    horizon_epochs: int = Field(strict=True, gt=0)
    min_lr: float = Field(ge=0, allow_inf_nan=False)


class StepLearningRateSchedule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["step"]
    step_size_epochs: int = Field(strict=True, gt=0)
    gamma: float = Field(gt=0, le=1, allow_inf_nan=False)


LearningRateSchedule = Annotated[
    CosineLearningRateSchedule | StepLearningRateSchedule, Field(discriminator="kind")
]


def epoch_learning_rate(schedule: LearningRateSchedule, base_lr: float, epoch: int) -> float:
    """Epoch zero uses base LR; cosine reaches its floor at the horizon index."""
    if not math.isfinite(base_lr) or base_lr < 0:
        raise ValueError("The optimizer base learning rate must be finite and nonnegative")
    if epoch < 0:
        raise ValueError("The epoch index must be nonnegative")
    if isinstance(schedule, CosineLearningRateSchedule):
        if schedule.min_lr > base_lr:
            raise ValueError("lr_schedule.min_lr must not exceed the optimizer base learning rate")
        if epoch == 0:
            return base_lr
        if epoch >= schedule.horizon_epochs:
            return schedule.min_lr
        fraction = epoch / schedule.horizon_epochs
        return (
            schedule.min_lr + (base_lr - schedule.min_lr) * (1 + math.cos(math.pi * fraction)) / 2
        )
    return base_lr * schedule.gamma ** (epoch // schedule.step_size_epochs)
