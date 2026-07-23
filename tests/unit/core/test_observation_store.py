"""
RT2-F unit tests: append-only observation store + derived priors.

Design: docs/design/runtime_estimation_and_watchdog.md §6/§6a/§6b/§6c.
Pins: append-only per-writer JSONL (no update/delete surface, malformed
lines fail safe), concurrent multi-process append safety, §6a key
composition, §6c eligibility filtering, realized-unit-time preference,
and §6b lookup invalidation (drift eviction, age staleness,
environment mismatch).
"""

from __future__ import annotations

import math
import multiprocessing
import time

import pytest

from core.runtime_control.observation_store import (
    ObservationStore,
    PriorPolicy,
    calibration_key,
    component_calibration_eligible,
    observation_calibration_key,
    realized_unit_ms,
)
from core.runtime_control.records import (
    AdmissionRecord,
    PhaseComponentRecord,
    PhaseMeasurement,
    RuntimeObservation,
    RuntimePrediction,
)
from core.runtime_control.workload import ResolvedPhaseWorkload

_CONTEXT = {
    "precision": "float32",
    "optimizer_type": "adam",
    "model_family": "wavenet",
    "param_count": 141_280,
    "seg_size": 1250,
    "batch_size": 2,
}


def _observation(
    *,
    unit_ms: float = 40.0,
    actual_seconds: float | None = None,
    predicted_seconds: float | None = None,
    timestamp: str = "2026-07-23T12:00:00+0000",
    final_status: str = "completed",
    steady: bool = True,
    watchdog: str | None = None,
    admission_decision: str | None = "admitted",
    unit_count: int = 1000,
    gpu_name: str = "NVIDIA H100",
    torch_version: str = "2.6.0",
) -> RuntimeObservation:
    measurement = PhaseMeasurement(
        unit="optimizer_step",
        n_measured_units=10,
        n_stabilization_units=5,
        unit_time_ms_median=unit_ms,
        steady_state_reached=steady,
        total_measurement_seconds=unit_ms * 10 / 1000.0,
    )
    prediction = None
    if predicted_seconds is not None:
        prediction = RuntimePrediction(
            predicted_seconds=predicted_seconds,
            source="real_training_verification",
            formal_execution_eligible=True,
            steady_state=True,
            verification="passed",
            confidence="high",
            ms_per_unit=unit_ms,
            n_steady_units=10,
            unit_count=unit_count,
            safety_factor=1.0,
        )
    component = PhaseComponentRecord(
        workload=ResolvedPhaseWorkload(
            phase="training", unit="optimizer_step", unit_count=unit_count
        ),
        prediction=prediction,
        measurement=measurement,
    )
    if actual_seconds is not None:
        component = component.with_actual(actual_seconds)
    return RuntimeObservation(
        timestamp=timestamp,
        hardware={"gpu_name": gpu_name},
        software={"torch_version": torch_version},
        calibration_context=dict(_CONTEXT),
        components={"training": component},
        admission=(
            AdmissionRecord(decision=admission_decision, stage="post_training_verification")  # type: ignore[arg-type]
            if admission_decision is not None
            else None
        ),
        watchdog_status=watchdog,
        final_status=final_status,
    )


_KEY = calibration_key(
    "training",
    gpu_name="NVIDIA H100",
    torch_version="2.6.0",
    precision="float32",
    optimizer_type="adam",
    model_family="wavenet",
    param_count=141_280,
    seg_size=1250,
    batch_size=2,
)


class TestAppendOnly:
    def test_round_trip(self, tmp_path):
        store = ObservationStore(str(tmp_path))
        store.append(_observation(), writer_id="chain_a")
        store.append(_observation(unit_ms=50.0), writer_id="chain_a")
        observations = store.read_all()
        assert len(observations) == 2

    def test_no_mutation_surface(self, tmp_path):
        store = ObservationStore(str(tmp_path))
        assert not hasattr(store, "delete")
        assert not hasattr(store, "update")
        assert not hasattr(store, "overwrite")

    def test_appends_never_overwrite(self, tmp_path):
        store = ObservationStore(str(tmp_path))
        obs = _observation()
        for _ in range(3):
            store.append(obs, writer_id="chain_a")
        assert len(store.read_all()) == 3  # identical records accumulate

    def test_invalid_writer_id_rejected(self, tmp_path):
        store = ObservationStore(str(tmp_path))
        with pytest.raises(ValueError, match="writer_id"):
            store.append(_observation(), writer_id="../escape")

    def test_malformed_lines_fail_safe(self, tmp_path):
        store = ObservationStore(str(tmp_path))
        path = store.append(_observation(), writer_id="chain_a")
        with open(path, "a") as f:
            f.write("{corrupt json\n")
        store.append(_observation(unit_ms=50.0), writer_id="chain_a")
        observations = store.read_all()
        assert len(observations) == 2  # corrupt line skipped, rest intact


def _append_worker(root: str, writer_id: str, n: int) -> None:
    store = ObservationStore(root)
    for _ in range(n):
        store.append(_observation(), writer_id=writer_id)


