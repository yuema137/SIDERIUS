"""Main score: balanced accuracy (mean per-class recall) on the validation file.

Declared by ``declared/metric_balanced_accuracy.json`` (id, direction,
scoreability) and bound by ``task.yaml`` ``metric.implementation``. This class
owns only the arithmetic.

Where the truth comes from. The scoring stage calls ``_compute`` with the
decoded predictions (``evaluation_payload``), the evaluation scope
(``task_scope``) and the run's data folder (``data_dir``), while this task's
data path is bound. The labels are read from the validation CSV through that
data path, so the metric and the datasets parse the file with one set of rules
and select the same rows.

To use another score, change ``IMPLEMENTS`` and the arithmetic here, and the
``id`` (and, if needed, ``direction``) in the declaration file.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from execute_tools.evaluation_metric import EvaluationMetric
from execute_tools.task_data_path import require_bound_task_data_path


class BalancedAccuracyMetric(EvaluationMetric):
    """Mean over classes of (correct predictions in the class / rows in the class).

    The selected validation rows define the denominator: a row with no
    prediction counts as wrong, and a prediction for an ID outside those rows
    is ignored. Classes absent from the selected rows are left out of the mean.
    """

    IMPLEMENTS: ClassVar[tuple[str, ...]] = ("balanced_accuracy",)

    def _compute(
        self,
        deliverables: Mapping[int, str],
        /,
        *,
        evaluation_payload: Mapping[str, int],
        task_scope: Any,
        data_dir: str | None = None,
    ) -> tuple[float, list[float | None] | None, tuple[str, ...]]:
        if data_dir is None:
            raise ValueError(
                "balanced_accuracy reads labels from the data folder; data_dir is None"
            )
        labels_by_sample_id = getattr(require_bound_task_data_path(), "labels_by_sample_id", None)
        if not callable(labels_by_sample_id):
            raise TypeError("the bound task data path does not provide labels_by_sample_id")
        truth = labels_by_sample_id(task_scope, data_dir)
        if not isinstance(truth, dict):
            raise TypeError("labels_by_sample_id must return a {sample_id: class} mapping")
        if not truth:
            raise ValueError("balanced_accuracy needs at least one validation row")
        recalls = []
        for label in sorted(set(truth.values())):
            members = [sample_id for sample_id, value in truth.items() if value == label]
            correct = sum(evaluation_payload.get(sample_id) == label for sample_id in members)
            recalls.append(correct / len(members))
        return sum(recalls) / len(recalls), None, ()
