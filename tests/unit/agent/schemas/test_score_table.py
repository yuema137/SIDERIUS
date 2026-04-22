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
                file_index=20,   # out of 0..19
                raw_baseline=0.0,
                ground_truth=0.0,
                model=None, gain_vs_raw=None, headroom_vs_gt=None,
            )
        with pytest.raises(ValidationError):
            PerFileRow(
                file_index=-1,
                raw_baseline=0.0,
                ground_truth=0.0,
                model=None, gain_vs_raw=None, headroom_vs_gt=None,
            )

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            PerFileRow(
                file_index=0,
                raw_baseline=0.0,
                ground_truth=0.0,
                model=None, gain_vs_raw=None, headroom_vs_gt=None,
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
    return PerFileRow(
        file_index=i,
        raw_baseline=0.1 * i,
        ground_truth=0.5 * i,
        model=model,
        gain_vs_raw=(model - 0.1 * i) if model is not None else None,
        headroom_vs_gt=(0.5 * i - model) if model is not None else None,
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
