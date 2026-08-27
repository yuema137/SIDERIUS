# execute_tools/health_checks/_multi_file_peek.py
"""
Shared multi-file peek helper for blocking health checks (M9 / Strategy C).

The three blocking checks — ``output_diversity``, ``output_std``,
``amplitude_collapse`` — all follow the same shape: peek CH1 of one or
more denoised HDF5 files, compute a scalar per file, apply a threshold
per file, aggregate the per-file verdicts into a single gate verdict.

This module owns that peek + metric + predicate + aggregate loop so the
three checks don't drift. See
``docs/design/m9_multi_file_peek_execution_plan.md`` for the design.

Aggregation modes (see ``AggregationMode``):
  * ``any_pass``  — at least one per-file passed (I/O failures dropped)
  * ``all_pass``  — every per-file passed (I/O failures count as fail)
  * ``max`` / ``min`` / ``mean`` / ``median`` — apply predicate to the
    named aggregate of the per-file metric values (I/O failures dropped)

Backward compat: empty ``peek_file_indices`` triggers a fallback to
``[min(ctx.denoised_paths)]`` (or ``[0]``) — matches the pre-M9
single-file peek behavior; existing YAML entries keep working.

"Not applicable" contract: when the caller passes an empty
``peek_file_indices`` AND every resolved file lacks a path in the
context (context has no ``denoised_paths`` and no ``denoised_filename_fn``
that can produce one), the outcome is ``passed=True`` with a
"not applicable" reason — mirrors the pre-M9 output_diversity fallback
so tests / stubs that build empty contexts don't accidentally fail.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, get_args

import numpy as np
from pydantic import BaseModel, Field

from execute_tools.deliverable_spec import default_deliverable_storage
from execute_tools.health_checks._peek import peek_int8_at_channel
from execute_tools.health_checks.schemas import HealthCheckContext

AggregationMode = Literal["any_pass", "all_pass", "max", "min", "mean", "median"]

VALID_AGGREGATION_MODES: frozenset[str] = frozenset(get_args(AggregationMode))
"""Runtime mirror of ``AggregationMode``, derived from the Literal so the two
can never drift.

``peek_and_aggregate`` enforces membership BEFORE any file I/O (M cleanup,
2026-08-26). The mode reaches this module as a bare string out of YAML/dict
check config, so the ``AggregationMode`` annotation alone enforced nothing at
runtime: an unrecognized value used to fail only after the peeks — or, when
every peek failed, not at all, because ``_apply_aggregation`` returned a
silent ``False`` that recorded a config typo as an aggregation failure. An
unknown mode is a configuration error and fails closed with the valid
vocabulary named; on a blocking gate the runner's guard turns the raise into
``CheckVerdict.ERROR`` -> ``on_fail``, never a pass."""


class PerFilePeekResult(BaseModel):
    """One file's contribution to a multi-file peek."""

    file_index: int = Field(
        description="Which file_index this row corresponds to.",
    )
    metric_value: float | int | None = Field(
        default=None,
        description=(
            "Scalar per-file metric from ``metric_fn``. ``None`` when the "
            "peek failed (see ``io_error``)."
        ),
    )
    passed: bool = Field(
        default=False,
        description=(
            "Per-file predicate verdict. I/O-failed entries have "
            "``passed=False``; the aggregation step then decides how to "
            "treat them (any_pass drops failed rows from consideration; "
            "all_pass counts them as fail)."
        ),
    )
    io_error: str | None = Field(
        default=None,
        description=(
            "Populated on peek failure — either an OSError/KeyError from "
            "the HDF5 read, or a synthetic 'no path resolved' error when "
            "``ctx.get_denoised_path`` returned ``None``. ``None`` when "
            "the peek succeeded."
        ),
    )


