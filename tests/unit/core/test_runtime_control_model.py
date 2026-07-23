"""RT2-A — runtime data model: P/M/A separation, component-first schema,
verifier lifecycle, legacy-record compatibility.

Design: docs/design/runtime_estimation_and_watchdog.md §2.3, §2.4,
§2.8, §6.1, §7.3.
"""

from __future__ import annotations

import math
from typing import ClassVar

import pytest
from pydantic import ValidationError

from core.runtime_control import (
    MEASUREMENT_BACKED_SOURCES,
    AdmissionRecord,
    PhaseComponentRecord,
    PhaseMeasurement,
    PredictionError,
    ResolvedPhaseWorkload,
    RuntimeObservation,
    RuntimePhaseVerifier,
    RuntimePrediction,
    SteadyStateConfig,
    SteadyStateDetection,
    extract_runtime_observation,
    observation_totals_from_components,
    record_is_formal_verified,
)


def _measured_prediction(seconds: float = 2520.0, **overrides) -> RuntimePrediction:
    kw = dict(
        predicted_seconds=seconds,
        source="real_training_verification",
        formal_execution_eligible=True,
        steady_state=True,
        verification="passed",
        confidence="high",
        ms_per_unit=44.3,
        n_steady_units=50,
        unit_count=480_000,
        safety_factor=1.5,
    )
    kw.update(overrides)
    return RuntimePrediction(**kw)


def _static_prediction(seconds: float = 1248.0) -> RuntimePrediction:
    return RuntimePrediction(
        predicted_seconds=seconds,
        source="static_uncalibrated",
        formal_execution_eligible=False,
        steady_state=False,
        verification="not_attempted",
        confidence="low",
        safety_factor=1.3,
    )


def _measurement(unit: str = "optimizer_step") -> PhaseMeasurement:
    return PhaseMeasurement(
        unit=unit,
        n_measured_units=50,
        n_stabilization_units=12,
        unit_time_ms_median=44.3,
        unit_time_ms_mad=0.3,
        steady_state_reached=True,
        total_measurement_seconds=4.1,
    )


class TestWidenedSourceVocabulary:
    def test_every_measurement_backed_source_can_be_formal_eligible(self):
        for source in sorted(MEASUREMENT_BACKED_SOURCES):
            p = _measured_prediction(source=source)
            assert p.formal_execution_eligible

    def test_prior_sources_can_never_be_formal_eligible(self):
        for source in (
            "static_uncalibrated",
            "legacy_calibration_prior",
            "historical_observation_prior",
            "historical_orchestration",
            "bounded_negligible",
            "derived_total",
        ):
            with pytest.raises(ValidationError, match="admission"):
                _measured_prediction(source=source)

    def test_legacy_wrapper_source_string_retained(self):
        # §7.1: the RT1 wrapper contract exposes "real_dataset_warmup".
        assert "real_dataset_warmup" in MEASUREMENT_BACKED_SOURCES


class TestPredictionMeasurementActualSeparation:
    def test_error_is_prediction_vs_actual_never_measurement(self):
        pred = _measured_prediction(seconds=1000.0)
        meas = _measurement()
        rec = PhaseComponentRecord(prediction=pred, measurement=meas)
        done = rec.with_actual(1500.0)
        assert done.prediction_error is not None
        assert done.prediction_error.predicted_seconds == 1000.0
        assert done.prediction_error.actual_seconds == 1500.0
        assert done.prediction_error.ratio == pytest.approx(1.5)
        # The measurement is untouched evidence, not the error target.
        assert done.measurement == meas

    def test_error_without_prediction_rejected(self):
        err = PredictionError.from_values(1000.0, 1500.0)
        with pytest.raises(ValidationError, match="prediction"):
            PhaseComponentRecord(prediction_error=err, actual_seconds=1500.0)

    def test_error_mismatching_own_record_rejected(self):
        foreign = PredictionError.from_values(999.0, 1500.0)
        with pytest.raises(ValidationError, match="THIS record"):
            PhaseComponentRecord(
                prediction=_measured_prediction(seconds=1000.0),
                actual_seconds=1500.0,
                prediction_error=foreign,
            )

    def test_contract_check(self):
        err = PredictionError.from_values(1000.0, 1400.0)
        assert err.within_contract(1.5)
        assert not err.within_contract(1.2)
        # Symmetric: overprediction is judged identically.
        assert PredictionError.from_values(1400.0, 1000.0).log_error == pytest.approx(err.log_error)


