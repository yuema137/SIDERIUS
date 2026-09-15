"""Asset descriptors, scope references and authorized materialized views."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import Field, model_validator

from execute_tools.dataset_config import DataScope

from .access import AnalysisAccessPolicy, InformationClass, InformationRequirement
from .common import CertifiedArtifactRef, FrozenModel, NonEmptyStr, Sha256, canonical_sha256
from .resources import CertifiedSelectionIdentity
from .time import TimePrecisionRequirement
from .trained_model import ModelInferenceReceipt, TrainedModelArtifact
from .view_formats import TIMESERIES_ARRAY_V1

AnalysisAssetType = Literal[
    "dataset",
    "trained_model",
    "predictions",
    "residuals",
    "training_history",
    "analysis_artifact",
    "evaluation_artifact",
]
AnalysisOperation = Literal["read", "materialize", "infer"]


class LegacyPartitionScope(FrozenModel):
    kind: Literal["legacy_partitions"] = "legacy_partitions"
    data_scope: DataScope


class TaskOpaqueScopeRef(FrozenModel):
    kind: Literal["task_opaque"] = "task_opaque"
    task_data_path_id: NonEmptyStr
    serialized_scope: NonEmptyStr
    sha256: Sha256

    @model_validator(mode="after")
    def verify_digest(self) -> TaskOpaqueScopeRef:
        observed = hashlib.sha256(self.serialized_scope.encode("utf-8")).hexdigest()
        if observed != self.sha256:
            raise ValueError("task-opaque scope digest does not match serialized_scope")
        return self


class ArtifactIntrinsicScope(FrozenModel):
    kind: Literal["artifact_intrinsic"] = "artifact_intrinsic"
    split_id: NonEmptyStr
    description: NonEmptyStr


AnalysisScopeDescriptor = LegacyPartitionScope | TaskOpaqueScopeRef | ArtifactIntrinsicScope


class TaskDataAssetLocation(FrozenModel):
    kind: Literal["task_data"] = "task_data"
    task_data_path_id: NonEmptyStr
    dataset_profile_sha256: Sha256
    logical_role: NonEmptyStr


class WorkspaceArtifactLocation(FrozenModel):
    kind: Literal["workspace_artifact"] = "workspace_artifact"
    artifact_ref: CertifiedArtifactRef


class TrainedModelArtifactLocation(FrozenModel):
    kind: Literal["trained_model_artifact"] = "trained_model_artifact"
    artifact_ref: CertifiedArtifactRef
    artifact: TrainedModelArtifact

    @model_validator(mode="after")
    def validate_artifact_ref(self) -> TrainedModelArtifactLocation:
        if self.artifact_ref.sha256 != canonical_sha256(self.artifact):
            raise ValueError("trained-model artifact ref does not match the embedded document")
        return self


AnalysisAssetLocation = (
    TaskDataAssetLocation | WorkspaceArtifactLocation | TrainedModelArtifactLocation
)


class AssetProvenance(FrozenModel):
    producer: NonEmptyStr
    run_id: str | None = None
    iteration_id: str | None = None
    source_asset_ids: tuple[NonEmptyStr, ...] = ()
    created_at: str | None = None


class DescriptorMetadataSource(FrozenModel):
    """Lineage needed to prove discovery metadata is policy-safe."""

    information_class: InformationClass
    split_id: str | None = None
    source_fields: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_lineage(self) -> DescriptorMetadataSource:
        if self.information_class == "identity":
            if self.split_id is not None or self.source_fields:
                raise ValueError("identity metadata cannot claim a split or source fields")
        elif self.split_id is None:
            raise ValueError("non-identity discovery metadata requires a split_id")
        if len(set(self.source_fields)) != len(self.source_fields):
            raise ValueError("metadata source fields must be unique")
        return self


class AnalysisAsset(FrozenModel):
    """Small descriptor only; never a carrier for bulk analysis content."""

    asset_id: NonEmptyStr
    asset_type: AnalysisAssetType
    description: NonEmptyStr
    location: AnalysisAssetLocation = Field(discriminator="kind")
    provenance: AssetProvenance
    authorized_scope: AnalysisScopeDescriptor = Field(discriminator="kind")
    split_id: NonEmptyStr
    metadata: dict[NonEmptyStr, Any] = Field(default_factory=dict)
    metadata_sources: dict[NonEmptyStr, DescriptorMetadataSource] = Field(default_factory=dict)
    time_precision_requirement: TimePrecisionRequirement | None = None
    allowed_operations: tuple[AnalysisOperation, ...] = ("read", "materialize")

    @model_validator(mode="after")
    def validate_descriptor(self) -> AnalysisAsset:
        if set(self.metadata) != set(self.metadata_sources):
            raise ValueError("every discovery metadata key requires exactly one metadata source")
        encoded = json.dumps(
            self.metadata,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
        if len(encoded) > 16 * 1024:
            raise ValueError("asset discovery metadata exceeds the 16 KiB descriptor limit")
        if len(set(self.allowed_operations)) != len(self.allowed_operations):
            raise ValueError("asset allowed_operations must be unique")
        if self.asset_type == "trained_model" and not isinstance(
            self.location, TrainedModelArtifactLocation
        ):
            raise ValueError("trained_model assets require a trained_model_artifact location")
        if (
            isinstance(self.authorized_scope, ArtifactIntrinsicScope)
            and self.authorized_scope.split_id != self.split_id
        ):
            raise ValueError("asset split_id must match its artifact-intrinsic scope")
        return self

    def validate_discovery_metadata(self, policy: AnalysisAccessPolicy) -> None:
        policy.rule_for(self.split_id)
        for name, source in self.metadata_sources.items():
            if not policy.permits(
                split_id=source.split_id,
                information_class=source.information_class,
                source_fields=source.source_fields,
            ):
                raise ValueError(
                    f"asset {self.asset_id!r} discovery metadata {name!r} is not visible "
                    f"under access policy {policy.policy_id!r}"
                )


class AnalysisAuthorizationReceipt(FrozenModel):
    invocation_id: NonEmptyStr
    binding_id: NonEmptyStr
    slot_id: NonEmptyStr
    request_digest: Sha256
    policy_digest: Sha256
    asset_digest: Sha256
    decision: Literal["allowed"] = "allowed"
    authorized_at: NonEmptyStr


class MaterializedAnalysisView(FrozenModel):
    """Authorized content reference created for one invocation."""

    materialization_id: NonEmptyStr
    invocation_id: NonEmptyStr
    binding_id: NonEmptyStr
    slot_id: NonEmptyStr
    asset_id: NonEmptyStr
    split_id: NonEmptyStr
    content_ref: CertifiedArtifactRef
    format_id: NonEmptyStr
    time_precision_requirement: TimePrecisionRequirement | None = None
    population_unit: NonEmptyStr
    total_available: int | None = Field(default=None, ge=0)
    materialized_count: int = Field(ge=0)
    certified_information: tuple[InformationRequirement, ...]
    selection_identity: CertifiedSelectionIdentity
    task_data_path_id: str | None = None
    source_digests: tuple[Sha256, ...]
    authorization_receipt: AnalysisAuthorizationReceipt
    historical_inference_receipt: ModelInferenceReceipt | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def validate_counts(self) -> MaterializedAnalysisView:
        if self.time_precision_requirement is not None and self.format_id != TIMESERIES_ARRAY_V1:
            raise ValueError(
                "time_precision_requirement applies only to siderius.timeseries-array.v1"
            )
        if self.total_available is not None and self.materialized_count > self.total_available:
            raise ValueError("materialized_count cannot exceed total_available")
        if self.materialized_count != self.selection_identity.selected_count:
            raise ValueError("materialized_count must match the certified selection count")
        if self.total_available != self.selection_identity.total_available:
            raise ValueError("view population must match the certified selection population")
        classes = [item.information_class for item in self.certified_information]
        if not classes or len(set(classes)) != len(classes):
            raise ValueError("certified information classes must be non-empty and unique")
        receipt = self.authorization_receipt
        if (
            receipt.invocation_id != self.invocation_id
            or receipt.binding_id != self.binding_id
            or receipt.slot_id != self.slot_id
        ):
            raise ValueError("materialized view identity must match its authorization receipt")
        inference = self.historical_inference_receipt
        if inference is not None:
            if inference.status != "completed":
                raise ValueError("prediction view requires a completed inference receipt")
            if inference.prediction_artifact_ref != self.content_ref:
                raise ValueError("inference receipt prediction artifact must match view content")
            if inference.selection_sha256 != self.selection_identity.selection_sha256:
                raise ValueError("inference receipt selection must match the prediction view")
            if inference.prediction_count != self.materialized_count:
                raise ValueError("inference prediction count must match materialized count")
        return self
