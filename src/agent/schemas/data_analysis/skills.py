"""Serializable skill-pack discovery and execution contracts."""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .access import InformationRequirement
from .action_identity import AnalysisExecutionOrigin, GeneratedProgramIdentity
from .assets import AnalysisAssetType, AnalysisAuthorizationReceipt, MaterializedAnalysisView
from .common import CertifiedArtifactRef, FrozenModel, NonEmptyStr, Sha256, canonical_json_bytes
from .resources import ResourceUsage
from .trained_model import ModelInferenceReceipt

CostClass = Literal["cheap", "moderate", "expensive"]
DevicePreference = Literal["cpu", "gpu", "either"]
DeterminismPosture = Literal["deterministic", "nondeterministic"]
InvocationStatus = Literal["completed", "partial", "failed", "refused", "timed_out"]


class NumericalTolerance(FrozenModel):
    atol: float = Field(default=0.0, ge=0.0)
    rtol: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def validate_nonzero(self) -> NumericalTolerance:
        if self.atol == 0.0 and self.rtol == 0.0:
            raise ValueError("use numerical_tolerance=None for exact-result semantics")
        return self


class InvocationMetadataSelection(FrozenModel):
    """Bounded metadata names selected explicitly by one validated parameter."""

    minimum_fields: int = Field(ge=0, le=8)
    maximum_fields: int = Field(ge=1, le=8)
    parameter_name: NonEmptyStr

    @model_validator(mode="after")
    def validate_bounds(self) -> InvocationMetadataSelection:
        if self.minimum_fields > self.maximum_fields:
            raise ValueError("minimum_fields cannot exceed maximum_fields")
        return self


class SkillInputSlot(FrozenModel):
    slot_id: NonEmptyStr
    description: NonEmptyStr
    accepted_asset_types: tuple[AnalysisAssetType, ...]
    accepted_view_formats: tuple[NonEmptyStr, ...]
    required_information: tuple[InformationRequirement, ...]
    optional_information: tuple[InformationRequirement, ...] = ()
    invocation_metadata_selection: InvocationMetadataSelection | None = None
    required: bool = True
    cardinality: Literal["one", "many"] = "one"

    @model_validator(mode="after")
    def validate_slot(self) -> SkillInputSlot:
        if not self.accepted_asset_types or len(set(self.accepted_asset_types)) != len(
            self.accepted_asset_types
        ):
            raise ValueError("accepted asset types must be non-empty and unique")
        if not self.accepted_view_formats or len(set(self.accepted_view_formats)) != len(
            self.accepted_view_formats
        ):
            raise ValueError("accepted view formats must be non-empty and unique")
        if not self.required_information and (
            self.invocation_metadata_selection is None
            or self.invocation_metadata_selection.minimum_fields == 0
        ):
            raise ValueError(
                "a skill input slot requires static information or required "
                "invocation-selected metadata"
            )
        for label, requirements in (
            ("required", self.required_information),
            ("optional", self.optional_information),
        ):
            classes = [item.information_class for item in requirements]
            if len(set(classes)) != len(classes):
                raise ValueError(f"{label} information classes must be unique within the slot")
        required_by_class = {
            item.information_class: set(item.fields) for item in self.required_information
        }
        optional_by_class = {
            item.information_class: set(item.fields) for item in self.optional_information
        }
        for information_class in set(required_by_class) & set(optional_by_class):
            if information_class != "metadata":
                raise ValueError(f"{information_class!r} cannot be both required and optional")
            if required_by_class[information_class] & optional_by_class[information_class]:
                raise ValueError("required and optional metadata fields must be disjoint")
        return self


