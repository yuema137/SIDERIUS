"""Prepare one skill invocation's ordinary and inferred materializations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent.schemas.data_analysis.assets import AnalysisAsset, MaterializedAnalysisView
from agent.schemas.data_analysis.source_scope import AnalysisSourceScope
from agent.schemas.data_analysis.trained_model import ModelInferenceReceipt
from execute_tools.analysis_materialization import TaskAnalysisCapability
from execute_tools.historical_model_inference import HistoricalModelInferenceCapability

from .historical_inference import HistoricalInferenceError, run_historical_inference_binding
from .materialization import (
    authorize_invocation_bindings,
    export_materialized_view_content,
    materialize_authorized_invocation,
)
from .plan_validation import ResolvedAnalysisInvocation, ResolvedPlannedInvocation


@dataclass(frozen=True)
class InvocationMaterializationBundle:
    views: tuple[MaterializedAnalysisView, ...]
    paths: dict[str, str]
    inference_receipts: tuple[ModelInferenceReceipt, ...]
    inspected_asset_ids: tuple[str, ...]


def prepare_invocation_materializations(
    *,
    invocation: ResolvedAnalysisInvocation,
    task_capability: TaskAnalysisCapability,
    inference_capability: HistoricalModelInferenceCapability | None,
    available_assets: dict[str, AnalysisAsset],
    access_policy,
    source_scope: AnalysisSourceScope | None = None,
    resource_envelope,
    deadline_monotonic_s: float,
    destination_root: Path,
) -> InvocationMaterializationBundle:
    """Authorize every output, but expose model inputs only to inference."""

    inference_bindings = [
        binding for binding in invocation.bindings if binding.plan_binding.operation == "infer"
    ]
    if inference_bindings and inference_capability is None:
        raise HistoricalInferenceError(
            "historical inference was planned but no caller capability was supplied",
            refused=True,
        )
    requests = authorize_invocation_bindings(
        invocation,
        available_assets=available_assets,
        access_policy=access_policy,
        source_scope=source_scope,
    )
    ordinary_ids = {
        binding.plan_binding.binding_id
        for binding in invocation.bindings
        if binding.plan_binding.operation != "infer"
    }
    ordinary_requests = tuple(
        request for request in requests if request.request.binding_id in ordinary_ids
    )
    ordinary_views: tuple[MaterializedAnalysisView, ...] = ()
    paths: dict[str, str] = {}
    if ordinary_requests:
        ordinary_views = materialize_authorized_invocation(
            task_capability,
            invocation=invocation,
            requests=ordinary_requests,
        )
        paths.update(
            export_materialized_view_content(
                task_capability,
                views=ordinary_views,
                destination_root=destination_root / "ordinary",
            )
        )

    inferred_views: list[MaterializedAnalysisView] = []
    receipts: list[ModelInferenceReceipt] = []
    inspected_asset_ids = {view.asset_id for view in ordinary_views}
    for binding in inference_bindings:
        assert inference_capability is not None
        if not isinstance(invocation, ResolvedPlannedInvocation):
            raise HistoricalInferenceError(
                "generated-program invocations cannot request historical inference"
            )
        binding_id = binding.plan_binding.binding_id
        view, path = run_historical_inference_binding(
            capability=inference_capability,
            task_capability=task_capability,
            invocation=invocation,
            resolved=binding,
            output_requests=requests,
            available_assets=available_assets,
            access_policy=access_policy,
            source_scope=source_scope,
            input_directory=destination_root / f"{binding_id}-inputs",
            output_directory=destination_root / f"{binding_id}-output",
            resource_envelope=resource_envelope,
            deadline_monotonic_s=deadline_monotonic_s,
        )
        inferred_views.append(view)
        inspected_asset_ids.add(view.asset_id)
        inspected_asset_ids.update(item.asset.asset_id for item in binding.inference_inputs)
        paths[view.binding_id] = path
        assert view.historical_inference_receipt is not None
        receipts.append(view.historical_inference_receipt)

    views = ordinary_views + tuple(inferred_views)
    if not views:
        raise HistoricalInferenceError("invocation produced no materialized skill inputs")
    selections = {view.selection_identity.selection_sha256 for view in views}
    if len(selections) != 1:
        raise HistoricalInferenceError(
            "ordinary and inferred skill inputs do not share one selection identity"
        )
    return InvocationMaterializationBundle(
        views=views,
        paths=paths,
        inference_receipts=tuple(receipts),
        inspected_asset_ids=tuple(sorted(inspected_asset_ids)),
    )
