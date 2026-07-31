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
        assert labels == {"small_cross_family", "large_cross_family", "heterogeneous_compute"}
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
    """Threshold behaviour only. Required-cell COVERAGE is a separate gate
    with its own tests, so these cases excuse it explicitly rather than
    accidentally passing or failing on it."""

    def _thresholds(self, **over) -> CampaignThresholds:
        return CampaignThresholds(**over)

    def _evaluate(self, cells, thresholds):
        from core.runtime_control.campaign import required_cell_ids

        return evaluate_campaign(
            cells, thresholds, approved_replacements=frozenset(required_cell_ids())
        )

    def test_an_accurate_campaign_passes(self):
        cells = [_cell(f"punet@{i}", projected=100.0, actual=105.0) for i in ("50K", "500K", "5M")]
        report = self._evaluate(cells, self._thresholds())
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
        report = self._evaluate(cells, self._thresholds())
        assert report.verdict == "C12 FAIL — RUNTIME ACCURACY"
        assert any("median absolute percentage error" in r for r in report.reasons)

    def test_a_uniformly_underestimated_family_reports_family_bias(self):
        """When an entire family is underestimated 2x at every size, the
        actionable diagnosis is the family, not generic inaccuracy — the
        verdict precedence says so deterministically."""
        cells = [_cell(f"punet@{i}", projected=100.0, actual=200.0) for i in ("a", "b", "c")]
        report = self._evaluate(cells, self._thresholds())
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
        report = self._evaluate(cells, self._thresholds())
        assert report.verdict in ("C12 FAIL — SIZE BIAS", "C12 FAIL — RUNTIME ACCURACY")
        assert any("underestimated by" in r for r in report.reasons)

    def test_size_bias_needs_both_a_material_spread_and_an_upward_trend(self):
        """FROZEN rule: spread(largest - smallest) > 0.25 AND a majority of
        adjacent sizes trending upward. Each individual error here is
        tolerable; the TREND across sizes is not."""
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
                actual=120.0,
                probe=_measurement(realized_parameter_count=500_000),
            ),
            _cell(
                "punet@5M",
                projected=100.0,
                actual=140.0,
                probe=_measurement(realized_parameter_count=5_000_000),
            ),
        ]
        report = self._evaluate(cells, self._thresholds())
        assert report.verdict == "C12 FAIL — SIZE BIAS"
        assert any("underprediction grows with size" in r for r in report.reasons)
        assert any("adjacent sizes trending upward" in r for r in report.reasons)

    def test_family_bias_needs_enough_cells_and_a_median_above_the_bar(self):
        cells = [
            _cell(
                f"wavenet@{label}",
                family="wavenet",
                projected=100.0,
                actual=115.0,
                probe=_measurement(realized_parameter_count=size),
            )
            # flat, not trending: the size rule must not claim this first
            for label, size in (("50K", 50_000), ("500K", 500_000), ("5M", 5_000_000))
        ]
        report = self._evaluate(cells, self._thresholds())
        assert report.verdict == "C12 FAIL — FAMILY BIAS"
        assert any("cells underestimated with a median ratio" in r for r in report.reasons)

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
        report = self._evaluate(cells, self._thresholds())
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
        assert self._evaluate(cells, self._thresholds()).verdict == "C12 PASS"

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
        report = self._evaluate(cells, self._thresholds())
        assert report.verdict == "STOPPED — RESOURCE / ENVIRONMENT"
        assert report.cells_excluded == 1

    def test_evaluation_is_order_independent(self):
        cells = [
            _cell("a", projected=100.0, actual=101.0),
            _cell("b", projected=100.0, actual=140.0),
            _cell("c", projected=100.0, actual=90.0),
        ]
        first = self._evaluate(cells, self._thresholds())
        second = self._evaluate(list(reversed(cells)), self._thresholds())
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


