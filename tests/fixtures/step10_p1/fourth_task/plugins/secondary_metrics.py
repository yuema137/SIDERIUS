"""Synthetic secondary metrics for composition-contract tests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from execute_tools.evaluation_metric import EvaluationMetric


class _MeanDeclaredValueMetric(EvaluationMetric):
    """Return the mean of a synthetic mapping supplied by the test."""

    def _compute(
        self,
        deliverables: Mapping[int, str],
        /,
        *,
        values: Mapping[str, float] | None = None,
        **_unused: Any,
    ) -> tuple[float, list[float | None] | None, tuple[str, ...]]:
        resolved = list((values or {}).values())
        if not resolved:
            raise ValueError("synthetic secondary metric requires declared values.")
        return sum(resolved) / len(resolved), None, ()


class BandBiasMetric(_MeanDeclaredValueMetric):
    IMPLEMENTS: ClassVar[tuple[str, ...]] = ("band_bias",)


class BandSpreadMetric(_MeanDeclaredValueMetric):
    IMPLEMENTS: ClassVar[tuple[str, ...]] = ("band_spread",)
