"""Power in explicit physical-frequency bands using the reviewed Welch estimator."""

from itertools import pairwise

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.schemas.data_analysis.skills import QuantitativeResult, SkillPayload

from .._shared import (
    atomic_series,
    regular_values,
    series_view,
    usable_series_measurement,
    welch,
    write_json_artifact,
)

SKILL_INSTRUCTIONS = """Use to quantify absolute and fractional power in caller-specified,
nonoverlapping frequency bands. It uses the same explicit-resolution Welch estimator."""


class FrequencyBand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, description="Caller-owned stable band label.")
    minimum_hz: float = Field(ge=0.0, description="Inclusive lower frequency in Hz.")
    maximum_hz: float = Field(gt=0.0, description="Upper frequency in Hz; Nyquist is inclusive.")

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.maximum_hz <= self.minimum_hz:
            raise ValueError("frequency band maximum must exceed minimum")
        return self


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    nperseg: int = Field(ge=8, description="Explicit samples per Welch segment.")
    noverlap: int | None = Field(
        default=None, ge=0, description="Overlap in samples; None means 50 percent."
    )
    bands: tuple[FrequencyBand, ...] = Field(
        min_length=1, max_length=32, description="Ordered, nonoverlapping physical-frequency bands."
    )

    @model_validator(mode="after")
    def validate_bands(self):
        if len({band.name for band in self.bands}) != len(self.bands):
            raise ValueError("frequency band names must be unique")
        ordered = sorted(self.bands, key=lambda item: item.minimum_hz)
        if any(right.minimum_hz < left.maximum_hz for left, right in pairwise(ordered)):
            raise ValueError("frequency bands must not overlap")
        return self


def run(skill_input, parameters: Parameters, runtime):
    view = series_view(runtime, skill_input)
    records = []
    for item in atomic_series(view, "data"):
        try:
            values, sample_rate = regular_values(view, item)
            nyquist = sample_rate / 2
            if any(band.maximum_hz > nyquist for band in parameters.bands):
                raise ValueError("frequency band exceeds Nyquist")
            frequency, density, receipt = welch(
                values, sample_rate, parameters.nperseg, parameters.noverlap
            )
            total = float(np.trapezoid(density, frequency))
            bands = []
            for band in parameters.bands:
                selected = (frequency >= band.minimum_hz) & (
                    frequency <= band.maximum_hz
                    if band.maximum_hz == nyquist
                    else frequency < band.maximum_hz
                )
                if np.count_nonzero(selected) < 2:
                    raise ValueError(f"band {band.name!r} is unresolved by the selected nperseg")
                power = float(np.trapezoid(density[selected], frequency[selected]))
                bands.append(
                    {
                        "name": band.name,
                        "minimum_hz": band.minimum_hz,
                        "maximum_hz": band.maximum_hz,
                        "power": power,
                        "fraction_of_total": None if total == 0 else power / total,
                    }
                )
            records.append(
                {
                    "example_id": item.example_id,
                    "channel_id": item.channel_id,
                    "total_power": total,
                    "bands": bands,
                    **receipt,
                    "unusable_reason": None,
                }
            )
        except ValueError as exc:
            records.append(
                {
                    "example_id": item.example_id,
                    "channel_id": item.channel_id,
                    "unusable_reason": str(exc),
                }
            )
    measurements = [usable_series_measurement(records)]
    for channel_id in sorted({item["channel_id"] for item in records if "channel_id" in item}):
        channel_records = [
            item
            for item in records
            if item.get("channel_id") == channel_id and item["unusable_reason"] is None
        ]
        for band in parameters.bands:
            values = [
                candidate
                for item in channel_records
                for candidate in item["bands"]
                if candidate["name"] == band.name
            ]
            if not values:
                continue
            measurements.append(
                QuantitativeResult(
                    result_key=f"channel.{channel_id}.band.{band.name}.power.mean",
                    value=float(np.mean([item["power"] for item in values])),
                    unit="input_unit_squared",
                    description="Equal-example mean Welch-integrated power in the requested band",
                )
            )
            fractions = [item["fraction_of_total"] for item in values]
            if all(item is not None for item in fractions):
                measurements.append(
                    QuantitativeResult(
                        result_key=f"channel.{channel_id}.band.{band.name}.fraction.mean",
                        value=float(np.mean(fractions)),
                        description="Equal-example mean fraction of total power in the requested band",
                    )
                )
            if len(measurements) >= 25:
                break
        if len(measurements) >= 25:
            break
    artifact = write_json_artifact(
        runtime,
        "band_power_summary.json",
        {"per_series": records, "power_unit": "input_unit_squared"},
        "Welch-integrated power in explicit physical-frequency bands",
    )
    return SkillPayload(
        summary="Measured power in explicitly requested frequency bands.",
        quantitative_results=tuple(measurements),
        produced_artifacts=(artifact,),
    )
