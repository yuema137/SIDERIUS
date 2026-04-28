"""
Unit tests for ``execute_tools.scoring_helpers`` — pure table math and
markdown rendering.

Covers:
* ``build_score_table`` full-20 path (aggregate reproduces on-disk scalars).
* ``build_score_table`` trial-mode subset (aggregate re-computed; rows
  None-propagate).
* ``build_score_table`` model_scalar=None → returns None.
* ``render_comparison_table`` exact output on hand-computable scenarios
  (header, row rendering, N/A cells, aggregate block, subset footer).
"""
from __future__ import annotations

import math
from typing import List, Optional

import pytest

from agent.schemas.score_table import ScoreComparisonTable
from execute_tools.scoring_helpers import (
    _LOG_BASE,
    build_score_table,
    render_comparison_table,
)
from nodes.scoring_reference import ReferenceScores


# -----------------------------------------------------------------------------
# Helpers — build a synthetic ReferenceScores bundle.
# -----------------------------------------------------------------------------


def _make_reference(
    *,
    raw_linear_sum: Optional[List[float]] = None,
    gt_linear_sum: Optional[List[float]] = None,
    n_segments: int = 200,
    s_max: float = 295_715_680.14,
) -> ReferenceScores:
    """A 20-file reference bundle.

    Default: raw per-file linear_sum = 2.0 everywhere (per-file mean = 0.01
    → log_{5.27}(0.01) ≈ -2.7708);
    gt per-file linear_sum = 20.0 everywhere (per-file mean = 0.10
    → log_{5.27}(0.10) ≈ -1.3854 on base 5.27).

    Phase-67 scoring-precision fix: dropped the legacy ``round(·, 2) + 1e-10``
    quantization (which collapsed any per-file or grand mean in
    ``[0.005, 0.0149]`` to the ghost score ``-2.7708098959837675``). Now
    ``log_{5.27}(x)`` is taken directly when ``x > 0`` and ``isfinite(x)``;
    otherwise the helper returns ``float('-inf')``.

    Callers can override either list to hit specific subset-aggregation cases.
    """
    raw_linear_sum = raw_linear_sum or [2.0] * 20
    gt_linear_sum = gt_linear_sum or [20.0] * 20

    def _log_or_neg_inf(x: float) -> float:
        if x > 0 and math.isfinite(x):
            return math.log(x, _LOG_BASE)
        return float("-inf")

    raw_per_file_log = [_log_or_neg_inf(ls / n_segments) for ls in raw_linear_sum]
    gt_per_file_log = [_log_or_neg_inf(ls / n_segments) for ls in gt_linear_sum]
    # Full-20 grand-mean scalars.
    raw_gm = sum(raw_linear_sum) / (n_segments * 20)
    gt_gm = sum(gt_linear_sum) / (n_segments * 20)
    raw_scalar_full = _log_or_neg_inf(raw_gm)
    gt_scalar_full = _log_or_neg_inf(gt_gm)

    return ReferenceScores(
        raw_per_file_log=raw_per_file_log,
        gt_per_file_log=gt_per_file_log,
        raw_per_file_linear_sum=list(raw_linear_sum),
        raw_per_file_n_segments=[n_segments] * 20,
        gt_per_file_linear_sum=list(gt_linear_sum),
        gt_per_file_n_segments=[n_segments] * 20,
        raw_scalar_full=raw_scalar_full,
        gt_scalar_full=gt_scalar_full,
        s_max=s_max,
    )


# =============================================================================
# build_score_table — full-20 run
# =============================================================================


