"""
RT2-E unit tests: contribution-based total assembly (operator decision
2026-07-23) + the three §11 worked examples.

Pins: phase classification is source-based never name-based; the
configurable historical share limit with automatic escalation;
incomplete/inadmissible fail-closed; conservative aggregation (§2.9:
exact sum, safety multiplier, min confidence); the scoring
historically-calibrated bridge; and `record_is_formal_verified` under
the new policy.
"""

from __future__ import annotations

import pytest

from core.runtime_control.records import (
    AdmissionRecord,
    PhaseComponentRecord,
    RuntimeObservation,
    RuntimePrediction,
    record_is_formal_verified,
)
from core.runtime_control.total_assembly import (
    DEFAULT_HISTORICAL_SHARE_LIMIT,
    assemble_total,
    classify_prediction_source,
    evidence_backed_prediction,
)
from core.runtime_control.workload import ResolvedPhaseWorkload
from execute_tools.workload_resolvers import (
    resolve_scoring_workload,
    scoring_prediction_from_server_config,
)


def _live(seconds: float, source: str = "real_training_verification") -> PhaseComponentRecord:
    return PhaseComponentRecord(
        prediction=RuntimePrediction(
            predicted_seconds=seconds,
            source=source,  # type: ignore[arg-type]
            formal_execution_eligible=True,
            steady_state=True,
            verification="passed",
            confidence="high",
            ms_per_unit=1.0,
            n_steady_units=10,
            safety_factor=1.0,
        )
    )


def _historical(
    seconds: float, source: str = "historical_observation_prior"
) -> PhaseComponentRecord:
    return PhaseComponentRecord(
        prediction=evidence_backed_prediction(
            predicted_seconds=seconds,
            source=source,
            confidence="medium",
            evidence={"origin": "test"},
        )
    )


def _static(seconds: float) -> PhaseComponentRecord:
    return PhaseComponentRecord(
        prediction=RuntimePrediction(
            predicted_seconds=seconds,
            source="static_uncalibrated",
            formal_execution_eligible=False,
            steady_state=False,
            verification="not_attempted",
            confidence="low",
            safety_factor=1.0,
        )
    )


_FIVE_PHASES = ("setup", "training", "inference", "scoring", "orchestration")


class TestClassification:
    def test_classes_are_source_based_never_name_based(self):
        # The SAME phase name classifies differently by source alone.
        assert classify_prediction_source("real_training_verification") == "live_verified"
        assert classify_prediction_source("historical_observation_prior") == "historical_estimate"
        assert classify_prediction_source("bounded_negligible") == "historical_estimate"
        assert classify_prediction_source("static_uncalibrated") == "inadmissible"
        assert classify_prediction_source("derived_total") == "inadmissible"

    def test_evidence_backed_prediction_never_individually_eligible(self):
        pred = evidence_backed_prediction(
            predicted_seconds=60.0,
            source="historical_orchestration",
            confidence="low",
            evidence={"origin": "env-scoped estimate"},
        )
        assert pred.formal_execution_eligible is False
        assert pred.detail["classification"] == "historical_estimate"

    def test_evidence_backed_rejects_non_historical_sources(self):
        with pytest.raises(ValueError, match="historical"):
            evidence_backed_prediction(
                predicted_seconds=1.0, source="static_uncalibrated", confidence="low"
            )


class TestWorkedExamples:
    """The three §11 RT2-E worked examples with admission decisions."""

    def test_example_1_normal_run_admitted(self):
        # setup 2min + training 80min + inference 15min live; scoring
        # 2min + orchestration 1min historical → share 3% ≤ 10% →
        # eligible; safety-adjusted 150min ≤ 180min budget → ADMIT.
        components = {
            "setup": _live(120.0, "real_dataset_setup"),
            "training": _live(4800.0),
            "inference": _live(900.0, "real_inference_verification"),
            "scoring": _historical(120.0),
            "orchestration": _historical(60.0, "historical_orchestration"),
        }
        assessment = assemble_total(
            components,
            required_phases=_FIVE_PHASES,
            historical_phase_share_limit=0.10,
            safety_factor=1.5,
            operator_budget_seconds=10_800.0,
        )
        assert assessment.formal_eligible is True
        assert assessment.historical_share == pytest.approx(180.0 / 6000.0)
        assert assessment.total is not None
        assert assessment.total.predicted_seconds == pytest.approx(6000.0)
        assert assessment.total.safety_adjusted_seconds == pytest.approx(9000.0)
        assert assessment.overall_confidence == "medium"  # min over components
        admitted = assessment.total.safety_adjusted_seconds <= 10_800.0
        assert admitted

    def test_example_2_scoring_dominated_escalates(self):
        # A "minor" phase grown large: scoring 45min historical of a
        # 60min total → share 75% → automatic escalation, INELIGIBLE
        # regardless of budget (fail closed for formal).
        components = {
            "setup": _live(60.0, "real_dataset_setup"),
            "training": _live(600.0),
            "inference": _live(240.0, "real_inference_verification"),
            "scoring": _historical(2700.0),
            "orchestration": _historical(30.0, "historical_orchestration"),
        }
        assessment = assemble_total(
            components,
            required_phases=_FIVE_PHASES,
            historical_phase_share_limit=0.10,
            operator_budget_seconds=86_400.0,  # budget is NOT the problem
        )
        assert assessment.formal_eligible is False
        assert assessment.escalation_required[0] == "scoring"  # largest first
        assert "escalate" in assessment.reason

    def test_example_3_incident_shape_rejected_on_budget(self):
        # All live-verified, complete — but the safety-adjusted total
        # exceeds the operator budget: the admission layer rejects.
        components = {
            "setup": _live(150.0, "real_dataset_setup"),
            "training": _live(21_264.0),
            "inference": _live(7200.0, "real_inference_verification"),
            "scoring": _historical(180.0),
            "orchestration": _historical(60.0, "historical_orchestration"),
        }
        assessment = assemble_total(
            components,
            required_phases=_FIVE_PHASES,
            historical_phase_share_limit=0.10,
            safety_factor=1.0,
            operator_budget_seconds=7200.0,
        )
        assert assessment.formal_eligible is True  # eligibility ≠ admission
        assert assessment.total is not None
        assert assessment.total.safety_adjusted_seconds is not None
        rejected = assessment.total.safety_adjusted_seconds > 7200.0
        assert rejected  # 28,854s ≫ 7,200s — the V18 incident caught


