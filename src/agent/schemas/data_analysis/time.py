"""Caller-independent scientific time-precision requirement contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .common import FrozenModel, NonEmptyStr, Sha256


class FixedTimePrecisionRequirement(FrozenModel):
    kind: Literal["fixed"] = "fixed"
    required_resolution_seconds: float = Field(gt=0.0, allow_inf_nan=False)


class TaskProvidedTimePrecisionRequirement(FrozenModel):
    kind: Literal["task_provided"] = "task_provided"
    requirement_id: NonEmptyStr
    source_sha256: Sha256


TimePrecisionRequirement = Annotated[
    FixedTimePrecisionRequirement | TaskProvidedTimePrecisionRequirement,
    Field(discriminator="kind"),
]