class MultiFilePeekOutcome(BaseModel):
    """Aggregated verdict + per-file breakdown for record observability."""

    passed: bool = Field(
        description="Aggregated verdict after applying ``aggregation``.",
    )
    aggregation: AggregationMode = Field(
        description=(
            "Aggregation mode used ('any_pass', 'all_pass', ...). Typed as "
            "the ``AggregationMode`` Literal (M cleanup, 2026-08-26) so the "
            "carrier itself refuses a value the runtime does not implement."
        ),
    )
    per_file: list[PerFilePeekResult] = Field(
        default_factory=list,
        description="One entry per resolved file_index, in the order peeked.",
    )
    n_files_attempted: int = Field(
        default=0,
        description="Number of file_indices the helper attempted to peek.",
    )
    n_files_io_failed: int = Field(
        default=0,
        description=(
            "Subset of ``n_files_attempted`` where the peek raised (or the "
            "context had no resolvable path)."
        ),
    )
    reason: str = Field(
        default="",
        description=(
            "Human-readable summary of the failure. Empty when ``passed`` "
            "is True. Populated on 'not applicable' passes with the "
            "fallback reason string."
        ),
    )


def _resolve_indices(ctx: HealthCheckContext, peek_file_indices: list[int]) -> list[int]:
    """Return the list of file_indices to actually peek.

    Explicit list → dedupe while preserving order (so a typo like
    ``[3, 3, 10]`` doesn't double-count). Empty list → fall back to
    ``[min(ctx.denoised_paths)]`` (or ``[0]``) — the pre-M9 single-file
    behavior.
    """
    if peek_file_indices:
        seen: set[int] = set()
        deduped: list[int] = []
        for idx in peek_file_indices:
            if idx not in seen:
                seen.add(idx)
                deduped.append(idx)
        return deduped
    if ctx.denoised_paths:
        return [min(ctx.denoised_paths.keys())]
    return [0]


def _apply_aggregation(
    per_file: list[PerFilePeekResult],
    predicate: Callable[[float | int], bool],
    aggregation: AggregationMode,
) -> bool:
    """Combine per-file verdicts into a single gate verdict.

    ``any_pass`` / ``all_pass`` operate on the per-file ``passed`` field
    (predicate already applied). ``max`` / ``min`` / ``mean`` / ``median``
    operate on the per-file ``metric_value`` field (predicate applied to
    the aggregate).
    """
    if aggregation == "any_pass":
        # I/O-failed entries are dropped from consideration. If at least
        # one succeeded AND passed, the gate passes. No successes → fail.
        return any(r.passed for r in per_file if r.io_error is None)
    if aggregation == "all_pass":
        # I/O failure counts as fail (strictest interpretation).
        return all(r.passed for r in per_file)
    # Numeric aggregation modes.
    values: list[float | int] = [
        r.metric_value for r in per_file if r.io_error is None and r.metric_value is not None
    ]
    if not values:
        return False
    if aggregation == "max":
        return predicate(max(values))
    if aggregation == "min":
        return predicate(min(values))
    if aggregation == "mean":
        return predicate(float(np.mean(values)))
    if aggregation == "median":
        return predicate(float(np.median(values)))
    raise ValueError(f"unknown aggregation mode: {aggregation!r}")


