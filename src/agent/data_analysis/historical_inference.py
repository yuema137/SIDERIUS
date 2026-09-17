"""Orchestrate explicit authorized historical-model inference bindings."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agent.schemas.data_analysis.assets import (
    MaterializedAnalysisView,
    TrainedModelArtifactLocation,
)
from agent.schemas.data_analysis.common import canonical_sha256
from agent.schemas.data_analysis.inference import HistoricalModelInferenceRequest
from agent.schemas.data_analysis.trained_model import ModelInferenceReceipt, TrainedModelArtifactRef
from core.campaign_identity import validate_path_component
from execute_tools.analysis_materialization import (
    AuthorizedAnalysisMaterializationRequest,
    TaskAnalysisCapability,
)
from execute_tools.historical_model_inference import (
    HistoricalInferenceInputPath,
    HistoricalInferenceRuntimeInputs,
    HistoricalModelInferenceCapability,
)

from .materialization import (
    AnalysisMaterializationError,
    authorize_inference_input_bindings,
    export_materialized_view_content,
    materialize_authorized_invocation,
)
from .plan_validation import ResolvedAnalysisInvocation, ResolvedAssetBinding


class HistoricalInferenceError(RuntimeError):
    """A model-inference capability returned a failed or inconsistent receipt."""

    def __init__(
        self,
        message: str,
        *,
        receipt: ModelInferenceReceipt | None = None,
        completed_receipts: tuple[ModelInferenceReceipt, ...] = (),
        refused: bool = False,
    ) -> None:
        super().__init__(message)
        self.receipt = receipt
        self.completed_receipts = tuple(completed_receipts)
        self.refused = refused


def _top_request(
    resolved: ResolvedAssetBinding,
    requests: tuple[AuthorizedAnalysisMaterializationRequest, ...],
) -> AuthorizedAnalysisMaterializationRequest:
    matches = [
        item for item in requests if item.request.binding_id == resolved.plan_binding.binding_id
    ]
    if len(matches) != 1:
        raise HistoricalInferenceError("historical inference lacks one exact output authorization")
    return matches[0]


def _validate_receipt(
    request: HistoricalModelInferenceRequest,
    view: MaterializedAnalysisView,
) -> None:
    receipt = view.historical_inference_receipt
    if receipt is None:
        raise HistoricalInferenceError("prediction view omits its inference receipt")
    artifact = request.model_artifact
    construction = artifact.model_construction_contract
    if receipt.request_sha256 != request.scientific_identity_sha256:
        raise HistoricalInferenceError("inference receipt does not bind the scientific request")
    if receipt.model_artifact_ref != request.model_artifact_ref:
        raise HistoricalInferenceError("inference receipt misstates the trained-model artifact")
    if receipt.checkpoint_sha256 != artifact.checkpoint.ref.sha256:
        raise HistoricalInferenceError("inference receipt misstates the checkpoint")
    if receipt.model_config_sha256 != artifact.model_config_ref.sha256:
        raise HistoricalInferenceError("inference receipt misstates model configuration")
    if receipt.model_plugin_sha256 != artifact.model_plugin_identity.content_sha256:
        raise HistoricalInferenceError("inference receipt misstates model plugin identity")
    if (
        receipt.construction_protocol_id != construction.protocol_id
        or receipt.construction_implementation_sha256 != construction.implementation_sha256
        or receipt.construction_loss_type != construction.loss_type
    ):
        raise HistoricalInferenceError("inference receipt misstates model construction identity")
    inference = artifact.model_io_contract.inference
    assert inference is not None
    if receipt.inference_protocol_id != artifact.inference_protocol_id:
        raise HistoricalInferenceError("inference receipt misstates the inference protocol")
    if receipt.input_materialization_ids != tuple(
        item.materialization_id for item in request.input_views
    ) or receipt.input_materialization_sha256s != tuple(
        item.content_ref.sha256 for item in request.input_views
    ):
        raise HistoricalInferenceError("inference receipt misstates its exact input views")
    if (
        receipt.split_id != request.split_id
        or receipt.scope_sha256 != canonical_sha256(request.requested_scope)
        or receipt.selection_sha256 != request.selection_identity.selection_sha256
    ):
        raise HistoricalInferenceError("inference receipt misstates scope or selection")
    if (
        receipt.prediction_output_format != request.requested_prediction_format
        or receipt.prediction_semantic_id != inference.prediction_semantic_id
    ):
        raise HistoricalInferenceError("inference receipt misstates prediction semantics")
    if (
        receipt.determinism != request.configuration.determinism
        or receipt.seed != request.configuration.seed
    ):
        raise HistoricalInferenceError("inference receipt misstates determinism configuration")
    if receipt.target_exposed_to_inference:
        raise HistoricalInferenceError("historical predictor receipt exposed target information")
    if receipt.prediction_count != request.selection_identity.selected_count:
        raise HistoricalInferenceError("prediction count differs from certified selection")


def run_historical_inference_binding(
    *,
    capability: HistoricalModelInferenceCapability,
    task_capability: TaskAnalysisCapability,
    invocation: ResolvedAnalysisInvocation,
    resolved: ResolvedAssetBinding,
    output_requests: tuple[AuthorizedAnalysisMaterializationRequest, ...],
    available_assets,
    access_policy,
    source_scope=None,
    input_directory: Path,
    output_directory: Path,
    resource_envelope,
    deadline_monotonic_s: float,
) -> tuple[MaterializedAnalysisView, str]:
    """Materialize only explicit inputs, then invoke the injected capability."""

    location = resolved.asset.location
    if not isinstance(location, TrainedModelArtifactLocation):
        raise HistoricalInferenceError("inference binding does not identify a trained model")
    output_authorization = _top_request(resolved, output_requests)
    input_requests = authorize_inference_input_bindings(
        resolved,
        invocation=invocation,
        available_assets=available_assets,
        access_policy=access_policy,
        source_scope=source_scope,
    )
    input_views = materialize_authorized_invocation(
        task_capability,
        invocation=invocation,
        requests=input_requests,
    )
    input_paths = export_materialized_view_content(
        task_capability,
        views=input_views,
        destination_root=input_directory,
    )
    configuration = resolved.plan_binding.inference_configuration
    assert configuration is not None
    request = HistoricalModelInferenceRequest(
        request_id=output_authorization.request.request_id,
        invocation_id=invocation.invocation.invocation_id,
        output_binding_id=resolved.plan_binding.binding_id,
        output_slot_id=resolved.plan_binding.slot_id,
        output_asset_id=resolved.asset.asset_id,
        model_artifact=location.artifact,
        model_artifact_ref=TrainedModelArtifactRef(
            artifact_ref=location.artifact_ref,
            model_artifact_id=location.artifact.model_artifact_id,
            executable_model_identity_sha256=(location.artifact.executable_model_identity_sha256),
        ),
        model_authorization_receipt=output_authorization.authorization_receipt,
        input_views=input_views,
        split_id=invocation.invocation.sampling_plan.split_id,
        requested_scope=invocation.resolved_scope,
        selection_identity=input_views[0].selection_identity,
        requested_prediction_format=resolved.plan_binding.requested_format_id,
        requested_information=resolved.plan_binding.requested_information,
        configuration=configuration,
        resource_envelope=resource_envelope,
        deadline_monotonic_s=deadline_monotonic_s,
    )
    materialization = capability.run_historical_inference(
        request,
        HistoricalInferenceRuntimeInputs(
            paths=tuple(
                HistoricalInferenceInputPath(binding_id=key, path=value)
                for key, value in sorted(input_paths.items())
            )
        ),
    )
    if materialization.receipt.status != "completed" or materialization.view is None:
        raise HistoricalInferenceError(
            "historical inference did not produce a complete prediction artifact",
            receipt=materialization.receipt,
            refused=materialization.receipt.status == "refused",
        )
    view = materialization.view
    try:
        return _certify_and_export_prediction(
            capability=capability,
            request=request,
            view=view,
            expected=output_authorization.request,
            authorization_receipt=output_authorization.authorization_receipt,
            input_views=input_views,
            output_directory=output_directory,
        )
    except Exception as exc:
        # The worker has already produced a certified prediction. Even if a
        # later view/export check fails, the caller must retire that exact
        # output under the run's retention policy.
        raise HistoricalInferenceError(
            str(exc),
            receipt=materialization.receipt,
            completed_receipts=(materialization.receipt,),
        ) from exc


def _certify_and_export_prediction(
    *,
    capability: HistoricalModelInferenceCapability,
    request: HistoricalModelInferenceRequest,
    view: MaterializedAnalysisView,
    expected,
    authorization_receipt,
    input_views: tuple[MaterializedAnalysisView, ...],
    output_directory: Path,
) -> tuple[MaterializedAnalysisView, str]:
    if (
        view.invocation_id != expected.invocation_id
        or view.binding_id != expected.binding_id
        or view.slot_id != expected.slot_id
        or view.asset_id != expected.asset.asset_id
        or view.split_id != expected.split_id
        or view.format_id != expected.requested_format_id
        or view.certified_information != expected.requested_information
        or view.authorization_receipt != authorization_receipt
        or view.selection_identity != input_views[0].selection_identity
    ):
        raise HistoricalInferenceError("prediction view differs from its authorized binding")
    _validate_receipt(request, view)

    output_directory.mkdir(parents=True, exist_ok=False)
    binding_name = validate_path_component(view.binding_id, kind="inference output binding id")
    destination = output_directory / f"{binding_name}.materialized"
    capability.export_historical_prediction(view.content_ref, destination)
    if destination.is_symlink() or not destination.is_file():
        raise HistoricalInferenceError("inference capability did not export a regular file")
    payload = destination.read_bytes()
    if hashlib.sha256(payload).hexdigest() != view.content_ref.sha256:
        raise HistoricalInferenceError("exported prediction digest differs from its receipt")
    if view.content_ref.byte_size is not None and len(payload) != view.content_ref.byte_size:
        raise HistoricalInferenceError("exported prediction size differs from its receipt")
    if canonical_sha256(view.selection_identity) != canonical_sha256(
        input_views[0].selection_identity
    ):
        raise AnalysisMaterializationError("prediction selection identity changed after export")
    return view, str(destination.resolve())
