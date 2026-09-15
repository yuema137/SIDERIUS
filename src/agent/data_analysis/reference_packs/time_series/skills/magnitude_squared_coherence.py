"""Magnitude-squared coherence for an explicit channel pair."""

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from scipy import signal

from agent.schemas.data_analysis.skills import SkillPayload

from .._shared import (
    bounded_example_measurements,
    deterministic_peaks,
    information_array,
    series_view,
    spectral_parameters,
    write_json_artifact,
)

SKILL_INSTRUCTIONS = """Use to measure frequency-localized linear dependence between two
channels. The optional reporting threshold is descriptive, not a significance cutoff."""


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    first_channel_id: str = Field(min_length=1, description="First channel in the explicit pair.")
    second_channel_id: str = Field(min_length=1, description="Second channel in the explicit pair.")
    nperseg: int = Field(ge=8, description="Explicit samples per coherence segment.")
    noverlap: int | None = Field(
        default=None, ge=0, description="Overlap in samples; None means 50 percent."
    )
    reporting_threshold: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Descriptive threshold, not a significance cutoff."
    )
    maximum_peaks: int = Field(
        default=8, ge=1, le=64, description="Maximum deterministic coherence peaks to return."
    )

    @model_validator(mode="after")
    def validate_pair(self):
        if self.first_channel_id == self.second_channel_id:
            raise ValueError("coherence requires two distinct channels")
        return self


def run(skill_input, parameters: Parameters, runtime):
    view = series_view(runtime, skill_input)
    channel_map = {str(channel): index for index, channel in enumerate(view.channel_ids)}
    try:
        first_index = channel_map[parameters.first_channel_id]
        second_index = channel_map[parameters.second_channel_id]
    except KeyError as exc:
        raise ValueError(f"requested channel is absent: {exc.args[0]!r}") from exc
    values = information_array(view, "data")
    records = []
    for example_index, example_id in enumerate(view.example_ids):
        first = values[example_index, first_index]
        second = values[example_index, second_index]
        try:
            if (
                not view.is_time_certified_regular(example_index)
                or not np.all(view.valid_mask[example_index])
                or not np.all(np.isfinite(first))
                or not np.all(np.isfinite(second))
            ):
                raise ValueError("pair requires complete finite certified-regular series")
            sample_rate = view.sample_rate_hz(example_index)
            receipt = spectral_parameters(
                parameters.nperseg, parameters.noverlap, len(first), sample_rate
            )
            if receipt["usable_segment_count"] < 2:
                raise ValueError("coherence requires at least two complete segments")
            frequency, coherence = signal.coherence(
                first,
                second,
                fs=sample_rate,
                window="hann_periodic",
                nperseg=parameters.nperseg,
                noverlap=receipt["resolved_noverlap"],
                detrend="constant",
            )
            records.append(
                {
                    "example_id": str(example_id),
                    "frequency_hz": frequency.tolist(),
                    "coherence": coherence.tolist(),
                    "mean_coherence": float(np.mean(coherence)),
                    "peaks": deterministic_peaks(
                        frequency, coherence, maximum=parameters.maximum_peaks
                    ),
                    "frequency_fraction_above_reporting_threshold": float(
                        np.mean(coherence >= parameters.reporting_threshold)
                    ),
                    **receipt,
                    "unusable_reason": None,
                }
            )
        except ValueError as exc:
            records.append({"example_id": str(example_id), "unusable_reason": str(exc)})
    artifact = write_json_artifact(
        runtime,
        "magnitude_squared_coherence.json",
        {
            "ordered_channel_pair": [parameters.first_channel_id, parameters.second_channel_id],
            "reporting_threshold": parameters.reporting_threshold,
            "per_example": records,
        },
        "Magnitude-squared coherence for an explicit channel pair",
    )
    return SkillPayload(
        summary="Measured frequency-domain coherence for the requested channel pair.",
        quantitative_results=bounded_example_measurements(
            records,
            (
                ("mean_coherence", None, "Mean magnitude-squared coherence"),
                (
                    "frequency_fraction_above_reporting_threshold",
                    None,
                    "Frequency-bin fraction above the descriptive threshold",
                ),
            ),
        ),
        produced_artifacts=(artifact,),
    )
