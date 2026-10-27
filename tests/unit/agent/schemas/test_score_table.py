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


class TestPerFileRow:
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


class TestAggregateScalars:
    def test_num_sampled_files_upper_bound(self):
        with pytest.raises(ValidationError):
            AggregateScalars(
                raw_baseline_scalar=0.0,
                ground_truth_scalar=0.0,
                model_scalar=0.0,
                percent_of_ceiling_log=0.0,
                num_sampled_files=21,
            )


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


pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")
