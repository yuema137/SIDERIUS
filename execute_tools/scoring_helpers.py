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
from nodes.scoring_reference import ReferenceScores


_LOG_BASE = 5.27
_ROUND_EPS = 1e-10
_LOG_FLOOR = math.log(_ROUND_EPS, _LOG_BASE)  # ≈ -13.854


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
    for i in range(20):
        raw = reference.raw_per_file_log[i]
        gt = reference.gt_per_file_log[i]
        m = model_fv_log[i]
        gain = (m - raw) if (m is not None) else None
        headroom = (gt - m) if (m is not None) else None
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

    if gt_scalar == 0.0:
        # Ceiling at log-zero would make the ratio undefined; clip to a
        # sentinel 0.0 recovery rather than raising — very-small-injection
        # edge case only, sits at the log floor for all three.
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
    """Identical to the Phase-1 aggregator: round to 2 dp, shift by eps, log_{5.27}."""
    if total_n <= 0:
        return _LOG_FLOOR
    grand_mean = total_linear / total_n
    return float(math.log(round(grand_mean, 2) + _ROUND_EPS, _LOG_BASE))


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
    # Render negatives with a Unicode minus so columns align with the
    # reference_data/raw_and_ground_score.md table style.
    if value < 0:
        return f"\u2212{abs(value):.4f}"
    return f"{value:.4f}"
