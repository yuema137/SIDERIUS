# execute_tools/health_checks/categorical_dominant_fraction.py
"""Generic categorical collapse check: does one symbol dominate the output.

The complement of ``categorical_distinct_symbols``, and the reason the
parent's collapse evidence had to be corrected before this family was
designed: the REAL preserved D14 Pets collapse is 369/370 = 0.9972973 on
the dominant class with 2 distinct classes — NEAR-constant, not constant.
A ``distinct == 1`` test would have called it healthy. Dominance
thresholds on a FRACTION, so a deliverable that is 99% one class fails
regardless of a handful of stray predictions.

Task-agnostic: consumes the standard ``categorical_predictions`` view and
the injected ``symbol_cardinality`` (needed by the §3.2a range validity —
the family's ONE shared mechanism in ``_categorical_validity``). No task
name, no artifact I/O, no metric consumption.
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np

from execute_tools.health_checks._categorical_validity import (
    resolve_categorical_inputs,
    validate_symbols,
)
from execute_tools.health_checks._view_provider import HealthView
from execute_tools.health_checks.schemas import (
    CheckInputDeclaration,
    CheckVerdict,
    FactRequirement,
    HealthCheckContext,
    HealthCheckResult,
)
from execute_tools.health_checks.standard_views import CATEGORICAL_PREDICTIONS


class CategoricalDominantFractionCheck:
    """Flag a categorical deliverable dominated by one symbol."""

    name: ClassVar[str] = "categorical_dominant_fraction"

    declaration: ClassVar[CheckInputDeclaration] = CheckInputDeclaration(
        consumes_view=CATEGORICAL_PREDICTIONS,
        requires_view=True,
        required_context_inputs=(),
        # Consumed by the shared range-validity ruling (§3.2a): a symbol
        # outside [0, cardinality) is FAILED, and the range needs the
        # declared alphabet size. Presence-only, injected by composition.
        required_facts=(FactRequirement(axis="symbol_cardinality"),),
        threshold_parameter_names=("max_dominant_fraction",),
    )

    #: Authoring safety net only — real tasks author their own ceiling
    #: (task-owned threshold, §3.4).
    _DEFAULT_MAX_DOMINANT_FRACTION: ClassVar[float] = 0.95

    def run(
        self,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
        *,
        view: HealthView | None = None,
    ) -> HealthCheckResult:
        cfg = config or {}
        ceiling = float(cfg.get("max_dominant_fraction", self._DEFAULT_MAX_DOMINANT_FRACTION))

        resolved = resolve_categorical_inputs(
            self.name, cfg, view, extra_metrics={"max_dominant_fraction": ceiling}
        )
        if isinstance(resolved, HealthCheckResult):
            return resolved
        symbols, cardinality, n = resolved

        validity = validate_symbols(symbols, cardinality)
        if not validity.valid:
            return HealthCheckResult(
                check_name=self.name,
                passed=False,
                reason=f"{self.name}: {validity.reason}",
                metrics={
                    "n_samples": n,
                    "symbol_cardinality": cardinality,
                    "invalid_symbol_count": validity.invalid_count,
                    "max_dominant_fraction": ceiling,
                },
                verdict=CheckVerdict.FAILED,
            )

        values, counts = np.unique(symbols, return_counts=True)
        dominant_index = int(np.argmax(counts))
        dominant_symbol = int(values[dominant_index])
        dominant_fraction = int(counts[dominant_index]) / n
        passed = dominant_fraction <= ceiling

        reason = ""
        if not passed:
            reason = (
                f"{self.name}: symbol {dominant_symbol} accounts for "
                f"{dominant_fraction:.6g} of {n} prediction(s), above the "
                f"ceiling {ceiling:g} — a collapsed or near-collapsed "
                f"categorical deliverable."
            )
        return HealthCheckResult(
            check_name=self.name,
            passed=passed,
            reason=reason,
            metrics={
                "n_samples": n,
                "dominant_symbol": dominant_symbol,
                "dominant_fraction": dominant_fraction,
                "symbol_cardinality": cardinality,
                "max_dominant_fraction": ceiling,
            },
            verdict=CheckVerdict.PASSED if passed else CheckVerdict.FAILED,
        )