class TestComponentFirstObservation:
    @staticmethod
    def _components() -> dict:
        return {
            "training": PhaseComponentRecord(prediction=_measured_prediction(21264.0)),
            "inference": PhaseComponentRecord(
                prediction=_measured_prediction(
                    7200.0, source="real_inference_verification", unit_count=120
                )
            ),
            "scoring": PhaseComponentRecord(prediction=_static_prediction(180.0)),
        }

    def test_total_derived_from_components(self):
        comps = self._components()
        total = observation_totals_from_components(
            comps, safety_factor=1.5, operator_budget_seconds=7200.0
        )
        assert total.predicted_seconds == pytest.approx(21264.0 + 7200.0 + 180.0)
        assert total.safety_adjusted_seconds == pytest.approx(total.predicted_seconds * 1.5)

    def test_incomplete_components_cannot_derive_total(self):
        comps = self._components()
        comps["inference"] = PhaseComponentRecord(measurement=_measurement("inference_batch"))
        with pytest.raises(ValueError, match="missing predictions"):
            observation_totals_from_components(comps)

    def test_observation_rejects_non_derived_total(self):
        comps = self._components()
        good_total = observation_totals_from_components(comps)
        RuntimeObservation(
            timestamp="2026-07-23T20:00:00+00:00", components=comps, total=good_total
        )
        with pytest.raises(ValidationError, match="DERIVED"):
            RuntimeObservation(
                timestamp="2026-07-23T20:00:00+00:00",
                components=comps,
                total=good_total.model_copy(update={"predicted_seconds": 1.0}),
            )

    def test_admission_cost_model_round_trip(self):
        adm = AdmissionRecord(
            decision="rejected",
            stage="post_setup_runtime_verification",
            setup_cost_seconds=110.0,
            verification_cost_seconds=6.2,
            avoided_predicted_runtime_seconds=27_600.0,
        )
        obs = RuntimeObservation(
            timestamp="2026-07-23T20:00:00+00:00",
            components=self._components(),
            admission=adm,
        )
        assert obs.admission is not None and obs.admission.decision == "rejected"


class TestLegacyRecordCompatibility:
    def test_legacy_record_without_block_is_explicit_absence(self):
        legacy = {"record_type": "attempt", "score": 0.85}  # archived V18 shape
        assert extract_runtime_observation(legacy) is None
        assert record_is_formal_verified(legacy) is False

    def test_malformed_block_fails_closed_not_verified(self):
        assert record_is_formal_verified({"runtime_verification": {"bogus": 1}}) is False

    def test_admitted_verified_observation_round_trip(self):
        comps = {"training": PhaseComponentRecord(prediction=_measured_prediction())}
        obs = RuntimeObservation(
            timestamp="2026-07-23T20:00:00+00:00",
            components=comps,
            admission=AdmissionRecord(decision="admitted", stage="post_setup_runtime_verification"),
        )
        record = {"record_type": "attempt", "runtime_verification": obs.model_dump()}
        assert record_is_formal_verified(record) is True

    def test_static_backed_admission_is_not_verified(self):
        comps = {"training": PhaseComponentRecord(prediction=_static_prediction())}
        obs = RuntimeObservation(
            timestamp="2026-07-23T20:00:00+00:00",
            components=comps,
            admission=AdmissionRecord(decision="admitted", stage="pre_launch_screen"),
        )
        record = {"runtime_verification": obs.model_dump()}
        assert record_is_formal_verified(record) is False


class _StubVerifier(RuntimePhaseVerifier):
    """Deterministic stub phase exercising the lifecycle driver."""

    phase: ClassVar = "training"

    def __init__(self):
        self.calls: list[str] = []

    def resolve_workload(self) -> ResolvedPhaseWorkload:
        self.calls.append("resolve_workload")
        return ResolvedPhaseWorkload(phase="training", unit="optimizer_step", unit_count=1000)

    def prepare(self) -> None:
        self.calls.append("prepare")

    def reach_steady_state(self) -> SteadyStateDetection:
        self.calls.append("reach_steady_state")
        return SteadyStateDetection(
            reached=True,
            steady_from_step=3,
            steps_observed=20,
            steady_median_ms=10.0,
            steady_mad_ms=0.1,
            reason="stable_spread",
            config=SteadyStateConfig(),
        )

    def measure(self, detection: SteadyStateDetection) -> PhaseMeasurement:
        self.calls.append("measure")
        assert detection.reached
        return PhaseMeasurement(
            unit="optimizer_step",
            n_measured_units=17,
            n_stabilization_units=3,
            unit_time_ms_median=10.0,
            steady_state_reached=True,
            total_measurement_seconds=0.2,
        )

    def predict(self, workload, measurement) -> RuntimePrediction:
        self.calls.append("predict")
        seconds = workload.unit_count * measurement.unit_time_ms_median / 1000.0 * 1.5
        return RuntimePrediction(
            predicted_seconds=seconds,
            source="real_training_verification",
            formal_execution_eligible=True,
            steady_state=True,
            verification="passed",
            confidence="high",
            ms_per_unit=measurement.unit_time_ms_median,
            n_steady_units=measurement.n_measured_units,
            unit_count=workload.unit_count,
            safety_factor=1.5,
        )


class TestVerifierLifecycle:
    def test_driver_runs_lifecycle_in_order_and_assembles_record(self):
        v = _StubVerifier()
        rec = v.run_verification()
        assert v.calls == [
            "resolve_workload",
            "prepare",
            "reach_steady_state",
            "measure",
            "predict",
        ]
        assert rec.workload is not None and rec.workload.unit_count == 1000
        assert rec.measurement is not None and rec.measurement.n_measured_units == 17
        assert rec.prediction is not None
        assert rec.prediction.predicted_seconds == pytest.approx(1000 * 10.0 / 1000.0 * 1.5)
        assert rec.actual_seconds is None and rec.prediction_error is None

    def test_finalize_actual_derives_error(self):
        rec = _StubVerifier().run_verification()
        done = RuntimePhaseVerifier.finalize_actual(rec, actual_seconds=18.0)
        assert done.prediction_error is not None
        assert done.prediction_error.ratio == pytest.approx(18.0 / 15.0)
        assert math.isclose(done.prediction_error.log_error, abs(math.log(18.0 / 15.0)))
