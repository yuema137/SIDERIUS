"""Task-owned, data-free inputs for deterministic model candidate checks."""

from pathlib import Path
from typing import TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent.schemas.model_io_contract import ModelIOContract


class ModelProbeSetupError(RuntimeError):
    """Invalid task/probe setup; never feedback to repair a candidate model."""


class ModelProbeContext(BaseModel):
    """Explicit locator and identity transported to candidate-check children."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_path: str
    semantic_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_data_path_id: str = Field(min_length=1)

    @field_validator("manifest_path")
    @classmethod
    def absolute_manifest(cls, value: str) -> str:
        if not Path(value).is_absolute():
            raise ValueError("model probe manifest must be an absolute path")
        return value


class ModelProbeRequest(BaseModel):
    """Resolved geometry, not permission to read datasets or run a model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_io_contract: ModelIOContract
    input_shape: tuple[int, ...] = Field(min_length=1)
    dtype: str = Field(min_length=1)

    @field_validator("input_shape")
    @classmethod
    def positive_shape(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(extent <= 0 for extent in value):
            raise ValueError("probe extents must be positive")
        return value


class ModelProbeFailure(BaseModel):
    """Structured child setup failure; ordinary candidate failures stay separate."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    message: str = Field(min_length=1)


class ModelProbeOptions(TypedDict, total=False):
    """Optional keyword transport without changing legacy helper invocations."""

    model_probe_context: ModelProbeContext
