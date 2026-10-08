"""Typed declarations and reports, independent of runtime initialization."""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue, field_validator

from tools.setup_review.route_models import CredentialNameCheck, LLMRoute


class SetupReviewRequest(BaseModel):
    """Arguments for the standard runner, interpreted from the named directory."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    working_directory: str
    argv: list[str]

    @field_validator("working_directory")
    @classmethod
    def absolute_directory(cls, value: str) -> str:
        if not os.path.isabs(value) or "\0" in value:
            raise ValueError("working_directory must be an absolute directory path")
        return value

    @field_validator("argv")
    @classmethod
    def valid_arguments(cls, value: list[str]) -> list[str]:
        if any("\0" in item for item in value):
            raise ValueError("argv cannot contain NUL characters")
        return value


class ParameterDeclaration(BaseModel):
    """A real parser default beside the value produced by normalization."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    name: str
    flags: list[str]
    required: bool
    description: str
    cli_default: JsonValue
    normalized_name: str
    declared_value: JsonValue
    owner: Literal["standard_cli.build_parser", "standard_cli.normalize_args"]


class SetupDeclarationReport(BaseModel):
    """An inspection snapshot, never a launch approval or an effective run config."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal["siderius.setup-declaration/v2"] = "siderius.setup-declaration/v2"
    outcome: Literal["declaration_inspected"] = "declaration_inspected"
    scope: Literal["fresh_standard_single_iteration"] = "fresh_standard_single_iteration"
    llm_review: Literal["not_performed"] = "not_performed"
    request: SetupReviewRequest
    launch_argv: list[str]
    workspace: str
    task_manifest: str
    output_directory: str
    parameters: list[ParameterDeclaration]
    launch_identity: dict[str, JsonValue]
    declared_llm_config: dict[str, JsonValue]
    llm_routes: list[LLMRoute]
    environment_check_requested: bool
    credentials: list[CredentialNameCheck]
    unresolved: list[str]