def peek_and_aggregate(
    ctx: HealthCheckContext,
    peek_file_indices: list[int],
    metric_fn: Callable[[np.ndarray], float | int],
    predicate: Callable[[float | int], bool],
    aggregation: AggregationMode,
    peek_samples: int,
    channel: str | None = None,
) -> MultiFilePeekOutcome:
    """Peek each file, compute per-file metric, apply predicate, aggregate.

    Args:
        ctx: standard ``HealthCheckContext``.
        peek_file_indices: which file_indices to peek. Empty list →
            fallback to ``[min(ctx.denoised_paths)]`` (or ``[0]``) for
            backward compat with the pre-M9 single-file peek behavior.
        metric_fn: per-file scalar — takes int8 numpy array of peek
            samples, returns a float or int.
        predicate: per-file pass/fail — takes the scalar, returns bool.
            Used for ``any_pass`` / ``all_pass`` modes AND applied to
            the aggregated scalar for ``max`` / ``min`` / ``mean`` /
            ``median`` modes.
        aggregation: how to combine per-file verdicts.
        peek_samples: forwarded to ``peek_int8_at_channel``.
        channel: which in-file channel group to read. ``None`` resolves it
            from the Deliverable Contract, which OWNS that identity
            (Step 08a C5) — the same adapter shape
            :func:`~execute_tools.deliverable_spec.default_deliverable_storage`
            was introduced for at 05c, so a caller predating the parameter
            keeps reading exactly what it read before while no channel
            literal survives in this module. Production checks pass it
            explicitly, resolved once per ``run``.

    Returns:
        ``MultiFilePeekOutcome`` with per-file breakdown and aggregated
        verdict. Callers should surface ``per_file`` via
        ``HealthCheckResult.metrics["per_file_json"]``
        (json-serialised) for record observability.

    Raises:
        ValueError: ``aggregation`` is not a member of ``AggregationMode``.
            Raised BEFORE any file is opened — an unimplemented rule must
            never be paid for with I/O, and must never resolve to a verdict.
    """
    if aggregation not in VALID_AGGREGATION_MODES:
        raise ValueError(
            f"unknown aggregation mode {aggregation!r}; valid modes: "
            f"{sorted(VALID_AGGREGATION_MODES)}. Aggregation comes either "
            f"from the task roster entry's parameters or, when the entry "
            f"declares none, from health_policy.<disposition>.check_config "
            f"in configs/health_checks.yaml — failing closed rather than "
            f"peeking under a rule the runtime does not implement."
        )
    if channel is None:
        channel = default_deliverable_storage().input_channel_group
    resolved = _resolve_indices(ctx, peek_file_indices)
    per_file: list[PerFilePeekResult] = []
    no_path_count = 0
    for i in resolved:
        path = ctx.get_denoised_path(i)
        if path is None:
            no_path_count += 1
            per_file.append(
                PerFilePeekResult(
                    file_index=i,
                    metric_value=None,
                    passed=False,
                    io_error=f"no path resolved for file_index={i}",
                )
            )
            continue
        try:
            samples = peek_int8_at_channel(path, channel, peek_samples)
        except (OSError, KeyError) as exc:
            per_file.append(
                PerFilePeekResult(
                    file_index=i,
                    metric_value=None,
                    passed=False,
                    io_error=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        metric = metric_fn(samples)
        # Pydantic v2 accepts numpy scalars via type coercion, but be
        # explicit so downstream JSON serialisation is well-typed.
        py_metric: float | int = (
            float(metric) if isinstance(metric, float | np.floating) else int(metric)
        )
        per_file.append(
            PerFilePeekResult(
                file_index=i,
                metric_value=py_metric,
                passed=bool(predicate(py_metric)),
                io_error=None,
            )
        )

    n_attempted = len(per_file)
    n_io_failed = sum(1 for r in per_file if r.io_error is not None)

    # "Not applicable" contract: caller did not ask for specific files
    # AND every resolved fallback file lacked a resolvable path. This
    # is the pre-M9 output_diversity behaviour — passing tests / stubs
    # that construct empty contexts must not fail here.
    if not peek_file_indices and no_path_count == n_attempted and n_attempted > 0:
        return MultiFilePeekOutcome(
            passed=True,
            aggregation=aggregation,
            per_file=per_file,
            n_files_attempted=n_attempted,
            n_files_io_failed=n_io_failed,
            reason="not applicable — no path configured in context",
        )

    verdict = _apply_aggregation(per_file, predicate, aggregation)
    reason = ""
    if not verdict:
        io_errors = [r for r in per_file if r.io_error is not None]
        if len(io_errors) == n_attempted:
            reason = (
                f"all {n_attempted} peeked file(s) failed I/O; first error: {io_errors[0].io_error}"
            )
        else:
            per_file_summary = ", ".join(
                (
                    f"file_{r.file_index}=io_err"
                    if r.io_error
                    else f"file_{r.file_index}={r.metric_value}"
                )
                for r in per_file
            )
            reason = f"aggregation={aggregation} failed — per-file: {per_file_summary}"

    return MultiFilePeekOutcome(
        passed=verdict,
        aggregation=aggregation,
        per_file=per_file,
        n_files_attempted=n_attempted,
        n_files_io_failed=n_io_failed,
        reason=reason,
    )
