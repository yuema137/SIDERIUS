"""Explicit selection and limits for measured, protected native GPU execution."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_control.gpu_protection import GpuRuntimeProtectionPolicy


class GpuExecutionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    phase_measurement_budget_seconds: float = Field(gt=0, allow_inf_nan=False, strict=True)
    worker_rss_limit_bytes: int = Field(gt=0, strict=True)
    startup_ack_timeout_seconds: float = Field(gt=0, allow_inf_nan=False, strict=True)
    startup_receipt_limit_bytes: int = Field(gt=0, strict=True)
    protection: GpuRuntimeProtectionPolicy


def load_gpu_execution_policy(path: str | None) -> GpuExecutionPolicy | None:
    """Read only the explicitly supplied configuration; omission has no effects."""
    return None if path is None else GpuExecutionPolicy.model_validate_json(Path(path).read_bytes())
