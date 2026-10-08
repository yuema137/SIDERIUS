"""Explicit native checkpoint identity for one disposable inference worker."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from agent.schemas.data_analysis.common import NonEmptyStr, Sha256
from core.sandbox_layout import training_checkpoint_path


def validate_native_checkpoint_path(path_value: str, model_type: str, experiment_id: str) -> None:
    """Share the native filename/path rule before and after bytes are identified."""
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError("inference checkpoint path must be absolute")
    if path != training_checkpoint_path(path.parent, model_type, experiment_id):
        raise ValueError("inference checkpoint path differs from its model and experiment")


class InferenceCheckpointReference(BaseModel):
    """Supplied identity, never checkpoint discovery or a model construction rule."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    checkpoint_path: NonEmptyStr
    experiment_id: NonEmptyStr
    checkpoint_sha256: Sha256
    checkpoint_byte_size: StrictInt = Field(ge=0)

    @field_validator("checkpoint_path")
    @classmethod
    def _absolute_path(cls, value: str) -> str:
        if not Path(value).is_absolute():
            raise ValueError("inference checkpoint path must be absolute")
        return value

    def validate_native_path(self, model_type: str) -> None:
        """Use the native writer's owner rather than interpret a filename."""
        validate_native_checkpoint_path(self.checkpoint_path, model_type, self.experiment_id)
