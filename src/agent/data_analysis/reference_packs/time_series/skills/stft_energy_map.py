"""Time-frequency energy map without boundary synthesis or padding."""

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from scipy import signal

from agent.schemas.data_analysis.skills import SkillPayload

from .._shared import (
    aggregate_channel_scalars,
    atomic_series,
    bounded_channel_measurements,
    regular_values,
    series_view,
    spectral_parameters,
    usable_series_measurement,
    write_json_artifact,
)

SKILL_INSTRUCTIONS = """Use to expose time-varying spectral structure in certified regular
series. It emits a standard STFT energy map; higher-level chirp or morphology interpretation
belongs to synthesis."""


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    nperseg: int = Field(
        ge=8, description="Explicit samples per STFT segment controlling time/frequency resolution."
    )
    noverlap: int | None = Field(
        default=None, ge=0, description="Overlap in samples; None means 50 percent."
    )


def run(skill_input, parameters: Parameters, runtime):
    view = series_view(runtime, skill_input)
    records = []
    for item in atomic_series(view, "data"):
        try:
            values, sample_rate = regular_values(view, item)
            receipt = spectral_parameters(
                parameters.nperseg, parameters.noverlap, len(values), sample_rate
            )
            frequency, centers, transformed = signal.stft(
                values,
                fs=sample_rate,
                window="hann_periodic",
                nperseg=parameters.nperseg,
                noverlap=receipt["resolved_noverlap"],
                detrend="constant",
                return_onesided=True,
                boundary=None,
                padded=False,
                scaling="psd",
            )
            energy = np.square(np.abs(transformed))
            total = float(np.sum(energy))
            threshold = float(np.quantile(energy, 0.9)) if energy.size else 0.0
            active_columns = (
                np.any(energy >= threshold, axis=0) if energy.size else np.asarray([], dtype=bool)
            )
            records.append(
                {
                    "example_id": item.example_id,
                    "channel_id": item.channel_id,
                    "frequency_hz": frequency.tolist(),
                    "time_seconds": (centers + item.time[0]).tolist(),
                    "energy_density": energy.tolist(),
                    "top_decile_energy_fraction": None
                    if total == 0
                    else float(np.sum(energy[energy >= threshold]) / total),
                    "active_duration_fraction": None
                    if not len(active_columns)
                    else float(np.mean(active_columns)),
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
            "top_decile_energy_fraction",
            "active_duration_fraction",
            "frequency_resolution_hz",
            "segment_duration_seconds",
        ),
    )
    artifact = write_json_artifact(
        runtime,
        "stft_energy_map.json",
        {
            "per_series": records,
            "per_channel": aggregate,
            "energy_unit": "input_unit_squared_per_hz",
            "boundary": None,
            "padded": False,
        },
        "STFT time-frequency energy maps",
    )
    return SkillPayload(
        summary="Computed unpadded STFT energy maps for applicable regular series.",
        quantitative_results=(
            usable_series_measurement(records),
            *bounded_channel_measurements(
                aggregate,
                (
                    ("top_decile_energy_fraction", None, "Energy fraction in top-decile cells"),
                    ("active_duration_fraction", None, "Fraction of active STFT time bins"),
                    ("frequency_resolution_hz", "Hz", "Resolved STFT frequency spacing"),
                    ("segment_duration_seconds", "s", "Resolved STFT segment duration"),
                ),
            ),
        ),
        produced_artifacts=(artifact,),
    )
