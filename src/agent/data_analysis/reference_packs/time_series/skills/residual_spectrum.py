"""Welch spectral diagnostics for already-certified residual series."""

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

SKILL_INSTRUCTIONS = """Use to determine whether already-certified model residuals retain
frequency-dependent structure. The skill never constructs residuals or initiates inference."""


class FrequencyBand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, description="Caller-owned stable residual band label.")
    minimum_hz: float = Field(ge=0.0, description="Inclusive lower band frequency in Hz.")
    maximum_hz: float = Field(gt=0.0, description="Upper band frequency in Hz.")


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    nperseg: int = Field(ge=8, description="Explicit samples per residual Welch segment.")
    noverlap: int | None = Field(
        default=None, ge=0, description="Overlap in samples; None means 50 percent."
    )
    maximum_peaks: int = Field(
        default=8, ge=1, le=64, description="Maximum deterministic residual PSD peaks."
    )
    bands: tuple[FrequencyBand, ...] = Field(
        default=(), description="Optional explicit residual frequency bands."
    )


def run(skill_input, parameters: Parameters, runtime):
    view = series_view(runtime, skill_input, "residuals")
    records = []
    for item in atomic_series(view, "residual"):
        try:
            values, sample_rate = regular_values(view, item)
            frequency, density, receipt = welch(
                values, sample_rate, parameters.nperseg, parameters.noverlap
            )
            positive = density[(frequency > 0) & (density > 0)]
            bands = []
            for band in parameters.bands:
                if band.maximum_hz <= band.minimum_hz or band.maximum_hz > sample_rate / 2:
                    raise ValueError(f"invalid residual band {band.name!r}")
                selected = (frequency >= band.minimum_hz) & (frequency < band.maximum_hz)
                if np.count_nonzero(selected) < 2:
                    raise ValueError(f"residual band {band.name!r} is unresolved")
                bands.append(
                    {
                        "name": band.name,
                        "power": float(np.trapezoid(density[selected], frequency[selected])),
                    }
                )
            peaks = deterministic_peaks(frequency, density, maximum=parameters.maximum_peaks)
            records.append(
                {
                    "example_id": item.example_id,
                    "channel_id": item.channel_id,
                    "frequency_hz": frequency.tolist(),
                    "residual_psd_density": density.tolist(),
                    "integrated_residual_power": float(np.trapezoid(density, frequency)),
                    "spectral_flatness": None
                    if not len(positive)
                    else float(np.exp(np.mean(np.log(positive))) / np.mean(positive)),
                    "peaks": peaks,
                    "dominant_frequency_hz": None if not peaks else peaks[0]["frequency_hz"],
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
    aggregate = aggregate_channel_scalars(
        [item for item in records if item["unusable_reason"] is None],
        (
            "dominant_frequency_hz",
            "integrated_residual_power",
            "spectral_flatness",
            "frequency_resolution_hz",
        ),
    )
    artifact = write_json_artifact(
        runtime,
        "residual_spectrum.json",
        {
            "per_series": records,
            "per_channel": aggregate,
            "residual_definition": "task-provenance-owned",
        },
        "Welch residual spectra and structured power summaries",
    )
    return SkillPayload(
        summary="Measured spectral structure in already-certified residual series.",
        quantitative_results=(
            usable_series_measurement(records),
            *bounded_channel_measurements(
                aggregate,
                (
                    ("dominant_frequency_hz", "Hz", "Dominant residual PSD peak frequency"),
                    (
                        "integrated_residual_power",
                        "residual_unit_squared",
                        "Integrated residual PSD power",
                    ),
                    ("spectral_flatness", None, "Residual PSD spectral flatness"),
                ),
            ),
        ),
        produced_artifacts=(artifact,),
    )