class SkillCard(FrozenModel):
    skill_id: NonEmptyStr
    title: NonEmptyStr
    one_line_description: NonEmptyStr = Field(max_length=300)
    keywords: tuple[NonEmptyStr, ...]
    aliases: tuple[NonEmptyStr, ...] = ()
    tags: tuple[NonEmptyStr, ...] = ()
    input_slots: tuple[SkillInputSlot, ...]
    produced_artifact_types: tuple[NonEmptyStr, ...] = ()
    applicable_when: NonEmptyStr
    time_cost: CostClass
    memory_cost: Literal["low", "medium", "high"]
    preferred_device: DevicePreference
    supports_sampling: bool
    skill_version: NonEmptyStr
    determinism: DeterminismPosture
    numerical_tolerance: NumericalTolerance | None = None
    determinism_notes: str | None = None

    @model_validator(mode="after")
    def validate_card(self) -> SkillCard:
        for label, values in (
            ("keywords", self.keywords),
            ("aliases", self.aliases),
            ("tags", self.tags),
            ("produced_artifact_types", self.produced_artifact_types),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"skill card {label} must be unique")
        if not self.keywords:
            raise ValueError("skill card requires at least one keyword")
        slot_ids = [slot.slot_id for slot in self.input_slots]
        if not slot_ids or len(set(slot_ids)) != len(slot_ids):
            raise ValueError("skill card input slot IDs must be non-empty and unique")
        if self.determinism == "nondeterministic" and not self.determinism_notes:
            raise ValueError("nondeterministic skills require determinism_notes")
        dynamic_parameter_names = [
            slot.invocation_metadata_selection.parameter_name
            for slot in self.input_slots
            if slot.invocation_metadata_selection is not None
        ]
        if len(set(dynamic_parameter_names)) != len(dynamic_parameter_names):
            raise ValueError(
                "invocation metadata parameter names must be unique across skill slots"
            )
        return self


class SkillEntrypoint(FrozenModel):
    module_path: NonEmptyStr
    callable_symbol: NonEmptyStr = "run"
    parameter_schema_symbol: NonEmptyStr = "Parameters"
    instructions_symbol: NonEmptyStr = "SKILL_INSTRUCTIONS"

    @model_validator(mode="after")
    def validate_relative_path(self) -> SkillEntrypoint:
        if "\\" in self.module_path:
            raise ValueError("skill module_path must use normalized POSIX separators")
        path = self.module_path
        if path.startswith("/") or ".." in path.split("/") or not path.endswith(".py"):
            raise ValueError("skill module_path must be a relative .py path without '..'")
        return self


class SkillContentFile(FrozenModel):
    relative_path: NonEmptyStr
    sha256: Sha256

    @model_validator(mode="after")
    def validate_relative_path(self) -> SkillContentFile:
        if "\\" in self.relative_path:
            raise ValueError("skill content paths must use normalized POSIX separators")
        path = self.relative_path
        if path.startswith("/") or ".." in path.split("/") or path.endswith("/"):
            raise ValueError("skill content path must be a relative file path without '..'")
        return self


def implementation_identity_sha256(files: tuple[SkillContentFile, ...]) -> str:
    ordered = sorted(
        (item.model_dump(mode="json") for item in files),
        key=lambda item: item["relative_path"],
    )
    return hashlib.sha256(canonical_json_bytes(ordered)).hexdigest()


class SkillDeclaration(FrozenModel):
    card: SkillCard
    entrypoint: SkillEntrypoint
    implementation_files: tuple[SkillContentFile, ...]
    implementation_sha256: Sha256

    @model_validator(mode="after")
    def validate_implementation_identity(self) -> SkillDeclaration:
        paths = [item.relative_path for item in self.implementation_files]
        if not paths or len(set(paths)) != len(paths):
            raise ValueError("implementation file paths must be non-empty and unique")
        if self.entrypoint.module_path not in paths:
            raise ValueError("skill entrypoint must be included in implementation_files")
        if implementation_identity_sha256(self.implementation_files) != self.implementation_sha256:
            raise ValueError("implementation_sha256 does not match implementation_files")
        return self


