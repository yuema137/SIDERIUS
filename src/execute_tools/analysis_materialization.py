"""Authorized task-owned materialization seam for scientific analysis."""

from __future__ import annotations

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
)
from agent.schemas.data_analysis.common import CertifiedArtifactRef, FrozenModel, NonEmptyStr
from agent.schemas.data_analysis.resources import SamplingPolicy
from agent.schemas.data_analysis.time import TimePrecisionRequirement
from agent.schemas.data_analysis.view_formats import TIMESERIES_ARRAY_V1


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
