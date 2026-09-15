"""Generic prediction error conditioned on one authorized metadata field."""

from itertools import pairwise
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.schemas.data_analysis.skills import QuantitativeResult, SkillPayload

from .._shared import aligned_scalar, binding_id, join_scalar_inputs, write_json_artifact

SKILL_INSTRUCTIONS = """Use to ask whether scalar prediction error changes with one explicitly
authorized metadata variable. Select numeric quantiles, explicit numeric edges, or explicit
categories. The metadata parameter is descriptive and grants no access by itself."""


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata_field: str = Field(
        min_length=1, description="Exact authorized metadata field used for grouping."
    )
    grouping: Literal["quantile", "numeric_bins", "categorical"] = Field(
        default="quantile", description="Explicit grouping rule for the selected metadata."
    )
    quantile_group_count: int = Field(
        default=5, ge=2, le=20, description="Requested number of empirical quantile groups."
    )
    numeric_bin_edges: tuple[float, ...] = Field(
        default=(), description="Strictly increasing physical edges for numeric_bins."
    )
    categories: tuple[str, ...] = Field(
        default=(), description="Explicit category values included in categorical grouping."
    )
    minimum_examples_per_group: int = Field(
        default=20, ge=2, description="Support below which metrics are suppressed, never merged."
    )
    include_r_squared: bool = Field(
        default=True, description="Whether to report R-squared when mathematically defined."
    )

    @model_validator(mode="after")
    def validate_grouping(self):
        if self.grouping == "numeric_bins":
            if len(self.numeric_bin_edges) < 2 or any(
                right <= left for left, right in pairwise(self.numeric_bin_edges)
            ):
                raise ValueError("numeric_bins requires strictly increasing explicit edges")
        elif self.numeric_bin_edges:
            raise ValueError("numeric_bin_edges apply only to numeric_bins")
        if self.grouping == "categorical" and not self.categories:
            raise ValueError("categorical grouping requires explicit categories")
        if self.grouping != "categorical" and self.categories:
            raise ValueError("categories apply only to categorical grouping")
        if len(set(self.categories)) != len(self.categories):
            raise ValueError("categories must be unique")
        return self


def _metrics(prediction: np.ndarray, target: np.ndarray, minimum: int, include_r2: bool):
    count = len(target)
    if count < minimum:
        return {"count": count, "metrics": None, "suppression_reason": "insufficient_support"}
    error = prediction - target
    metrics = {
        "bias": float(np.mean(error)),
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(np.square(error)))),
    }
    if include_r2:
        denominator = float(np.sum(np.square(target - np.mean(target))))
        if denominator == 0:
            metrics["r_squared"] = None
            metrics["r_squared_suppression_reason"] = "zero_target_variance"
        else:
            metrics["r_squared"] = 1.0 - float(np.sum(np.square(error))) / denominator
            metrics["r_squared_suppression_reason"] = None
    return {"count": count, "metrics": metrics, "suppression_reason": None}


def _canonical_group_indices(groups: list[dict]) -> tuple[int, ...]:
    """Keep all modest tables; otherwise retain bounded RMSE extremes and sparse groups."""

    if len(groups) <= 5:
        return tuple(range(len(groups)))
    ranked = sorted(
        (
            (index, float(group["metrics"]["rmse"]))
            for index, group in enumerate(groups)
            if group["metrics"] is not None
        ),
        key=lambda item: item[1],
    )
    selected = [index for index, _value in ranked[:2]]
    selected.extend(index for index, _value in ranked[-2:])
    selected.extend(index for index, group in enumerate(groups) if group["metrics"] is None)
    return tuple(sorted(tuple(dict.fromkeys(selected))[:5]))


