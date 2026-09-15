"""Lomb-Scargle power on an explicit caller-selected frequency grid."""

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from scipy import signal

from agent.schemas.data_analysis.skills import SkillPayload

from .._shared import (
    aggregate_channel_scalars,
    atomic_series,
    bounded_channel_measurements,
    deterministic_peaks,
    series_view,
    usable_series_measurement,
    write_json_artifact,
)

SKILL_INSTRUCTIONS = """Use for periodic structure in irregularly sampled data. The frequency
grid is explicit; the skill uses a floating mean and normalized power but reports no FAP."""


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum_frequency_hz: float = Field(gt=0.0, description="Inclusive lower grid frequency in Hz.")
    maximum_frequency_hz: float = Field(gt=0.0, description="Inclusive upper grid frequency in Hz.")
    frequency_count: int = Field(
        ge=16,
        le=1_000_000,
        description="Number of linearly spaced frequencies in the explicit grid.",
    )
    maximum_peaks: int = Field(
        default=8, ge=1, le=64, description="Maximum deterministic local maxima to return."
    )


def run(skill_input, parameters: Parameters, runtime):
    if parameters.maximum_frequency_hz <= parameters.minimum_frequency_hz:
        raise ValueError("maximum_frequency_hz must exceed minimum_frequency_hz")
    view = series_view(runtime, skill_input)
    frequency = np.linspace(
        parameters.minimum_frequency_hz, parameters.maximum_frequency_hz, parameters.frequency_count
    )
    angular = 2 * np.pi * frequency
    records = []
    for item in atomic_series(view, "data"):
        selected = item.mask & np.isfinite(item.time) & np.isfinite(item.values)
        time = item.time[selected]
        values = item.values[selected]
        if len(time) < 3 or np.ptp(time) == 0 or np.ptp(values) == 0:
            records.append(
                {
                    "example_id": item.example_id,
                    "channel_id": item.channel_id,
                    "unusable_reason": "requires at least three finite varying samples",
                }
            )
            continue
        power = signal.lombscargle(time, values, angular, normalize=True, floating_mean=True)
        peaks = deterministic_peaks(frequency, power, maximum=parameters.maximum_peaks)
        records.append(
            {
                "example_id": item.example_id,
                "channel_id": item.channel_id,
                "frequency_hz": frequency.tolist(),
                "normalized_power": power.tolist(),
                "peaks": peaks,
                "dominant_frequency_hz": None if not peaks else peaks[0]["frequency_hz"],
                "dominant_normalized_power": None if not peaks else peaks[0]["value"],
                "effective_sample_count": len(values),
                "dropped_sample_count": int(len(item.values) - len(values)),
                "unusable_reason": None,
            }
        )
    aggregate = aggregate_channel_scalars(
        [item for item in records if item["unusable_reason"] is None],
        ("dominant_frequency_hz", "dominant_normalized_power"),
    )
    artifact = write_json_artifact(
        runtime,
        "lomb_scargle_periodogram.json",
        {
            "per_series": records,
            "per_channel": aggregate,
            "normalization": "normalized",
            "false_alarm_probability": None,
        },
        "Lomb-Scargle normalized power on the explicit frequency grid",
    )
    return SkillPayload(
        summary="Computed Lomb-Scargle periodicity evidence on an explicit grid.",
        quantitative_results=(
            usable_series_measurement(records),
            *bounded_channel_measurements(
                aggregate,
                (
                    ("dominant_frequency_hz", "Hz", "Dominant Lomb-Scargle peak frequency"),
                    ("dominant_normalized_power", None, "Dominant normalized periodogram power"),
                ),
            ),
        ),
        produced_artifacts=(artifact,),
    )
