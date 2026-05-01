"""
Pure table math + markdown rendering for the per-file score comparison table
(Phase 2 of ``docs/aggregated_score_table_awareness.md``).

Zero I/O, zero side effects — the "atomic tool" half of the Phase 2 split
(Decision 10). The node-side loader + caching lives in
``nodes/scoring_reference.py``.

Two entry points:

* ``build_score_table(model_fv_log, model_scalar, reference)`` — produces a
  ``ScoreComparisonTable`` (or ``None`` when the model has no scalar, i.e. a
  fully failed run). Aggregates are re-computed over the sampled subset; see
  Decision 14.
* ``render_comparison_table(table)`` — the one authoritative markdown
  renderer. The produced string lives on ``table.rendered_markdown`` and is
  substituted verbatim into LLM prompts.
"""

from __future__ import annotations

import math
from typing import List, Optional

from agent.schemas.score_table import (
    AggregateScalars,
    PerFileRow,
    ScoreComparisonTable,
)
from execute_tools.dataset_config import NUM_FILES
from nodes.scoring_reference import ReferenceScores


_LOG_BASE = 5.27
_LOG_OFFSET = 1e-10


# ---------------------------------------------------------------------------
# file_vector_to_log_space
# ---------------------------------------------------------------------------

def file_vector_to_log_space(
    file_vector_linear: List[Optional[float]],
    *,
    base: float = _LOG_BASE,
    offset: float = _LOG_OFFSET,
) -> List[Optional[float]]:
    """Convert a linear-space per-file vector to log-space.

    ``execute_tools.scoring_utils.score_vector`` returns the per-file
    vector in *linear* units (``file_sum / n_segments`` of the normalised
    score). The reference per-file columns
    (``ReferenceScores.raw_per_file_log`` and ``gt_per_file_log``) are
    in *log* units (``math.log(mean_linear, 5.27)`` — see
    ``compute_raw_baseline._per_file_log_score``). ``build_score_table``
    expects the model column in the same log-space units so the rendered
    markdown is unit-consistent across all three columns.

    The conversion mirrors the reference convention with one robustness
    knob: an additive ``offset`` (default ``1e-10``) keeps ``log(0)``
    finite. At base 5.27 this places the soft floor at
    ``log_5.27(1e-10) ≈ -13.854``, matching the floor visible in the
    reference per-file log columns for files with no signal.

    Parameters
    ----------
    file_vector_linear
        Length-``NUM_FILES`` list of per-file linear scalars from
        ``score_vector``. ``None`` entries (un-sampled files in trial
        mode) pass through unchanged.
    base
        Logarithm base. Default ``5.27`` (the project-wide convention).
    offset
        Additive offset applied before the log to keep ``log(0)`` finite.
        Default ``1e-10``.

    Returns
    -------
    Same-length list with each non-``None`` entry mapped to
    ``log_{base}(max(v, 0) + offset)``. Negative inputs (which are not
    expected from the score formula but are clipped defensively) are
    treated as zero before applying the offset.
    """
    out: List[Optional[float]] = []
    for v in file_vector_linear:
        if v is None:
            out.append(None)
            continue
        clamped = max(float(v), 0.0)
        out.append(float(math.log(clamped + offset, base)))
    return out


# ---------------------------------------------------------------------------
# build_score_table
# ---------------------------------------------------------------------------