class TestBuildScoreTableFullRun:

    def test_aggregate_matches_on_disk_scalars(self):
        """When every index is sampled, the subset-aware aggregate equals the
        on-disk full-20 scalars by construction (same linear sums, same formula)."""
        ref = _make_reference()
        model_fv = list(ref.gt_per_file_log)          # perfect denoiser
        model_scalar = ref.gt_scalar_full

        tbl = build_score_table(model_fv, model_scalar, ref)
        assert tbl is not None
        assert tbl.aggregate.num_sampled_files == 20
        assert tbl.aggregate.raw_baseline_scalar == pytest.approx(
            ref.raw_scalar_full, abs=1e-12,
        )
        assert tbl.aggregate.ground_truth_scalar == pytest.approx(
            ref.gt_scalar_full, abs=1e-12,
        )
        assert tbl.aggregate.model_scalar == pytest.approx(model_scalar)
        assert tbl.aggregate.percent_of_ceiling_log == pytest.approx(
            model_scalar / ref.gt_scalar_full,
        )

    def test_rows_are_fully_populated(self):
        ref = _make_reference()
        model_fv = [0.5 * i for i in range(20)]
        tbl = build_score_table(model_fv, model_scalar=5.0, reference=ref)
        assert tbl is not None
        for i, row in enumerate(tbl.rows):
            assert row.file_index == i
            assert row.model == pytest.approx(model_fv[i])
            assert row.raw_baseline == pytest.approx(ref.raw_per_file_log[i])
            assert row.ground_truth == pytest.approx(ref.gt_per_file_log[i])
            assert row.gain_vs_raw == pytest.approx(
                model_fv[i] - ref.raw_per_file_log[i],
            )
            assert row.headroom_vs_gt == pytest.approx(
                ref.gt_per_file_log[i] - model_fv[i],
            )

    def test_rendered_markdown_attached(self):
        ref = _make_reference()
        tbl = build_score_table(
            model_fv_log=[0.0] * 20,
            model_scalar=0.5,
            reference=ref,
        )
        assert tbl is not None
        assert tbl.rendered_markdown.startswith(
            "### Per-file performance (log-space, all three columns on global s_max)"
        )
        assert "Aggregated scalar (log space, global s_max)" in tbl.rendered_markdown


# =============================================================================
# build_score_table — trial-mode subset
# =============================================================================


class TestBuildScoreTableTrialSubset:

    def test_aggregate_is_subset_scoped(self):
        """Sample only files 10..14. The subset-scoped raw/gt scalars are
        computed from ΣL[10..14] / ΣN[10..14], NOT the full-20 scalars."""
        raw_ls = [0.0] * 20
        for i in (10, 11, 12, 13, 14):
            raw_ls[i] = 40.0   # subset mean = 40/200 = 0.20
        gt_ls = [0.0] * 20
        for i in (10, 11, 12, 13, 14):
            gt_ls[i] = 400.0   # subset mean = 400/200 = 2.00

        ref = _make_reference(raw_linear_sum=raw_ls, gt_linear_sum=gt_ls)

        model_fv: list[Optional[float]] = [None] * 20
        for i in (10, 11, 12, 13, 14):
            model_fv[i] = 1.0
        tbl = build_score_table(model_fv, model_scalar=2.5, reference=ref)
        assert tbl is not None

        expected_raw = math.log(0.20, _LOG_BASE)
        expected_gt = math.log(2.00, _LOG_BASE)
        assert tbl.aggregate.raw_baseline_scalar == pytest.approx(
            expected_raw, abs=1e-12,
        )
        assert tbl.aggregate.ground_truth_scalar == pytest.approx(
            expected_gt, abs=1e-12,
        )
        assert tbl.aggregate.num_sampled_files == 5
        assert tbl.aggregate.model_scalar == pytest.approx(2.5)
        assert tbl.aggregate.percent_of_ceiling_log == pytest.approx(
            2.5 / expected_gt,
        )

    def test_unsampled_rows_carry_none_for_model_columns(self):
        ref = _make_reference()
        model_fv: list[Optional[float]] = [None] * 20
        model_fv[5] = 0.7
        tbl = build_score_table(model_fv, model_scalar=0.7, reference=ref)
        assert tbl is not None

        # File 5 — sampled.
        assert tbl.rows[5].model == pytest.approx(0.7)
        assert tbl.rows[5].gain_vs_raw is not None
        assert tbl.rows[5].headroom_vs_gt is not None

        # File 17 — not sampled.
        assert tbl.rows[17].model is None
        assert tbl.rows[17].gain_vs_raw is None
        assert tbl.rows[17].headroom_vs_gt is None
        # Reference columns still populated.
        assert tbl.rows[17].raw_baseline is not None
        assert tbl.rows[17].ground_truth is not None

    def test_all_rows_are_always_length_20(self):
        ref = _make_reference()
        model_fv: list[Optional[float]] = [None] * 20
        model_fv[0] = 0.1
        tbl = build_score_table(model_fv, model_scalar=0.1, reference=ref)
        assert tbl is not None
        assert len(tbl.rows) == 20


