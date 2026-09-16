"""Generic scalar-regression prediction/target distribution diagnostics."""

from typing import cast

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
    robust_probabilities = (0.05, 0.5, 0.95)
    prediction_robust = np.quantile(prediction, robust_probabilities, method="linear")
    target_robust = np.quantile(target, robust_probabilities, method="linear")
    prediction_robust_span = float(prediction_robust[2] - prediction_robust[0])
    target_robust_span = float(target_robust[2] - target_robust[0])
    target_scale = float(np.max(np.abs(target)))
    numerical_spread_floor = float(np.spacing(target_scale))
    std_ratio_reason = None
    if target_std is None or target_std <= numerical_spread_floor:
        standard_deviation_ratio = None
        std_ratio_reason = "target_standard_deviation_zero_or_numerically_unresolvable"
    else:
        standard_deviation_ratio = float(prediction_std / target_std)
    robust_span_ratio_reason = None
    if target_robust_span <= numerical_spread_floor:
        robust_span_ratio = None
        robust_span_ratio_reason = "target_robust_span_zero_or_numerically_unresolvable"
    else:
        robust_span_ratio = prediction_robust_span / target_robust_span
    rank = None
    if len(target) >= 2 and np.ptp(target) > 0 and np.ptp(prediction) > 0:
        rank = float(cast(float, spearmanr(target, prediction)[0]))
    result = {
        "count": len(target),
        "prediction": prediction_summary,
        "target": target_summary,
        "bias": float(np.mean(prediction - target)),
        "standard_deviation_ratio": standard_deviation_ratio,
        "standard_deviation_ratio_suppression_reason": std_ratio_reason,
        "iqr_ratio": None if target_iqr == 0 else prediction_iqr / target_iqr,
        "robust_quantiles": {
            "probabilities": list(robust_probabilities),
            "prediction": prediction_robust.tolist(),
            "target": target_robust.tolist(),
        },
        "robust_span_ratio": robust_span_ratio,
        "robust_span_ratio_suppression_reason": robust_span_ratio_reason,
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
    quantitative_results = [
        QuantitativeResult(
            result_key="prediction.mean",
            value=prediction_summary["mean"],
            description="Mean scalar prediction",
        ),
        QuantitativeResult(
            result_key="prediction.standard_deviation",
            value=prediction_std,
            description="Sample standard deviation of scalar predictions",
        ),
        QuantitativeResult(
            result_key="target.mean",
            value=target_summary["mean"],
            description="Mean scalar target",
        ),
        QuantitativeResult(
            result_key="target.standard_deviation",
            value=target_std,
            description="Sample standard deviation of scalar targets",
        ),
    ]
    quantitative_results.extend(
        QuantitativeResult(
            result_key=f"prediction.q{int(probability * 100):02d}",
            value=float(prediction_robust[index]),
            description=f"Prediction quantile at probability {probability:g}",
        )
        for index, probability in enumerate(robust_probabilities)
    )
    quantitative_results.extend(
        QuantitativeResult(
            result_key=f"target.q{int(probability * 100):02d}",
            value=float(target_robust[index]),
            description=f"Target quantile at probability {probability:g}",
        )
        for index, probability in enumerate(robust_probabilities)
    )
    quantitative_results.extend(
        (
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
            QuantitativeResult(
                result_key="standard_deviation_ratio",
                value=standard_deviation_ratio,
                description=(
                    "Prediction sample standard deviation divided by target sample standard "
                    "deviation"
                ),
            ),
        )
    )
    if standard_deviation_ratio is None:
        quantitative_results.append(
            QuantitativeResult(
                result_key="standard_deviation_ratio_suppression_reason",
                value=std_ratio_reason,
                description="Why the standard-deviation ratio is undefined",
            )
        )
    quantitative_results.append(
        QuantitativeResult(
            result_key="robust_span_ratio",
            value=robust_span_ratio,
            description="Prediction q95-q05 span divided by target q95-q05 span",
        )
    )
    if robust_span_ratio is None:
        quantitative_results.append(
            QuantitativeResult(
                result_key="robust_span_ratio_suppression_reason",
                value=robust_span_ratio_reason,
                description="Why the robust central-span ratio is undefined",
            )
        )
    return SkillPayload(
        summary=f"Compared {len(target)} finite aligned scalar prediction/target pairs.",
        quantitative_results=tuple(quantitative_results),
        produced_artifacts=(artifact,),
    )