def build_score_table(
    model_fv_log: List[Optional[float]],
    model_scalar: Optional[float],
    reference: ReferenceScores,
    *,
    reference_source: str = "reference_data/raw_and_ground_score.md",
) -> Optional[ScoreComparisonTable]:
    """Assemble a ``ScoreComparisonTable`` for one run's file_vector.

    Parameters
    ----------
    model_fv_log
        Length-20 vector of log-space per-file scores from this run. Entries
        are ``None`` for files outside the sampled set (trial mode).
    model_scalar
        The ``final_scalar`` returned by ``score_vector`` for this run. Pass
        ``None`` to signal a fully failed run — the function returns ``None``.
    reference
        Frozen ``ReferenceScores`` bundle from
        ``nodes.scoring_reference.load_reference_scores``.
    reference_source
        Human-readable pointer recorded on the table. Default is the canonical
        markdown reference file.

    Returns
    -------
    ``ScoreComparisonTable`` with 20 rows, subset-scoped aggregate scalars,
    and the pre-rendered markdown. Returns ``None`` iff ``model_scalar is
    None``.
    """
    if model_scalar is None:
        return None
    if len(model_fv_log) != 20:
        raise ValueError(
            f"model_fv_log must have length 20, got {len(model_fv_log)}."
        )

    sampled_indices = [i for i, v in enumerate(model_fv_log) if v is not None]
    if not sampled_indices:
        # Defensive: a non-None model_scalar with an all-None file_vector is
        # inconsistent — score_vector cannot produce a scalar from nothing.
        raise ValueError(
            "model_scalar is not None but model_fv_log is all-None — "
            "inconsistent: score_vector requires at least one sampled file."
        )

    rows = _build_rows(model_fv_log, reference)
    aggregate = _aggregate_over_subset(
        sampled_indices=sampled_indices,
        model_scalar=model_scalar,
        reference=reference,
    )

    table = ScoreComparisonTable(
        rows=rows,
        aggregate=aggregate,
        s_max_global=reference.s_max,
        reference_source=reference_source,
        rendered_markdown="",  # filled below
    )
    # Render once, store on the model — single source of truth (Decision 3).
    table = table.model_copy(update={"rendered_markdown": render_comparison_table(table)})
    return table


def _build_rows(
    model_fv_log: List[Optional[float]],
    reference: ReferenceScores,
) -> List[PerFileRow]:
    rows: List[PerFileRow] = []
    for i in range(NUM_FILES):
        raw = reference.raw_per_file_log[i]
        gt = reference.gt_per_file_log[i]
        m = model_fv_log[i]
        gain = (m - raw) if (m is not None) else None
        # Phase 8: ``headroom_vs_gt`` is "remaining room to grow toward the
        # ceiling" — by definition non-negative. A raw ``gt - model``
        # difference can come out negative on dead-zone files (gt at floor,
        # model slightly above floor due to noise output) or in rare
        # numerical-overshoot cases on real-signal files; in neither case
        # is "negative headroom" a meaningful improvement target. Clip at
        # zero so the column means exactly one thing the LLM can act on.
        # The "ceiling reached / dead zone" diagnostic is conveyed
        # separately by P1 (gt-at-floor partition), not by this column.
        headroom = max(gt - m, 0.0) if (m is not None) else None
        rows.append(
            PerFileRow(
                file_index=i,
                raw_baseline=raw,
                ground_truth=gt,
                model=m,
                gain_vs_raw=gain,
                headroom_vs_gt=headroom,
            )
        )
    return rows


def _aggregate_over_subset(
    *,
    sampled_indices: List[int],
    model_scalar: float,
    reference: ReferenceScores,
) -> AggregateScalars:
    raw_total_linear = sum(
        reference.raw_per_file_linear_sum[i] for i in sampled_indices
    )
    raw_total_n = sum(
        reference.raw_per_file_n_segments[i] for i in sampled_indices
    )
    gt_total_linear = sum(
        reference.gt_per_file_linear_sum[i] for i in sampled_indices
    )
    gt_total_n = sum(
        reference.gt_per_file_n_segments[i] for i in sampled_indices
    )

    raw_scalar = _grand_mean_log_scalar(raw_total_linear, raw_total_n)
    gt_scalar = _grand_mean_log_scalar(gt_total_linear, gt_total_n)

    if gt_scalar == 0.0 or not math.isfinite(gt_scalar):
        # Ratio is undefined when the ceiling is at log(1) or at the -inf
        # sentinel. Clip to 0.0 — the markdown render guard handles the
        # below-baseline messaging separately.
        recovery = 0.0
    else:
        recovery = model_scalar / gt_scalar

    return AggregateScalars(
        raw_baseline_scalar=raw_scalar,
        ground_truth_scalar=gt_scalar,
        model_scalar=model_scalar,
        percent_of_ceiling_log=recovery,
        num_sampled_files=len(sampled_indices),
    )


