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
from typing import Optional

import pytest

from agent.schemas.score_table import ScoreComparisonTable
from execute_tools.scoring_helpers import (
    _LOG_BASE,
    _LOG_OFFSET,
    build_score_table,
    file_vector_to_log_space,
    render_comparison_table,
)
from nodes.scoring_reference import ReferenceScores

# -----------------------------------------------------------------------------
# Helpers — build a synthetic ReferenceScores bundle.
# -----------------------------------------------------------------------------


def _make_reference(
    *,
    raw_linear_sum: list[float] | None = None,
    gt_linear_sum: list[float] | None = None,
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
        model_fv = list(ref.gt_per_file_log)  # perfect denoiser
        model_scalar = ref.gt_scalar_full

        tbl = build_score_table(model_fv, model_scalar, ref)
        assert tbl is not None
        assert tbl.aggregate.num_sampled_files == 20
        assert tbl.aggregate.raw_baseline_scalar == pytest.approx(
            ref.raw_scalar_full,
            abs=1e-12,
        )
        assert tbl.aggregate.ground_truth_scalar == pytest.approx(
            ref.gt_scalar_full,
            abs=1e-12,
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
            # ``headroom_vs_gt`` is clipped at zero — files where the model
            # exceeds the ceiling (numerical overshoot or dead-zone noise)
            # render as 0.0, not a negative value. The schema enforces this
            # invariant via ``ge=0.0``.
            assert row.headroom_vs_gt == pytest.approx(
                max(ref.gt_per_file_log[i] - model_fv[i], 0.0),
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
            raw_ls[i] = 40.0  # subset mean = 40/200 = 0.20
        gt_ls = [0.0] * 20
        for i in (10, 11, 12, 13, 14):
            gt_ls[i] = 400.0  # subset mean = 400/200 = 2.00

        ref = _make_reference(raw_linear_sum=raw_ls, gt_linear_sum=gt_ls)

        model_fv: list[float | None] = [None] * 20
        for i in (10, 11, 12, 13, 14):
            model_fv[i] = 1.0
        tbl = build_score_table(model_fv, model_scalar=2.5, reference=ref)
        assert tbl is not None

        expected_raw = math.log(0.20, _LOG_BASE)
        expected_gt = math.log(2.00, _LOG_BASE)
        assert tbl.aggregate.raw_baseline_scalar == pytest.approx(
            expected_raw,
            abs=1e-12,
        )
        assert tbl.aggregate.ground_truth_scalar == pytest.approx(
            expected_gt,
            abs=1e-12,
        )
        assert tbl.aggregate.num_sampled_files == 5
        assert tbl.aggregate.model_scalar == pytest.approx(2.5)
        assert tbl.aggregate.percent_of_ceiling_log == pytest.approx(
            2.5 / expected_gt,
        )

    def test_unsampled_rows_carry_none_for_model_columns(self):
        ref = _make_reference()
        model_fv: list[float | None] = [None] * 20
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
        model_fv: list[float | None] = [None] * 20
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
        # Phase 8 / P1-Impact: header carries Impact and Weight % columns.
        # Post-V9 audit: Impact precedes Weight % so the visual scan order
        # matches the synthesis directive ("Read the Impact_Score column FIRST").
        assert (
            "| file | raw_baseline | ground_truth | **model** | gain vs raw | "
            "headroom vs gt | Impact | Weight % |"
        ) in md
        assert "### Aggregated scalar (log space, global s_max)" in md
        assert "### Sampled files re-ranked by Impact_Score (descending)" in md

    def test_renders_exactly_20_body_rows(self):
        ref = _make_reference()
        tbl = build_score_table([0.5] * 20, model_scalar=0.5, reference=ref)
        md = render_comparison_table(tbl)
        # Filter to MAIN-table body rows only — the secondary impact-ranked
        # block also renders rows beginning with ``|<digit>``.
        lines = md.splitlines()
        secondary_idx = next(
            i
            for i, ln in enumerate(lines)
            if ln.startswith("### Sampled files re-ranked by Impact_Score")
        )
        main_body = [
            ln
            for ln in lines[:secondary_idx]
            if ln.startswith("|") and ln[1:].lstrip()[:1].isdigit()
        ]
        assert len(main_body) == 20

    def test_na_cell_rendered_for_unsampled_files(self):
        ref = _make_reference()
        model_fv: list[float | None] = [None] * 20
        model_fv[4] = 3.0
        tbl = build_score_table(model_fv, model_scalar=3.0, reference=ref)
        md = render_comparison_table(tbl)
        lines = md.splitlines()

        # Locate the MAIN-table row for file 0 — must render N/A in
        # model/gain/headroom/Weight %/Impact (5 unsampled-side columns).
        secondary_idx = next(
            i
            for i, ln in enumerate(lines)
            if ln.startswith("### Sampled files re-ranked by Impact_Score")
        )
        main_lines = lines[:secondary_idx]
        row0 = next(ln for ln in main_lines if ln.startswith("|    0 "))
        assert row0.count("N/A") == 5

        # Row for file 4 — fully populated, zero N/A.
        row4 = next(ln for ln in main_lines if ln.startswith("|    4 "))
        assert "N/A" not in row4

    def test_aggregate_block_and_recovery(self):
        ref = _make_reference()
        tbl = build_score_table(
            [2.0] * 20,
            model_scalar=5.5763,
            reference=ref,
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
        model_fv: list[float | None] = [None] * 20
        for i in range(3):
            model_fv[i] = 0.3
        sub_tbl = build_score_table(model_fv, model_scalar=0.3, reference=ref)
        assert "_Note: scalars computed over 3 sampled files._" in sub_tbl.rendered_markdown

    def test_negative_values_use_unicode_minus(self):
        """Row values rendered with a U+2212 minus for column alignment."""
        ref = _make_reference()
        model_fv: list[float | None] = [None] * 20
        model_fv[0] = -13.8540
        tbl = build_score_table(model_fv, model_scalar=-13.8540, reference=ref)
        md = render_comparison_table(tbl)
        row0 = next(ln for ln in md.splitlines() if ln.startswith("|    0 "))
        # Unicode minus, not ASCII hyphen-minus.
        assert "\u221213.8540" in row0


# =============================================================================
# file_vector_to_log_space — P0 unit-fix helper
# =============================================================================


class TestFileVectorToLogSpace:
    """Tests for the linear→log conversion that closes the unit-mismatch bug.

    ``score_vector`` returns the per-file vector in linear units; the
    reference ``raw_per_file_log`` / ``gt_per_file_log`` columns and the
    aggregate scalar are in log_{5.27}-space. ``file_vector_to_log_space``
    is the helper that puts the model column on the same ruler before
    ``build_score_table`` consumes it. Formula:
    ``log_{5.27}(v)`` for ``v > 0``, else ``-inf`` (no ``+ 1e-10`` offset).
    """

    def test_typical_linear_values_map_correctly(self):
        # Hand-computed expected values under the production formula.
        fv_lin = [0.01, 1.0, 1e6]
        out = file_vector_to_log_space(fv_lin)
        expected = [math.log(v + _LOG_OFFSET, _LOG_BASE) for v in fv_lin]
        assert out == pytest.approx(expected, rel=1e-12)

    def test_none_passes_through_for_unsampled_files(self):
        # Trial-mode subset: unsampled positions stay None — the conversion
        # must not coerce them to the soft floor.
        fv = [0.01, None, 1e3, None]
        out = file_vector_to_log_space(fv)
        assert out[0] == pytest.approx(math.log(0.01 + _LOG_OFFSET, _LOG_BASE), rel=1e-12)
        assert out[1] is None
        assert out[2] == pytest.approx(math.log(1e3 + _LOG_OFFSET, _LOG_BASE), rel=1e-12)
        assert out[3] is None

    def test_zero_maps_to_neg_inf(self):
        # No soft floor: a zero linear mean maps to -inf, matching
        # score_vector's grand-mean guard (the +1e-10 offset was removed).
        out = file_vector_to_log_space([0.0])
        assert out[0] == float("-inf")

    def test_negative_input_maps_to_neg_inf(self):
        # Defensive clip: negative linear means (not expected from the score
        # formula) must not crash the log. They map to -inf like zero.
        out = file_vector_to_log_space([-0.5, -1e-12])
        assert out[0] == float("-inf")
        assert out[1] == float("-inf")

    def test_length_preserved(self):
        fv = [0.0, None, 1.0, 1e3, None, 1e-9]
        out = file_vector_to_log_space(fv)
        assert len(out) == len(fv)

    def test_custom_base_and_offset_kwargs(self):
        # Both knobs work; default base is 5.27, default offset 0.0.
        out_default = file_vector_to_log_space([1.0])
        out_base_e = file_vector_to_log_space([1.0], base=math.e)
        out_explicit_offset = file_vector_to_log_space([1.0], offset=1e-10)

        assert out_default[0] == pytest.approx(math.log(1.0, 5.27), abs=1e-9)
        assert out_base_e[0] == pytest.approx(math.log(1.0, math.e), abs=1e-9)
        assert out_explicit_offset[0] == pytest.approx(math.log(1.0 + 1e-10, 5.27), rel=1e-12)


# =============================================================================
# P1-Impact (1-zh) — property-based tests for Linear_Weight + Impact_Score
# =============================================================================


class TestLinearWeightProperty:
    """Σ linear_weight ≈ 1 over the sampled subset, regardless of subset size."""

    def test_weights_sum_to_one_full_subset(self):
        # Full 20-file run: every row carries a weight that sums to 1.
        ref = _make_reference()
        # Linear file_vector — heterogeneous values stress the math.
        fv_linear = [0.01 * (i + 1) for i in range(20)]  # 0.01..0.20
        # Pre-converted log column for build_score_table.
        fv_log = [math.log(v + _LOG_OFFSET, _LOG_BASE) for v in fv_linear]
        tbl = build_score_table(
            fv_log,
            model_scalar=2.0,
            reference=ref,
            model_fv_linear=fv_linear,
        )
        assert tbl is not None
        weights = [r.linear_weight for r in tbl.rows]
        assert all(w is not None for w in weights)
        assert sum(weights) == pytest.approx(1.0, abs=1e-9)
        assert tbl.linear_weight_total == pytest.approx(1.0, abs=1e-9)

    def test_weights_sum_to_one_trial_subset(self):
        # 5-file trial: sampled rows sum to 1, unsampled rows are None.
        ref = _make_reference()
        fv_linear: list[float | None] = [None] * 20
        for i, val in zip((2, 5, 11, 13, 17), (0.05, 0.10, 0.20, 0.15, 0.30), strict=True):
            fv_linear[i] = val
        fv_log = [
            (math.log(v + _LOG_OFFSET, _LOG_BASE) if v is not None else None) for v in fv_linear
        ]
        tbl = build_score_table(
            fv_log,
            model_scalar=1.5,
            reference=ref,
            model_fv_linear=fv_linear,
        )
        assert tbl is not None

        sampled = [r for r in tbl.rows if r.linear_weight is not None]
        unsampled = [r for r in tbl.rows if r.linear_weight is None]
        assert len(sampled) == 5
        assert len(unsampled) == 15
        assert sum(r.linear_weight for r in sampled) == pytest.approx(
            1.0,
            abs=1e-9,
        )
        assert tbl.linear_weight_total == pytest.approx(1.0, abs=1e-9)
        # Unsampled rows must also have impact_score=None (no opportunity
        # data outside the sampled subset).
        assert all(r.impact_score is None for r in unsampled)


class TestImpactScoreProperty:
    """Impact_Score = max(log_5.27(gm_after) - log_5.27(gm_current), 0)."""

    def test_impact_zero_iff_model_at_or_above_gt(self):
        # Construct a reference and a model fv where every sampled file is
        # at-or-above its gt ceiling — every impact must be 0.0.
        ref = _make_reference()  # gt per-file mean = 0.10 everywhere.
        # model linear == gt linear for all files: model_linear = 0.10.
        fv_linear = [0.10] * 20
        fv_log = [math.log(0.10 + _LOG_OFFSET, _LOG_BASE)] * 20
        tbl = build_score_table(
            fv_log,
            model_scalar=fv_log[0],
            reference=ref,
            model_fv_linear=fv_linear,
        )
        assert tbl is not None
        for r in tbl.rows:
            assert r.impact_score == pytest.approx(0.0, abs=1e-12)

        # Above gt also clips at 0 (overshoot is not negative impact).
        fv_linear_over = [0.20] * 20
        fv_log_over = [math.log(0.20 + _LOG_OFFSET, _LOG_BASE)] * 20
        tbl2 = build_score_table(
            fv_log_over,
            model_scalar=fv_log_over[0],
            reference=ref,
            model_fv_linear=fv_linear_over,
        )
        assert tbl2 is not None
        for r in tbl2.rows:
            assert r.impact_score == 0.0

    def test_impact_strictly_positive_when_model_below_gt(self):
        # Model is uniformly below gt → every sampled impact > 0.
        ref = _make_reference()  # gt per-file mean = 0.10.
        fv_linear = [0.001] * 20
        fv_log = [math.log(0.001 + _LOG_OFFSET, _LOG_BASE)] * 20
        tbl = build_score_table(
            fv_log,
            model_scalar=fv_log[0],
            reference=ref,
            model_fv_linear=fv_linear,
        )
        assert tbl is not None
        for r in tbl.rows:
            assert r.impact_score is not None
            assert r.impact_score > 0.0

    def test_impact_ranking_invariant_under_input_permutation(self):
        # Zero-hardcoding proof: shuffling the (mean, gt) pairing across
        # file indices leaves the SET of impact scores unchanged.
        ref = _make_reference()
        # Heterogeneous fv so impacts span a range.
        base_fv_linear = [0.005 * (i + 1) for i in range(20)]  # 0.005..0.10
        base_fv_log = [math.log(v + _LOG_OFFSET, _LOG_BASE) for v in base_fv_linear]

        tbl_a = build_score_table(
            base_fv_log,
            model_scalar=0.0,
            reference=ref,
            model_fv_linear=base_fv_linear,
        )
        impacts_a = sorted(r.impact_score for r in tbl_a.rows if r.impact_score is not None)

        # Permutation: reverse the linear vector AND the reference's per-
        # file linear sums + n_segments together (so each pair stays
        # bound to its partner just at a different file index).
        perm = list(reversed(range(20)))
        permuted_fv_linear = [base_fv_linear[p] for p in perm]
        permuted_fv_log = [base_fv_log[p] for p in perm]
        from nodes.scoring_reference import ReferenceScores

        permuted_ref = ReferenceScores(
            raw_per_file_log=[ref.raw_per_file_log[p] for p in perm],
            gt_per_file_log=[ref.gt_per_file_log[p] for p in perm],
            raw_per_file_linear_sum=[ref.raw_per_file_linear_sum[p] for p in perm],
            raw_per_file_n_segments=[ref.raw_per_file_n_segments[p] for p in perm],
            gt_per_file_linear_sum=[ref.gt_per_file_linear_sum[p] for p in perm],
            gt_per_file_n_segments=[ref.gt_per_file_n_segments[p] for p in perm],
            raw_scalar_full=ref.raw_scalar_full,
            gt_scalar_full=ref.gt_scalar_full,
            s_max=ref.s_max,
        )
        tbl_b = build_score_table(
            permuted_fv_log,
            model_scalar=0.0,
            reference=permuted_ref,
            model_fv_linear=permuted_fv_linear,
        )
        impacts_b = sorted(r.impact_score for r in tbl_b.rows if r.impact_score is not None)

        assert len(impacts_a) == 20
        assert len(impacts_b) == 20
        for a, b in zip(impacts_a, impacts_b, strict=True):
            assert a == pytest.approx(b, abs=1e-12)


class TestSecondaryBlock:
    """The secondary 'Sampled files re-ranked by Impact' block ordering."""

    def test_secondary_block_sorted_by_impact_desc(self):
        ref = _make_reference()
        # Mix of impacts — heterogeneous fv produces a non-trivial ordering.
        fv_linear = [0.005 * (i + 1) for i in range(20)]
        fv_log = [math.log(v + _LOG_OFFSET, _LOG_BASE) for v in fv_linear]
        tbl = build_score_table(
            fv_log,
            model_scalar=0.0,
            reference=ref,
            model_fv_linear=fv_linear,
        )
        md = render_comparison_table(tbl)
        lines = md.splitlines()

        # Slice from the secondary header to the next blank-line break (or
        # the subset footer / EOF).
        sec_idx = next(
            i
            for i, ln in enumerate(lines)
            if ln.startswith("### Sampled files re-ranked by Impact_Score")
        )
        # First two lines after header are the table column header + sep.
        body = [
            ln
            for ln in lines[sec_idx + 1 :]
            if ln.startswith("|") and ln[1:].lstrip()[:1].isdigit()
        ]
        assert len(body) == 20

        # Extract impact column (column 2) from each rendered row and assert
        # monotonic non-increasing — the renderer's contract.
        def _impact_from_row(line: str) -> float:
            cells = [c.strip() for c in line.split("|") if c.strip()]
            cell = cells[1]
            if cell.startswith("\u2212"):
                return -float(cell[1:])
            return float(cell)

        impacts_in_render_order = [_impact_from_row(ln) for ln in body]
        assert impacts_in_render_order == sorted(
            impacts_in_render_order,
            reverse=True,
        )

        # And: the order matches sorting tbl.rows by impact desc.
        expected_file_order = [
            r.file_index
            for r in sorted(
                (r for r in tbl.rows if r.impact_score is not None),
                key=lambda r: -r.impact_score,
            )
        ]
        rendered_file_order = [int(ln.split("|")[1].strip()) for ln in body]
        assert rendered_file_order == expected_file_order

    def test_secondary_block_omitted_when_no_impact_data(self):
        # Direct ScoreComparisonTable construction with no impact data → the
        # secondary block must not appear in the rendered markdown.
        from agent.schemas.score_table import (
            AggregateScalars,
            PerFileRow,
            ScoreComparisonTable,
        )

        rows = [
            PerFileRow(
                file_index=i,
                raw_baseline=0.0,
                ground_truth=0.0,
                model=0.0,
                gain_vs_raw=0.0,
                headroom_vs_gt=0.0,
            )
            for i in range(20)
        ]
        tbl = ScoreComparisonTable(
            rows=rows,
            aggregate=AggregateScalars(
                raw_baseline_scalar=0.0,
                ground_truth_scalar=10.0,
                model_scalar=5.0,
                percent_of_ceiling_log=0.5,
                num_sampled_files=20,
            ),
            s_max_global=1.0,
            reference_source="legacy",
            rendered_markdown="",
        )
        md = render_comparison_table(tbl)
        assert "### Sampled files re-ranked by Impact_Score" not in md


pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")
