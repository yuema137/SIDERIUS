"""Normalized lag autocorrelation for certified regular series."""

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from agent.schemas.data_analysis.skills import SkillPayload

from .._shared import (
    aggregate_channel_scalars,
    atomic_series,
    bounded_channel_measurements,
    regular_values,
    series_view,
    usable_series_measurement,
    write_json_artifact,
)

SKILL_INSTRUCTIONS = """Use to measure lag memory or repeating structure in a certified regular
series. It returns a normalized descriptive autocorrelation, not confidence intervals."""


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    maximum_lag_samples: int | None = Field(
        default=None,
        ge=1,
        description="Largest lag in samples; None uses the reviewed bounded rule.",
    )


def run(skill_input, parameters: Parameters, runtime):
    view = series_view(runtime, skill_input)
    records = []
    for item in atomic_series(view, "data"):
        try:
            values, sample_rate = regular_values(view, item)
            centered = values - np.mean(values)
            denominator = float(np.dot(centered, centered))
            if denominator == 0:
                raise ValueError("constant series")
            maximum = (
                min((len(values) - 1) // 4, 4096)
                if parameters.maximum_lag_samples is None
                else parameters.maximum_lag_samples
            )
            if maximum < 1 or maximum >= len(values):
                raise ValueError("maximum lag must be between 1 and N-1")
            coefficients = np.asarray(
                [
                    np.dot(centered[:-lag], centered[lag:]) / denominator
                    for lag in range(1, maximum + 1)
                ]
            )
            strongest_index = int(np.argmax(np.abs(coefficients)))
            sign_crossings = np.flatnonzero(np.signbit(coefficients) != np.signbit(1.0))
            decay = np.flatnonzero(np.abs(coefficients) <= np.exp(-1))
            record = {
                "example_id": item.example_id,
                "channel_id": item.channel_id,
                "sample_rate_hz": sample_rate,
                "strongest_lag_samples": strongest_index + 1,
                "strongest_lag_seconds": (strongest_index + 1) / sample_rate,
                "strongest_coefficient": float(coefficients[strongest_index]),
                "first_sign_crossing_samples": None
                if not len(sign_crossings)
                else int(sign_crossings[0] + 1),
                "first_decay_lag_samples": None if not len(decay) else int(decay[0] + 1),
                "coefficients": [1.0, *coefficients.tolist()],
                "unusable_reason": None,
            }
        except ValueError as exc:
            record = {
                "example_id": item.example_id,
                "channel_id": item.channel_id,
                "unusable_reason": str(exc),
            }
        records.append(record)
    aggregate = aggregate_channel_scalars(
        [item for item in records if item["unusable_reason"] is None],
        ("strongest_lag_seconds", "strongest_coefficient"),
    )
    artifact = write_json_artifact(
        runtime,
        "autocorrelation.json",
        {"per_series": records, "per_channel": aggregate},
        "Normalized lag autocorrelation",
    )
    return SkillPayload(
        summary="Computed normalized autocorrelation for applicable regular series.",
        quantitative_results=(
            usable_series_measurement(records),
            *bounded_channel_measurements(
                aggregate,
                (
                    ("strongest_lag_seconds", "s", "Strongest absolute-correlation lag"),
                    ("strongest_coefficient", None, "Signed coefficient at strongest lag"),
                ),
            ),
        ),
        produced_artifacts=(artifact,),
    )
