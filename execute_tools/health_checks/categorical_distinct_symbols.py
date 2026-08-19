# execute_tools/health_checks/categorical_distinct_symbols.py
"""Generic categorical collapse check: how much of the alphabet is alive.

The mechanism extracted from parent §3.2 — a collapsed classifier stops
using its alphabet. The REAL anchor is the preserved D14 Pets collapse
(child design §2.5): 370 predictions using 2 of 37 classes, occupancy
2/37 ≈ 0.054. A healthy 37-class model spreads far wider.

Task-agnostic by construction: it consumes the standard
``categorical_predictions`` view (whoever provides it) and the task's
declared ``symbol_cardinality`` (injected by composition, §3.3). No task
name, no artifact I/O, no metric consumption — the provider owns the
reading, this check owns the arithmetic. The §3.2a ERROR/FAILED boundary
is the family's shared mechanism in ``_categorical_validity``.
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


class CategoricalDistinctSymbolsCheck:
    """Flag a categorical deliverable that uses too few distinct symbols."""

    name: ClassVar[str] = "categorical_distinct_symbols"

    declaration: ClassVar[CheckInputDeclaration] = CheckInputDeclaration(
        consumes_view=CATEGORICAL_PREDICTIONS,
        requires_view=True,
        required_context_inputs=(),
        # Presence-only: the check needs the alphabet size, whatever it is.
        # A task declaring no cardinality makes this check honestly
        # INAPPLICABLE (axis named) before any I/O — never an error.
        required_facts=(FactRequirement(axis="symbol_cardinality"),),
        threshold_parameter_names=("min_distinct_symbols",),
    )

    #: Authoring safety net only — real tasks author their own floor
    #: (task-owned threshold, §3.4). 2 is the weakest meaningful floor:
    #: below it the deliverable is a literal constant.
    _DEFAULT_MIN_DISTINCT_SYMBOLS: ClassVar[int] = 2

    def run(
        self,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
        *,
        view: HealthView | None = None,
    ) -> HealthCheckResult:
        cfg = config or {}
        floor = int(cfg.get("min_distinct_symbols", self._DEFAULT_MIN_DISTINCT_SYMBOLS))

        resolved = resolve_categorical_inputs(
            self.name, cfg, view, extra_metrics={"min_distinct_symbols": floor}
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
                    "min_distinct_symbols": floor,
                },
                verdict=CheckVerdict.FAILED,
            )

        distinct = int(np.unique(symbols).size)
        # The injected cardinality provably enters the arithmetic (§3.2):
        # occupancy is the alphabet fraction actually in use.
        occupancy = distinct / cardinality
        passed = distinct >= floor

        reason = ""
        if not passed:
            reason = (
                f"{self.name}: {distinct} distinct symbol(s) of a "
                f"{cardinality}-symbol alphabet over {n} prediction(s) is "
                f"below the floor {floor} (occupancy {occupancy:.6g}) — a "
                f"collapsed or near-collapsed categorical deliverable."
            )
        return HealthCheckResult(
            check_name=self.name,
            passed=passed,
            reason=reason,
            metrics={
                "n_samples": n,
                "distinct_symbols": distinct,
                "symbol_cardinality": cardinality,
                "occupancy": occupancy,
                "min_distinct_symbols": floor,
            },
            verdict=CheckVerdict.PASSED if passed else CheckVerdict.FAILED,
        )
