"""Caller-selected recovery allowances; validation remains framework-owned."""

from typing import Literal

from pydantic import Field

from .common import FrozenModel


class AnalysisRecoveryPolicy(FrozenModel):
    """Additional attempts after an initial generation and its schema repair.

    Zero disables fresh generation for that stage, not validation or the
    existing representation-only repair. All attempts share the request's
    deadline and access/resource contracts. Provider errors are not retried here.
    """

    schema_version: Literal[1] = 1
    generated_program_retries: int = Field(default=1, ge=0, strict=True)
    plan_retries: int = Field(default=1, ge=0, strict=True)
