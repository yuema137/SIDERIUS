"""Builtin measurements of the serialized trained checkpoint, run in the scoring child.

#1296. The parent writes a validated :class:`MeasurementRequest`; the native
task-owned scoring child calls :func:`measure_components` after source metrics
and before formula aggregation. Every failure becomes a typed failure result:
a measurement never raises out of the child, and a failed measurement that a
formula term needs makes the candidate not scoreable through aggregation.
Latency is a dedicated timed-forward protocol, never inference-phase wall time.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from execute_tools.evaluation_spec import LatencyProtocol, MeasurementComponent
from execute_tools.measurement_results import (
    MEASUREMENT_UNITS,
    MeasurementNoise,
    MeasurementResult,
)


class MeasurementRequest(BaseModel):
    """Parent-written reconstruction inputs for the attempt's serialized checkpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_type: str = Field(min_length=1)
    experiment_id: str = Field(min_length=1)
    model_configuration: dict[str, JsonValue]
    loss_type: str = Field(min_length=1)
    checkpoint_path: str = Field(min_length=1)
    model_io_json: str | None = None


def read_measurement_request(path: str) -> MeasurementRequest:
    with open(path, encoding="utf-8") as handle:
        return MeasurementRequest.model_validate(json.load(handle))


def _percentile(ordered: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile of an ascending sequence."""
    position = (len(ordered) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def time_forward(
    forward: Callable[[], Any],
    protocol: LatencyProtocol,
    *,
    synchronize: Callable[[], None] = lambda: None,
    clock: Callable[[], float] = time.perf_counter,
) -> tuple[float, MeasurementNoise]:
    """Median and IQR (ms) of ``repeats`` timed forwards after ``warmup`` untimed ones."""
    deadline = clock() + protocol.timeout_seconds
    for _ in range(protocol.warmup):
        forward()
        if clock() > deadline:
            raise TimeoutError("latency warm-up exceeded timeout_seconds")
    synchronize()
    samples: list[float] = []
    for _ in range(protocol.repeats):
        started = clock()
        forward()
        synchronize()
        ended = clock()
        samples.append((ended - started) * 1000.0)
        if ended > deadline:
            raise TimeoutError("latency repeats exceeded timeout_seconds")
    ordered = sorted(samples)
    iqr = _percentile(ordered, 0.75) - _percentile(ordered, 0.25)
    return _percentile(ordered, 0.5), MeasurementNoise(repeats=len(ordered), iqr=iqr)


class _LoadedCandidate:
    """Lazily load the checkpoint once for every component that needs the model."""

    def __init__(self, request: MeasurementRequest):
        self.request = request
        self._model: Any = None
        self.contract: Any = None
        self.device = "cpu"

    def model(self) -> Any:
        if self._model is None:
            import torch

            from agent.schemas.model_io_contract import ModelIOContract
            from execute_tools.inference_checkpoint import load_inference_checkpoint
            from execute_tools.inference_model import construct_inference_model

            request = self.request
            contract = None
            if request.model_io_json is not None:
                with open(request.model_io_json, encoding="utf-8") as handle:
                    contract = ModelIOContract.model_validate(json.load(handle))
            self.contract = contract
            model, _config = construct_inference_model(
                request.model_type,
                dict(request.model_configuration),
                model_io_contract=contract,
                loss_type=request.loss_type,
            )
            model = load_inference_checkpoint(model, request.checkpoint_path, request.experiment_id)
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model = model.to(self.device).eval()
        return self._model


def _input_tensor(loaded: _LoadedCandidate, shape: Sequence[int]) -> Any:
    import torch

    from execute_tools.model_input_dtype import resolve_inference_input_dtype

    dtype = resolve_inference_input_dtype(loaded.request.model_type, loaded.contract)
    generator = torch.Generator().manual_seed(0)
    if dtype is not None and not dtype.is_floating_point:
        tensor = torch.zeros(tuple(shape), dtype=dtype)
    else:
        tensor = torch.randn(tuple(shape), generator=generator, dtype=dtype or torch.float32)
    return tensor.to(loaded.device)


def _measure(
    component: MeasurementComponent, loaded: _LoadedCandidate
) -> tuple[float, MeasurementNoise]:
    exact = MeasurementNoise(repeats=1, iqr=0.0)
    if component.measurement == "model_bytes":
        return float(os.path.getsize(loaded.request.checkpoint_path)), exact
    model = loaded.model()
    if component.measurement == "trainable_parameter_count":
        return float(sum(p.numel() for p in model.parameters() if p.requires_grad)), exact
    if component.measurement == "total_parameter_count":
        return float(sum(p.numel() for p in model.parameters())), exact
    import torch

    assert component.protocol is not None
    batch = _input_tensor(loaded, component.protocol.input_shape)
    synchronize = torch.cuda.synchronize if loaded.device == "cuda" else (lambda: None)

    def forward() -> None:
        with torch.inference_mode():
            model(batch)

    return time_forward(forward, component.protocol, synchronize=synchronize)


def _checkpoint_sha256(path: str) -> str | None:
    from core.stream_identity import stream_file_identity

    try:
        with open(path, "rb") as handle:
            digest, _size = stream_file_identity(handle)
        return digest
    except OSError:
        return None


def measure_components(
    components: Sequence[MeasurementComponent], request: MeasurementRequest
) -> list[MeasurementResult]:
    """One result per component, in declaration order; failures are recorded, not raised."""
    if not components:
        return []
    loaded = _LoadedCandidate(request)
    checkpoint = _checkpoint_sha256(request.checkpoint_path)
    results: list[MeasurementResult] = []
    for component in components:
        unit = MEASUREMENT_UNITS[component.measurement]
        try:
            value, noise = _measure(component, loaded)
            if not math.isfinite(value):
                raise ValueError("measurement produced a nonfinite value")
            result = MeasurementResult(
                component_id=component.id,
                measurement=component.measurement,
                unit=unit,
                value=value,
                noise=noise,
                device=loaded.device,
                checkpoint_sha256=checkpoint,
            )
        except Exception as error:  # every failure is typed evidence, never a crash
            from core.local_code.failure import raise_if_code_package_failure

            raise_if_code_package_failure(error)
            result = MeasurementResult(
                component_id=component.id,
                measurement=component.measurement,
                unit=unit,
                device=loaded.device,
                checkpoint_sha256=checkpoint,
                failure=f"{type(error).__name__}: {error}",
            )
        results.append(result)
    return results