def _grand_mean_log_scalar(total_linear: float, total_n: int) -> float:
    """Phase-1 aggregator: log_{5.27}(grand_mean). Returns -inf when no signal."""
    if total_n <= 0:
        return float("-inf")
    grand_mean = total_linear / total_n
    if grand_mean > 0 and math.isfinite(grand_mean):
        return float(math.log(grand_mean, _LOG_BASE))
    return float("-inf")


# ---------------------------------------------------------------------------
# render_comparison_table
# ---------------------------------------------------------------------------

_HEADER = (
    "### Per-file performance (log-space, all three columns on global s_max)\n"
    "\n"
    "| file | raw_baseline | ground_truth | **model** | gain vs raw | headroom vs gt |\n"
    "|-----:|-------------:|-------------:|----------:|------------:|---------------:|"
)

_AGG_HEADER = (
    "### Aggregated scalar (log space, global s_max)\n"
    "\n"
    "Single number per row — the `final_scalar` returned by `score_vector()` "
    "for each source. This is the only aggregation in the pipeline.\n"
    "\n"
    "| metric               | log scalar |\n"
    "|----------------------|-----------:|"
)


def render_comparison_table(table: ScoreComparisonTable) -> str:
    """Render the exact prompt-ready markdown for a ``ScoreComparisonTable``.

    Pure function (does not mutate the input). The table.rendered_markdown
    field is populated with the output of this function by ``build_score_table``.
    """
    lines: List[str] = [_HEADER]
    for row in table.rows:
        lines.append(_render_row(row))

    lines.append("")
    lines.append(_AGG_HEADER)
    agg = table.aggregate
    lines.append(
        f"| ground_truth ceiling | {_fmt_log(agg.ground_truth_scalar):>10} |"
    )
    lines.append(
        f"| **model**            | **{_fmt_log(agg.model_scalar)}** |"
    )
    lines.append(
        f"| raw baseline         | {_fmt_log(agg.raw_baseline_scalar):>10} |"
    )
    lines.append("")
    if agg.model_scalar < agg.raw_baseline_scalar:
        # Below-baseline guard: when the model scores worse than the raw
        # baseline, the log-space ratio flips sign and the "% of ceiling"
        # framing is actively misleading (e.g. -108.3% of ceiling). Replace
        # with an honest one-liner the LLM can reason about directly.
        lines.append(
            "Recovery: < 0% (Model performance is below raw baseline)."
        )
    else:
        lines.append(
            f"Recovery: **{agg.percent_of_ceiling_log * 100:.1f}% of ceiling** "
            f"(model_scalar / ground_truth_scalar)."
        )

    if agg.num_sampled_files < 20:
        lines.append("")
        lines.append(
            f"_Note: scalars computed over {agg.num_sampled_files} sampled files._"
        )

    return "\n".join(lines)


def _render_row(row: PerFileRow) -> str:
    cells = [
        f"{row.file_index:>4}",
        _fmt_log(row.raw_baseline),
        _fmt_log(row.ground_truth),
        _fmt_log(row.model),
        _fmt_log(row.gain_vs_raw),
        _fmt_log(row.headroom_vs_gt),
    ]
    return (
        f"| {cells[0]} "
        f"| {cells[1]:>12} "
        f"| {cells[2]:>12} "
        f"| {cells[3]:>9} "
        f"| {cells[4]:>11} "
        f"| {cells[5]:>14} |"
    )


def _fmt_log(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    if not math.isfinite(value):
        # math.isnan/isinf — render the sentinel cleanly rather than letting
        # f-string emit "-inf.0000" garbage.
        if math.isnan(value):
            return "NaN"
        return "\u2212\u221E" if value < 0 else "\u221E"
    # Render negatives with a Unicode minus so columns align with the
    # reference_data/raw_and_ground_score.md table style.
    if value < 0:
        return f"\u2212{abs(value):.4f}"
    return f"{value:.4f}"
