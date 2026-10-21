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
from datetime import datetime, timedelta

import pytest

from core.runtime_control.calibration_derivation import (
    IdentityContext,
    derive_duration_calibration_record,
)
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

# These fixtures use local, timezone-naive timestamps, which the store supports.
# Lookup time is explicit so unrelated assertions cannot age out with the calendar.
_OBSERVATION_TIME = datetime(2026, 7, 23, 12)
_LOOKUP_TIME = (_OBSERVATION_TIME + timedelta(minutes=1)).timestamp()

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
    timestamp: str = _OBSERVATION_TIME.isoformat(),
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
        lookup = store.lookup_prior(_KEY, "training", now=_LOOKUP_TIME)
        assert lookup.status == "valid"
        assert lookup.prior_unit_ms == pytest.approx(40.0)
        assert lookup.n_observations == 3

    def test_absent_key(self, tmp_path):
        assert (
            ObservationStore(str(tmp_path)).lookup_prior(_KEY, "training", now=_LOOKUP_TIME).status
            == "absent"
        )

    def test_ineligible_observations_never_feed_priors(self, tmp_path):
        store = ObservationStore(str(tmp_path))
        store.append(_observation(watchdog="killed"), writer_id="c")
        assert store.lookup_prior(_KEY, "training", now=_LOOKUP_TIME).status == "absent"

    def test_drift_evicts_prior(self, tmp_path):
        # §6b rule 4: 3 consecutive contract violations (ratio 2.0 →
        # log_error ≈ 0.69 > ln 1.5) evict the prior.
        store = ObservationStore(str(tmp_path))
        for i in range(3):
            store.append(
                _observation(
                    predicted_seconds=20.0,
                    actual_seconds=40.0,
                    timestamp=(_OBSERVATION_TIME + timedelta(seconds=i)).isoformat(),
                ),
                writer_id="c",
            )
        lookup = store.lookup_prior(_KEY, "training", now=_LOOKUP_TIME)
        assert lookup.status == "evicted_drift"
        assert lookup.prior_unit_ms is None

    def test_within_contract_errors_keep_prior(self, tmp_path):
        store = ObservationStore(str(tmp_path))
        for i in range(3):
            store.append(
                _observation(
                    predicted_seconds=40.0,
                    actual_seconds=44.0,  # ratio 1.1 — inside F=1.5
                    timestamp=(_OBSERVATION_TIME + timedelta(seconds=i)).isoformat(),
                ),
                writer_id="c",
            )
        assert store.lookup_prior(_KEY, "training", now=_LOOKUP_TIME).status == "valid"

    @pytest.mark.parametrize("max_age_days", [0.5, 90.0])
    @pytest.mark.parametrize("offset, expected", [(-1, "valid"), (0, "valid"), (1, "stale")])
    def test_age_boundary_uses_declared_policy(self, tmp_path, max_age_days, offset, expected):
        store = ObservationStore(str(tmp_path))
        store.append(_observation(actual_seconds=40.0), writer_id="c")
        policy = PriorPolicy(max_age_days=max_age_days)
        deadline = _OBSERVATION_TIME.timestamp() + timedelta(days=max_age_days).total_seconds()
        lookup = store.lookup_prior(_KEY, "training", now=deadline + offset, policy=policy)
        assert lookup.status == expected
        assert lookup.prior_unit_ms == pytest.approx(40.0)  # stale remains usable

    def test_env_mismatch_never_cross_applied(self, tmp_path):
        store = ObservationStore(str(tmp_path))
        store.append(_observation(actual_seconds=40.0), writer_id="c")
        assert (
            store.lookup_prior(
                _KEY, "training", now=_LOOKUP_TIME, current_gpu_name="RTX 5090"
            ).status
            == "env_mismatch"
        )
        assert (
            store.lookup_prior(
                _KEY, "training", now=_LOOKUP_TIME, current_torch_version="3.0.0"
            ).status
            == "env_mismatch"
        )
        assert (
            store.lookup_prior(
                _KEY,
                "training",
                now=_LOOKUP_TIME,
                current_gpu_name="NVIDIA H100",
                current_torch_version="2.6.0",
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
                    timestamp=(_OBSERVATION_TIME + timedelta(seconds=i)).isoformat(),
                ),
                writer_id="c",
            )
        assert store.lookup_prior(_KEY, "training", now=_LOOKUP_TIME).status == "valid"
        strict = PriorPolicy(contract_factor=1.2)
        assert (
            store.lookup_prior(_KEY, "training", now=_LOOKUP_TIME, policy=strict).status
            == "evicted_drift"
        )
        assert math.log(40.0 / 30.0) > math.log(1.2)  # scenario sanity


