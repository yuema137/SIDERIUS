"""Separate unavailable positions from nonfinite observed numeric values."""

import numpy as np
from pydantic import BaseModel, ConfigDict

from agent.schemas.data_analysis.skills import QuantitativeResult, SkillPayload

from .._shared import binding_id, first_information, write_json_artifact

SKILL_INSTRUCTIONS = """Use to count mask-false positions separately from NaN and infinities
inside observed support. The skill reports data quality; it never imputes or repairs values."""


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def run(skill_input, parameters: Parameters, runtime):
    del parameters
    view = runtime.load_materialization(binding_id(skill_input, "values"))
    values = np.asarray(first_information(view), dtype=np.float64)
    if view.valid_mask is None:
        support = np.ones(values.shape, dtype=np.bool_)
        missing_count = 0
    else:
        mask = np.asarray(view.valid_mask, dtype=np.bool_)
        support = (
            np.broadcast_to(mask[:, None, :], values.shape)
            if values.ndim == 3 and mask.ndim == 2
            else np.broadcast_to(
                mask.reshape((len(mask),) + (1,) * (values.ndim - 1)), values.shape
            )
        )
        missing_count = int(np.count_nonzero(~support))
    result = {
        "observed_count": int(np.count_nonzero(support)),
        "mask_false_count": missing_count,
        "nan_count": int(np.count_nonzero(np.isnan(values) & support)),
        "positive_infinity_count": int(np.count_nonzero(np.isposinf(values) & support)),
        "negative_infinity_count": int(np.count_nonzero(np.isneginf(values) & support)),
    }
    artifact = write_json_artifact(
        runtime, "nonfinite_and_missingness.json", result, "Missing and nonfinite counts"
    )
    return SkillPayload(
        summary=(
            f"Found {missing_count} unavailable positions and "
            f"{result['nan_count'] + result['positive_infinity_count'] + result['negative_infinity_count']} "
            "nonfinite observed values."
        ),
        quantitative_results=tuple(
            QuantitativeResult(result_key=key, value=value, description=key.replace("_", " "))
            for key, value in result.items()
        ),
        produced_artifacts=(artifact,),
    )
