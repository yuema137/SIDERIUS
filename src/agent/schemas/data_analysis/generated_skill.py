"""Run-scoped promotion contracts for untrusted generated analysis skills."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from .action_identity import GeneratedProgramIdentity
from .common import CertifiedArtifactRef, FrozenModel, NonEmptyStr, Sha256, canonical_sha256
from .skills import ResolvedSkillInterface, SkillDeclaration, SkillIdentity


class GeneratedSkillPromotionDraft(FrozenModel):
    """Bounded LLM decision to expose one completed program as a local skill."""

    program_id: NonEmptyStr
    skill_id: NonEmptyStr = Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")
    title: NonEmptyStr
    one_line_description: NonEmptyStr = Field(max_length=300)
    keywords: tuple[NonEmptyStr, ...]
    aliases: tuple[NonEmptyStr, ...] = ()
    tags: tuple[NonEmptyStr, ...] = ()
    applicable_when: NonEmptyStr
    time_cost: Literal["cheap", "moderate", "expensive"]
    memory_cost: Literal["low", "medium", "high"]
    rationale: NonEmptyStr

    @model_validator(mode="after")
    def validate_card_fields(self) -> GeneratedSkillPromotionDraft:
        if self.skill_id in {".", ".."}:
            raise ValueError("promoted skill_id must be a safe path component")
        if not self.keywords:
            raise ValueError("promoted skill requires at least one keyword")
        for label, values in (
            ("keywords", self.keywords),
            ("aliases", self.aliases),
            ("tags", self.tags),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"promoted skill {label} must be unique")
        return self


class GeneratedSkillPromotionProvenance(FrozenModel):
    originating_request_id: NonEmptyStr
    originating_result_id: NonEmptyStr
    rationale: NonEmptyStr
    promoted_at: NonEmptyStr


class GeneratedExperimentSkill(FrozenModel):
    """One immutable skill interface backed by an untrusted generated program."""

    schema_version: Literal[1] = 1
    declaration: SkillDeclaration
    skill_identity: SkillIdentity
    program_identity: GeneratedProgramIdentity
    program_declaration_ref: CertifiedArtifactRef
    resolved_interface: ResolvedSkillInterface
    promotion_provenance: GeneratedSkillPromotionProvenance

    @model_validator(mode="after")
    def validate_skill(self) -> GeneratedExperimentSkill:
        card = self.declaration.card
        if self.skill_identity.skill_id != card.skill_id:
            raise ValueError("generated skill identity differs from its SkillCard")
        if self.skill_identity.skill_version != card.skill_version:
            raise ValueError("generated skill version differs from its SkillCard")
        if self.skill_identity.implementation_sha256 != self.declaration.implementation_sha256:
            raise ValueError("generated skill implementation identity differs from declaration")
        if self.skill_identity.determinism != card.determinism:
            raise ValueError("generated skill determinism differs from its SkillCard")
        if self.resolved_interface.skill_identity != self.skill_identity:
            raise ValueError("generated skill interface identity differs from declaration")
        return self

    def executable_identity_body(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"promotion_provenance"})


class GeneratedExperimentSkillRegistry(FrozenModel):
    """Content-addressed manifest; it has no mutable latest pointer."""

    schema_version: Literal[1] = 1
    registry_id: NonEmptyStr
    skills: tuple[GeneratedExperimentSkill, ...] = ()
    registry_sha256: Sha256

    @model_validator(mode="after")
    def validate_registry(self) -> GeneratedExperimentSkillRegistry:
        skill_ids = [item.skill_identity.skill_id for item in self.skills]
        if len(set(skill_ids)) != len(skill_ids):
            raise ValueError("generated experiment skill IDs must be unique")
        if canonical_sha256(self.identity_body()) != self.registry_sha256:
            raise ValueError("generated experiment registry digest differs from its body")
        return self

    def identity_body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "registry_id": self.registry_id,
            "skills": [item.model_dump(mode="json") for item in self.skills],
        }


class GeneratedExperimentSkillRegistryRef(FrozenModel):
    """Explicit caller-carried location and identity of one registry snapshot."""

    registry_id: NonEmptyStr
    registry_root: NonEmptyStr
    manifest_ref: CertifiedArtifactRef
    registry_sha256: Sha256

    @model_validator(mode="after")
    def validate_ref(self) -> GeneratedExperimentSkillRegistryRef:
        if self.manifest_ref.media_type != "application/json":
            raise ValueError("generated skill registry manifest must be JSON")
        return self
