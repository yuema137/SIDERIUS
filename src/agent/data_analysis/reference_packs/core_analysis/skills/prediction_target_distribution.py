"""Generic scalar-regression prediction/target distribution diagnostics."""

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from scipy.stats import spearmanr, wasserstein_distance

from agent.schemas.data_analysis.skills import QuantitativeResult, SkillPayload

from .._shared import (
    aligned_scalar,
    binding_id,
    descriptive,
    join_scalar_inputs,
    write_json_artifact,
)

SKILL_INSTRUCTIONS = """Use with aligned scalar predictions and targets to detect bias,
range compression, variance collapse, and support mismatch. It is descriptive regression
evidence and makes no calibration or goodness-of-fit claim."""


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    quantiles: tuple[float, ...] = Field(
        default=(0.05, 0.25, 0.5, 0.75, 0.95),
        min_length=1,
        description="Shared probability levels used to compare prediction and target quantiles.",
    )


def run(skill_input, parameters: Parameters, runtime):
    if any(not 0.0 <= item <= 1.0 for item in parameters.quantiles):
        raise ValueError("quantiles must lie in [0, 1]")
    prediction_view = runtime.load_materialization(binding_id(skill_input, "predictions"))
    target_view = runtime.load_materialization(binding_id(skill_input, "targets"))
    prediction, target = join_scalar_inputs(
        aligned_scalar(prediction_view, "prediction"),
        aligned_scalar(target_view, "target"),
    )
    valid = np.isfinite(prediction) & np.isfinite(target)
    prediction = prediction[valid]
    target = target[valid]
    if not len(target):
        raise ValueError("no finite aligned prediction/target pairs")
    prediction_summary = descriptive(prediction, parameters.quantiles)
    target_summary = descriptive(target, parameters.quantiles)
    target_std = target_summary["standard_deviation"]
    prediction_std = prediction_summary["standard_deviation"]
    target_iqr = float(np.quantile(target, 0.75) - np.quantile(target, 0.25))
    prediction_iqr = float(np.quantile(prediction, 0.75) - np.quantile(prediction, 0.25))
    rank = None
    if len(target) >= 2 and np.ptp(target) > 0 and np.ptp(prediction) > 0:
        rank = float(spearmanr(target, prediction).statistic)
    result = {
        "count": len(target),
        "prediction": prediction_summary,
        "target": target_summary,
        "bias": float(np.mean(prediction - target)),
        "standard_deviation_ratio": (
            None if target_std in (None, 0.0) else float(prediction_std / target_std)
        ),
        "iqr_ratio": None if target_iqr == 0 else prediction_iqr / target_iqr,
        "prediction_inside_target_range_fraction": float(
            np.mean((prediction >= np.min(target)) & (prediction <= np.max(target)))
        ),
        "spearman_rank_correlation": rank,
        "wasserstein_1": float(wasserstein_distance(target, prediction)),
    }
    artifact = write_json_artifact(
        runtime,
        "prediction_target_distribution.json",
        result,
        "Prediction and target distribution comparison",
    )
    return SkillPayload(
        summary=f"Compared {len(target)} finite aligned scalar prediction/target pairs.",
        quantitative_results=(
            QuantitativeResult(
                result_key="bias",
                value=result["bias"],
                description="Mean prediction minus target",
            ),
            QuantitativeResult(
                result_key="wasserstein_1",
                value=result["wasserstein_1"],
                description="One-dimensional Wasserstein distance in target units",
            ),
        ),
        produced_artifacts=(artifact,),
    )
