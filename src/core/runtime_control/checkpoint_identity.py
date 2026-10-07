"""Typed protocol for fixed CPU preparation of one explicit native checkpoint."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from agent.schemas.data_analysis.common import NonEmptyStr
from core.runtime_control.inference_checkpoint_reference import (
    InferenceCheckpointReference,
    validate_native_checkpoint_path,
)
from core.runtime_control.observed_subprocess import ProcessLifecycle


class CheckpointIdentityRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    checkpoint_path: NonEmptyStr
    model_type: NonEmptyStr
    experiment_id: NonEmptyStr
    request_nonce: NonEmptyStr
    cooperative_seconds: float = Field(gt=0, allow_inf_nan=False, strict=True)

    @model_validator(mode="after")
    def _native_path(self) -> CheckpointIdentityRequest:
        validate_native_checkpoint_path(self.checkpoint_path, self.model_type, self.experiment_id)
        return self


class CheckpointIdentityReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    request_nonce: NonEmptyStr
    child_pid: StrictInt = Field(gt=0)
    reference: InferenceCheckpointReference | None = None
    unavailable_reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _one_outcome(self) -> CheckpointIdentityReceipt:
        if (self.reference is None) == (self.unavailable_reason is None):
            raise ValueError("checkpoint identity receipt requires exactly one outcome")
        return self


class CheckpointPreparationTiming(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    request_seconds: float = Field(ge=0)
    supervised_seconds: float = Field(ge=0)
    finalization_seconds: float = Field(ge=0)
    elapsed_seconds: float = Field(ge=0)


class CheckpointPreparationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["available", "unavailable"]
    reference: InferenceCheckpointReference | None = None
    detail: str
    timing: CheckpointPreparationTiming
    worker_receipt: CheckpointIdentityReceipt | None = None
    lifecycle: ProcessLifecycle | None = None

    @model_validator(mode="after")
    def _accepted_reference(self) -> CheckpointPreparationResult:
        if (self.status == "available") != (self.reference is not None):
            raise ValueError("only available preparation may publish an accepted reference")
        return self
