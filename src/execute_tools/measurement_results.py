"""Typed candidate measurement results and their record accessor (#1296).

Measurement values are raw, in the unit fixed by the measurement kind. Their
preference direction belongs to the evaluation component declaration, never to
this module or to a name. Feasibility (#1295) and rubric projection (#1297)
read values through :func:`measurement_value`, which fails closed.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

MeasurementKind = Literal[
    "trainable_parameter_count", "total_parameter_count", "model_bytes", "inference_latency_ms"
]

MEASUREMENT_UNITS: Mapping[str, str] = {
    "trainable_parameter_count": "parameters",
    "total_parameter_count": "parameters",
    "model_bytes": "bytes",
    "inference_latency_ms": "ms",
}


class MeasurementNoise(BaseModel):
    """Dispersion of a repeated measurement; exact quantities report one repeat, zero IQR."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    repeats: int = Field(ge=1)
    iqr: float = Field(ge=0)


class MeasurementResult(BaseModel):
    """One evaluation component's measurement: a finite value or a failure reason."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal["siderius.measurement-result/v1"] = "siderius.measurement-result/v1"
    component_id: str = Field(min_length=1)
    measurement: MeasurementKind
    unit: str
    value: float | None = None
    noise: MeasurementNoise | None = None
    device: str | None = None
    checkpoint_sha256: str | None = None
    failure: str | None = None

    @model_validator(mode="after")
    def one_outcome(self) -> Self:
        if self.unit != MEASUREMENT_UNITS[self.measurement]:
            raise ValueError(f"measurement {self.measurement!r} reports unit {self.unit!r}")
        if (self.value is None) == (self.failure is None):
            raise ValueError("measurement result requires exactly one of value or failure")
        if (self.value is None) != (self.noise is None):
            raise ValueError("measurement noise accompanies a value and only a value")
        return self


class MeasurementUnavailable(ValueError):
    """A required measurement is missing, failed or nonfinite."""


def _raw_results(record: Mapping[str, Any] | BaseModel) -> Any:
    if isinstance(record, BaseModel):
        return getattr(record, "measurement_results", ())
    return record.get("measurement_results") or ()


def record_measurements(record: Mapping[str, Any] | BaseModel) -> dict[str, MeasurementResult]:
    """Measurements keyed by component id; empty for records that carry none."""
    results: dict[str, MeasurementResult] = {}
    for item in _raw_results(record):
        result = MeasurementResult.model_validate(item)
        if result.component_id in results:
            raise ValueError(f"duplicate measurement for component {result.component_id!r}")
        results[result.component_id] = result
    return results


def measurement_value(record: Mapping[str, Any] | BaseModel, component_id: str) -> float:
    """The finite raw value of one component, or raise ``MeasurementUnavailable``."""
    result = record_measurements(record).get(component_id)
    if result is None:
        raise MeasurementUnavailable(f"measurement {component_id!r} was not recorded")
    if result.failure is not None:
        raise MeasurementUnavailable(f"measurement {component_id!r} failed: {result.failure}")
    assert result.value is not None
    if not math.isfinite(result.value):
        raise MeasurementUnavailable(f"measurement {component_id!r} is nonfinite")
    return result.value