# =============================================================================
# build_score_table — degenerate inputs
# =============================================================================


class TestBuildScoreTableDegenerate:

    def test_returns_none_when_model_scalar_is_none(self):
        ref = _make_reference()
        assert build_score_table([1.0] * 20, model_scalar=None, reference=ref) is None

    def test_rejects_wrong_length_fv(self):
        ref = _make_reference()
        with pytest.raises(ValueError, match="length 20"):
            build_score_table([1.0] * 19, model_scalar=0.5, reference=ref)

    def test_rejects_all_none_fv_with_non_none_scalar(self):
        ref = _make_reference()
        with pytest.raises(ValueError, match="inconsistent"):
            build_score_table([None] * 20, model_scalar=0.5, reference=ref)


# =============================================================================
# render_comparison_table
# =============================================================================


class TestRenderComparisonTable:

    def test_contains_header_and_columns(self):
        ref = _make_reference()
        tbl = build_score_table([1.0] * 20, model_scalar=1.0, reference=ref)
        md = render_comparison_table(tbl)
        assert md.startswith(
            "### Per-file performance (log-space, all three columns on global s_max)"
        )
        assert "| file | raw_baseline | ground_truth | **model** | gain vs raw | headroom vs gt |" in md
        assert "### Aggregated scalar (log space, global s_max)" in md

    def test_renders_exactly_20_body_rows(self):
        ref = _make_reference()
        tbl = build_score_table([0.5] * 20, model_scalar=0.5, reference=ref)
        md = render_comparison_table(tbl)
        body_rows = [ln for ln in md.splitlines()
                     if ln.startswith("|") and ln[1:].lstrip()[:1].isdigit()]
        assert len(body_rows) == 20

    def test_na_cell_rendered_for_unsampled_files(self):
        ref = _make_reference()
        model_fv: list[Optional[float]] = [None] * 20
        model_fv[4] = 3.0
        tbl = build_score_table(model_fv, model_scalar=3.0, reference=ref)
        md = render_comparison_table(tbl)
        lines = md.splitlines()

        # Locate the row for file 0 — must render N/A in model/gain/headroom.
        row0 = next(ln for ln in lines if ln.startswith("|    0 "))
        assert row0.count("N/A") == 3

        # Row for file 4 — fully populated, zero N/A.
        row4 = next(ln for ln in lines if ln.startswith("|    4 "))
        assert "N/A" not in row4

    def test_aggregate_block_and_recovery(self):
        ref = _make_reference()
        tbl = build_score_table(
            [2.0] * 20, model_scalar=5.5763, reference=ref,
        )
        md = render_comparison_table(tbl)
        assert "| **model**            | **5.5763** |" in md
        expected_recovery = 5.5763 / tbl.aggregate.ground_truth_scalar * 100
        assert f"Recovery: **{expected_recovery:.1f}% of ceiling**" in md

    def test_subset_footer_only_appears_when_n_lt_20(self):
        ref = _make_reference()
        # Full-run table — no footer.
        full_tbl = build_score_table([1.0] * 20, model_scalar=1.0, reference=ref)
        assert "scalars computed over" not in full_tbl.rendered_markdown

        # Subset table — footer with count.
        model_fv: list[Optional[float]] = [None] * 20
        for i in range(3):
            model_fv[i] = 0.3
        sub_tbl = build_score_table(model_fv, model_scalar=0.3, reference=ref)
        assert "_Note: scalars computed over 3 sampled files._" in sub_tbl.rendered_markdown

    def test_negative_values_use_unicode_minus(self):
        """Row values rendered with a U+2212 minus for column alignment."""
        ref = _make_reference()
        model_fv: list[Optional[float]] = [None] * 20
        model_fv[0] = -13.8540
        tbl = build_score_table(model_fv, model_scalar=-13.8540, reference=ref)
        md = render_comparison_table(tbl)
        row0 = next(ln for ln in md.splitlines() if ln.startswith("|    0 "))
        # Unicode minus, not ASCII hyphen-minus.
        assert "\u221213.8540" in row0