class TestFailClosed:
    def test_incomplete_required_set_ineligible(self):
        components = {"training": _live(100.0)}
        assessment = assemble_total(
            components,
            required_phases=("training", "inference"),
            historical_phase_share_limit=0.10,
        )
        assert assessment.formal_eligible is False
        assert assessment.missing_phases == ["inference"]

    def test_static_source_inadmissible(self):
        components = {"training": _live(100.0), "inference": _static(50.0)}
        assessment = assemble_total(
            components,
            required_phases=("training", "inference"),
            historical_phase_share_limit=0.10,
        )
        assert assessment.formal_eligible is False
        assert "inadmissible" in assessment.reason

    def test_share_limit_is_configurable(self):
        components = {"training": _live(80.0), "scoring": _historical(20.0)}  # 20%
        strict = assemble_total(
            components,
            required_phases=("training", "scoring"),
            historical_phase_share_limit=0.10,
        )
        lenient = assemble_total(
            components,
            required_phases=("training", "scoring"),
            historical_phase_share_limit=0.25,
        )
        assert strict.formal_eligible is False
        assert lenient.formal_eligible is True


class TestScoringBridge:
    def test_historically_calibrated_scoring_prediction(self):
        workload = resolve_scoring_workload({"0": list(range(6))}, num_workers=3)
        pred = scoring_prediction_from_server_config(
            workload,
            per_psd_segment_seconds=2.21,  # ligroup measured value
            hostname="ligroup",
            num_workers=3,
        )
        assert pred.predicted_seconds == pytest.approx(6 * 2.21 / 3)
        assert pred.source == "historical_observation_prior"
        assert pred.formal_execution_eligible is False
        evidence = pred.detail["evidence"]
        assert evidence["classification"] == "historically_calibrated"
        assert evidence["hostname"] == "ligroup"
        assert evidence["parallel_model"] == "linear_speedup_assumed"

    def test_invalid_inputs_raise(self):
        workload = resolve_scoring_workload({"0": [0]}, num_workers=1)
        with pytest.raises(ValueError):
            scoring_prediction_from_server_config(
                workload, per_psd_segment_seconds=0.0, hostname="h", num_workers=1
            )
        with pytest.raises(ValueError):
            scoring_prediction_from_server_config(
                workload, per_psd_segment_seconds=1.0, hostname="h", num_workers=0
            )


class TestRecordVerifiedUnderContributionPolicy:
    @staticmethod
    def _record(components, policy: dict | None = None) -> dict:
        obs = RuntimeObservation(
            timestamp="2026-07-23T20:00:00+0000",
            runtime_policy=policy or {},
            components=components,
            admission=AdmissionRecord(decision="admitted", stage="post_setup_runtime_verification"),
        )
        return {"runtime_verification": obs.model_dump(mode="json")}

    def test_live_plus_small_historical_verified(self):
        record = self._record(
            {"training": _live(950.0), "scoring": _historical(50.0)}  # 5% share
        )
        assert record_is_formal_verified(record) is True

    def test_large_historical_share_not_verified(self):
        record = self._record(
            {"training": _live(400.0), "scoring": _historical(600.0)}  # 60%
        )
        assert record_is_formal_verified(record) is False

    def test_recorded_policy_limit_respected(self):
        components = {"training": _live(800.0), "scoring": _historical(200.0)}  # 20%
        assert record_is_formal_verified(self._record(components)) is False  # default 10%
        lenient = self._record(components, policy={"historical_phase_share_limit": 0.3})
        assert record_is_formal_verified(lenient) is True

    def test_default_limit_constant(self):
        assert DEFAULT_HISTORICAL_SHARE_LIMIT == pytest.approx(0.10)
