"""Explicit scientific inputs for effectful replay; never inferred from paths."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from core.runtime_control.probe import ProbeCaps
from core.runtime_control.probe_task import StandaloneProbeDevice
from execute_tools.task_data_path import TaskProbeDataSpec
from ml_models.models_format_sandbox import LossConfig, TrainConfig


class ReplayProbeConfig(BaseModel):
    """One caller-selected workload applied to the eligible snapshot candidates.

    Model fields are validated by each candidate's registered config class in
    the worker. Loss may be omitted only when the task declares its objective.
    CPU execution still requires an explicit VRAM threshold for the existing
    contention classifier; it does not invent a GPU measurement.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_probe_data: TaskProbeDataSpec
    model_config_payload: dict[str, Any]
    train_config: TrainConfig
    loss_config: LossConfig | None = None
    caps: ProbeCaps = Field(default_factory=ProbeCaps)
    device_vram_gb: float | None = Field(default=None, gt=0.0)

    @field_validator("train_config")
    @classmethod
    def _supported_device(cls, value: TrainConfig) -> TrainConfig:
        TypeAdapter(StandaloneProbeDevice).validate_python(value.device)
        return value
