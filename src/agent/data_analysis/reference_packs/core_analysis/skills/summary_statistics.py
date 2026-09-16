"""Deterministic descriptive statistics over authorized numeric values."""

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from agent.schemas.data_analysis.skills import QuantitativeResult, SkillPayload

from .._shared import binding_id, descriptive, finite_values, first_information, write_json_artifact

SKILL_INSTRUCTIONS = """Use for bounded descriptive statistics of authorized numeric data.
It returns finite-value counts, location, spread, extrema, and explicit quantiles. It does not
impute, characterize temporal structure, or decide whether observations should be removed."""


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    quantiles: tuple[float, ...] = Field(
        default=(0.05, 0.25, 0.5, 0.75, 0.95),
        min_length=1,
        description="Explicit probability levels in [0,1] for linear empirical quantiles.",
    )


def run(skill_input, parameters: Parameters, runtime):
    if any(not 0.0 <= item <= 1.0 for item in parameters.quantiles):
        raise ValueError("quantiles must lie in [0, 1]")
    view = runtime.load_materialization(binding_id(skill_input, "values"))
    raw = first_information(view)
    values = finite_values(raw, view.valid_mask)
    result = descriptive(values, parameters.quantiles)
    if view.valid_mask is None:
        supported = np.asarray(raw).reshape(-1)
    else:
        mask = np.asarray(view.valid_mask, dtype=np.bool_)
        if raw.ndim == 3 and mask.ndim == 2:
            mask = np.broadcast_to(mask[:, None, :], raw.shape)
        elif mask.ndim == 1 and raw.ndim > 1:
            mask = np.broadcast_to(mask.reshape((len(mask),) + (1,) * (raw.ndim - 1)), raw.shape)
        supported = np.asarray(raw)[mask]
    result["nonfinite_count"] = int(np.count_nonzero(~np.isfinite(supported)))
    artifact = write_json_artifact(
        runtime, "summary_statistics.json", result, "Certified descriptive statistics"
    )
    return SkillPayload(
        summary=f"Summarized {len(values)} finite numeric values.",
        quantitative_results=(
            QuantitativeResult(
                result_key="finite_count",
                value=len(values),
                description="Number of finite values included",
            ),
            QuantitativeResult(
                result_key="mean", value=result["mean"], description="Finite-value mean"
            ),
        ),
        produced_artifacts=(artifact,),
    )