def _canonical_results(groups: list[dict]) -> tuple[QuantitativeResult, ...]:
    selected = _canonical_group_indices(groups)
    results = [
        QuantitativeResult(
            result_key="group_count",
            value=len(groups),
            description="Number of requested slice groups in the complete artifact table",
        ),
        QuantitativeResult(
            result_key="canonical_group_count",
            value=len(selected),
            description="Number of bounded group summaries exposed as canonical evidence",
        ),
    ]
    for index in selected:
        group = groups[index]
        prefix = f"group.{index}"
        results.extend(
            (
                QuantitativeResult(
                    result_key=f"{prefix}.label",
                    value=group["label"],
                    description="Exact requested slice label from the complete artifact table",
                ),
                QuantitativeResult(
                    result_key=f"{prefix}.count",
                    value=group["count"],
                    description="Finite aligned examples in this slice",
                ),
            )
        )
        metrics = group["metrics"]
        if metrics is None:
            results.append(
                QuantitativeResult(
                    result_key=f"{prefix}.metrics_suppression_reason",
                    value=group["suppression_reason"],
                    description="Why performance metrics are suppressed for this visible slice",
                )
            )
            continue
        for metric in ("bias", "mae", "rmse"):
            results.append(
                QuantitativeResult(
                    result_key=f"{prefix}.{metric}",
                    value=metrics[metric],
                    description=f"Scalar-regression {metric} for this slice",
                )
            )
        if "r_squared" in metrics:
            if metrics["r_squared"] is None:
                results.append(
                    QuantitativeResult(
                        result_key=f"{prefix}.r_squared_suppression_reason",
                        value=metrics["r_squared_suppression_reason"],
                        description="Why R-squared is undefined for this supported slice",
                    )
                )
            else:
                results.append(
                    QuantitativeResult(
                        result_key=f"{prefix}.r_squared",
                        value=metrics["r_squared"],
                        description="R-squared for this slice",
                    )
                )
    return tuple(results)


def run(skill_input, parameters: Parameters, runtime):
    prediction_view = runtime.load_materialization(binding_id(skill_input, "predictions"))
    target_view = runtime.load_materialization(binding_id(skill_input, "targets"))
    metadata_view = runtime.load_materialization(binding_id(skill_input, "slice_metadata"))
    if parameters.metadata_field not in metadata_view.metadata:
        raise ValueError("authorized view does not contain the requested metadata field")
    metadata = np.asarray(metadata_view.metadata[parameters.metadata_field])
    if metadata.ndim != 1:
        raise ValueError("slice metadata must be scalar [N]")
    prediction, target, metadata = join_scalar_inputs(
        aligned_scalar(prediction_view, "prediction"),
        aligned_scalar(target_view, "target"),
        (np.asarray(metadata_view.example_ids), metadata),
    )
    valid = np.isfinite(prediction) & np.isfinite(target)
    groups = []
    dropped = 0
    if parameters.grouping == "categorical":
        for category in parameters.categories:
            selected = valid & (metadata.astype(str) == category)
            groups.append(
                {
                    "label": category,
                    **_metrics(
                        prediction[selected],
                        target[selected],
                        parameters.minimum_examples_per_group,
                        parameters.include_r_squared,
                    ),
                }
            )
        dropped = int(
            np.count_nonzero(valid & ~np.isin(metadata.astype(str), parameters.categories))
        )
        boundaries = list(parameters.categories)
    else:
        numeric = np.asarray(metadata, dtype=np.float64)
        valid &= np.isfinite(numeric)
        if parameters.grouping == "quantile":
            edges = np.unique(
                np.quantile(
                    numeric[valid],
                    np.linspace(0, 1, parameters.quantile_group_count + 1),
                    method="linear",
                )
            )
        else:
            edges = np.asarray(parameters.numeric_bin_edges, dtype=np.float64)
        if len(edges) < 2:
            raise ValueError("grouping produced fewer than two distinct numeric edges")
        for index, (left, right) in enumerate(pairwise(edges)):
            selected = (
                valid
                & (numeric >= left)
                & ((numeric <= right) if index == len(edges) - 2 else (numeric < right))
            )
            groups.append(
                {
                    "label": f"[{left},{right}{']' if index == len(edges) - 2 else ')'}",
                    "left": float(left),
                    "right": float(right),
                    **_metrics(
                        prediction[selected],
                        target[selected],
                        parameters.minimum_examples_per_group,
                        parameters.include_r_squared,
                    ),
                }
            )
        included = valid & (numeric >= edges[0]) & (numeric <= edges[-1])
        dropped = int(np.count_nonzero(valid & ~included))
        boundaries = edges.tolist()
    artifact = write_json_artifact(
        runtime,
        "performance_slice_summary.json",
        {
            "metadata_field": parameters.metadata_field,
            "grouping": parameters.grouping,
            "requested_boundaries": boundaries,
            "minimum_examples_per_group": parameters.minimum_examples_per_group,
            "groups": groups,
            "dropped_outside_groups": dropped,
            "error_definition": "prediction-target",
        },
        "Per-group scalar-regression error measurements",
    )
    return SkillPayload(
        summary=f"Measured prediction error across {len(groups)} groups of {parameters.metadata_field!r}.",
        quantitative_results=_canonical_results(groups),
        produced_artifacts=(artifact,),
    )
