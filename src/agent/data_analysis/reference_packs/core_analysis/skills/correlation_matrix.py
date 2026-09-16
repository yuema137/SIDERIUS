"""Pairwise-complete Pearson correlation over aligned numeric columns."""

import numpy as np
from pydantic import BaseModel, ConfigDict

from agent.schemas.data_analysis.skills import SkillPayload

from .._shared import binding_id, first_information, write_json_artifact

SKILL_INSTRUCTIONS = """Use to measure linear association among aligned numeric variables.
It emits pair counts and Pearson coefficients without p-values, causal claims, or imputation."""


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def run(skill_input, parameters: Parameters, runtime):
    del parameters
    view = runtime.load_materialization(binding_id(skill_input, "matrix"))
    values = np.asarray(first_information(view), dtype=np.float64)
    if values.ndim == 1:
        values = values[:, None]
    if values.ndim != 2:
        raise ValueError("correlation_matrix requires [N, K] numeric data")
    width = values.shape[1]
    matrix: list[list[float | None]] = []
    pair_counts: list[list[int]] = []
    for left in range(width):
        row: list[float | None] = []
        count_row: list[int] = []
        for right in range(width):
            mask = np.isfinite(values[:, left]) & np.isfinite(values[:, right])
            count = int(np.count_nonzero(mask))
            count_row.append(count)
            if count < 2:
                row.append(None)
                continue
            x = values[mask, left]
            y = values[mask, right]
            if np.ptp(x) == 0 or np.ptp(y) == 0:
                row.append(None)
            else:
                row.append(float(np.corrcoef(x, y)[0, 1]))
        matrix.append(row)
        pair_counts.append(count_row)
    artifact = write_json_artifact(
        runtime,
        "correlation_matrix.json",
        {"pearson_correlation": matrix, "pair_counts": pair_counts},
        "Pairwise Pearson correlations and support counts",
    )
    return SkillPayload(
        summary=f"Computed pairwise Pearson evidence for {width} numeric variables.",
        produced_artifacts=(artifact,),
    )
