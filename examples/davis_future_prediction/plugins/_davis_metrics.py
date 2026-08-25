"""DAVIS 2017 future-frame prediction — the pack's OWN terminal metrics.

Step 12 / PR-12d D4c (ruling A2-b). `psnr` and `mae` were DECLARED and both
bound to :class:`~execute_tools.evaluation_metric.GlobalMseMetric`, which
computes neither. Composition accepted it because the only identity check
compared the declaration to itself (**F-12d-3**) — so a terminal report could
have read `psnr / HIGHER` while mean squared error executed. That is the
failure D4c's acceptance names explicitly as a FAIL, and it is why these exist.

Aggregation matches `mse`'s frozen rule: the EXACT global mean over every
element of every scored sample — sums and element counts accumulated across
samples, divided ONCE. Never a mean-of-means; with unequal clip sizes those
differ, and the declared aggregation says "over clips × C × T × H × W".

A truth sample with no prediction is a LOUD error, not a zero. A missing dense
prediction has no defensible numeric stand-in, and a partial deliverable that
scored anyway would flatter the model silently.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from execute_tools.evaluation_metric import EvaluationMetric


def _accumulate(
    predictions: Mapping[str, Any], truth: Mapping[str, Any], *, absolute: bool
) -> tuple[float, int]:
    """``(summed_error, element_count)`` over every element of every sample.

    One traversal shared by both metrics, so the two cannot drift on what
    "global" means — the difference between them is a single call, and it is
    visible right there in the signature rather than buried in two copies.
    """
    import numpy as np

    total = 0.0
    count = 0
    for clip_id, target in truth.items():
        prediction = predictions.get(clip_id)
        if prediction is None:
            raise ValueError(
                f"no prediction for clip {clip_id!r}. A missing dense prediction has "
                "no defensible numeric stand-in; scoring a partial deliverable would "
                "silently flatter the model."
            )
        target_array = np.asarray(target, dtype=np.float64)
        predicted_array = np.asarray(prediction, dtype=np.float64)
        if target_array.shape != predicted_array.shape:
            raise ValueError(
                f"clip {clip_id!r}: prediction shape {predicted_array.shape} does not "
                f"match target shape {target_array.shape}."
            )
        error = predicted_array - target_array
        total += float(np.abs(error).sum() if absolute else np.square(error).sum())
        count += int(target_array.size)
    if count == 0:
        raise ValueError(
            "an empty evaluation scope is a caller wiring defect, not a scoreability case."
        )
    return total, count


class DavisMseMetric(EvaluationMetric):
    """Global mean SQUARED error over every element of every clip. LOWER better.

    **Why this exists beside the framework's `GlobalMseMetric`.** Identical
    arithmetic, different calling vocabulary — see
    :class:`~examples.oxford_iiit_pet.plugins._pets_metrics.PetsAccuracyMetric`
    for the full reasoning. ``GlobalMseMetric`` takes ``predictions`` and
    ``truth`` already assembled, which suits the in-process
    ``scripts/run_davis_gate2.py``; the composed scoring child owns only
    ``evaluation_payload`` / ``task_scope`` / ``data_dir``, because decoding a
    DAVIS clip's target frames is task knowledge the framework must not hold.

    Aggregation is the frozen rule and is shared with `mae` through
    :func:`_accumulate`: sums and element counts accumulated across clips and
    divided ONCE. Never a mean-of-means.
    """

    IMPLEMENTS: ClassVar[tuple[str, ...]] = ("mse",)

    def _compute(
        self,
        deliverables: Mapping[int, str],
        /,
        *,
        evaluation_payload: Mapping[str, Any],
        task_scope: Any,
        data_dir: str | None = None,
    ) -> tuple[float, list[float | None] | None, tuple[str, ...]]:
        truth = _davis_truth(task_scope, data_dir)
        total, count = _accumulate(evaluation_payload, truth, absolute=False)
        return total / count, None, ()


class DavisMaeMetric(EvaluationMetric):
    """Global mean ABSOLUTE error. LOWER is better.

    Deliberately the same aggregation shape as `mse` and deliberately a
    different number: MAE and MSE rank models differently whenever the error
    distribution is not symmetric, which is precisely why declaring both is
    informative rather than redundant. MAE is also the metric that MATCHES
    DAVIS's frozen training objective (exact L1), so the run is measured on
    what it optimised — the alignment A3 exists to protect.
    """

    IMPLEMENTS: ClassVar[tuple[str, ...]] = ("mae",)

    def _compute(
        self,
        deliverables: Mapping[int, str],
        /,
        *,
        evaluation_payload: Mapping[str, Any],
        task_scope: Any,
        data_dir: str | None = None,
    ) -> tuple[float, list[float | None] | None, tuple[str, ...]]:
        truth = _davis_truth(task_scope, data_dir)
        total, count = _accumulate(evaluation_payload, truth, absolute=True)
        return total / count, None, ()


class DavisPsnrMetric(EvaluationMetric):
    """Peak signal-to-noise ratio in dB over the global MSE. HIGHER is better.

    **This is where `MetricSpec.transform_params` stops being decoration.**
    The shipped declaration carries ``transform: "psnr_db"`` and
    ``transform_params: {"data_range": 1.0}``, and until D4c nothing read
    either — the declaration described a computation that did not exist. PSNR
    is meaningless without its data range (the same MSE over ``[0,1]`` images
    and over ``[0,255]`` images differs by ~48 dB), so this implementation
    REQUIRES the declared value and refuses rather than assuming one. Assuming
    is how a plausible-looking number gets reported in the wrong units.

    A perfect reconstruction (MSE exactly 0) has infinite PSNR. That is a real
    mathematical answer and a useless score, so it is refused: on real video it
    means the pipeline compared something to itself, not that the model is
    perfect.
    """

    IMPLEMENTS: ClassVar[tuple[str, ...]] = ("psnr",)

    def _compute(
        self,
        deliverables: Mapping[int, str],
        /,
        *,
        evaluation_payload: Mapping[str, Any],
        task_scope: Any,
        data_dir: str | None = None,
    ) -> tuple[float, list[float | None] | None, tuple[str, ...]]:
        import math

        data_range = self.spec.transform_params.get("data_range")
        if data_range is None or data_range <= 0:
            raise ValueError(
                "psnr requires a positive `data_range` in the declaration's "
                f"transform_params; got {data_range!r}. PSNR is expressed relative "
                "to the signal's peak value, so a default would silently report dB "
                "in the wrong scale."
            )
        truth = _davis_truth(task_scope, data_dir)
        total, count = _accumulate(evaluation_payload, truth, absolute=False)
        mse = total / count
        if mse <= 0:
            raise ValueError(
                "psnr is undefined for an exactly-zero MSE. On real video this means "
                "the deliverable was compared against itself, which is a wiring "
                "defect rather than a perfect model."
            )
        return 10.0 * math.log10((float(data_range) ** 2) / mse), None, ()


def _davis_truth(task_scope: Any, data_dir: str | None) -> Mapping[str, Any]:
    """``{clip_id: target_array}`` for the run's evaluation scope.

    The scope is the truth authority, exactly as it is for Pets. Reading the
    frames is the pack's own business — it is the only party that knows how a
    DAVIS clip is laid out — so this delegates to the pack's data path rather
    than re-implementing a second decoder that could drift from the first.
    """
    from execute_tools.davis_data_path import truth_windows

    rows = getattr(task_scope, "rows", None)
    if rows is None:
        raise ValueError(
            "the DAVIS metrics need the run's evaluation scope to read truth from; "
            f"got {type(task_scope).__name__}, which declares no `rows`."
        )
    if not data_dir:
        raise ValueError(
            "the DAVIS metrics need `data_dir` to read the target frames; the "
            "framework transports it, so an absent value is a wiring defect."
        )
    # `truth_windows` is the pack's EXISTING single authority for evaluation
    # ground truth — its own docstring says "one authority; the metric never
    # re-derives pixels". Assembling the mapping here from `load_window` would
    # have been a second traversal that looked identical and could drift, which
    # is precisely what that authority exists to prevent.
    return truth_windows(data_dir, rows)
