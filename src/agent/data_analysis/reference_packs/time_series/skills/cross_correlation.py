"""Lagged correlation for an explicit ordered channel pair."""

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.schemas.data_analysis.skills import SkillPayload

from .._shared import (
    bounded_example_measurements,
    information_array,
    series_view,
    write_json_artifact,
)

SKILL_INSTRUCTIONS = """Use to measure whether one channel follows another at a lag. Specify
an ordered pair; positive lag means the second channel lags the first channel."""


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    first_channel_id: str = Field(
        min_length=1, description="Reference channel in the ordered pair."
    )
    second_channel_id: str = Field(
        min_length=1, description="Channel whose positive lag means it follows the first."
    )
    maximum_lag_samples: int = Field(ge=1, description="Symmetric maximum lag in samples.")

    @model_validator(mode="after")
    def validate_pair(self):
        if self.first_channel_id == self.second_channel_id:
            raise ValueError("cross_correlation requires two distinct channels")
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
        if (
            not view.is_time_certified_regular(example_index)
            or not np.all(view.valid_mask[example_index])
            or not np.all(np.isfinite(first))
            or not np.all(np.isfinite(second))
        ):
            records.append(
                {
                    "example_id": str(example_id),
                    "unusable_reason": "pair requires complete finite certified-regular series",
                }
            )
            continue
        if parameters.maximum_lag_samples >= len(first):
            records.append(
                {
                    "example_id": str(example_id),
                    "unusable_reason": "maximum lag must be smaller than sequence length",
                }
            )
            continue
        first = first - np.mean(first)
        second = second - np.mean(second)
        denominator = float(np.linalg.norm(first) * np.linalg.norm(second))
        if denominator == 0:
            records.append({"example_id": str(example_id), "unusable_reason": "constant channel"})
            continue
        lags = np.arange(-parameters.maximum_lag_samples, parameters.maximum_lag_samples + 1)
        coefficients = []
        for lag in lags:
            if lag > 0:
                numerator = np.dot(first[:-lag], second[lag:])
            elif lag < 0:
                numerator = np.dot(first[-lag:], second[:lag])
            else:
                numerator = np.dot(first, second)
            coefficients.append(float(numerator / denominator))
        peak_index = int(np.argmax(np.abs(coefficients)))
        sample_rate = view.sample_rate_hz(example_index)
        records.append(
            {
                "example_id": str(example_id),
                "first_channel_id": parameters.first_channel_id,
                "second_channel_id": parameters.second_channel_id,
                "lag_samples": lags.tolist(),
                "correlation": coefficients,
                "peak_lag_samples": int(lags[peak_index]),
                "peak_lag_seconds": float(lags[peak_index] / sample_rate),
                "peak_correlation": coefficients[peak_index],
                "lag_sign_convention": "positive means second channel lags first",
                "unusable_reason": None,
            }
        )
    artifact = write_json_artifact(
        runtime,
        "cross_correlation.json",
        {
            "ordered_channel_pair": [parameters.first_channel_id, parameters.second_channel_id],
            "per_example": records,
        },
        "Lag correlation for an explicit ordered channel pair",
    )
    return SkillPayload(
        summary="Measured lag correlation for the requested ordered channel pair.",
        quantitative_results=bounded_example_measurements(
            records,
            (
                ("peak_lag_seconds", "s", "Peak signed-correlation lag"),
                ("peak_correlation", None, "Signed correlation at the peak absolute lag"),
            ),
        ),
        produced_artifacts=(artifact,),
    )
