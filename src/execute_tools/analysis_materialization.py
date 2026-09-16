"""Authorized task-owned materialization seam for scientific analysis."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from pydantic import Field, model_validator

from agent.schemas.data_analysis.access import AnalysisAccessPolicy, RequestedInformation
from agent.schemas.data_analysis.assets import (
    AnalysisAsset,
    AnalysisAuthorizationReceipt,
    AnalysisOperation,
    AnalysisScopeDescriptor,
    MaterializedAnalysisView,
    TaskDataAssetLocation,
    TaskOpaqueScopeRef,
)
from agent.schemas.data_analysis.common import (
    CertifiedArtifactRef,
    FrozenModel,
    NonEmptyStr,
    canonical_sha256,
)
from agent.schemas.data_analysis.resources import SamplingPolicy
from agent.schemas.data_analysis.time import TimePrecisionRequirement
from agent.schemas.data_analysis.trained_model import TrainedModelArtifact
from agent.schemas.data_analysis.view_formats import TIMESERIES_ARRAY_V1
from execute_tools.dataset_config import DatasetProfile


class AnalysisMaterializationRequest(FrozenModel):
    request_id: NonEmptyStr
    invocation_id: NonEmptyStr
    binding_id: NonEmptyStr
    slot_id: NonEmptyStr
    asset: AnalysisAsset
    split_id: NonEmptyStr
    requested_scope: AnalysisScopeDescriptor = Field(discriminator="kind")
    requested_information: tuple[RequestedInformation, ...]
    requested_format_id: NonEmptyStr
    time_precision_requirement: TimePrecisionRequirement | None = None
    operation: AnalysisOperation
    sampling_policy: SamplingPolicy
    access_policy: AnalysisAccessPolicy

    @model_validator(mode="after")
    def validate_request_shape(self) -> AnalysisMaterializationRequest:
        if not self.requested_information:
            raise ValueError("materialization request requires requested information")
        classes = [item.information_class for item in self.requested_information]
        if len(set(classes)) != len(classes):
            raise ValueError("requested information classes must be unique")
        if (
            self.time_precision_requirement is not None
            and self.requested_format_id != TIMESERIES_ARRAY_V1
        ):
            raise ValueError(
                "time_precision_requirement applies only to siderius.timeseries-array.v1"
            )
        return self


class AuthorizedAnalysisMaterializationRequest(FrozenModel):
    request: AnalysisMaterializationRequest
    authorization_receipt: AnalysisAuthorizationReceipt


class AnalysisMaterializationRefusal(FrozenModel):
    code: Literal[
        "asset_not_available",
        "operation_not_allowed",
        "split_not_allowed",
        "information_not_visible",
        "scope_not_authorized",
        "model_inference_not_allowed",
        "task_capability_unavailable",
        "task_materialization_refused",
        "materialization_requirement_mismatch",
    ]
    message: NonEmptyStr
    request_id: NonEmptyStr
    materialization_occurred: Literal[False] = False


class AnalysisAuthorizationError(ValueError):
    """A request was refused before any analysis content was materialized."""

    def __init__(self, refusal: AnalysisMaterializationRefusal) -> None:
        super().__init__(refusal.message)
        self.refusal = refusal


@runtime_checkable
class TaskAnalysisCapability(Protocol):
    """Optional sibling capability implemented by a bound task data path.

    A task that emits a regular time-axis encoding certifies that it is an
    exact representation compression under the frozen cadence tolerance. This
    seam never authorizes sorting, interpolation, resampling, gap filling, or
    timestamp repair.
    """

    def materialize_analysis_view(
        self,
        request: AuthorizedAnalysisMaterializationRequest,
    ) -> MaterializedAnalysisView: ...

    def export_analysis_materialization(
        self,
        content_ref: CertifiedArtifactRef,
        destination: Path,
    ) -> None:
        """Write the referenced bytes to an executor-owned destination."""
        ...


class HistoricalInferenceInputDerivationRequest(FrozenModel):
    """Verified candidate and caller-declared region for task-owned input geometry.

    The model configuration is the exact UTF-8 JSON payload already certified
    by ``model_artifact.model_config_ref``.  It is supplied as content rather
    than a path so a task adapter cannot gain arbitrary workspace access.
    """

    base_asset: AnalysisAsset
    model_artifact: TrainedModelArtifact
    model_config_json: str = Field(min_length=1)
    dataset_profile_json: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_authorities(self) -> HistoricalInferenceInputDerivationRequest:
        location = self.base_asset.location
        if self.base_asset.asset_type != "dataset" or not isinstance(
            location, TaskDataAssetLocation
        ):
            raise ValueError("historical inference base asset must be task-owned dataset data")
        binding = self.model_artifact.task_inference_binding
        if location.task_data_path_id != binding.task_data_path_id:
            raise ValueError("historical model and base asset use different task data paths")
        profile_payload = self.dataset_profile_json.encode("utf-8")
        if len(profile_payload) > 1024 * 1024:
            raise ValueError("historical inference profile exceeds the 1 MiB request limit")
        if hashlib.sha256(profile_payload).hexdigest() != location.dataset_profile_sha256:
            raise ValueError("historical inference profile differs from base asset source")
        try:
            profile = DatasetProfile.model_validate_json(self.dataset_profile_json)
        except ValueError as exc:
            raise ValueError("historical inference profile is not a valid DatasetProfile") from exc
        if canonical_sha256(profile.to_wire()) != binding.dataset_profile_sha256:
            raise ValueError("historical model and base asset use different dataset profiles")
        payload = self.model_config_json.encode("utf-8")
        if len(payload) > 1024 * 1024:
            raise ValueError("historical model configuration exceeds the 1 MiB request limit")
        ref = self.model_artifact.model_config_ref
        if hashlib.sha256(payload).hexdigest() != ref.sha256:
            raise ValueError("historical model configuration differs from its certified artifact")
        if ref.byte_size is not None and len(payload) != ref.byte_size:
            raise ValueError("historical model configuration byte size differs from its ref")
        try:
            config = json.loads(self.model_config_json)
        except json.JSONDecodeError as exc:
            raise ValueError("historical model configuration is not valid JSON") from exc
        if not isinstance(config, dict):
            raise ValueError("historical model configuration must be a JSON object")
        return self


@runtime_checkable
class TaskHistoricalInferenceInputCapability(Protocol):
    """Optional task-owned sibling for candidate-compatible analysis input.

    Implementations may interpret the *verified* model configuration using
    their own task vocabulary, and must certify that the returned opaque
    scope remains inside ``base_asset.authorized_scope``.  They may not read
    the data, choose a model, authorize information, or change the candidate.
    """

    def derive_historical_inference_input_asset(
        self, request: HistoricalInferenceInputDerivationRequest
    ) -> AnalysisAsset: ...


def validate_derived_historical_inference_input_asset(
    request: HistoricalInferenceInputDerivationRequest,
    asset: AnalysisAsset,
) -> AnalysisAsset:
    """Check generic invariants; region containment is the task's authority."""

    source = request.base_asset
    source_location = source.location
    derived_location = asset.location
    assert isinstance(source_location, TaskDataAssetLocation)
    if asset.asset_type != "dataset" or not isinstance(derived_location, TaskDataAssetLocation):
        raise ValueError("derived historical inference input must be task-owned dataset data")
    if asset.split_id != source.split_id:
        raise ValueError("derived historical inference input changed the authorized split")
    if source.asset_id not in asset.provenance.source_asset_ids:
        raise ValueError("derived historical inference input omitted its base-asset lineage")
    if (
        derived_location.task_data_path_id != source_location.task_data_path_id
        or derived_location.dataset_profile_sha256 != source_location.dataset_profile_sha256
    ):
        raise ValueError("derived historical inference input changed the task data authority")
    if isinstance(asset.authorized_scope, TaskOpaqueScopeRef) and (
        asset.authorized_scope.task_data_path_id != source_location.task_data_path_id
    ):
        raise ValueError("derived historical inference scope belongs to another task")
    if "materialize" not in source.allowed_operations or asset.allowed_operations != (
        "materialize",
    ):
        raise ValueError("derived inference input may grant only materialization already allowed")
    return asset