def test_storage_evidence_does_not_change_prior_or_calibration_identity(tmp_path):
    """#419: unknown cache provenance must not fork or suppress throughput reuse."""
    original = _observation(actual_seconds=40.0).model_copy(
        update={"storage": {"cache_state": "warm_page_cache"}}
    )
    changed = original.model_copy(
        update={
            "storage": {
                "cache_state": "unknown",
                "process_read_bytes_scope": "incomplete",
                "cache_state_unknown_reason": "reader runs elsewhere",
            }
        }
    )
    identity = IdentityContext(
        task_identity="synthetic",
        data_shape_class="vector",
        hardware_uuid="fixture-device",
        runtime_stack_identity="fixture-stack",
    )
    assert observation_calibration_key(original, "training") == _KEY
    assert observation_calibration_key(changed, "training") == _KEY
    assert component_calibration_eligible(changed, "training")
    assert derive_duration_calibration_record(original, "training", identity=identity) == (
        derive_duration_calibration_record(changed, "training", identity=identity)
    )
    priors = []
    for name, observation in (("before", original), ("after", changed)):
        store = ObservationStore(str(tmp_path / name))
        store.append(observation, writer_id="fixture")
        priors.append(store.lookup_prior(_KEY, "training", now=_LOOKUP_TIME))
    assert priors[0] == priors[1]
    assert priors[1].prior_unit_ms == 40.0


@pytest.mark.parametrize("zone", ["UTC", "America/Los_Angeles", "Asia/Shanghai"])
def test_offset_age_and_expiry_are_independent_of_host_timezone(tmp_path, zone):
    """Exercise persisted observations in isolated host-timezone processes."""
    import json
    import os
    import subprocess
    import sys
    import time

    if not hasattr(time, "tzset"):
        pytest.skip("host timezone isolation requires time.tzset")

    script = """
import json, sys, time
from datetime import datetime
from pathlib import Path
from core.runtime_control.observation_store import ObservationStore, PriorPolicy, _age_seconds, observation_calibration_key
from core.runtime_control.records import RuntimeObservation

time.tzset()
payload = json.load(sys.stdin)
now = datetime.fromisoformat("2026-07-23T12:00:00+00:00").timestamp()
offsets = ["2026-07-23T12:00:00+0000", "2026-07-23T05:00:00-0700",
           "2026-07-23T20:00:00+0800", "2026-07-23T17:30:00+05:30",
           "2026-07-23T12:00:00Z"]
results = []
for index, timestamp in enumerate(offsets):
    observation = RuntimeObservation.model_validate(dict(payload, timestamp=timestamp))
    store = ObservationStore(str(Path(sys.argv[1]) / str(index)))
    store.append(observation, writer_id="offset-test")
    key = observation_calibration_key(observation, "training")
    statuses = []
    for days in (0.5, 90):
        for delta in (-1, 0, 1):
            lookup = store.lookup_prior(key, "training", policy=PriorPolicy(max_age_days=days),
                                        now=now + days * 86400 + delta)
            statuses.append(lookup.status)
            assert lookup.prior_unit_ms == 40.0
    results.append([_age_seconds(timestamp, now=now), statuses])
naive = "2026-07-23T12:00:00"
local_epoch = time.mktime(time.strptime(naive, "%Y-%m-%dT%H:%M:%S"))
assert _age_seconds(naive, now=local_epoch + 60) == 60
assert _age_seconds("not-a-timestamp", now=now) is None
assert _age_seconds(offsets[0], now=now - 1) == -1
print(json.dumps(results))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        input=_observation().model_dump_json(),
        text=True,
        capture_output=True,
        env={**os.environ, "TZ": zone},
        check=True,
        timeout=30,
    )
    expected = [0.0, ["valid", "valid", "stale"] * 2]
    assert json.loads(result.stdout) == [expected] * 5


@pytest.mark.parametrize("parsed", [None, float("nan"), float("inf"), -float("inf")])
def test_unknown_or_nonfinite_provider_timestamp_never_yields_valid_prior(tmp_path, parsed):
    store = ObservationStore(str(tmp_path))
    store.append(_observation(), writer_id="fixture")
    lookup = store.lookup_prior(
        _KEY, "training", now=_LOOKUP_TIME, timestamp_parser=lambda timestamp: parsed
    )
    assert lookup.status == "stale"
