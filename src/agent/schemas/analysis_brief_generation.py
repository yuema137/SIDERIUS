"""Interpreter-owned execution receipt for optional AnalysisBrief generation."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from agent.schemas.data_analysis.common import FrozenModel, NonEmptyStr, Sha256


class AnalysisBriefGenerationReceipt(FrozenModel):
    """Auditable disposition of the optional Interpreter second stage."""

    requested: Literal[True] = True
    status: Literal["generated", "failed", "refused", "timed_out"]
    brief_id: NonEmptyStr | None = None
    brief_sha256: Sha256 | None = None
    failure_code: NonEmptyStr | None = None
    failure_message: NonEmptyStr | None = None
    prompt_sha256: Sha256
    response_schema_sha256: Sha256
    advice_sha256: Sha256
    provider: NonEmptyStr
    model_id: NonEmptyStr
    generated_at: NonEmptyStr

    @model_validator(mode="after")
    def validate_disposition(self) -> AnalysisBriefGenerationReceipt:
        if self.status == "generated":
            if self.brief_id is None or self.brief_sha256 is None:
                raise ValueError("generated brief receipt requires brief identity")
            if self.failure_code is not None or self.failure_message is not None:
                raise ValueError("generated brief receipt cannot carry failure details")
        else:
            if self.brief_id is not None or self.brief_sha256 is not None:
                raise ValueError("unsuccessful brief receipt cannot claim a brief identity")
            if self.failure_code is None or self.failure_message is None:
                raise ValueError("unsuccessful brief receipt requires structured failure details")
        return self
