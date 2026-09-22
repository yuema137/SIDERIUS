"""Provenance for an explicitly enabled scalar affine target transform."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TargetStandardization = Literal["none", "training_pool_global"]


class TargetStandardizationReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    policy: Literal["training_pool_global"] = "training_pool_global"
    mean: float
    scale: float = Field(gt=0)
    training_rows: int = Field(gt=0)
    target_elements: int = Field(gt=1)
    fit_seconds: float = Field(ge=0)
