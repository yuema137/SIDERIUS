"""Typed identity of the weights exported by a native training attempt."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CheckpointSelection = Literal["last_completed_epoch", "best_validation_loss"]


class SelectedCheckpoint(BaseModel):
    """One-based epoch selected using the fixed training-validation objective."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    policy: Literal["best_validation_loss"] = "best_validation_loss"
    epoch: int = Field(ge=1)
    validation_loss: float
