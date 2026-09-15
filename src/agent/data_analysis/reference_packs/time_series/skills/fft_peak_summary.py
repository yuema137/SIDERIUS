"""One-sided coherent-gain-corrected FFT amplitude and peak evidence."""

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from scipy.signal import get_window

from agent.schemas.data_analysis.skills import SkillPayload

from .._shared import (
    aggregate_channel_scalars,
    atomic_series,
    bounded_channel_measurements,
    deterministic_peaks,
    regular_values,
    series_view,
    usable_series_measurement,
    write_json_artifact,
)

SKILL_INSTRUCTIONS = """Use to find deterministic nonzero-frequency peaks and spectral
concentration in real-valued certified regular series. It reports amplitude, not PSD."""


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    maximum_peaks: int = Field(
        default=8, ge=1, le=64, description="Maximum deterministic local maxima to return."
    )
    minimum_frequency_hz: float | None = Field(
        default=None, ge=0.0, description="Optional inclusive lower peak-search frequency in Hz."
    )
    maximum_frequency_hz: float | None = Field(
        default=None, gt=0.0, description="Optional inclusive upper peak-search frequency in Hz."
    )


def run(skill_input, parameters: Parameters, runtime):
    if (
        parameters.minimum_frequency_hz is not None
        and parameters.maximum_frequency_hz is not None
        and parameters.minimum_frequency_hz >= parameters.maximum_frequency_hz
    ):
        raise ValueError("minimum_frequency_hz must be below maximum_frequency_hz")
    view = series_view(runtime, skill_input)
    records = []
    for item in atomic_series(view, "data"):
        try:
            values, sample_rate = regular_values(view, item)
            window = get_window("hann_periodic", len(values), fftbins=True)
            transformed = np.fft.rfft((values - np.mean(values)) * window)
            amplitude = np.abs(transformed) / np.sum(window)
            if len(values) % 2 == 0:
                amplitude[1:-1] *= 2
            else:
                amplitude[1:] *= 2
            frequency = np.fft.rfftfreq(len(values), d=1.0 / sample_rate)
            power = np.square(amplitude)
            nonzero = frequency > 0
            total = float(np.sum(power[nonzero]))
            peaks = deterministic_peaks(
                frequency,
                amplitude,
                maximum=parameters.maximum_peaks,
                minimum_hz=parameters.minimum_frequency_hz,
                maximum_hz=parameters.maximum_frequency_hz,
            )
            records.append(
                {
                    "example_id": item.example_id,
                    "channel_id": item.channel_id,
                    "frequency_hz": frequency.tolist(),
                    "amplitude": amplitude.tolist(),
                    "peaks": peaks,
                    "dominant_frequency_hz": None if not peaks else peaks[0]["frequency_hz"],
                    "spectral_centroid_hz": None
                    if total == 0
                    else float(np.sum(frequency[nonzero] * power[nonzero]) / total),
                    "maximum_bin_power_fraction": None
                    if total == 0
                    else float(np.max(power[nonzero]) / total),
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
        ("dominant_frequency_hz", "spectral_centroid_hz", "maximum_bin_power_fraction"),
    )
    artifact = write_json_artifact(
        runtime,
        "fft_peak_summary.json",
        {"per_series": records, "per_channel": aggregate, "amplitude_unit": "input_unit"},
        "One-sided FFT amplitude and deterministic peaks",
    )
    return SkillPayload(
        summary="Computed one-sided FFT peak evidence for applicable regular series.",
        quantitative_results=(
            usable_series_measurement(records),
            *bounded_channel_measurements(
                aggregate,
                (
                    ("dominant_frequency_hz", "Hz", "Dominant non-DC FFT peak frequency"),
                    ("spectral_centroid_hz", "Hz", "Amplitude-squared spectral centroid"),
                    ("maximum_bin_power_fraction", None, "Maximum-bin power concentration"),
                ),
            ),
        ),
        produced_artifacts=(artifact,),
    )
