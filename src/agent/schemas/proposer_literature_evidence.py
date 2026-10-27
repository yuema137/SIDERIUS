"""Typed Proposer views of one or more separately attributed review outputs.

The legacy singular projection remains the wire shape for one review. The
collection wraps named projections in caller order and applies the same
65,536-byte ceiling to the complete collection as well as to every review.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

MAX_PROPOSER_LITERATURE_EVIDENCE_BYTES = 65_536


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
        if len(self.model_dump_json().encode("utf-8")) > MAX_PROPOSER_LITERATURE_EVIDENCE_BYTES:
            raise ValueError("literature evidence exceeds the 65536-byte proposer limit")
        return self


class ProposerLiteratureReviewContribution(_LiteratureProjection):
    """One named review with its own contributor and cited evidence."""

    contribution_id: NonEmptyStr = Field(max_length=256)
    evidence: ProposerLiteratureReviewEvidence


class ProposerLiteratureReviewEvidenceCollection(_LiteratureProjection):
    """Ordered, separately attributed reviews admitted as one proposer value."""

    reviews: tuple[ProposerLiteratureReviewContribution, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_collection(self) -> ProposerLiteratureReviewEvidenceCollection:
        contribution_ids = [item.contribution_id for item in self.reviews]
        if len(contribution_ids) != len(set(contribution_ids)):
            raise ValueError("literature evidence contribution IDs must be unique")
        run_names = {item.evidence.run_name for item in self.reviews}
        if len(run_names) != 1:
            raise ValueError("all literature reviews must share the same run_name")
        if len(self.model_dump_json().encode("utf-8")) > MAX_PROPOSER_LITERATURE_EVIDENCE_BYTES:
            raise ValueError("literature evidence collection exceeds the 65536-byte proposer limit")
        return self
