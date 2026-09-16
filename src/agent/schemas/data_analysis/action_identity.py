"""Canonical identity and provenance for generated analysis actions."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import FrozenModel, NonEmptyStr, Sha256

AnalysisExecutionOrigin = Literal[
    "reference_skill",
    "configured_external_skill",
    "generated_program",
    "generated_experiment_skill",
]


class GeneratedProgramGenerationProvenance(FrozenModel):
    """How source was produced; not part of executable program identity."""

    provider: NonEmptyStr
    model_id: NonEmptyStr
    llm_config_sha256: Sha256
    generation_prompt_sha256: Sha256
    originating_request_id: NonEmptyStr
    question_ids: tuple[NonEmptyStr, ...]

    @model_validator(mode="after")
    def validate_questions(self) -> GeneratedProgramGenerationProvenance:
        if not self.question_ids or len(set(self.question_ids)) != len(self.question_ids):
            raise ValueError("generation provenance question IDs must be non-empty and unique")
        return self


class GeneratedProgramIdentity(FrozenModel):
    """Host-independent executable identity of one persisted generated program."""

    program_id: NonEmptyStr
    declaration_sha256: Sha256
    source_sha256: Sha256
    parameter_schema_sha256: Sha256
    runtime_environment_sha256: Sha256
    sandbox_protocol_id: Literal["siderius.generated-analysis-sandbox.v1"] = (
        "siderius.generated-analysis-sandbox.v1"
    )
    determinism: Literal["deterministic", "nondeterministic"]
    seed: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_determinism(self) -> GeneratedProgramIdentity:
        if self.determinism == "deterministic" and self.seed is None:
            raise ValueError("deterministic generated programs require an explicit seed")
        return self
