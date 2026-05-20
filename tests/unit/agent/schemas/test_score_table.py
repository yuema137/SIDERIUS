"""
Unit tests for ``agent/schemas/score_table.py`` — Pydantic validation + JSON
round-trip invariants for ``PerFileRow``, ``AggregateScalars``, and
``ScoreComparisonTable``. No table-math logic here — that lives in
``tests/unit/execute_tools/test_scoring_helpers.py``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.schemas.score_table import (
    AggregateScalars,
    PerFileRow,
    ScoreComparisonTable,
)

# =============================================================================
# PerFileRow
# =============================================================================


class TestPerFileRow:
    def test_fully_populated_row(self):
        row = PerFileRow(
            file_index=12,
            raw_baseline=0.36,
            ground_truth=10.12,
            model=8.0,
            gain_vs_raw=7.64,
            headroom_vs_gt=2.12,
        )
        assert row.file_index == 12
        assert row.model == 8.0

    def test_all_model_side_columns_may_be_none(self):
        """Trial-mode rows — file not sampled. raw/gt still set."""
        row = PerFileRow(
            file_index=3,
            raw_baseline=-13.854,
            ground_truth=0.0945,
            model=None,
            gain_vs_raw=None,
            headroom_vs_gt=None,
        )
        assert row.model is None
        assert row.gain_vs_raw is None

    def test_file_index_range(self):
        with pytest.raises(ValidationError):
            PerFileRow(
                file_index=20,  # out of 0..19
                raw_baseline=0.0,
                ground_truth=0.0,
                model=None,
                gain_vs_raw=None,
                headroom_vs_gt=None,
            )
        with pytest.raises(ValidationError):
            PerFileRow(
                file_index=-1,
                raw_baseline=0.0,
                ground_truth=0.0,
                model=None,
                gain_vs_raw=None,
                headroom_vs_gt=None,
            )

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            PerFileRow(
                file_index=0,
                raw_baseline=0.0,
                ground_truth=0.0,
                model=None,
                gain_vs_raw=None,
                headroom_vs_gt=None,
                whatever="nope",
            )

    def test_json_round_trip_preserves_none(self):
        row = PerFileRow(
            file_index=17,
            raw_baseline=1.83,
            ground_truth=11.22,
            model=None,
            gain_vs_raw=None,
            headroom_vs_gt=None,
        )
        restored = PerFileRow.model_validate_json(row.model_dump_json())
        assert restored == row

    def test_headroom_negative_rejected(self):
        # The schema enforces ``headroom_vs_gt >= 0``. ``_build_rows`` clips at
        # zero before construction; this test guards that contract at the
        # schema layer so any caller that forgets to clip is caught.
        with pytest.raises(ValidationError):
            PerFileRow(
                file_index=0,
                raw_baseline=-11.43,
                ground_truth=-8.26,
                model=-13.27,
                gain_vs_raw=-1.84,
                headroom_vs_gt=-5.0,
            )

    def test_headroom_zero_accepted(self):
        row = PerFileRow(
            file_index=0,
            raw_baseline=-11.43,
            ground_truth=-8.26,
            model=-8.26,
            gain_vs_raw=3.17,
            headroom_vs_gt=0.0,
        )
        assert row.headroom_vs_gt == 0.0

    def test_headroom_none_accepted_for_unsampled_file(self):
        row = PerFileRow(
            file_index=5,
            raw_baseline=-1.87,
            ground_truth=7.46,
            model=None,
            gain_vs_raw=None,
            headroom_vs_gt=None,
        )
        assert row.headroom_vs_gt is None


# =============================================================================
# AggregateScalars
# =============================================================================


class TestAggregateScalars:
    def test_full_run_aggregate(self):
        agg = AggregateScalars(
            raw_baseline_scalar=1.0011,
            ground_truth_scalar=10.1134,
            model_scalar=5.5763,
            percent_of_ceiling_log=0.551,
            num_sampled_files=20,
        )
        assert agg.num_sampled_files == 20

    def test_trial_run_aggregate(self):
        agg = AggregateScalars(
            raw_baseline_scalar=1.09,
            ground_truth_scalar=9.78,
            model_scalar=5.0,
            percent_of_ceiling_log=0.511,
            num_sampled_files=5,
        )
        assert agg.num_sampled_files == 5

    def test_num_sampled_files_lower_bound(self):
        """Cannot aggregate over zero files — the schema enforces ge=1."""
        with pytest.raises(ValidationError):
            AggregateScalars(
                raw_baseline_scalar=0.0,
                ground_truth_scalar=0.0,
                model_scalar=0.0,
                percent_of_ceiling_log=0.0,
                num_sampled_files=0,
            )

    def test_num_sampled_files_upper_bound(self):
        with pytest.raises(ValidationError):
            AggregateScalars(
                raw_baseline_scalar=0.0,
                ground_truth_scalar=0.0,
                model_scalar=0.0,
                percent_of_ceiling_log=0.0,
                num_sampled_files=21,
            )


# =============================================================================
# ScoreComparisonTable
# =============================================================================


def _row(i: int, model: float | None = None) -> PerFileRow:
    # ``headroom_vs_gt`` is clipped at zero (schema invariant ``ge=0.0``);
    # mirror the same clip ``_build_rows`` applies in production.
    return PerFileRow(
        file_index=i,
        raw_baseline=0.1 * i,
        ground_truth=0.5 * i,
        model=model,
        gain_vs_raw=(model - 0.1 * i) if model is not None else None,
        headroom_vs_gt=max(0.5 * i - model, 0.0) if model is not None else None,
    )


def _agg(n: int = 20) -> AggregateScalars:
    return AggregateScalars(
        raw_baseline_scalar=1.0,
        ground_truth_scalar=10.0,
        model_scalar=5.0,
        percent_of_ceiling_log=0.5,
        num_sampled_files=n,
    )


class TestScoreComparisonTable:
    def test_happy_path_20_rows(self):
        rows = [_row(i, model=float(i)) for i in range(20)]
        tbl = ScoreComparisonTable(
            rows=rows,
            aggregate=_agg(20),
            s_max_global=2.957e8,
            reference_source="reference_data/raw_and_ground_score.md",
            rendered_markdown="### stub\n",
        )
        assert len(tbl.rows) == 20
        assert tbl.s_max_global == pytest.approx(2.957e8)

    def test_rejects_fewer_than_20_rows(self):
        rows = [_row(i, model=0.0) for i in range(19)]
        with pytest.raises(ValidationError):
            ScoreComparisonTable(
                rows=rows,
                aggregate=_agg(19),
                s_max_global=1.0,
                reference_source="x",
                rendered_markdown="",
            )

    def test_rejects_more_than_20_rows(self):
        rows = [_row(i % 20, model=0.0) for i in range(21)]
        with pytest.raises(ValidationError):
            ScoreComparisonTable(
                rows=rows,
                aggregate=_agg(20),
                s_max_global=1.0,
                reference_source="x",
                rendered_markdown="",
            )

    def test_json_round_trip_preserves_rendered_markdown(self):
        rows = [_row(i, model=None) for i in range(20)]
        tbl = ScoreComparisonTable(
            rows=rows,
            aggregate=_agg(1),
            s_max_global=1.0,
            reference_source="x",
            rendered_markdown="### title\n\n| a | b |\n|---|---|\n| 1 | 2 |\n",
        )
        restored = ScoreComparisonTable.model_validate_json(tbl.model_dump_json())
        assert restored.rendered_markdown == tbl.rendered_markdown
        assert restored == tbl

    def test_extra_fields_forbidden_on_table(self):
        rows = [_row(i, model=0.0) for i in range(20)]
        with pytest.raises(ValidationError):
            ScoreComparisonTable(
                rows=rows,
                aggregate=_agg(20),
                s_max_global=1.0,
                reference_source="x",
                rendered_markdown="",
                who="knows",
            )


# =============================================================================
# P1-Impact: linear_weight / impact_score row fields + table invariant
# =============================================================================


def _row_with_impact(
    i: int,
    *,
    model: float | None,
    weight: float | None,
    impact: float | None,
) -> PerFileRow:
    return PerFileRow(
        file_index=i,
        raw_baseline=0.1 * i,
        ground_truth=0.5 * i,
        model=model,
        gain_vs_raw=(model - 0.1 * i) if model is not None else None,
        headroom_vs_gt=max(0.5 * i - model, 0.0) if model is not None else None,
        linear_weight=weight,
        impact_score=impact,
    )


class TestPerFileRowImpactFields:
    """Schema-level invariants on the two new opportunity columns."""

    def test_linear_weight_at_bounds_accepted(self):
        # Both endpoints of the [0, 1] interval are valid.
        for w in (0.0, 1.0, 0.5):
            row = _row_with_impact(0, model=0.0, weight=w, impact=0.0)
            assert row.linear_weight == pytest.approx(w)

    def test_linear_weight_negative_rejected(self):
        with pytest.raises(ValidationError):
            _row_with_impact(0, model=0.0, weight=-0.1, impact=0.0)

    def test_linear_weight_above_one_rejected(self):
        with pytest.raises(ValidationError):
            _row_with_impact(0, model=0.0, weight=1.000001, impact=0.0)

    def test_impact_score_clamps_at_zero_for_already_saturated_file(self):
        # A saturated file (model at the gt ceiling) yields impact=0.0
        # in the helper. The schema must accept the boundary value.
        row = _row_with_impact(3, model=1.5, weight=0.05, impact=0.0)
        assert row.impact_score == 0.0

    def test_impact_score_negative_rejected(self):
        # Helper clips at 0 — the schema is the second line of defense.
        with pytest.raises(ValidationError):
            _row_with_impact(0, model=0.0, weight=0.05, impact=-0.1)

    def test_impact_columns_default_to_none(self):
        # Existing PerFileRow constructions (no impact data) keep working —
        # both new fields default to None.
        row = PerFileRow(
            file_index=0,
            raw_baseline=0.0,
            ground_truth=0.0,
            model=0.0,
            gain_vs_raw=0.0,
            headroom_vs_gt=0.0,
        )
        assert row.linear_weight is None
        assert row.impact_score is None


class TestLinearWeightTotalInvariant:
    """Validator on ScoreComparisonTable: Σ linear_weight ≈ 1.0 (1e-9)."""

    def _build_table(
        self,
        *,
        weights: list[float | None],
        stored_total: float,
    ) -> ScoreComparisonTable:
        rows = [
            _row_with_impact(
                i,
                model=(0.5 * i if weights[i] is not None else None),
                weight=weights[i],
                impact=(0.0 if weights[i] is not None else None),
            )
            for i in range(20)
        ]
        return ScoreComparisonTable(
            rows=rows,
            aggregate=_agg(sum(1 for w in weights if w is not None) or 1),
            s_max_global=1.0,
            reference_source="invariant_probe",
            rendered_markdown="",
            linear_weight_total=stored_total,
        )

    def test_validator_rejects_off_sum_full_subset(self):
        weights = [0.04] * 20  # Σ = 0.80, not 1.0
        with pytest.raises(ValidationError, match="sum to"):
            self._build_table(weights=weights, stored_total=1.0)

    def test_validator_rejects_stored_total_off_even_when_rows_sum_to_one(self):
        weights = [0.05] * 20  # Σ = 1.0 exactly
        with pytest.raises(ValidationError, match="linear_weight_total"):
            self._build_table(weights=weights, stored_total=0.95)

    def test_validator_passes_when_rows_and_total_agree(self):
        weights = [0.05] * 20  # Σ = 1.0 exactly
        tbl = self._build_table(weights=weights, stored_total=1.0)
        assert tbl.linear_weight_total == pytest.approx(1.0)

    def test_validator_skipped_when_no_sampled_weights(self):
        # Legacy / direct-dict tables carry None linear_weight on every
        # row — the validator returns self without checking the total.
        weights: list[float | None] = [None] * 20
        tbl = self._build_table(weights=weights, stored_total=0.0)
        assert tbl.linear_weight_total == 0.0

    def test_validator_tolerates_float_round_off_within_1e9(self):
        # A 5-file subset summing to 0.999999999 (within tolerance) passes.
        weights: list[float | None] = [None] * 20
        # 0.2 cannot be represented exactly in binary; five copies sum to
        # 1.0000000000000002 on most platforms — which is inside 1e-9.
        for i in (3, 7, 9, 11, 14):
            weights[i] = 0.2
        tbl = self._build_table(
            weights=weights,
            stored_total=sum(0.2 for _ in range(5)),
        )
        assert tbl.linear_weight_total == pytest.approx(1.0, abs=1e-9)
