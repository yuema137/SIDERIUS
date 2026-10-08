"""Explicit request/source authority for a complete training measurement."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from core.runtime_control.inference_measurement_binding import (
    MeasurementSources,
    measurement_request_digest,
    measurement_sources,
)

if TYPE_CHECKING:
    from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec


class TrainingMeasurementBinding(MeasurementSources):
    version: Literal["training-measurement-v1"] = "training-measurement-v1"
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def validate_training_measurement_request(spec: GpuMeasurementSpec) -> None:
    """Validate the selected protocol, including before an initial binding exists."""
    if spec.phase != "training" or spec.inference_binding or spec.inference_checkpoint:
        raise ValueError("bound training requires training without inference binding/checkpoint")
    bounds = (
        spec.request.deadline_seconds,
        spec.request.sampling_interval_seconds,
        spec.max_phase_seconds,
        spec.sampler_ready_timeout_seconds,
    )
    if any(not math.isfinite(value) or value <= 0 for value in bounds):
        raise ValueError("bound training requires finite positive measurement time bounds")
    reference = spec.task_probe_data
    if reference is None or reference.sampling.data_dir != spec.data_dir:
        raise ValueError("bound training requires a task-owned scope and matching data directory")
    if reference.sampling.epoch_seed is None:
        raise ValueError("bound training requires the resolved training sampling seed")
    if not all(
        (
            spec.sampler_ready_path,
            spec.setup_complete_path,
            spec.phase_complete_path,
            spec.reservation_ack_path,
        )
    ):
        raise ValueError("bound training requires sampler, setup, work and reservation channels")


def training_measurement_binding(
    spec: GpuMeasurementSpec, *, environ: Mapping[str, str] | None = None
) -> TrainingMeasurementBinding:
    validate_training_measurement_request(spec)
    return TrainingMeasurementBinding(
        **(
            measurement_sources() if environ is None else measurement_sources(environ=environ)
        ).model_dump(),
        request_sha256=measurement_request_digest(spec, binding_field="training_binding"),
    )


def bind_training_measurement(
    spec: GpuMeasurementSpec, *, environ: Mapping[str, str] | None = None
) -> GpuMeasurementSpec:
    """Bind a fully prepared request without introducing a validation deadlock."""
    return spec.model_copy(
        update={"training_binding": training_measurement_binding(spec, environ=environ)}
    )
