"""Quickstart — the pack's OWN terminal metric implementation.

Bound by the run manifest's ``metric.implementation: {file: ...}`` reference;
never imported by the framework (governance guard (c)) and never found by a
directory scan (the leading underscore keeps both plugin scanners away — the
``_pets_metrics.py`` convention from PR-12d).

The ``_compute`` signature follows the composed SCORING CHILD's calling
vocabulary established by PR-12d — ``evaluation_payload`` / ``task_scope`` /
``data_dir``, the three values the framework owns — because assembling truth
from a scope is TASK knowledge. On the current master nothing in the composed
loop invokes it (scoring-child execution for a non-TIDMAD task is PR-12d
scope); composition validates the declaration/implementation pair, and the
pack's unit tests exercise the arithmetic directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from execute_tools.evaluation_metric import EvaluationMetric

#: The quickstart task has exactly two classes; a fact about THIS task,
#: declared in its own file — the framework never learns it.
QUICKSTART_CLASS_COUNT = 2


def _truth_from_scope(task_scope: Any) -> dict[str, int]:
    """``{sample_id: label}`` from the run's evaluation scope.

    The scope IS the truth authority — it is what the run declared it would
    be evaluated on. Deriving truth from anything else (a data-dir re-read,
    the deliverable itself) would let the denominator drift from the scope
    the scoreability contract already validated.
    """
    rows = getattr(task_scope, "rows", None)
    if rows is None:
        raise ValueError(
            "the quickstart metric needs the run's evaluation scope to read "
            f"truth from; got {type(task_scope).__name__}, which declares no "
            "`rows`."
        )
    return {str(row.sample_id): int(row.label) for row in rows}


class QuickstartAccuracyMetric(EvaluationMetric):
    """Fraction of the evaluation scope whose predicted class is correct.

    The DENOMINATOR is the truth mapping (the scope), so a prediction missing
    from a partial deliverable counts as not-correct — the declared
    aggregation (``fraction_correct_over_eval_rows``) read literally.
    Direction (``higher``) and the scoreability contract come from the
    declared ``MetricSpec``; this class owns arithmetic only.
    """

    #: PR-12d ``IMPLEMENTS`` discipline (declaration/implementation agreement);
    #: inert on the current master, consumed by the 12d census when it lands.
    IMPLEMENTS: ClassVar[tuple[str, ...]] = ("accuracy",)

    def _compute(
        self,
        deliverables: Mapping[int, str],
        /,
        *,
        evaluation_payload: Mapping[str, int],
        task_scope: Any,
        data_dir: str | None = None,
    ) -> tuple[float, list[float | None] | None, tuple[str, ...]]:
        truth = _truth_from_scope(task_scope)
        if not truth:
            raise ValueError(
                "accuracy needs a non-empty evaluation scope — an empty scope "
                "is a caller wiring defect, not a scoreability case."
            )
        correct = sum(
            1 for sample_id, label in truth.items() if evaluation_payload.get(sample_id) == label
        )
        return correct / len(truth), None, ()