class TestConcurrentWriters:
    def test_multiprocess_appends_do_not_corrupt(self, tmp_path):
        procs = [
            multiprocessing.Process(target=_append_worker, args=(str(tmp_path), f"chain_{i}", 25))
            for i in range(4)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join()
            assert p.exitcode == 0
        observations = ObservationStore(str(tmp_path)).read_all()
        assert len(observations) == 100  # every append visible, none torn


class TestCalibrationKey:
    def test_observation_key_from_context(self):
        assert observation_calibration_key(_observation(), "training") == _KEY

    def test_missing_context_yields_none(self):
        obs = _observation().model_copy(update={"calibration_context": {}})
        assert observation_calibration_key(obs, "training") is None

    def test_key_separates_gpus_and_batch(self):
        other = calibration_key(
            "training",
            gpu_name="RTX 5090",
            torch_version="2.6.0",
            precision="float32",
            optimizer_type="adam",
            model_family="wavenet",
            param_count=141_280,
            seg_size=1250,
            batch_size=2,
        )
        assert other != _KEY


class TestEligibility:
    def test_clean_completed_is_eligible(self):
        assert component_calibration_eligible(_observation(), "training")

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"final_status": "rejected"},
            {"watchdog": "killed_wall_clock"},
            {"admission_decision": "rejected"},
            {"steady": False},
        ],
    )
    def test_unclean_observations_excluded(self, kwargs):
        assert not component_calibration_eligible(_observation(**kwargs), "training")

    def test_realized_prefers_actual_over_measurement(self):
        obs = _observation(unit_ms=40.0, actual_seconds=50.0, unit_count=1000)
        assert realized_unit_ms(obs, "training") == pytest.approx(50.0)  # 50s/1000
        no_actual = _observation(unit_ms=40.0)
        assert realized_unit_ms(no_actual, "training") == pytest.approx(40.0)


class TestPriorDerivation:
    def test_median_of_realized_unit_times(self, tmp_path):
        store = ObservationStore(str(tmp_path))
        for actual in (30.0, 40.0, 50.0):  # realized 30/40/50 ms at 1000 units
            store.append(_observation(actual_seconds=actual), writer_id="c")
        lookup = store.lookup_prior(_KEY, "training")
        assert lookup.status == "valid"
        assert lookup.prior_unit_ms == pytest.approx(40.0)
        assert lookup.n_observations == 3

    def test_absent_key(self, tmp_path):
        assert ObservationStore(str(tmp_path)).lookup_prior(_KEY, "training").status == "absent"

    def test_ineligible_observations_never_feed_priors(self, tmp_path):
        store = ObservationStore(str(tmp_path))
        store.append(_observation(watchdog="killed"), writer_id="c")
        assert store.lookup_prior(_KEY, "training").status == "absent"

    def test_drift_evicts_prior(self, tmp_path):
        # §6b rule 4: 3 consecutive contract violations (ratio 2.0 →
        # log_error ≈ 0.69 > ln 1.5) evict the prior.
        store = ObservationStore(str(tmp_path))
        for i in range(3):
            store.append(
                _observation(
                    predicted_seconds=20.0,
                    actual_seconds=40.0,
                    timestamp=f"2026-07-23T12:00:0{i}+0000",
                ),
                writer_id="c",
            )
        lookup = store.lookup_prior(_KEY, "training")
        assert lookup.status == "evicted_drift"
        assert lookup.prior_unit_ms is None

    def test_within_contract_errors_keep_prior(self, tmp_path):
        store = ObservationStore(str(tmp_path))
        for i in range(3):
            store.append(
                _observation(
                    predicted_seconds=40.0,
                    actual_seconds=44.0,  # ratio 1.1 — inside F=1.5
                    timestamp=f"2026-07-23T12:00:0{i}+0000",
                ),
                writer_id="c",
            )
        assert store.lookup_prior(_KEY, "training").status == "valid"

    def test_age_marks_stale(self, tmp_path):
        store = ObservationStore(str(tmp_path))
        store.append(_observation(actual_seconds=40.0), writer_id="c")
        future = time.time() + 200 * 86400
        lookup = store.lookup_prior(_KEY, "training", now=future)
        assert lookup.status == "stale"
        assert lookup.prior_unit_ms == pytest.approx(40.0)  # usable w/ elevated safety

    def test_env_mismatch_never_cross_applied(self, tmp_path):
        store = ObservationStore(str(tmp_path))
        store.append(_observation(actual_seconds=40.0), writer_id="c")
        assert (
            store.lookup_prior(_KEY, "training", current_gpu_name="RTX 5090").status
            == "env_mismatch"
        )
        assert (
            store.lookup_prior(_KEY, "training", current_torch_version="3.0.0").status
            == "env_mismatch"
        )
        assert (
            store.lookup_prior(
                _KEY, "training", current_gpu_name="NVIDIA H100", current_torch_version="2.6.0"
            ).status
            == "valid"
        )

    def test_drift_threshold_uses_contract_factor(self, tmp_path):
        store = ObservationStore(str(tmp_path))
        for i in range(3):
            store.append(
                _observation(
                    predicted_seconds=30.0,
                    actual_seconds=40.0,  # ratio 1.33: inside F=1.5, outside F=1.2
                    timestamp=f"2026-07-23T12:00:0{i}+0000",
                ),
                writer_id="c",
            )
        assert store.lookup_prior(_KEY, "training").status == "valid"
        strict = PriorPolicy(contract_factor=1.2)
        assert store.lookup_prior(_KEY, "training", policy=strict).status == "evicted_drift"
        assert math.log(40.0 / 30.0) > math.log(1.2)  # scenario sanity
