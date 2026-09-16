"""Typed Proposer consumer view of a Literature Review output."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _LiteratureProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProposerLiteratureAgentCard(_LiteratureProjection):
    agent_name: NonEmptyStr = Field(max_length=256)
    role: NonEmptyStr = Field(max_length=2000)
    expertise_domain: NonEmptyStr = Field(max_length=2000)
    coverage: NonEmptyStr = Field(max_length=4000)
    limitations: NonEmptyStr = Field(max_length=4000)
    trust_level: Literal["hard_limit", "strong_prior", "soft_prior"]
    trust_guidance: NonEmptyStr = Field(max_length=8000)


class ProposerLiteratureFinding(_LiteratureProjection):
    source_ref: NonEmptyStr = Field(max_length=1024)
    content: NonEmptyStr = Field(max_length=8000)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class ProposerLiteratureReviewEvidence(_LiteratureProjection):
    """Bounded cited literature evidence, kept distinct from observed data."""

    run_name: NonEmptyStr = Field(max_length=256)
    agent_card: ProposerLiteratureAgentCard
    findings: tuple[ProposerLiteratureFinding, ...] = Field(default=(), max_length=32)
    retrieved_paper_ids: tuple[NonEmptyStr, ...] = Field(default=(), max_length=128)
    search_rounds_used: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_prompt_budget(self) -> ProposerLiteratureReviewEvidence:
        if len(self.model_dump_json().encode("utf-8")) > 65_536:
            raise ValueError("literature evidence exceeds the 65536-byte proposer limit")
        return self
