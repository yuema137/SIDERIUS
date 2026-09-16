"""One-sided Welch power spectral density with explicit resolution."""

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from agent.schemas.data_analysis.skills import SkillPayload

from .._shared import (
    aggregate_channel_scalars,
    atomic_series,
    bounded_channel_measurements,
    deterministic_peaks,
    regular_values,
    series_view,
    usable_series_measurement,
    welch,
    write_json_artifact,
)

SKILL_INSTRUCTIONS = """Use to estimate broadband and narrowband power density for certified
regular real-valued series. nperseg is required so physical frequency resolution is explicit."""


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    nperseg: int = Field(ge=8, description="Explicit samples per Welch segment.")
    noverlap: int | None = Field(
        default=None, ge=0, description="Overlap in samples; None resolves to floor(nperseg/2)."
    )
    maximum_peaks: int = Field(
        default=8, ge=1, le=64, description="Maximum deterministic PSD peaks to return."
    )
    minimum_frequency_hz: float | None = Field(
        default=None, ge=0.0, description="Optional inclusive lower peak-search frequency in Hz."
    )
    maximum_frequency_hz: float | None = Field(
        default=None, gt=0.0, description="Optional inclusive upper peak-search frequency in Hz."
    )


def run(skill_input, parameters: Parameters, runtime):
    view = series_view(runtime, skill_input)
    records = []
    for item in atomic_series(view, "data"):
        try:
            values, sample_rate = regular_values(view, item)
            frequency, density, receipt = welch(
                values, sample_rate, parameters.nperseg, parameters.noverlap
            )
            peaks = deterministic_peaks(
                frequency,
                density,
                maximum=parameters.maximum_peaks,
                minimum_hz=parameters.minimum_frequency_hz,
                maximum_hz=parameters.maximum_frequency_hz,
            )
            records.append(
                {
                    "example_id": item.example_id,
                    "channel_id": item.channel_id,
                    "frequency_hz": frequency.tolist(),
                    "psd_density": density.tolist(),
                    "integrated_power": float(np.trapezoid(density, frequency)),
                    "peaks": peaks,
                    "dominant_frequency_hz": None if not peaks else peaks[0]["frequency_hz"],
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
    aggregate = aggregate_channel_scalars(
        [item for item in records if item["unusable_reason"] is None],
        ("dominant_frequency_hz", "integrated_power", "frequency_resolution_hz"),
    )
    artifact = write_json_artifact(
        runtime,
        "welch_psd.json",
        {
            "per_series": records,
            "per_channel": aggregate,
            "psd_unit": "input_unit_squared_per_hz",
        },
        "Welch PSD estimates and resolution receipts",
    )
    return SkillPayload(
        summary="Estimated one-sided Welch PSD for applicable regular series.",
        quantitative_results=(
            usable_series_measurement(records),
            *bounded_channel_measurements(
                aggregate,
                (
                    ("dominant_frequency_hz", "Hz", "Dominant Welch PSD peak frequency"),
                    ("integrated_power", "input_unit_squared", "Integrated one-sided PSD power"),
                    ("frequency_resolution_hz", "Hz", "Resolved Welch frequency spacing"),
                ),
            ),
        ),
        produced_artifacts=(artifact,),
    )
