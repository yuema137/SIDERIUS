"""Typed declaration for one persisted experiment-local analysis program."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import Field, model_validator

from .action_identity import GeneratedProgramGenerationProvenance, GeneratedProgramIdentity
from .common import CertifiedArtifactRef, FrozenModel, NonEmptyStr, Sha256, canonical_sha256
from .skills import SkillInputSlot

GeneratedParameterValue = str | int | float | bool | None


class GeneratedParameterDeclaration(FrozenModel):
    name: NonEmptyStr
    value_type: Literal["string", "integer", "number", "boolean"]
    description: NonEmptyStr
    required: bool = True
    default: GeneratedParameterValue = None
    choices: tuple[GeneratedParameterValue, ...] = ()
    minimum: float | None = None
    maximum: float | None = None

    @staticmethod
    def _matches_type(value: GeneratedParameterValue, value_type: str) -> bool:
        if value is None:
            return True
        if value_type == "boolean":
            return isinstance(value, bool)
        if value_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if value_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        return isinstance(value, str)

    @model_validator(mode="after")
    def validate_declaration(self) -> GeneratedParameterDeclaration:
        if self.required and self.default is not None:
            raise ValueError("required generated parameters cannot declare a default")
        if not self._matches_type(self.default, self.value_type):
            raise ValueError("generated parameter default does not match value_type")
        if any(not self._matches_type(value, self.value_type) for value in self.choices):
            raise ValueError("generated parameter choices do not match value_type")
        if len(set(map(repr, self.choices))) != len(self.choices):
            raise ValueError("generated parameter choices must be unique")
        if self.minimum is not None or self.maximum is not None:
            if self.value_type not in {"integer", "number"}:
                raise ValueError("minimum/maximum are valid only for numeric parameters")
            if (
                self.minimum is not None
                and self.maximum is not None
                and self.minimum > self.maximum
            ):
                raise ValueError("generated parameter minimum cannot exceed maximum")
        numeric_values = (
            (self.default, *self.choices, self.minimum, self.maximum)
            if self.value_type in {"integer", "number"}
            else ()
        )
        if any(value is not None and not math.isfinite(float(value)) for value in numeric_values):
            raise ValueError("generated numeric parameter declarations must be finite")
        return self


class GeneratedMeasurementDeclaration(FrozenModel):
    result_key: NonEmptyStr
    description: NonEmptyStr
    value_type: Literal["number", "integer", "string", "boolean", "nullable_number"]
    unit: str | None = None


class GeneratedArtifactDeclaration(FrozenModel):
    artifact_type: NonEmptyStr
    media_type: NonEmptyStr
    description: NonEmptyStr
    required: bool = False


class GeneratedProgramResourceRequest(FrozenModel):
    wall_time_s: float = Field(gt=0.0)
    max_host_memory_gb: float = Field(gt=0.0)
    preferred_device: Literal["cpu"] = "cpu"
    max_artifact_count: int = Field(default=8, ge=0, le=64)
    max_artifact_bytes: int = Field(default=16 * 1024 * 1024, ge=0)


class GeneratedAnalysisProgram(FrozenModel):
    """Validated immutable declaration; source bytes live at ``source_ref``."""

    schema_version: Literal[1] = 1
    program_id: NonEmptyStr
    question_ids: tuple[NonEmptyStr, ...]
    source_ref: CertifiedArtifactRef
    source_sha256: Sha256
    input_slots: tuple[SkillInputSlot, ...]
    parameters: tuple[GeneratedParameterDeclaration, ...] = ()
    expected_measurements: tuple[GeneratedMeasurementDeclaration, ...]
    expected_artifacts: tuple[GeneratedArtifactDeclaration, ...] = ()
    resource_request: GeneratedProgramResourceRequest
    determinism: Literal["deterministic", "nondeterministic"]
    seed: int | None = Field(default=None, ge=0)
    generation_provenance: GeneratedProgramGenerationProvenance

    @model_validator(mode="after")
    def validate_program(self) -> GeneratedAnalysisProgram:
        if self.source_ref.sha256 != self.source_sha256:
            raise ValueError("generated program source ref does not match source_sha256")
        if self.source_ref.media_type != "text/x-python":
            raise ValueError("generated program source must use text/x-python")
        if not self.question_ids or len(set(self.question_ids)) != len(self.question_ids):
            raise ValueError("generated program question IDs must be non-empty and unique")
        if set(self.question_ids) != set(self.generation_provenance.question_ids):
            raise ValueError("generated program questions differ from generation provenance")
        slot_ids = [slot.slot_id for slot in self.input_slots]
        if not slot_ids or len(set(slot_ids)) != len(slot_ids):
            raise ValueError("generated program input slot IDs must be non-empty and unique")
        if any(slot.invocation_metadata_selection is not None for slot in self.input_slots):
            raise ValueError("one-off generated programs require concrete metadata declarations")
        if any(
            requirement.information_class == "identity"
            for slot in self.input_slots
            for requirement in (*slot.required_information, *slot.optional_information)
        ):
            raise ValueError(
                "generated program identity information is discovery-only and cannot be "
                "materialized"
            )
        parameter_names = [item.name for item in self.parameters]
        if len(set(parameter_names)) != len(parameter_names):
            raise ValueError("generated program parameter names must be unique")
        result_keys = [item.result_key for item in self.expected_measurements]
        if not result_keys or len(set(result_keys)) != len(result_keys):
            raise ValueError("expected measurement keys must be non-empty and unique")
        artifact_types = [item.artifact_type for item in self.expected_artifacts]
        if len(set(artifact_types)) != len(artifact_types):
            raise ValueError("expected generated artifact types must be unique")
        if self.determinism == "deterministic" and self.seed is None:
            raise ValueError("deterministic generated programs require an explicit seed")
        return self

    def parameter_schema_body(self) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in self.parameters]

    def parameter_schema_sha256(self) -> Sha256:
        return canonical_sha256(self.parameter_schema_body())

    def executable_declaration_body(self) -> dict[str, Any]:
        """Exclude generation history while retaining every execution determinant."""

        return self.model_dump(mode="json", exclude={"generation_provenance"})

    def executable_declaration_sha256(self) -> Sha256:
        return canonical_sha256(self.executable_declaration_body())

    def identity(self, *, runtime_environment_sha256: Sha256) -> GeneratedProgramIdentity:
        return GeneratedProgramIdentity(
            program_id=self.program_id,
            declaration_sha256=self.executable_declaration_sha256(),
            source_sha256=self.source_sha256,
            parameter_schema_sha256=self.parameter_schema_sha256(),
            runtime_environment_sha256=runtime_environment_sha256,
            determinism=self.determinism,
            seed=self.seed,
        )


def validate_generated_parameters(
    declarations: tuple[GeneratedParameterDeclaration, ...],
    supplied: dict[str, Any],
) -> dict[str, GeneratedParameterValue]:
    """Validate one-off scalar parameters without executing generated code."""

    by_name = {item.name: item for item in declarations}
    unknown = set(supplied) - set(by_name)
    if unknown:
        raise ValueError(f"unknown generated program parameters: {sorted(unknown)}")
    resolved: dict[str, GeneratedParameterValue] = {}
    for name, declaration in by_name.items():
        if name in supplied:
            value = supplied[name]
        elif declaration.required:
            raise ValueError(f"required generated program parameter {name!r} is missing")
        else:
            value = declaration.default
        if value is None and declaration.required:
            raise ValueError(f"required generated program parameter {name!r} cannot be null")
        if not declaration._matches_type(value, declaration.value_type):
            raise ValueError(f"generated program parameter {name!r} has the wrong type")
        if (
            value is not None
            and declaration.value_type in {"integer", "number"}
            and not math.isfinite(float(value))
        ):
            raise ValueError(f"generated program parameter {name!r} must be finite")
        if declaration.choices and value not in declaration.choices:
            raise ValueError(f"generated program parameter {name!r} is outside its choices")
        if value is not None and declaration.value_type in {"integer", "number"}:
            numeric = float(value)
            if declaration.minimum is not None and numeric < declaration.minimum:
                raise ValueError(f"generated program parameter {name!r} is below minimum")
            if declaration.maximum is not None and numeric > declaration.maximum:
                raise ValueError(f"generated program parameter {name!r} exceeds maximum")
        resolved[name] = value
    return resolved
