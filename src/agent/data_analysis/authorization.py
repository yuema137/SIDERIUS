"""Single generic authorization authority before task-owned materialization."""

from __future__ import annotations

from collections.abc import Mapping

from agent.schemas.data_analysis.assets import (
    AnalysisAsset,
    AnalysisAuthorizationReceipt,
    ArtifactIntrinsicScope,
    LegacyPartitionScope,
    TaskOpaqueScopeRef,
)
from agent.schemas.data_analysis.common import canonical_sha256, utc_now
from agent.schemas.data_analysis.view_formats import TIMESERIES_ARRAY_V1
from execute_tools.analysis_materialization import (
    AnalysisAuthorizationError,
    AnalysisMaterializationRefusal,
    AnalysisMaterializationRequest,
    AuthorizedAnalysisMaterializationRequest,
)


def _refuse(
    request: AnalysisMaterializationRequest,
    code: str,
    message: str,
) -> AnalysisAuthorizationError:
    return AnalysisAuthorizationError(
        AnalysisMaterializationRefusal(
            code=code,  # type: ignore[arg-type]
            message=message,
            request_id=request.request_id,
        )
    )


def _scope_is_contained(request: AnalysisMaterializationRequest) -> bool:
    authorized = request.asset.authorized_scope
    requested = request.requested_scope
    if type(authorized) is not type(requested):
        return False
    if isinstance(authorized, TaskOpaqueScopeRef):
        assert isinstance(requested, TaskOpaqueScopeRef)
        return (
            authorized.task_data_path_id == requested.task_data_path_id
            and authorized.sha256 == requested.sha256
        )
    if isinstance(authorized, ArtifactIntrinsicScope):
        assert isinstance(requested, ArtifactIntrinsicScope)
        return authorized == requested
    if isinstance(authorized, LegacyPartitionScope):
        assert isinstance(requested, LegacyPartitionScope)
        allowed = authorized.data_scope.file_indices
        selected = requested.data_scope.file_indices
        return allowed is None or (selected is not None and set(selected).issubset(allowed))
    return False


def authorize_materialization(
    request: AnalysisMaterializationRequest,
    *,
    available_assets: Mapping[str, AnalysisAsset],
) -> AuthorizedAnalysisMaterializationRequest:
    """Validate all generic policy before a task is allowed to expose content."""

    certified_asset = available_assets.get(request.asset.asset_id)
    if certified_asset is None:
        raise _refuse(request, "asset_not_available", "asset is not in DataAnalysisInput")
    if certified_asset != request.asset:
        raise _refuse(
            request,
            "asset_not_available",
            "requested asset descriptor differs from the certified DataAnalysisInput descriptor",
        )
    if request.operation not in request.asset.allowed_operations:
        raise _refuse(
            request,
            "operation_not_allowed",
            f"operation {request.operation!r} is not granted by the asset descriptor",
        )
    if request.split_id != request.asset.split_id:
        raise _refuse(
            request,
            "split_not_allowed",
            "requested split differs from the asset's certified split",
        )
    expected_precision = (
        request.asset.time_precision_requirement
        if request.requested_format_id == TIMESERIES_ARRAY_V1
        else None
    )
    if request.time_precision_requirement != expected_precision:
        raise _refuse(
            request,
            "materialization_requirement_mismatch",
            "time-precision requirement differs from the certified asset descriptor",
        )
    try:
        request.access_policy.rule_for(request.split_id)
    except ValueError as exc:
        raise _refuse(request, "split_not_allowed", str(exc)) from exc
    for item in request.requested_information:
        if not request.access_policy.permits(
            split_id=request.split_id,
            information_class=item.information_class,
            source_fields=item.fields,
        ):
            raise _refuse(
                request,
                "information_not_visible",
                f"{item.information_class!r} is not visible for split {request.split_id!r}",
            )
    if not _scope_is_contained(request):
        raise _refuse(
            request,
            "scope_not_authorized",
            "requested scope is not contained by the asset's authorized scope",
        )
    if request.operation == "infer":
        if request.asset.asset_type != "trained_model":
            raise _refuse(
                request,
                "operation_not_allowed",
                "historical inference requires a trained-model asset",
            )
        if not request.access_policy.allow_model_inference:
            raise _refuse(
                request,
                "model_inference_not_allowed",
                "active model inference is forbidden by the access policy",
            )
        rule = request.access_policy.rule_for(request.split_id)
        if not rule.data_visible or not rule.predictions_visible:
            raise _refuse(
                request,
                "information_not_visible",
                "historical inference requires both input-data and prediction visibility",
            )
        if tuple(item.information_class for item in request.requested_information) != (
            "prediction",
        ):
            raise _refuse(
                request,
                "information_not_visible",
                "historical inference may materialize only prediction information",
            )

    return AuthorizedAnalysisMaterializationRequest(
        request=request,
        authorization_receipt=AnalysisAuthorizationReceipt(
            invocation_id=request.invocation_id,
            binding_id=request.binding_id,
            slot_id=request.slot_id,
            request_digest=canonical_sha256(request),
            policy_digest=canonical_sha256(request.access_policy),
            asset_digest=canonical_sha256(request.asset),
            authorized_at=utc_now(),
        ),
    )
