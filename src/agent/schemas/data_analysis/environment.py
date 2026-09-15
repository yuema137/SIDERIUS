"""Optional, verifiable runtime dependency declaration for analysis skill packs."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import field_validator, model_validator

from .common import FrozenModel, NonEmptyStr


def normalize_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


class EnvironmentPackage(FrozenModel):
    name: NonEmptyStr
    version: NonEmptyStr

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_distribution_name(value)


class AnalysisEnvironmentLock(FrozenModel):
    """Exact versions the active runtime must satisfy; never an installer request."""

    schema_version: Literal[1] = 1
    python_version: NonEmptyStr
    packages: tuple[EnvironmentPackage, ...]

    @model_validator(mode="after")
    def validate_packages(self) -> AnalysisEnvironmentLock:
        names = [item.name for item in self.packages]
        if not names or len(set(names)) != len(names):
            raise ValueError("environment lock package names must be non-empty and unique")
        if tuple(names) != tuple(sorted(names)):
            raise ValueError("environment lock packages must be sorted by normalized name")
        if not re.fullmatch(r"\d+\.\d+\.\d+", self.python_version):
            raise ValueError("environment lock python_version must be exact major.minor.micro")
        return self
