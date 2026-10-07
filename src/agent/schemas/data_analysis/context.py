"""Caller-independent input contract for the Data Analysis capability."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, StrictBool, model_validator

from agent.schemas.storage import StorageConfig
from agent.schemas.task_config import ForwardContract
from execute_tools.evaluation_metric import MetricIdentityKey

from .access import AnalysisAccessPolicy
from .assets import AnalysisAsset, AnalysisScopeDescriptor
from .common import (
    CallerIdentity,
    CertifiedArtifactRef,
    FrozenModel,
    NonEmptyStr,
    Sha256,
    canonical_json_bytes,
    canonical_sha256,
)
from .generated_skill import GeneratedExperimentSkillRegistryRef
from .recovery import AnalysisRecoveryPolicy
from .resources import AnalysisResourceEnvelope
from .source_scope import (
    AnalysisSourceScope,
    DeclaredAnalysisScope,
)


class AnalysisTaskContext(FrozenModel):
    """Scientific meaning available to planning, without task-owned bulk data."""

    task_id: NonEmptyStr
    scientific_goal: NonEmptyStr
    task_description: NonEmptyStr
    target_description: str | None = None
    input_description: NonEmptyStr
    metric_identity: MetricIdentityKey | None = None
    metric_summary: NonEmptyStr
    scientific_constraints: tuple[NonEmptyStr, ...] = ()
    dataset_profile_ref: CertifiedArtifactRef | None = None
    forward_contract: ForwardContract

    @model_validator(mode="after")
    def validate_constraints(self) -> AnalysisTaskContext:
        if len(set(self.scientific_constraints)) != len(self.scientific_constraints):
            raise ValueError("scientific constraints must be unique")
        return self


class AnalysisQuestion(FrozenModel):
    question_id: NonEmptyStr
    question: NonEmptyStr
    priority: int = Field(default=3, ge=1, le=5)
    suspected_failure_modes: tuple[NonEmptyStr, ...] = ()
    observations_to_verify: tuple[NonEmptyStr, ...] = ()
    requested_scope: AnalysisScopeDescriptor | None = Field(default=None, discriminator="kind")
    completion_criterion: str | None = None

    @model_validator(mode="after")
    def validate_unique_prompts(self) -> AnalysisQuestion:
        for label, values in (
            ("suspected_failure_modes", self.suspected_failure_modes),
            ("observations_to_verify", self.observations_to_verify),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"analysis question {label} must be unique")
        return self


class AnalysisBrief(FrozenModel):
    brief_id: NonEmptyStr
    questions: tuple[AnalysisQuestion, ...]
    optional_scope_note: str | None = None
    source: Literal["interpreter", "human", "orchestrator", "agent"]
    source_ref: NonEmptyStr

    @model_validator(mode="after")
    def validate_questions(self) -> AnalysisBrief:
        question_ids = [question.question_id for question in self.questions]
        if not question_ids:
            raise ValueError("analysis brief requires at least one question")
        if len(set(question_ids)) != len(question_ids):
            raise ValueError("analysis question IDs must be unique")
        return self


class PriorEvidenceRef(FrozenModel):
    evidence_id: NonEmptyStr
    evidence_type: NonEmptyStr
    summary: NonEmptyStr
    artifact_ref: CertifiedArtifactRef


class DataAnalysisLiteratureFinding(FrozenModel):
    """One source-backed literature item available as reasoning context."""

    source_ref: NonEmptyStr = Field(max_length=1024)
    content: NonEmptyStr = Field(max_length=8000)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class DataAnalysisLiteratureEvidence(FrozenModel):
    """Data-Analysis-owned projection; never an access or skill grant."""

    review_run_name: NonEmptyStr = Field(max_length=256)
    findings: tuple[DataAnalysisLiteratureFinding, ...] = Field(default=(), max_length=32)
    retrieved_paper_ids: tuple[NonEmptyStr, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def validate_prompt_budget(self) -> DataAnalysisLiteratureEvidence:
        if len(canonical_json_bytes(self)) > 65_536:
            raise ValueError("literature evidence exceeds the 65536-byte reasoning limit")
        return self


class SkillPackRef(FrozenModel):
    """Configured pack location plus the manifest identity expected by the caller."""

    pack_id: NonEmptyStr
    pack_root: NonEmptyStr
    manifest_ref: CertifiedArtifactRef
    environment_lock_ref: CertifiedArtifactRef | None = None


class DataAnalysisInput(FrozenModel):
    schema_version: Literal[1] = 1
    request_id: NonEmptyStr
    task_context: AnalysisTaskContext
    analysis_brief: AnalysisBrief
    available_assets: tuple[AnalysisAsset, ...]
    declared_scope: DeclaredAnalysisScope = Field(
        description="One caller-declared ceiling over raw input and ordered prior models."
    )
    prior_evidence: tuple[PriorEvidenceRef, ...] = ()
    literature_evidence: DataAnalysisLiteratureEvidence | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "Optional source-backed hypotheses and caveats supplied by a workflow edge. "
            "Reasoning context only; it cannot grant assets, information or operations."
        ),
    )
    access_policy: AnalysisAccessPolicy
    resource_envelope: AnalysisResourceEnvelope
    recovery_policy: AnalysisRecoveryPolicy | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    allowed_skill_packs: tuple[SkillPackRef, ...]
    generated_skill_registry: GeneratedExperimentSkillRegistryRef | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    allow_generated_skill_promotion: bool = Field(
        default=False, exclude_if=lambda value: value is False
    )
    human_advice: str | None = None
    source_scope: AnalysisSourceScope | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description="Exact resolved lock; absent means automatic choice under declared_scope.",
    )
    retain_model_outputs: StrictBool = Field(
        default=False,
        description=(
            "Retain per-sample historical predictions after their analysis action. "
            "False retires exact output bytes; neither value changes source authorization."
        ),
    )
    storage: StorageConfig
    caller: CallerIdentity

    @model_validator(mode="after")
    def validate_input(self) -> DataAnalysisInput:
        asset_ids = [asset.asset_id for asset in self.available_assets]
        if len(set(asset_ids)) != len(asset_ids):
            raise ValueError("available asset IDs must be unique")
        evidence_ids = [evidence.evidence_id for evidence in self.prior_evidence]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("prior evidence IDs must be unique")
        pack_ids = [pack.pack_id for pack in self.allowed_skill_packs]
        if not pack_ids:
            raise ValueError("at least one allowed skill pack is required")
        if len(set(pack_ids)) != len(pack_ids):
            raise ValueError("allowed skill pack IDs must be unique")
        declared_splits = {rule.split_id for rule in self.access_policy.split_rules}
        for asset in self.available_assets:
            if asset.split_id not in declared_splits:
                raise ValueError(
                    f"asset {asset.asset_id!r} uses split {asset.split_id!r} not declared "
                    "by the access policy"
                )
            asset.validate_discovery_metadata(self.access_policy)
            if "infer" in asset.allowed_operations and not self.access_policy.allow_model_inference:
                raise ValueError(
                    f"asset {asset.asset_id!r} permits inference but the access policy forbids it"
                )
        if self.storage.local is None:
            raise ValueError("source-scoped analysis requires a local run identity")
        self.declared_scope.validate_assets(self.available_assets, self.access_policy)
        if self.source_scope is not None:
            if not set(self.source_scope.raw_input_asset_ids).issubset(
                self.declared_scope.raw_input_asset_ids
            ) or not set(self.source_scope.historical_model_asset_ids).issubset(
                self.declared_scope.historical_model_asset_ids
            ):
                raise ValueError("resolved source scope exceeds its declared raw/model ceiling")
            if self.source_scope.mode == "automatic" and self.source_scope != (
                AnalysisSourceScope.automatic(self.declared_scope)
            ):
                raise ValueError("automatic scope must contain exactly the declared assets")
            if self.source_scope.mode == "locked":
                from .source_directive import resolve_source_prompt

                expected = resolve_source_prompt(
                    self.source_scope.source_prompt,
                    declared_scope=self.declared_scope,
                    available_assets=self.available_assets,
                    access_policy=self.access_policy,
                )
                if self.source_scope != expected:
                    raise ValueError("resolved source scope differs from its lock directive")
            if self.source_scope.historical_model_asset_ids != tuple(
                asset_id
                for asset_id in self.declared_scope.historical_model_asset_ids
                if asset_id in self.source_scope.historical_model_asset_ids
            ):
                raise ValueError("resolved model order differs from certified completion order")
        return self

    def effective_recovery_policy(self) -> AnalysisRecoveryPolicy:
        """Resolve the native allowance only when the caller omitted a policy."""
        return (
            self.recovery_policy if self.recovery_policy is not None else AnalysisRecoveryPolicy()
        )

    def effective_source_scope(self) -> AnalysisSourceScope:
        """Automatic selection is still restricted to the declared ceiling."""

        return self.source_scope or AnalysisSourceScope.automatic(self.declared_scope)

    def planning_assets(self) -> tuple[AnalysisAsset, ...]:
        """Keep selected identities and only source-authorized derived metadata."""

        scope = self.effective_source_scope()
        visible = set(scope.raw_input_asset_ids) | set(scope.historical_model_asset_ids)
        scoped = []
        for asset in self.available_assets:
            if asset.asset_id not in visible:
                continue
            names = {
                name
                for name, source in asset.metadata_sources.items()
                # Identity descriptors have no split by contract. They are
                # already access-policy validated and belong to this selected
                # asset; source read permissions constrain derived values only.
                if source.information_class == "identity"
                or (
                    source.split_id is not None
                    and scope.permits(
                        asset_id=asset.asset_id,
                        information_class=source.information_class,
                        operation="infer" if asset.asset_type == "trained_model" else "materialize",
                        fields=source.source_fields,
                    )
                )
            }
            scoped.append(
                asset.model_copy(
                    update={
                        "metadata": {name: asset.metadata[name] for name in names},
                        "metadata_sources": {name: asset.metadata_sources[name] for name in names},
                    }
                )
            )
        return tuple(scoped)

    def canonical_scientific_identity(self) -> dict[str, object]:
        """Host-independent caller-controlled identity for resume comparison."""

        payload = self.model_dump(mode="json", exclude={"storage", "caller"})
        payload["allowed_skill_packs"] = [
            {
                "pack_id": pack.pack_id,
                "manifest_ref": pack.manifest_ref.model_dump(mode="json"),
                "environment_lock_ref": (
                    None
                    if pack.environment_lock_ref is None
                    else pack.environment_lock_ref.model_dump(mode="json")
                ),
            }
            for pack in sorted(self.allowed_skill_packs, key=lambda item: item.pack_id)
        ]
        if self.generated_skill_registry is not None:
            payload["generated_skill_registry"] = {
                "registry_id": self.generated_skill_registry.registry_id,
                "manifest_ref": self.generated_skill_registry.manifest_ref.model_dump(mode="json"),
                "registry_sha256": self.generated_skill_registry.registry_sha256,
            }
        return payload

    def canonical_scientific_digest(self) -> Sha256:
        return canonical_sha256(self.canonical_scientific_identity())
