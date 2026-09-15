"""Sampling cadence, irregularity and gap diagnostics."""

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from agent.schemas.data_analysis.skills import QuantitativeResult, SkillPayload

from .._shared import series_view, write_json_artifact

SKILL_INSTRUCTIONS = """Use to determine whether timestamps are regular, whether observations
contain gaps, and how much usable duration is present. It describes sampling and never repairs it."""


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cadence_rtol: float = Field(default=1e-6, ge=0.0, description="Relative cadence tolerance.")
    cadence_atol_seconds: float = Field(
        default=0.0, ge=0.0, description="Absolute cadence tolerance in seconds."
    )
    gap_factor: float = Field(
        default=1.5,
        gt=1.0,
        description="Delta/cadence ratio strictly above which a gap is counted.",
    )


def run(skill_input, parameters: Parameters, runtime):
    view = series_view(runtime, skill_input)
    records = []
    for example_index, example_id in enumerate(view.example_ids):
        time = np.asarray(view.time_seconds(example_index), dtype=np.float64)
        mask = np.asarray(view.valid_mask[example_index], dtype=np.bool_)
        observed = time[mask]
        record = {
            "example_id": str(example_id),
            "valid_count": int(mask.sum()),
            "masked_count": int((~mask).sum()),
            "duration_seconds": None,
            "median_cadence_seconds": None,
            "cadence_iqr_seconds": None,
            "cadence_cv": None,
            "uniform": False,
            "gap_count": 0,
            "gap_fraction": None,
            "maximum_gap_seconds": None,
            "missing_span_seconds": 0.0,
            "unusable_reason": None,
        }
        if len(observed) < 2 or not np.all(np.isfinite(observed)):
            record["unusable_reason"] = "fewer_than_two_finite_observed_timestamps"
            records.append(record)
            continue
        deltas = np.diff(observed)
        if np.any(deltas <= 0):
            record["unusable_reason"] = "timestamps_not_strictly_increasing"
            records.append(record)
            continue
        cadence = float(np.median(deltas))
        tolerance = max(parameters.cadence_atol_seconds, parameters.cadence_rtol * cadence)
        gaps = deltas > parameters.gap_factor * cadence
        record.update(
            duration_seconds=float(observed[-1] - observed[0]),
            median_cadence_seconds=cadence,
            cadence_iqr_seconds=float(np.quantile(deltas, 0.75) - np.quantile(deltas, 0.25)),
            cadence_cv=(
                None if len(deltas) < 2 else float(np.std(deltas, ddof=1) / abs(np.mean(deltas)))
            ),
            uniform=bool(np.all(np.abs(deltas - cadence) <= tolerance)),
            gap_count=int(np.count_nonzero(gaps)),
            gap_fraction=float(np.mean(gaps)),
            maximum_gap_seconds=float(np.max(deltas)),
            missing_span_seconds=float(np.sum(np.maximum(deltas[gaps] - cadence, 0.0))),
        )
        records.append(record)
    artifact = write_json_artifact(
        runtime,
        "sampling_cadence_and_gaps.json",
        {
            "cadence_rtol": parameters.cadence_rtol,
            "cadence_atol_seconds": parameters.cadence_atol_seconds,
            "gap_factor": parameters.gap_factor,
            "examples": records,
        },
        "Per-example sampling cadence and gap diagnostics",
    )
    usable = sum(item["unusable_reason"] is None for item in records)
    irregular = sum(item["unusable_reason"] is None and not item["uniform"] for item in records)
    return SkillPayload(
        summary=f"Characterized sampling for {usable}/{len(records)} examples.",
        quantitative_results=(
            QuantitativeResult(
                result_key="usable_example_count",
                value=usable,
                description="Examples with sufficient monotonic finite timestamps",
            ),
            QuantitativeResult(
                result_key="irregular_example_count",
                value=irregular,
                description="Usable examples outside the requested regular-cadence tolerance",
            ),
            QuantitativeResult(
                result_key="total_gap_count",
                value=sum(item["gap_count"] for item in records),
                description="Detected gaps across usable examples",
            ),
        ),
        produced_artifacts=(artifact,),
    )
