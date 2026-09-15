"""Bounded time-local descriptive statistics without stationarity claims."""

from itertools import pairwise

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from agent.schemas.data_analysis.skills import SkillPayload

from .._shared import (
    aggregate_channel_scalars,
    atomic_series,
    bounded_channel_measurements,
    series_view,
    usable_series_measurement,
    write_json_artifact,
)

SKILL_INSTRUCTIONS = """Use to measure whether local mean, scale, quantiles, or RMS drift over
elapsed time. It provides bounded window evidence, not a formal stationarity or change-point test."""


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    window_count: int = Field(
        default=8, ge=2, le=64, description="Number of equal-duration analysis windows."
    )
    minimum_points_per_window: int = Field(
        default=8, ge=2, description="Finite support required before reporting window statistics."
    )
    include_linear_trend: bool = Field(
        default=True, description="Whether to include descriptive OLS drift summaries."
    )


def run(skill_input, parameters: Parameters, runtime):
    view = series_view(runtime, skill_input)
    records = []
    for item in atomic_series(view, "data"):
        usable = item.mask & np.isfinite(item.time) & np.isfinite(item.values)
        time = item.time[usable]
        values = item.values[usable]
        if len(time) < 2 or np.any(np.diff(time) <= 0):
            records.append(
                {
                    "example_id": item.example_id,
                    "channel_id": item.channel_id,
                    "windows": [],
                    "unusable_reason": "insufficient_or_nonmonotonic_finite_data",
                }
            )
            continue
        edges = np.linspace(time[0], time[-1], parameters.window_count + 1)
        windows = []
        means = []
        scales = []
        for index, (left, right) in enumerate(pairwise(edges)):
            selected = (time >= left) & (
                (time <= right) if index == parameters.window_count - 1 else (time < right)
            )
            part = values[selected]
            row = {"start_seconds": float(left), "end_seconds": float(right), "count": len(part)}
            if len(part) < parameters.minimum_points_per_window:
                row.update(statistics=None, suppression_reason="insufficient_support")
            else:
                mean = float(np.mean(part))
                scale = float(np.std(part, ddof=1))
                row.update(
                    statistics={
                        "mean": mean,
                        "standard_deviation": scale,
                        "median": float(np.median(part)),
                        "q25": float(np.quantile(part, 0.25)),
                        "q75": float(np.quantile(part, 0.75)),
                        "rms": float(np.sqrt(np.mean(np.square(part)))),
                    },
                    suppression_reason=None,
                )
                means.append(mean)
                scales.append(scale)
            windows.append(row)
        trend = None
        if parameters.include_linear_trend and len(values) >= 2 and np.ptp(time) > 0:
            centered = time - np.mean(time)
            slope = float(np.dot(centered, values - np.mean(values)) / np.dot(centered, centered))
            end_to_end = slope * float(time[-1] - time[0])
            total_scale = float(np.std(values, ddof=1))
            trend = {
                "slope_per_second": slope,
                "fitted_end_to_end_change": end_to_end,
                "normalized_end_to_end_change": None
                if total_scale == 0
                else end_to_end / total_scale,
            }
        records.append(
            {
                "example_id": item.example_id,
                "channel_id": item.channel_id,
                "windows": windows,
                "window_mean_range": None if not means else max(means) - min(means),
                "window_mean_std": None if len(means) < 2 else float(np.std(means, ddof=1)),
                "window_scale_range": None if not scales else max(scales) - min(scales),
                "trend": trend,
                "unusable_reason": None,
            }
        )
    aggregate = aggregate_channel_scalars(
        [item for item in records if item["unusable_reason"] is None],
        ("window_mean_range", "window_mean_std", "window_scale_range"),
    )
    artifact = write_json_artifact(
        runtime,
        "temporal_stability_summary.json",
        {"parameters": parameters.model_dump(), "per_series": records, "per_channel": aggregate},
        "Windowed time-local statistics and drift summaries",
    )
    return SkillPayload(
        summary="Measured time-local statistical variation without assigning stationarity labels.",
        quantitative_results=(
            usable_series_measurement(records),
            *bounded_channel_measurements(
                aggregate,
                (
                    ("window_mean_range", None, "Range of supported window means"),
                    ("window_scale_range", None, "Range of supported window standard deviations"),
                ),
            ),
        ),
        produced_artifacts=(artifact,),
    )
