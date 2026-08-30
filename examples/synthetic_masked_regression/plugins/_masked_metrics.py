"""Primary and observational metrics for synthetic masked regression."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from execute_tools.evaluation_metric import EvaluationMetric


def _errors(payload: Mapping[str, Mapping[str, Any]]) -> list[float]:
    errors = [
        float(row["prediction"]) - float(row["target"])
        for row in payload.values()
        if bool(row["valid"])
    ]
    if not errors:
        raise ValueError("masked metrics need at least one valid evaluation row.")
    return errors


class MaskedMseMetric(EvaluationMetric):
    IMPLEMENTS: ClassVar[tuple[str, ...]] = ("masked_mse",)

    def _compute(
        self,
        deliverables: Mapping[int, str],
        /,
        *,
        evaluation_payload: Mapping[str, Mapping[str, Any]],
        task_scope: Any,
        data_dir: str | None = None,
    ) -> tuple[float, list[float | None] | None, tuple[str, ...]]:
        errors = _errors(evaluation_payload)
        return sum(error * error for error in errors) / len(errors), None, ()


class MaskedMaeMetric(EvaluationMetric):
    IMPLEMENTS: ClassVar[tuple[str, ...]] = ("masked_mae",)

    def _compute(
        self,
        deliverables: Mapping[int, str],
        /,
        *,
        evaluation_payload: Mapping[str, Mapping[str, Any]],
        task_scope: Any,
        data_dir: str | None = None,
    ) -> tuple[float, list[float | None] | None, tuple[str, ...]]:
        errors = _errors(evaluation_payload)
        return sum(abs(error) for error in errors) / len(errors), None, ()
