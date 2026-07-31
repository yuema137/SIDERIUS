"""C12 — campaign matrix, cell schemas, and frozen-threshold evaluation.

No GPU: cells are constructed directly, which is the right level — what
needs testing is that the thresholds decide correctly and that a cell
cannot smuggle non-measured evidence into a verdict.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.runtime_control.campaign import (
    MATRIX,
    PAIRWISE_PAIRS,
    CampaignCell,
    CampaignThresholds,
    CellMeasurement,
    evaluate_campaign,
    load_cells,
    write_cell,
)


def _measurement(**over) -> CellMeasurement:
    base = dict(
        provenance="bounded_live_probe",
        setup_seconds=1.0,
        train_ms_per_step=20.0,
        inference_ms_per_unit=8.0,
        peak_vram_allocated_gb=2.0,
        realized_parameter_count=500_000,
        trainable_parameter_count=500_000,
        parameter_memory_gb=0.002,
        dtype="float32",
        concurrency_identity="single_candidate_idle",
    )
    base.update(over)
    return CellMeasurement(**base)


def _cell(cell_id="punet@500K", *, family="punet", projected=100.0, actual=100.0, **over):
    base = dict(
        track="A_matrix",
        cell_id=cell_id,
        family=family,
        status="ok",
        probe=_measurement(),
        projected_seconds=projected,
        actual_seconds=actual,
        predicted_peak_vram_gb=2.0,
        actual_peak_vram_gb=2.0,
    )
    base.update(over)
    return CampaignCell(**base)


class TestMatrix:
    def test_three_families_and_four_scales(self):
        families = {entry["family"] for entry in MATRIX}
        assert len(families) >= 3
        for family in families:
            scales = {e["target"] for e in MATRIX if e["family"] == family}
            assert scales == {50_000, 500_000, 5_000_000, 20_000_000}, family

    def test_the_families_are_structurally_different(self):
        assert {"punet", "wavenet", "transformer"} <= {e["family"] for e in MATRIX}

    def test_a_family_ceiling_is_labeled_not_hidden(self):
        """The transformer cannot reach 20M within its VALIDATED config
        bounds. The cell records the real ceiling and says so, rather than
        raising a scientific bound to make the matrix look complete."""
        ceiling = [e for e in MATRIX if e.get("at_family_ceiling")]
        assert len(ceiling) == 1
        assert ceiling[0]["family"] == "transformer"
        assert ceiling[0]["realized"] < ceiling[0]["target"]

    def test_realized_counts_are_recorded_for_every_cell(self):
        for entry in MATRIX:
            assert entry["realized"] > 0
            assert entry["config"]["segmentation_size"] > 0

    def test_pairs_cover_small_large_and_heterogeneous(self):
        labels = {p["label"] for p in PAIRWISE_PAIRS}
        assert labels == {"small_homogeneous", "large_homogeneous", "heterogeneous"}
        for pair in PAIRWISE_PAIRS:
            assert len(pair["members"]) == 2


class TestCellEvidenceRules:
    def test_campaign_evidence_must_be_measured(self):
        """The legacy static/fallback path can never become campaign
        evidence — the failure mode this whole redesign exists to fix."""
        with pytest.raises(ValidationError, match="measurement-backed"):
            _measurement(provenance="static_uncalibrated")
        with pytest.raises(ValidationError, match="measurement-backed"):
            _measurement(provenance="legacy_calibration_prior")

    def test_training_and_inference_stay_separate(self):
        measurement = _measurement()
        assert measurement.train_ms_per_step == 20.0
        assert measurement.inference_ms_per_unit == 8.0
        assert measurement.inference_work_unit == "inference_batch"

    def test_ratios_are_defined_against_actual(self):
        cell = _cell(projected=50.0, actual=100.0)  # under-predicted 2x
        assert cell.underprediction_ratio == 2.0
        assert cell.runtime_error_ratio == 0.5
        assert cell.absolute_percentage_error == 50.0

    def test_an_incomplete_cell_cannot_score(self):
        for over in (
            {"status": "measured_failure", "projected_seconds": None, "actual_seconds": None},
            {"status": "infrastructure_failure", "projected_seconds": None, "actual_seconds": None},
            {"status": "skipped", "projected_seconds": None, "actual_seconds": None},
        ):
            assert _cell(probe=None, **over).contributes_to_verdict is False


class TestThresholdEvaluation:
    def _thresholds(self, **over) -> CampaignThresholds:
        return CampaignThresholds(**over)

    def test_an_accurate_campaign_passes(self):
        cells = [_cell(f"punet@{i}", projected=100.0, actual=105.0) for i in ("50K", "500K", "5M")]
        report = evaluate_campaign(cells, self._thresholds())
        assert report.verdict == "C12 PASS"
        assert report.cells_evaluated == 3

    def test_runtime_inaccuracy_fails(self):
        """Large errors in BOTH directions across different families: no
        family is systematically biased and there is no size trend, so the
        only thing wrong is raw accuracy."""
        cells = [
            _cell("punet@5M", family="punet", projected=250.0, actual=100.0),  # over 2.5x
            _cell("wavenet@5M", family="wavenet", projected=100.0, actual=180.0),  # under
            _cell("transformer@5M", family="transformer", projected=220.0, actual=100.0),
        ]
        report = evaluate_campaign(cells, self._thresholds())
        assert report.verdict == "C12 FAIL — RUNTIME ACCURACY"
        assert any("median absolute percentage error" in r for r in report.reasons)

    def test_a_uniformly_underestimated_family_reports_family_bias(self):
        """When an entire family is underestimated 2x at every size, the
        actionable diagnosis is the family, not generic inaccuracy — the
        verdict precedence says so deterministically."""
        cells = [_cell(f"punet@{i}", projected=100.0, actual=200.0) for i in ("a", "b", "c")]
        report = evaluate_campaign(cells, self._thresholds())
        assert report.verdict == "C12 FAIL — FAMILY BIAS"
        # the accuracy breach is still REPORTED, just not the headline
        assert any("median absolute percentage error" in r for r in report.reasons)

    def test_a_large_model_underestimated_twofold_fails_on_size_bias(self):
        cells = [
            _cell("punet@50K", projected=100.0, actual=100.0),
            _cell("punet@500K", projected=100.0, actual=100.0),
            _cell(
                "punet@20M",
                projected=100.0,
                actual=250.0,
                probe=_measurement(realized_parameter_count=20_000_000),
            ),
        ]
        report = evaluate_campaign(cells, self._thresholds())
        assert report.verdict in ("C12 FAIL — SIZE BIAS", "C12 FAIL — RUNTIME ACCURACY")
        assert any("underestimated by" in r for r in report.reasons)

    def test_monotonic_size_bias_is_caught_even_when_each_cell_is_small(self):
        """Each error is individually tolerable; the TREND is not."""
        cells = [
            _cell(
                "punet@50K",
                projected=100.0,
                actual=105.0,
                probe=_measurement(realized_parameter_count=50_000),
            ),
            _cell(
                "punet@500K",
                projected=100.0,
                actual=115.0,
                probe=_measurement(realized_parameter_count=500_000),
            ),
            _cell(
                "punet@5M",
                projected=100.0,
                actual=125.0,
                probe=_measurement(realized_parameter_count=5_000_000),
            ),
        ]
        report = evaluate_campaign(cells, self._thresholds())
        assert report.verdict == "C12 FAIL — SIZE BIAS"
        assert any("monotonically" in r for r in report.reasons)

    def test_family_wide_underprediction_is_caught(self):
        cells = [
            _cell(
                f"wavenet@{label}",
                family="wavenet",
                projected=100.0,
                actual=110.0,
                probe=_measurement(realized_parameter_count=size),
            )
            # non-monotonic so the size rule cannot claim it first
            for label, size in (("50K", 50_000), ("500K", 500_000), ("5M", 5_000_000))
        ]
        cells[1] = _cell(
            "wavenet@500K",
            family="wavenet",
            projected=100.0,
            actual=120.0,
            probe=_measurement(realized_parameter_count=500_000),
        )
        report = evaluate_campaign(cells, self._thresholds())
        assert report.verdict == "C12 FAIL — FAMILY BIAS"
        assert any("every tested size" in r for r in report.reasons)

    def test_vram_underprediction_fails(self):
        cells = [
            _cell(
                f"punet@{i}",
                projected=100.0,
                actual=100.0,
                predicted_peak_vram_gb=2.0,
                actual_peak_vram_gb=6.0,
            )
            for i in ("a", "b", "c")
        ]
        report = evaluate_campaign(cells, self._thresholds())
        assert report.verdict == "C12 FAIL — VRAM ACCURACY"

    def test_small_vram_gaps_are_tolerated_by_the_absolute_floor(self):
        cells = [
            _cell(
                f"punet@{i}",
                projected=100.0,
                actual=100.0,
                predicted_peak_vram_gb=2.0,
                actual_peak_vram_gb=2.8,  # 0.8 GB < max(1 GiB, 20%)
            )
            for i in ("a", "b", "c")
        ]
        assert evaluate_campaign(cells, self._thresholds()).verdict == "C12 PASS"

    def test_a_campaign_with_no_scorable_cell_is_stopped_not_passed(self):
        cells = [
            _cell(
                "x",
                probe=None,
                status="infrastructure_failure",
                projected_seconds=None,
                actual_seconds=None,
            )
        ]
        report = evaluate_campaign(cells, self._thresholds())
        assert report.verdict == "STOPPED — RESOURCE / ENVIRONMENT"
        assert report.cells_excluded == 1

    def test_evaluation_is_order_independent(self):
        cells = [
            _cell("a", projected=100.0, actual=101.0),
            _cell("b", projected=100.0, actual=140.0),
            _cell("c", projected=100.0, actual=90.0),
        ]
        first = evaluate_campaign(cells, self._thresholds())
        second = evaluate_campaign(list(reversed(cells)), self._thresholds())
        assert first.model_dump() == second.model_dump()

    def test_thresholds_carry_an_identity(self):
        default = CampaignThresholds()
        relaxed = CampaignThresholds(median_absolute_percentage_error_max=99.0)
        assert default.identity != relaxed.identity
        assert default.identity.startswith("campaign_thresholds@1.0.0+")


class TestPersistence:
    def test_a_cell_is_written_immediately_and_reloads(self, tmp_path):
        cell = _cell()
        path = write_cell(tmp_path, cell)
        assert path.is_file()
        loaded = load_cells(tmp_path)
        assert len(loaded) == 1
        assert loaded[0].cell_id == cell.cell_id

    def test_a_later_failure_does_not_erase_earlier_cells(self, tmp_path):
        write_cell(tmp_path, _cell("punet@50K"))
        write_cell(tmp_path, _cell("punet@500K"))
        write_cell(
            tmp_path,
            _cell(
                "punet@5M",
                probe=None,
                status="infrastructure_failure",
                projected_seconds=None,
                actual_seconds=None,
            ),
        )
        cells = load_cells(tmp_path)
        assert len(cells) == 3
        report = evaluate_campaign(cells, CampaignThresholds())
        assert report.cells_evaluated == 2
        assert report.cells_excluded == 1
