"""A fourth task's metric implementation, supplied as an out-of-tree plugin.

It subclasses the framework's ``EvaluationMetric`` — the ONE scoring contract
— and implements only ``_compute``. The spec (identity, direction,
aggregation, scoreability) comes from the task's own declaration JSON through
``metric_spec_from_declaration``, so this file decides arithmetic and nothing
about what the metric means.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from execute_tools.evaluation_metric import EvaluationMetric


class BandCoverageMetric(EvaluationMetric):
    """Mean absolute band-coverage error. LOWER is better, per its declaration."""

    def _compute(
        self,
        deliverables: Mapping[int, str],
        /,
        *,
        predictions: Mapping[str, float] | None = None,
        truth: Mapping[str, float] | None = None,
        **_unused: Any,
    ) -> tuple[float, list[float | None] | None, tuple[str, ...]]:
        predictions = predictions or {}
        truth = truth or {}
        if not truth:
            raise ValueError("band coverage needs a non-empty truth mapping.")
        errors = [abs(predictions.get(key, 0.0) - value) for key, value in truth.items()]
        return sum(errors) / len(errors), None, ()
