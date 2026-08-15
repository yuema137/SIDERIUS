"""Stub the tuner's LIVE scoring seam on a mocked sandbox (Step 06 C2).

Before Step 06 the tuner called ``sandbox.score_vector(...)`` and unpacked a
``(file_vector, scalar)`` 2-tuple, so tests stubbed
``mock_sandbox.score_vector.return_value``. Since Step 06 the live route is
``sandbox.evaluate_metric(run_metric, ...)`` returning a
:class:`~execute_tools.evaluation_metric.MetricResult`; a stub left on the
old attribute is aimed at a retired entry point and would silently let a
``MagicMock`` flow into the record. Every tuner test that fakes a score goes
through this ONE helper, so the next time the seam moves there is one place
to move it.
"""

from __future__ import annotations

from typing import Any

from execute_tools.evaluation_metric import TIDMAD_METRIC_ID, MetricResult


def stub_scoring(
    mock_sandbox: Any,
    file_vector: list[float | None],
    scalar: float,
    *,
    metric_id: str = TIDMAD_METRIC_ID,
    direction: str = "higher",
) -> MetricResult:
    """Make ``mock_sandbox`` return a fixed score on BOTH scoring seams.

    ``evaluate_metric`` is what the tuner's live route calls; ``score_vector``
    is kept in step for any helper that still reads the legacy 2-tuple. Same
    values on both, so a test cannot observe a difference between the seams.
    """
    result = MetricResult(
        metric_id=metric_id,
        direction=direction,  # type: ignore[arg-type]
        scalar=scalar,
        per_sample=list(file_vector),
        references_used=("anchor_map",),
    )
    mock_sandbox.evaluate_metric.return_value = result
    mock_sandbox.score_vector.return_value = (list(file_vector), scalar)
    return result
