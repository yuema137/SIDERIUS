"""Quantiles and descriptive Tukey-fence outlier counts."""

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from agent.schemas.data_analysis.skills import QuantitativeResult, SkillPayload

from .._shared import binding_id, descriptive, finite_values, first_information, write_json_artifact

SKILL_INSTRUCTIONS = """Use to inspect distribution shape through explicit quantiles and
Tukey-fence counts. Outlier flags are descriptive evidence, never a removal decision."""


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    quantiles: tuple[float, ...] = Field(
        default=(0.05, 0.25, 0.5, 0.75, 0.95),
        min_length=1,
        description="Explicit probability levels for linear empirical quantiles.",
    )
    iqr_multiplier: float = Field(
        default=1.5,
        gt=0.0,
        description="Positive multiplier applied to IQR for descriptive Tukey fences.",
    )


def run(skill_input, parameters: Parameters, runtime):
    if any(not 0.0 <= item <= 1.0 for item in parameters.quantiles):
        raise ValueError("quantiles must lie in [0, 1]")
    view = runtime.load_materialization(binding_id(skill_input, "values"))
    values = finite_values(first_information(view), view.valid_mask)
    result = descriptive(values, parameters.quantiles)
    if values.size:
        q1, q3 = np.quantile(values, (0.25, 0.75), method="linear")
        iqr = float(q3 - q1)
        lower = float(q1 - parameters.iqr_multiplier * iqr)
        upper = float(q3 + parameters.iqr_multiplier * iqr)
        outlier_count = int(np.count_nonzero((values < lower) | (values > upper)))
    else:
        iqr = lower = upper = None
        outlier_count = 0
    result.update(
        iqr=iqr,
        lower_tukey_fence=lower,
        upper_tukey_fence=upper,
        tukey_outlier_count=outlier_count,
        iqr_multiplier=parameters.iqr_multiplier,
    )
    artifact = write_json_artifact(
        runtime, "distribution_quantiles_and_outliers.json", result, "Distribution summary"
    )
    return SkillPayload(
        summary=f"Inspected {len(values)} finite values and flagged {outlier_count} beyond Tukey fences.",
        quantitative_results=(
            QuantitativeResult(
                result_key="tukey_outlier_count",
                value=outlier_count,
                description="Values strictly outside the requested Tukey fences",
            ),
        ),
        produced_artifacts=(artifact,),
    )
