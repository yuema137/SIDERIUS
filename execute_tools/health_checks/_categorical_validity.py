# execute_tools/health_checks/_categorical_validity.py
"""The ONE §3.2a boundary implementation for the categorical check family.

Step 08c §3.2a draws a frozen verdict boundary:

* inability to compute — no view, a foreign payload, a missing injected
  cardinality, an EMPTY stream — is **ERROR** (the absence of evidence,
  never a pass);
* a stream that was READ but carries symbols outside
  ``[0, symbol_cardinality)`` is **FAILED** (an observable deliverable
  pathology — the artifact is wrong, which is exactly the statement Health
  exists to make).

Both categorical collapse checks must draw both lines identically: a
malformed stream accepted by one check and rejected by the other would make
the family's verdicts depend on which gate happened to run first. So the
mechanism lives here exactly once, pure and NumPy-only, and both checks
consume it. Mutation tests prove each check actually calls it.
"""

from __future__ import annotations

from typing import Any, NamedTuple

import numpy as np

from execute_tools.health_checks._view_provider import HealthView
from execute_tools.health_checks.schemas import (
    CheckVerdict,
    HealthCheckResult,
)
from execute_tools.health_checks.standard_views import (
    CATEGORICAL_PREDICTIONS,
    CategoricalPredictionsPayload,
)


class SymbolValidity(NamedTuple):
    """One validity ruling over a symbol stream, computed exactly once."""

    valid: bool
    invalid_count: int
    first_invalid: int | None
    reason: str
    """Deterministic report naming the first offender and the valid range.

    Empty exactly when valid."""


def validate_symbols(symbols: np.ndarray, symbol_cardinality: int) -> SymbolValidity:
    """Rule on every symbol lying in ``[0, symbol_cardinality)``.

    Args:
        symbols: 1-D integer symbol stream (the standard categorical
            payload's array; read-only views are fine — nothing here
            mutates).
        symbol_cardinality: the task-declared alphabet size, > 1.

    Returns:
        The ruling. Never raises on stream CONTENT — content problems are a
        verdict, not an exception (§3.2a).
    """
    out_of_range = (symbols < 0) | (symbols >= symbol_cardinality)
    invalid_count = int(np.count_nonzero(out_of_range))
    if invalid_count == 0:
        return SymbolValidity(valid=True, invalid_count=0, first_invalid=None, reason="")
    first_index = int(np.argmax(out_of_range))
    first_value = int(symbols[first_index])
    return SymbolValidity(
        valid=False,
        invalid_count=invalid_count,
        first_invalid=first_value,
        reason=(
            f"{invalid_count} symbol(s) lie outside the declared alphabet "
            f"[0, {symbol_cardinality}) — first offender {first_value} at "
            f"index {first_index}. The deliverable was read and it is "
            f"invalid."
        ),
    )


class CategoricalInputs(NamedTuple):
    """Structurally sound inputs for one categorical check invocation."""

    symbols: np.ndarray
    symbol_cardinality: int
    n_samples: int


def resolve_categorical_inputs(
    check_name: str,
    cfg: dict[str, Any],
    view: HealthView | None,
    *,
    extra_metrics: dict[str, Any],
) -> CategoricalInputs | HealthCheckResult:
    """The §3.2a ERROR half, applied before any arithmetic.

    Args:
        check_name: the consuming check's registered name, prefixed into
            every reason.
        cfg: the check's composed config; ``symbol_cardinality`` must have
            been injected by composition (§3.3).
        view: the materialized standard view, or None when the dispatch
            path failed to supply one.
        extra_metrics: check-specific keys (its threshold) folded into an
            ERROR result's metrics, so the persisted record still names the
            boundary that would have applied.

    Returns:
        The validated inputs, or a ready ``CheckVerdict.ERROR`` result.
        Emptiness is ruled HERE (error), range validity is
        :func:`validate_symbols` (failed) — the two halves of §3.2a.
    """

    def _error(reason: str, metrics: dict[str, Any]) -> HealthCheckResult:
        return HealthCheckResult(
            check_name=check_name,
            passed=False,
            reason=f"{check_name}: {reason}",
            metrics={**metrics, **extra_metrics},
            verdict=CheckVerdict.ERROR,
        )

    if view is None:
        return _error(
            f"requires the {CATEGORICAL_PREDICTIONS!r} view and none was supplied",
            {},
        )
    if not isinstance(view.payload, CategoricalPredictionsPayload):
        return _error(
            f"view payload is {type(view.payload).__name__}, expected "
            f"CategoricalPredictionsPayload (provider {view.provider_id!r})",
            {},
        )
    cardinality = cfg.get("symbol_cardinality")
    if not isinstance(cardinality, int) or isinstance(cardinality, bool) or cardinality <= 1:
        return _error(
            f"symbol_cardinality {cardinality!r} was not injected as an "
            f"integer > 1; composition injects it from the task's declared "
            f"facts (§3.3), so this is a wiring defect, not task data",
            {},
        )
    symbols = view.payload.symbols
    n = int(symbols.size)
    if n == 0:
        return _error(
            "the symbol stream is empty; alphabet statistics over nothing "
            "are the absence of evidence, not a pass",
            {"n_samples": 0, "symbol_cardinality": cardinality},
        )
    return CategoricalInputs(symbols=symbols, symbol_cardinality=cardinality, n_samples=n)
