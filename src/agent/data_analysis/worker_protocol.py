"""Private parent/worker transport; not a capability or skill-pack contract."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from agent.schemas.data_analysis.common import FrozenModel, NonEmptyStr, Sha256
from agent.schemas.data_analysis.skills import ResolvedSkillInterface, SkillInput, SkillPayload

from .discovery import DiscoveredSkill


class SkillWorkerRequest(FrozenModel):
    mode: Literal["resolve_interface", "validate_parameters", "execute"]
    discovered_skill: DiscoveredSkill
    parameters: dict[str, Any] = Field(default_factory=dict)
    skill_input: SkillInput | None = None
    materialization_paths: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)
    artifact_directory: str | None = None
    expected_parameter_schema_sha256: Sha256 | None = None
    expected_validated_parameters_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def validate_mode(self) -> SkillWorkerRequest:
        execution_fields = (
            self.skill_input,
            self.artifact_directory,
            self.expected_parameter_schema_sha256,
            self.expected_validated_parameters_sha256,
        )
        if self.mode == "execute" and any(item is None for item in execution_fields):
            raise ValueError("execute worker request is missing execution fields")
        if self.mode == "validate_parameters":
            if self.expected_parameter_schema_sha256 is None:
                raise ValueError("parameter validation must pin a resolved schema identity")
            if any(
                item is not None
                for item in (
                    self.skill_input,
                    self.artifact_directory,
                    self.expected_validated_parameters_sha256,
                )
            ):
                raise ValueError("parameter-validation request cannot carry execution fields")
            if self.materialization_paths:
                raise ValueError("parameter validation cannot carry materialized data paths")
        if self.mode == "resolve_interface" and (
            self.parameters
            or self.materialization_paths
            or any(item is not None for item in execution_fields)
        ):
            raise ValueError(
                "interface resolution cannot carry parameters, materialized data, "
                "or execution fields"
            )
        return self


class ValidatedParameters(FrozenModel):
    parameters: dict[str, Any]
    parameter_schema_sha256: Sha256
    validated_parameters_sha256: Sha256


class SkillWorkerResponse(FrozenModel):
    status: Literal["interface_resolved", "validated", "completed", "failed"]
    resolved_interface: ResolvedSkillInterface | None = None
    validated_parameters: ValidatedParameters | None = None
    payload: SkillPayload | None = None
    error_type: str | None = None
    error_message: str | None = None
    environment_lock_verified: bool = False

    @model_validator(mode="after")
    def validate_response(self) -> SkillWorkerResponse:
        if self.status == "interface_resolved" and self.resolved_interface is None:
            raise ValueError("interface-resolved response requires an interface")
        if self.status == "validated" and self.validated_parameters is None:
            raise ValueError("validated response requires validated parameters")
        if self.status == "completed" and self.payload is None:
            raise ValueError("completed response requires a skill payload")
        if self.status == "failed" and (not self.error_type or not self.error_message):
            raise ValueError("failed response requires error details")
        return self
