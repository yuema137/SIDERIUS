"""Build authorized requests and verify task-owned materialized views."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agent.schemas.data_analysis.assets import AnalysisAsset, MaterializedAnalysisView
from agent.schemas.data_analysis.common import canonical_sha256
from agent.schemas.data_analysis.time import TaskProvidedTimePrecisionRequirement
from agent.schemas.data_analysis.view_formats import TIMESERIES_ARRAY_V1
from core.campaign_identity import validate_path_component
from execute_tools.analysis_materialization import (
    AnalysisMaterializationRequest,
    AuthorizedAnalysisMaterializationRequest,
    TaskAnalysisCapability,
)

from .authorization import authorize_materialization
from .plan_validation import ResolvedAnalysisInvocation, ResolvedAssetBinding


class AnalysisMaterializationError(ValueError):
    """A task capability returned a view broader or different than authorized."""


def export_materialized_view_content(
    capability: TaskAnalysisCapability,
    *,
    views: tuple[MaterializedAnalysisView, ...],
    destination_root: Path,
) -> dict[str, str]:
    """Export task-owned content into verified executor-owned files."""

    destination_root.mkdir(parents=True, exist_ok=False)
    paths: dict[str, str] = {}
    for view in views:
        binding_name = validate_path_component(
            view.binding_id, kind="analysis materialization binding id"
        )
        destination = destination_root / f"{binding_name}.materialized"
        capability.export_analysis_materialization(view.content_ref, destination)
        if destination.is_symlink() or not destination.is_file():
            raise AnalysisMaterializationError(
                "task capability did not export a regular non-symlink materialization"
            )
        payload = destination.read_bytes()
        if view.content_ref.byte_size is not None and len(payload) != view.content_ref.byte_size:
            raise AnalysisMaterializationError(
                "exported materialization byte size differs from its certified ref"
            )
        if hashlib.sha256(payload).hexdigest() != view.content_ref.sha256:
            raise AnalysisMaterializationError(
                "exported materialization digest differs from its certified ref"
            )
        paths[view.binding_id] = str(destination.resolve())
    return paths


def authorize_invocation_bindings(
    invocation: ResolvedAnalysisInvocation,
    *,
    available_assets: dict[str, AnalysisAsset],
    access_policy,
) -> tuple[AuthorizedAnalysisMaterializationRequest, ...]:
    authorized: list[AuthorizedAnalysisMaterializationRequest] = []
    for resolved in invocation.bindings:
        binding = resolved.plan_binding
        request = AnalysisMaterializationRequest(
            request_id=f"{invocation.invocation.invocation_id}.{binding.binding_id}",
            invocation_id=invocation.invocation.invocation_id,
            binding_id=binding.binding_id,
            slot_id=binding.slot_id,
            asset=resolved.asset,
            split_id=invocation.invocation.sampling_plan.split_id,
            requested_scope=invocation.invocation.sampling_plan.requested_scope,
            requested_information=binding.requested_information,
            requested_format_id=binding.requested_format_id,
            time_precision_requirement=(
                resolved.asset.time_precision_requirement
                if binding.requested_format_id == TIMESERIES_ARRAY_V1
                else None
            ),
            operation=binding.operation,
            sampling_policy=invocation.invocation.sampling_plan.policy,
            access_policy=access_policy,
        )
        authorized.append(authorize_materialization(request, available_assets=available_assets))
    return tuple(authorized)


def authorize_inference_input_bindings(
    resolved: ResolvedAssetBinding,
    *,
    invocation: ResolvedAnalysisInvocation,
    available_assets: dict[str, AnalysisAsset],
    access_policy,
) -> tuple[AuthorizedAnalysisMaterializationRequest, ...]:
    """Authorize the explicit plan-visible inputs of one model inference binding."""

    authorized: list[AuthorizedAnalysisMaterializationRequest] = []
    for item in resolved.inference_inputs:
        binding = item.plan_binding
        request = AnalysisMaterializationRequest(
            request_id=(
                f"{invocation.invocation.invocation_id}."
                f"{resolved.plan_binding.binding_id}.{binding.binding_id}"
            ),
            invocation_id=invocation.invocation.invocation_id,
            binding_id=binding.binding_id,
            slot_id=f"{resolved.plan_binding.slot_id}.inference_input",
            asset=item.asset,
            split_id=invocation.invocation.sampling_plan.split_id,
            requested_scope=invocation.invocation.sampling_plan.requested_scope,
            requested_information=binding.requested_information,
            requested_format_id=binding.requested_format_id,
            time_precision_requirement=(
                item.asset.time_precision_requirement
                if binding.requested_format_id == TIMESERIES_ARRAY_V1
                else None
            ),
            operation="materialize",
            sampling_policy=invocation.invocation.sampling_plan.policy,
            access_policy=access_policy,
        )
        authorized.append(authorize_materialization(request, available_assets=available_assets))
    return tuple(authorized)


def materialize_authorized_invocation(
    capability: TaskAnalysisCapability,
    *,
    invocation: ResolvedAnalysisInvocation,
    requests: tuple[AuthorizedAnalysisMaterializationRequest, ...],
) -> tuple[MaterializedAnalysisView, ...]:
    """Materialize bindings, then require one exact shared selection identity."""

    expected = {item.request.binding_id: item for item in requests}
    views = tuple(capability.materialize_analysis_view(item) for item in requests)
    if len(views) != len(expected):
        raise AnalysisMaterializationError("task capability returned the wrong number of views")
    seen: set[str] = set()
    selection_digests: set[str] = set()
    for view in views:
        if view.binding_id in seen or view.binding_id not in expected:
            raise AnalysisMaterializationError("task capability returned an unknown binding")
        seen.add(view.binding_id)
        authorized = expected[view.binding_id]
        request = authorized.request
        if view.authorization_receipt != authorized.authorization_receipt:
            raise AnalysisMaterializationError("materialized view does not echo its authorization")
        if (
            view.invocation_id != request.invocation_id
            or view.slot_id != request.slot_id
            or view.asset_id != request.asset.asset_id
            or view.split_id != request.split_id
        ):
            raise AnalysisMaterializationError(
                "materialized view identity differs from its request"
            )
        if view.format_id != request.requested_format_id:
            raise AnalysisMaterializationError(
                "task capability returned an unrequested view format"
            )
        if view.time_precision_requirement != request.time_precision_requirement:
            raise AnalysisMaterializationError(
                "materialized view does not preserve its time-precision requirement"
            )
        if view.certified_information != request.requested_information:
            raise AnalysisMaterializationError(
                "task capability returned information different from the authorized request"
            )
        if view.selection_identity.sampling_policy_sha256 != canonical_sha256(
            request.sampling_policy
        ):
            raise AnalysisMaterializationError(
                "selection identity does not bind the sampling policy"
            )
        if (
            view.selection_identity.sampling_mode != request.sampling_policy.mode
            or view.selection_identity.sampling_strategy != request.sampling_policy.strategy
            or view.selection_identity.sampling_seed != request.sampling_policy.seed
        ):
            raise AnalysisMaterializationError("selection identity misstates the sampling policy")
        precision = request.time_precision_requirement
        if (
            isinstance(precision, TaskProvidedTimePrecisionRequirement)
            and precision.source_sha256 not in view.source_digests
        ):
            raise AnalysisMaterializationError(
                "materialized view provenance omits its time-precision authority"
            )
        selection_digests.add(view.selection_identity.selection_sha256)
    if seen != set(expected):
        raise AnalysisMaterializationError("task capability omitted an authorized binding")
    if len(selection_digests) != 1:
        raise AnalysisMaterializationError(
            "row-aligned invocation bindings do not share one certified selection"
        )
    return views
