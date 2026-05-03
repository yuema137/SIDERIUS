"""
Pure table math + markdown rendering for the per-file score comparison table
(Phase 2 of ``docs/aggregated_score_table_awareness.md``).

Zero I/O, zero side effects — the "atomic tool" half of the Phase 2 split
(Decision 10). The node-side loader + caching lives in
``nodes/scoring_reference.py``.

Two entry points:

* ``build_score_table(model_fv_log, model_scalar, reference, *,
  model_fv_linear=...)`` — produces a ``ScoreComparisonTable`` (or ``None``
  when the model has no scalar, i.e. a fully failed run). Aggregates are
  re-computed over the sampled subset; see Decision 14. When
  ``model_fv_linear`` is supplied, each sampled row also carries a
  ``linear_weight`` (fractional contribution to the scalar denominator)
  and an ``impact_score`` (log-scalar gain if the file were lifted to its
  ground-truth ceiling). See P1-Impact (1-zh) in the design doc.
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
    model_fv_linear: Optional[List[Optional[float]]] = None,
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
    model_fv_linear
        Length-20 linear-space per-file vector (the raw output of
        ``score_vector``). Optional: when omitted, the helper derives a
        linear approximation from ``model_fv_log`` via the inverse of
        ``file_vector_to_log_space`` so legacy callers still get the
        impact columns. Production callers should pass the unconverted
        linear vector for numerical fidelity.
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
    if model_fv_linear is not None and len(model_fv_linear) != 20:
        raise ValueError(
            f"model_fv_linear must have length 20, got {len(model_fv_linear)}."
        )

    sampled_indices = [i for i, v in enumerate(model_fv_log) if v is not None]
    if not sampled_indices:
        # Defensive: a non-None model_scalar with an all-None file_vector is
        # inconsistent — score_vector cannot produce a scalar from nothing.
        raise ValueError(
            "model_scalar is not None but model_fv_log is all-None — "
            "inconsistent: score_vector requires at least one sampled file."
        )

    # Derive a linear vector from the log vector when the caller did not
    # supply one — keeps backward-compat with legacy call sites + tests
    # that only thread the log column through. The inverse formula mirrors
    # ``file_vector_to_log_space``: ``v_linear = base**v_log - offset``.
    if model_fv_linear is None:
        model_fv_linear = [
            (float(_LOG_BASE) ** v - _LOG_OFFSET) if v is not None else None
            for v in model_fv_log
        ]

    weights, impacts = _compute_weight_and_impact(
        sampled_indices=sampled_indices,
        model_fv_linear=model_fv_linear,
        reference=reference,
    )

    rows = _build_rows(model_fv_log, reference, weights=weights, impacts=impacts)
    aggregate = _aggregate_over_subset(
        sampled_indices=sampled_indices,
        model_scalar=model_scalar,
        reference=reference,
    )
    weight_total = sum(w for w in weights if w is not None)

    table = ScoreComparisonTable(
        rows=rows,
        aggregate=aggregate,
        s_max_global=reference.s_max,
        reference_source=reference_source,
        rendered_markdown="",  # filled below
        linear_weight_total=weight_total,
    )
    # Render once, store on the model — single source of truth (Decision 3).
    table = table.model_copy(update={"rendered_markdown": render_comparison_table(table)})
    return table


def _build_rows(
    model_fv_log: List[Optional[float]],
    reference: ReferenceScores,
    *,
    weights: Optional[List[Optional[float]]] = None,
    impacts: Optional[List[Optional[float]]] = None,
) -> List[PerFileRow]:
    rows: List[PerFileRow] = []
    for i in range(NUM_FILES):
        raw = reference.raw_per_file_log[i]
        gt = reference.gt_per_file_log[i]
        m = model_fv_log[i]
        # ``raw`` and ``gt`` are typed as ``list[float]`` on the dataclass
        # but defensively tolerate a missing reference entry (None) — the
        # PerFileRow schema accepts Optional[float] for both columns. If a
        # reference column is missing, the dependent ``gain_vs_raw`` /
        # ``headroom_vs_gt`` collapse to None (we cannot compute either
        # without both inputs).
        gain = (m - raw) if (m is not None and raw is not None) else None
        # Phase 8: ``headroom_vs_gt`` is "remaining room to grow toward the
        # ceiling" — by definition non-negative. A raw ``gt - model``
        # difference can come out negative on dead-zone files (gt at floor,
        # model slightly above floor due to noise output) or in rare
        # numerical-overshoot cases on real-signal files; in neither case
        # is "negative headroom" a meaningful improvement target. Clip at
        # zero so the column means exactly one thing the LLM can act on.
        # The "ceiling reached / dead zone" diagnostic is conveyed
        # separately by P1 (gt-at-floor partition), not by this column.
        headroom = (
            max(gt - m, 0.0) if (m is not None and gt is not None) else None
        )
        rows.append(
            PerFileRow(
                file_index=i,
                raw_baseline=raw,
                ground_truth=gt,
                model=m,
                gain_vs_raw=gain,
                headroom_vs_gt=headroom,
                linear_weight=(weights[i] if weights is not None else None),
                impact_score=(impacts[i] if impacts is not None else None),
            )
        )
    return rows


def _compute_weight_and_impact(
    *,
    sampled_indices: List[int],
    model_fv_linear: List[Optional[float]],
    reference: ReferenceScores,
) -> tuple[List[Optional[float]], List[Optional[float]]]:
    """Per-file Linear_Weight and Impact_Score over the sampled subset.

    Returns two length-NUM_FILES lists (``weights``, ``impacts``) with
    ``None`` at every unsampled index. When the sampled subset is degenerate
    (zero or non-finite linear mass, or any sampled file has missing
    reference data), both columns return all-None — the table still
    constructs cleanly, just without the impact block.

    Linear_Weight is computed from the per-file linear *means* (the same
    quantity the agent sees in the rendered ``model`` column once log-
    converted). Impact_Score is computed in linear-sum space (where the
    grand-mean lives), then converted to log_5.27 once.

    NOTE on the n_segments invariant: this helper reconstructs each file's
    model linear_sum as ``model_fv_linear[i] * reference.gt_per_file_n_
    segments[i]``. That holds today because the model and reference share
    a single fixed dataloader (same ``n_segments`` per file). If the
    project ever supports per-run-variable file shapes, the model's own
    n_segments must be threaded in instead.
    """
    weights: List[Optional[float]] = [None] * NUM_FILES
    impacts: List[Optional[float]] = [None] * NUM_FILES

    if not sampled_indices:
        return weights, impacts

    # Defensive precondition: every sampled index needs complete data
    # (model linear mean + reference n_segments + reference gt linear sum).
    # Path-A always fills the reference, so this guard exists only for
    # malformed test fixtures or partially-loaded reference bundles.
    means: List[float] = []
    for i in sampled_indices:
        m = model_fv_linear[i]
        n = reference.gt_per_file_n_segments[i]
        gt_sum = reference.gt_per_file_linear_sum[i]
        if m is None or n is None or gt_sum is None:
            return weights, impacts
        means.append(float(m))

    sigma = sum(means)
    if sigma <= 0 or not math.isfinite(sigma):
        return weights, impacts

    # Linear_Weight: fractional contribution of each sampled file to the
    # subset linear mean. Sums to 1 over the sampled subset.
    for i in sampled_indices:
        m = float(model_fv_linear[i])
        # Numerical clamp to [0, 1] — under exact arithmetic m/sigma is in
        # [0, 1] by construction, but float round-off can place the result
        # at 1.0 + epsilon, which would then trip the schema's le=1 bound.
        w = m / sigma
        if w < 0.0:
            w = 0.0
        elif w > 1.0:
            w = 1.0
        weights[i] = w

    # Impact_Score: log-space gain if file f were lifted to its gt ceiling,
    # holding the other sampled files fixed. Computed in linear-sum space
    # to match _aggregate_over_subset's grand-mean denominator.
    n_per_file_n: List[int] = [0] * NUM_FILES
    n_per_file_linear_sum: List[float] = [0.0] * NUM_FILES
    for i in sampled_indices:
        n_per_file_n[i] = int(reference.gt_per_file_n_segments[i])
        n_per_file_linear_sum[i] = float(model_fv_linear[i]) * n_per_file_n[i]

    total_n = sum(n_per_file_n[i] for i in sampled_indices)
    total_linear = sum(n_per_file_linear_sum[i] for i in sampled_indices)
    if total_n <= 0:
        return weights, impacts

    grand_mean_current = total_linear / total_n
    log_current = math.log(
        max(grand_mean_current, 0.0) + _LOG_OFFSET, _LOG_BASE,
    )

    for i in sampled_indices:
        gt_sum = float(reference.gt_per_file_linear_sum[i])
        # Replace this file's linear contribution with its ceiling.
        swapped = total_linear - n_per_file_linear_sum[i] + gt_sum
        gm_after = swapped / total_n
        log_after = math.log(
            max(gm_after, 0.0) + _LOG_OFFSET, _LOG_BASE,
        )
        # Clip to non-negative: a model that over-amplifies file i above
        # its gt ceiling would produce a negative raw delta when swapped
        # to ceiling. Surfacing that as "negative Impact" would invert
        # the agent's lever logic — over-amplification is not a fixable
        # lever, so clipping is the explicit design choice.
        impacts[i] = max(log_after - log_current, 0.0)

    return weights, impacts


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
    "| file | raw_baseline | ground_truth | **model** | gain vs raw | "
    "headroom vs gt | Impact | Weight % |\n"
    "|-----:|-------------:|-------------:|----------:|------------:|"
    "---------------:|-------:|---------:|"
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

_SECONDARY_HEADER = (
    "### Sampled files re-ranked by Impact_Score (descending)\n"
    "\n"
    "Highest-impact rows first — the marginal log-scalar gain available if "
    "each file were lifted to its ground-truth ceiling. Use this column to "
    "pick the next-iteration lever.\n"
    "\n"
    "| file | Impact | Weight % | headroom vs gt | model |\n"
    "|-----:|-------:|---------:|---------------:|------:|"
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

    # Secondary impact-ranked block — present only when at least one
    # sampled row carries an impact_score. Skipped on legacy / direct-dict
    # tables where the impact columns are all None.
    impact_rows = [r for r in table.rows if r.impact_score is not None]
    if impact_rows:
        lines.append("")
        lines.append(_SECONDARY_HEADER)
        for row in sorted(
            impact_rows,
            key=lambda r: (r.impact_score is None, -(r.impact_score or 0.0)),
        ):
            lines.append(_render_secondary_row(row))

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
        _fmt_log(row.impact_score),
        _fmt_pct(row.linear_weight),
    ]
    return (
        f"| {cells[0]} "
        f"| {cells[1]:>12} "
        f"| {cells[2]:>12} "
        f"| {cells[3]:>9} "
        f"| {cells[4]:>11} "
        f"| {cells[5]:>14} "
        f"| {cells[6]:>6} "
        f"| {cells[7]:>8} |"
    )


def _render_secondary_row(row: PerFileRow) -> str:
    cells = [
        f"{row.file_index:>4}",
        _fmt_log(row.impact_score),
        _fmt_pct(row.linear_weight),
        _fmt_log(row.headroom_vs_gt),
        _fmt_log(row.model),
    ]
    return (
        f"| {cells[0]} "
        f"| {cells[1]:>6} "
        f"| {cells[2]:>8} "
        f"| {cells[3]:>14} "
        f"| {cells[4]:>6} |"
    )


def _fmt_pct(value: Optional[float]) -> str:
    """Render a fraction in [0, 1] as a percent string with one decimal."""
    if value is None:
        return "N/A"
    if not math.isfinite(value):
        return "NaN" if math.isnan(value) else (
            "\u2212\u221E" if value < 0 else "\u221E"
        )
    return f"{value * 100:.1f}%"


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
