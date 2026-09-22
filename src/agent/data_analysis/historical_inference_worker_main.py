"""Fixed evaluation-only PyTorch worker for approved registered models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from agent.data_analysis.historical_inference_worker_protocol import (
    HistoricalInferenceWorkerRequest,
    HistoricalInferenceWorkerResponse,
)
from agent.data_analysis.view_formats import NumericArrayView, load_materialized_view
from agent.schemas.data_analysis.common import canonical_json_bytes
from agent.schemas.data_analysis.view_formats import NUMERIC_ARRAY_V1
from agent.schemas.model_io_contract import AxisRole, TensorContract
from core.durable_io import publish_bytes_write_once
from ml_models.models_format_sandbox import get_config_class
from ml_models.models_sandbox import (
    construct_registered_model,
    registered_model_construction_implementation_sha256,
)


def _validate_tensor(array: np.ndarray, contract: TensorContract, *, label: str) -> None:
    if array.ndim != contract.rank:
        raise ValueError(f"{label} rank {array.ndim} differs from {contract.render_shape()}")
    dtype_name = np.dtype(array.dtype).name
    if dtype_name not in contract.dtype.admissible:
        raise ValueError(f"{label} dtype {dtype_name!r} is outside ModelIOContract")
    for index, axis in enumerate(contract.axes):
        fixed = axis.dimension.fixed
        if fixed is not None and array.shape[index] != fixed:
            raise ValueError(f"{label} axis {index} differs from fixed extent {fixed}")
    batch_axes = [index for index, axis in enumerate(contract.axes) if axis.role is AxisRole.BATCH]
    if batch_axes != [0]:
        raise ValueError(f"{label} contract must declare batch as its leading axis")


def _load_model_input(
    request: HistoricalInferenceWorkerRequest,
) -> tuple[NumericArrayView, np.ndarray]:
    model_request = request.request
    if len(model_request.input_views) != 1:
        raise ValueError("registered-model inference v1 accepts one materialized tensor view")
    descriptor = model_request.input_views[0]
    loaded = load_materialized_view(descriptor, Path(request.input_paths[descriptor.binding_id]))
    if not isinstance(loaded, NumericArrayView):
        raise ValueError("registered-model inference v1 requires numeric-array.v1 model input")
    if set(loaded.information) != {"data"}:
        raise ValueError("registered-model inference v1 consumes exactly information.data")
    if loaded.metadata:
        raise ValueError("registered-model inference v1 has no metadata tensor adapter")
    if loaded.valid_mask is not None and not bool(np.all(loaded.valid_mask)):
        raise ValueError("registered-model inference v1 does not silently repair masked inputs")
    values = np.asarray(loaded.information["data"])
    _validate_tensor(values, model_request.model_artifact.model_io_contract.input, label="input")
    batch_axis = model_request.model_artifact.model_io_contract.input.axis_with_role(AxisRole.BATCH)
    if batch_axis is None or values.shape[0] != model_request.selection_identity.selected_count:
        raise ValueError("model input must have a leading batch matching certified selection")
    return loaded, values


def _write_predictions(
    path: Path,
    *,
    example_ids: np.ndarray,
    predictions: np.ndarray,
) -> None:
    if path.exists():
        raise FileExistsError(path)
    with path.open("wb") as handle:
        np.savez(handle, example_ids=example_ids, information__prediction=predictions)


def run_worker(request: HistoricalInferenceWorkerRequest) -> HistoricalInferenceWorkerResponse:
    model_request = request.request
    artifact = model_request.model_artifact
    construction = artifact.model_construction_contract
    if registered_model_construction_implementation_sha256() != construction.implementation_sha256:
        raise ValueError("registered-model construction implementation identity mismatch")
    inference = artifact.model_io_contract.inference
    assert inference is not None
    if inference.prediction_decoder_protocol_id != "siderius.identity-prediction-decoder.v1":
        raise ValueError("registered-model inference v1 does not implement the requested decoder")
    if inference.prediction_output_format != NUMERIC_ARRAY_V1:
        raise ValueError("registered-model inference v1 currently emits numeric-array.v1")
    if any(item.information_class == "metadata" for item in inference.required_information):
        raise ValueError("registered-model inference v1 has no metadata tensor adapter")

    config_payload = json.loads(Path(request.model_config_path).read_text(encoding="utf-8"))
    config_class = get_config_class(artifact.model_plugin_identity.model_type)
    if config_class is None:
        raise ValueError("approved model plugin did not register its config class")
    model_config = config_class.model_validate(config_payload)
    model = construct_registered_model(
        artifact.model_plugin_identity.model_type,
        model_config,
        loss_type=construction.loss_type,
    )
    state_dict = torch.load(request.checkpoint_path, map_location="cpu", weights_only=True)
    from ml_models.target_standardization import (
        load_trained_state,
        target_standardization_implementation_sha256,
    )

    transform_identity = construction.target_standardization_implementation_sha256
    if (
        transform_identity is not None
        and transform_identity != target_standardization_implementation_sha256()
    ):
        raise ValueError("target standardization implementation identity mismatch")
    model = load_trained_state(
        model, state_dict, require_standardized=transform_identity is not None
    )
    device = torch.device("cuda" if model_request.configuration.device == "gpu" else "cpu")
    if device.type == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA inference was requested but no CUDA device is available")
    model.to(device)
    model.eval()
    if model_request.configuration.determinism == "deterministic":
        torch.use_deterministic_algorithms(True)
        # The protocol declares that evaluation has no stochastic semantics.
        # A fixed defensive seed keeps an accidentally random eval-time op
        # from producing different bytes under one scientific identity.
        torch.manual_seed(0)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(0)
    else:
        assert model_request.configuration.seed is not None
        torch.manual_seed(model_request.configuration.seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(model_request.configuration.seed)

    loaded, values = _load_model_input(request)
    chunks: list[np.ndarray] = []
    with torch.inference_mode():
        for start in range(0, len(values), model_request.configuration.batch_size):
            stop = min(len(values), start + model_request.configuration.batch_size)
            tensor = torch.as_tensor(values[start:stop], device=device)
            output = model(tensor)
            if not isinstance(output, torch.Tensor):
                raise ValueError("registered model returned a non-tensor prediction")
            chunks.append(output.detach().cpu().numpy())
    predictions = np.concatenate(chunks, axis=0) if chunks else np.empty((0,), dtype=np.float32)
    _validate_tensor(predictions, artifact.model_io_contract.output, label="prediction")
    if len(predictions) != model_request.selection_identity.selected_count:
        raise ValueError("model output count differs from certified selection")
    _write_predictions(
        Path(request.output_path),
        example_ids=loaded.example_ids,
        predictions=predictions,
    )
    peak_vram = None
    if device.type == "cuda":
        peak_vram = int(torch.cuda.max_memory_allocated(device))
    return HistoricalInferenceWorkerResponse(
        status="completed",
        prediction_count=len(predictions),
        peak_vram_bytes=peak_vram,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--response", required=True)
    args = parser.parse_args()
    response_path = Path(args.response)
    try:
        request = HistoricalInferenceWorkerRequest.model_validate_json(
            Path(args.request).read_bytes()
        )
        response = run_worker(request)
    except Exception as exc:
        response = HistoricalInferenceWorkerResponse(
            status="failed",
            error_type=type(exc).__name__,
            error_message=str(exc) or type(exc).__name__,
        )
    publish_bytes_write_once(str(response_path), canonical_json_bytes(response))
    return 0 if response.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