class SkillPackManifest(FrozenModel):
    schema_version: Literal[1] = 1
    pack_id: NonEmptyStr
    pack_version: NonEmptyStr
    title: NonEmptyStr
    description: NonEmptyStr
    skills: tuple[SkillDeclaration, ...]
    pack_content_sha256: Sha256

    def canonical_body(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json", exclude={"pack_content_sha256"}))

    @model_validator(mode="after")
    def validate_manifest(self) -> SkillPackManifest:
        if not self.skills:
            raise ValueError("skill pack manifest requires at least one skill")
        skill_ids = [skill.card.skill_id for skill in self.skills]
        if len(set(skill_ids)) != len(skill_ids):
            raise ValueError("skill IDs must be unique within a pack")
        return self


class SkillIdentity(FrozenModel):
    pack_id: NonEmptyStr
    pack_version: NonEmptyStr
    pack_content_sha256: Sha256
    skill_id: NonEmptyStr
    skill_version: NonEmptyStr
    implementation_sha256: Sha256
    environment_lock_sha256: Sha256 | None = None
    determinism: DeterminismPosture


class ResolvedSkillInterface(FrozenModel):
    skill_identity: SkillIdentity
    parameter_json_schema: dict[str, Any]
    parameter_schema_sha256: Sha256
    selected_skill_instructions: NonEmptyStr

    @model_validator(mode="after")
    def validate_bounds(self) -> ResolvedSkillInterface:
        if len(canonical_json_bytes(self.parameter_json_schema)) > 64 * 1024:
            raise ValueError("selected parameter JSON schema exceeds 64 KiB")
        if len(self.selected_skill_instructions.encode("utf-8")) > 16 * 1024:
            raise ValueError("selected skill instructions exceed 16 KiB")
        if (
            hashlib.sha256(canonical_json_bytes(self.parameter_json_schema)).hexdigest()
            != self.parameter_schema_sha256
        ):
            raise ValueError("parameter schema digest does not match its JSON schema")
        return self


class ArtifactOutputContract(FrozenModel):
    output_directory_ref: NonEmptyStr
    allowed_media_types: tuple[NonEmptyStr, ...]
    max_artifact_count: int = Field(default=16, ge=0, le=256)
    max_total_bytes: int = Field(default=64 * 1024 * 1024, ge=0)


class SkillInput(FrozenModel):
    invocation_id: NonEmptyStr
    skill_identity: SkillIdentity
    materializations: tuple[MaterializedAnalysisView, ...]
    question_ids: tuple[NonEmptyStr, ...]
    deadline_monotonic_s: float
    artifact_output_contract: ArtifactOutputContract

    @model_validator(mode="after")
    def validate_input(self) -> SkillInput:
        if not self.materializations:
            raise ValueError("skill input requires at least one authorized materialization")
        if not self.question_ids:
            raise ValueError("skill input requires at least one question ID")
        if len(set(self.question_ids)) != len(self.question_ids):
            raise ValueError("skill input question IDs must be unique")
        binding_ids = [view.binding_id for view in self.materializations]
        if len(set(binding_ids)) != len(binding_ids):
            raise ValueError("skill input materialization binding IDs must be unique")
        if any(view.invocation_id != self.invocation_id for view in self.materializations):
            raise ValueError("all materialized views must belong to the SkillInput invocation")
        selections = {
            canonical_json_bytes(view.selection_identity) for view in self.materializations
        }
        if len(selections) != 1:
            raise ValueError("all materialized views must share one certified selection")
        return self


class AnalysisCoverage(FrozenModel):
    population_unit: NonEmptyStr
    total_available: int | None = Field(default=None, ge=0)
    analyzed_count: int = Field(ge=0)
    binding_ids: tuple[NonEmptyStr, ...]
    selection_sha256: Sha256
    split_id: NonEmptyStr
    sampling_strategy: NonEmptyStr
    sampling_seed: int | None = Field(default=None, ge=0)
    filters: tuple[str, ...] = ()
    slice_descriptions: tuple[str, ...] = ()
    model_artifact_ref: CertifiedArtifactRef | None = None
    inference_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_coverage(self) -> AnalysisCoverage:
        if self.total_available is not None and self.analyzed_count > self.total_available:
            raise ValueError("analyzed_count cannot exceed total_available")
        if self.inference_count is not None and self.model_artifact_ref is None:
            raise ValueError("inference_count requires model_artifact_ref")
        if not self.binding_ids or len(set(self.binding_ids)) != len(self.binding_ids):
            raise ValueError("coverage binding IDs must be non-empty and unique")
        return self


class AnalysisDropReason(FrozenModel):
    reason: NonEmptyStr
    count: int = Field(gt=0)


class SkillAnalysisUsage(FrozenModel):
    """Untrusted effective-use claim, bounded later by certified materialization."""

    effective_count: int = Field(ge=0)
    dropped_count: int = Field(ge=0)
    drop_reasons: tuple[AnalysisDropReason, ...] = ()

    @model_validator(mode="after")
    def validate_reasons(self) -> SkillAnalysisUsage:
        if sum(item.count for item in self.drop_reasons) != self.dropped_count:
            raise ValueError("drop reason counts must sum to dropped_count")
        reasons = [item.reason for item in self.drop_reasons]
        if len(set(reasons)) != len(reasons):
            raise ValueError("analysis drop reasons must be unique")
        return self


class QuantitativeResult(FrozenModel):
    result_key: NonEmptyStr
    value: float | int | str | bool | None
    unit: str | None = None
    description: NonEmptyStr


class ProducedArtifact(FrozenModel):
    artifact_type: NonEmptyStr
    logical_name: NonEmptyStr
    media_type: NonEmptyStr
    relative_path: NonEmptyStr
    description: NonEmptyStr

    @model_validator(mode="after")
    def validate_relative_path(self) -> ProducedArtifact:
        path = self.relative_path.replace("\\", "/")
        if path.startswith("/") or ".." in path.split("/"):
            raise ValueError("produced artifact path must be relative without '..'")
        return self


class SkillPayload(FrozenModel):
    """Untrusted skill-produced payload; executor certifies artifacts and usage."""

    summary: NonEmptyStr
    quantitative_results: tuple[QuantitativeResult, ...] = ()
    produced_artifacts: tuple[ProducedArtifact, ...] = ()
    analysis_usage: SkillAnalysisUsage | None = None
    warnings: tuple[str, ...] = ()


class SkillFailure(FrozenModel):
    failure_type: NonEmptyStr
    message: NonEmptyStr
    retryable: bool = False
    materialization_occurred: bool
    refusal_code: str | None = None


class SkillExecutionProvenance(FrozenModel):
    plan_sha256: Sha256
    parameter_schema_sha256: Sha256
    validated_parameters_sha256: Sha256
    authorization_receipts: tuple[AnalysisAuthorizationReceipt, ...]
    inference_receipts: tuple[ModelInferenceReceipt, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    environment_lock_verified: bool
    started_at: NonEmptyStr
    finished_at: NonEmptyStr
    worker_pid: int | None = Field(default=None, ge=1)
    host_details: dict[str, Any] = Field(default_factory=dict)


class SkillResult(FrozenModel):
    """Legacy-named certified analysis-execution result envelope."""

    result_id: NonEmptyStr
    invocation_id: NonEmptyStr
    execution_origin: AnalysisExecutionOrigin = "configured_external_skill"
    skill_identity: SkillIdentity | None = None
    generated_program_identity: GeneratedProgramIdentity | None = None
    status: InvocationStatus
    summary: NonEmptyStr
    quantitative_results: tuple[QuantitativeResult, ...] = ()
    artifact_refs: tuple[CertifiedArtifactRef, ...] = ()
    coverage: AnalysisCoverage | None = None
    resource_usage: ResourceUsage
    warnings: tuple[str, ...] = ()
    failure: SkillFailure | None = None
    provenance: SkillExecutionProvenance

    @model_validator(mode="after")
    def validate_outcome(self) -> SkillResult:
        generated = self.execution_origin == "generated_program"
        if generated:
            if self.generated_program_identity is None or self.skill_identity is not None:
                raise ValueError("generated-program result requires only generated identity")
        elif self.skill_identity is None or self.generated_program_identity is not None:
            raise ValueError("skill result requires only skill identity")
        if self.status == "completed":
            if self.coverage is None:
                raise ValueError("completed skill result requires measured coverage")
            if self.failure is not None:
                raise ValueError("completed skill result cannot carry failure")
        elif self.status == "refused":
            if self.coverage is not None:
                raise ValueError("pre-materialization refusal cannot fabricate coverage")
            if self.failure is None or self.failure.materialization_occurred:
                raise ValueError("refused result requires a pre-materialization failure")
        elif self.failure is None:
            raise ValueError(f"{self.status} skill result requires failure details")
        return self


def parameter_schema_sha256(schema: type[BaseModel]) -> str:
    return hashlib.sha256(canonical_json_bytes(schema.model_json_schema())).hexdigest()
