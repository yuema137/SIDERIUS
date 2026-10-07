"""Explicit native checkpoint identity for one disposable inference worker."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from agent.schemas.data_analysis.common import NonEmptyStr, Sha256
from core.sandbox_layout import training_checkpoint_path


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
        path = Path(self.checkpoint_path)
        if path != training_checkpoint_path(path.parent, model_type, self.experiment_id):
            raise ValueError("inference checkpoint path differs from its model and experiment")
