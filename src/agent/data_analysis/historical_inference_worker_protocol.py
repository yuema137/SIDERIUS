"""Private transport for the fixed historical-inference worker."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from agent.schemas.data_analysis.common import FrozenModel, NonEmptyStr
from agent.schemas.data_analysis.inference import HistoricalModelInferenceRequest


class HistoricalInferenceWorkerRequest(FrozenModel):
    request: HistoricalModelInferenceRequest
    input_paths: dict[NonEmptyStr, NonEmptyStr]
    checkpoint_path: NonEmptyStr
    model_config_path: NonEmptyStr
    plugin_directory: str | None = None
    output_path: NonEmptyStr

    @model_validator(mode="after")
    def validate_paths(self) -> HistoricalInferenceWorkerRequest:
        expected = {view.binding_id for view in self.request.input_views}
        if set(self.input_paths) != expected:
            raise ValueError("inference worker paths must exactly match request input views")
        return self


class HistoricalInferenceWorkerResponse(FrozenModel):
    status: Literal["completed", "failed"]
    prediction_count: int = Field(default=0, ge=0)
    peak_vram_bytes: int | None = Field(default=None, ge=0)
    error_type: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_status(self) -> HistoricalInferenceWorkerResponse:
        if self.status == "completed" and (self.error_type or self.error_message):
            raise ValueError("completed inference response cannot carry failure details")
        if self.status == "failed" and (not self.error_type or not self.error_message):
            raise ValueError("failed inference response requires typed error details")
        return self