class TestPairwiseConcurrency:
    def _result(self, **over):
        from core.runtime_control.campaign import PairwiseResult

        base = dict(
            label="small_cross_family",
            member="punet@50K",
            alone_ms_per_step=20.0,
            paired_ms_per_step=34.0,
            alone_concurrency_identity="single_candidate_idle",
            paired_concurrency_identity="pairwise_expected_peer",
            peer_pid_registered=True,
        )
        base.update(over)
        return PairwiseResult(**base)

    def test_plans_cover_the_three_required_shapes(self):
        from core.runtime_control.campaign import build_pairwise_plans

        plans = build_pairwise_plans({"punet@50K": 69_328, "wavenet@50K": 49_680})
        assert {p.label for p in plans} == {
            "small_cross_family",
            "large_cross_family",
            "heterogeneous_compute",
        }
        small = next(p for p in plans if p.label == "small_cross_family")
        assert small.member_parameter_counts == (69_328, 49_680)

    def test_each_pair_measures_alone_before_together(self):
        from core.runtime_control.campaign import build_pairwise_plans

        plan = build_pairwise_plans()[0]
        assert plan.stages[0].endswith("_alone")
        assert plan.stages[1].endswith("_alone")
        assert plan.stages[2].endswith("_pairwise")

    def test_the_contention_multiplier_is_per_member(self):
        assert self._result().contention_multiplier == pytest.approx(1.7)

    def test_an_idle_observation_cannot_be_recorded_as_concurrent(self):
        with pytest.raises(ValidationError, match="never be recorded"):
            self._result(paired_concurrency_identity="single_candidate_idle")

    def test_a_contended_baseline_cannot_define_a_multiplier(self):
        with pytest.raises(ValidationError, match="cannot define a contention multiplier"):
            self._result(alone_concurrency_identity="foreign_contended")

    def test_a_foreign_process_is_never_accepted_as_the_peer(self):
        with pytest.raises(ValidationError, match=r"never be recorded|REGISTERED PID"):
            self._result(paired_concurrency_identity="foreign_contended")
        with pytest.raises(ValidationError, match="REGISTERED PID"):
            self._result(peer_pid_registered=False)


class TestRequiredCellCoverage:
    """Operator rule (2026-07-31): a measured failure is preserved as
    evidence, but it still leaves a hole in the matrix. C12 cannot PASS
    while any required cell lacks a completed measurement."""

    def _complete_matrix(self):
        from core.runtime_control.campaign import required_cell_ids

        return [
            _cell(cell_id, family=cell_id.split("@")[0], projected=100.0, actual=102.0)
            for cell_id in required_cell_ids()
        ]

    def test_a_complete_accurate_matrix_passes(self):
        report = evaluate_campaign(self._complete_matrix(), CampaignThresholds())
        assert report.verdict == "C12 PASS"
        assert report.metrics["required_cells"] == 12

    def test_a_missing_cell_blocks_pass_even_when_everything_else_is_fine(self):
        cells = self._complete_matrix()[:-1]
        report = evaluate_campaign(cells, CampaignThresholds())
        assert report.verdict == "STOPPED — RESOURCE / ENVIRONMENT"
        assert any("required cells without a completed measurement" in r for r in report.reasons)
        assert "transformer@8M-ceiling" in report.reasons[-1]

    def test_a_measured_failure_is_preserved_but_still_leaves_a_hole(self):
        cells = self._complete_matrix()[:-1]
        cells.append(
            _cell(
                "transformer@8M-ceiling",
                family="transformer",
                probe=None,
                status="measured_failure",
                failure_detail="probe status=oom: CUDA out of memory",
                projected_seconds=None,
                actual_seconds=None,
            )
        )
        report = evaluate_campaign(cells, CampaignThresholds())
        assert report.verdict == "STOPPED — RESOURCE / ENVIRONMENT"
        assert "oom" in report.reasons[-1]  # the evidence is reported, not dropped

    def test_an_operator_approved_replacement_restores_coverage(self):
        cells = self._complete_matrix()[:-1]
        report = evaluate_campaign(
            cells,
            CampaignThresholds(),
            approved_replacements=frozenset({"transformer@8M-ceiling"}),
        )
        assert report.verdict == "C12 PASS"

    def test_the_ceiling_cell_is_named_by_its_realized_scale(self):
        from core.runtime_control.campaign import required_cell_ids

        ids = required_cell_ids()
        assert "transformer@8M-ceiling" in ids
        assert "transformer@20M" not in ids  # never analyzed as a 20M cell


class TestFrozenThresholdIdentity:
    def test_the_frozen_values_are_the_approved_ones(self):
        t = CampaignThresholds()
        assert t.median_absolute_percentage_error_max == 30.0
        assert t.p90_underprediction_ratio_max == 1.5
        assert t.large_model_underprediction_ratio_max == 2.0
        assert t.large_model_parameter_threshold == 5_000_000
        assert t.size_bias_ratio_spread_max == 0.25
        assert t.size_bias_min_completed_sizes == 3
        assert t.family_bias_min_completed_cells == 3
        assert t.family_bias_min_underestimated == 3
        assert t.family_bias_median_ratio_max == 1.10
        assert t.vram_underprediction_fraction_max == 0.20
        assert t.vram_underprediction_absolute_gb_max == 1.0
        assert t.frozen_by == "operator 2026-07-31"

    def test_the_identity_pins_the_frozen_set(self):
        """Any post-hoc edit changes this hash, so a silent relaxation is
        visible in every report rather than invisible in a diff."""
        assert CampaignThresholds().identity == "campaign_thresholds@1.0.0+4e06a54f5c2c"
