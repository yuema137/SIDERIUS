"""
RT2-C unit tests: AdaptiveUnitVerification over deterministic synthetic
traces (§2.5 B1/B2, §2.11, §2.12).

Scenario matrix from the design's validation plan (§8 "Steady state" +
"Training verification"): slow startup transient, fast-start drift
(re-arm), jitter, no steady state, pathological unit, prior
match/drift/absence, caps, finalize paths.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from core.runtime_control.adaptive import (
    AdaptiveUnitVerification,
    AdaptiveVerificationConfig,
)
from core.runtime_control.steady_state import SteadyStateConfig
from core.runtime_control.workload import ResolvedPhaseWorkload

# Small, fast detection for tests: window 4 + 3 stable windows.
_STEADY = SteadyStateConfig(window=4, stable_windows=3, rel_spread_tol=0.10, max_steps=100)


def _config(**overrides) -> AdaptiveVerificationConfig:
    defaults = dict(
        steady=_STEADY,
        min_timed_steps=5,
        min_timed_ms=0.0,
        max_steps=100,
        max_wall_ms=1e9,
        pathological_factor=10.0,
    )
    defaults.update(overrides)
    return AdaptiveVerificationConfig(**defaults)


def _feed_until_terminal(verifier: AdaptiveUnitVerification, trace: list[float]) -> str:
    for t in trace:
        state = verifier.feed(t)
        if verifier.is_terminal:
            return state
    return verifier.state


_WORKLOAD = ResolvedPhaseWorkload(phase="training", unit="optimizer_step", unit_count=1000)


class TestHappyPath:
    def test_clean_trace_verifies_with_median_prediction(self):
        v = AdaptiveUnitVerification("optimizer_step", _config())
        state = _feed_until_terminal(v, [10.0] * 30)
        assert state == "verified"
        pred = v.prediction(_WORKLOAD, "real_training_verification")
        assert pred is not None
        assert pred.formal_execution_eligible is True
        assert pred.ms_per_unit == pytest.approx(10.0)
        assert pred.predicted_seconds == pytest.approx(1000 * 10.0 / 1000.0)
        assert pred.confidence == "high"  # zero MAD, full evidence

    def test_not_verified_on_stability_alone(self):
        # §2.5: early exit never on B1 stability alone — the declaration
        # must survive min_timed_steps of B2 measurement.
        cfg = _config(min_timed_steps=50)
        v = AdaptiveUnitVerification("optimizer_step", cfg)
        for t in [10.0] * 20:
            v.feed(t)
        assert v.state == "measuring"
        assert not v.is_terminal

    def test_min_timed_ms_gates_fast_units(self):
        cfg = _config(min_timed_ms=1000.0)  # 10ms units → needs ~100 steady
        v = AdaptiveUnitVerification("optimizer_step", cfg)
        _feed_until_terminal(v, [10.0] * 50)
        assert v.state == "measuring"
        _feed_until_terminal(v, [10.0] * 60)
        assert v.state == "verified"

    def test_slow_units_verify_with_few_observations(self):
        # §2.5: for very slow units a few observations suffice —
        # min_timed_ms is satisfied almost immediately.
        cfg = _config(min_timed_ms=1000.0, min_timed_steps=2)
        v = AdaptiveUnitVerification("optimizer_step", cfg)
        state = _feed_until_terminal(v, [5000.0] * 10)
        assert state == "verified"
        assert v.verification_seconds < 60.0

    def test_leading_transient_excluded_from_prediction(self):
        # RT2a finding (a): step 0 at 82x must never feed the prediction.
        v = AdaptiveUnitVerification("optimizer_step", _config())
        state = _feed_until_terminal(v, [2000.0] + [10.0] * 30)
        assert state == "verified"
        pred = v.prediction(_WORKLOAD, "real_training_verification")
        assert pred is not None
        assert pred.ms_per_unit == pytest.approx(10.0)


class TestDriftAndFailure:
    def test_fast_start_drift_rearms_and_redeclares(self):
        # RT2a finding (b): fast start (8 ms) declared steady, drifts to
        # the true 29 ms plateau DURING B2 measurement → the declaration
        # must not survive; detection re-arms and re-declares at 29 ms.
        # (The fast phase is deliberately shorter than the B2 minimum so
        # the drift lands inside the measurement window.)
        v = AdaptiveUnitVerification("optimizer_step", _config(min_timed_steps=8))
        trace = [8.0] * 5 + [29.0] * 40
        state = _feed_until_terminal(v, trace)
        assert state == "verified"
        pred = v.prediction(_WORKLOAD, "real_training_verification")
        assert pred is not None
        assert pred.ms_per_unit == pytest.approx(29.0, rel=0.05)

    def test_no_steady_state_hits_step_cap(self):
        cfg = _config(max_steps=30)
        v = AdaptiveUnitVerification("optimizer_step", cfg)
        # Geometric ramp: relative spread of rolling medians stays wide.
        trace = [10.0 * (1.2**i) for i in range(40)]
        state = _feed_until_terminal(v, trace)
        assert state == "failed_no_steady_state"
        assert v.failure_reason is not None and "no steady state" in v.failure_reason

    def test_wall_cap_terminates(self):
        cfg = _config(max_wall_ms=100.0, max_steps=100)
        v = AdaptiveUnitVerification("optimizer_step", cfg)
        state = _feed_until_terminal(v, [60.0 * (1.5**i) for i in range(20)])
        assert state == "failed_no_steady_state"

    def test_pathological_relative_unit_during_measurement(self):
        cfg = _config(min_timed_ms=1000.0)  # keeps it measuring
        v = AdaptiveUnitVerification("optimizer_step", cfg)
        for t in [10.0] * 20:
            v.feed(t)
        assert v.state == "measuring"
        for _ in range(cfg.steady.stable_windows - 1):
            assert not v.feed(200.0).startswith("failed")
        assert v.feed(200.0) == "failed_pathological_unit"  # sustained > 10x median
        assert v.failure_reason is not None and "pathological" in v.failure_reason

    def test_pathological_absolute_threshold(self):
        cfg = _config(min_timed_ms=1000.0, max_unit_ms=50.0)
        v = AdaptiveUnitVerification("optimizer_step", cfg)
        for t in [10.0] * 20:
            v.feed(t)
        # 60ms < 10x median (100ms) but > absolute 50ms threshold (§5).
        assert v.feed(60.0) == "failed_pathological_unit"

    def test_transient_never_pathological(self):
        # The 82x warm-up transient must not trip the pathological rule.
        cfg = _config(max_unit_ms=500.0)
        v = AdaptiveUnitVerification("optimizer_step", cfg)
        state = _feed_until_terminal(v, [2000.0] + [10.0] * 30)
        assert state == "verified"

    def test_failed_verification_yields_no_prediction(self):
        cfg = _config(max_steps=30)
        v = AdaptiveUnitVerification("optimizer_step", cfg)
        _feed_until_terminal(v, [10.0 * (1.2**i) for i in range(40)])
        assert v.prediction(_WORKLOAD, "real_training_verification") is None
        m = v.measurement()
        assert m is not None and m.steady_state_reached is False


class TestPriorComparison:
    def test_no_prior_is_new_configuration(self):
        v = AdaptiveUnitVerification("optimizer_step", _config())
        _feed_until_terminal(v, [10.0] * 30)
        assert v.prior_agreement == "new_configuration"

    def test_matching_prior_verified_match(self):
        v = AdaptiveUnitVerification("optimizer_step", _config(), prior_expected_unit_ms=11.0)
        _feed_until_terminal(v, [10.0] * 30)
        assert v.prior_agreement == "verified_match"
        pred = v.prediction(_WORKLOAD, "real_training_verification")
        assert pred is not None
        assert pred.prior_agreement_ratio == pytest.approx(10.0 / 11.0)

    def test_drifting_prior_extends_measurement(self):
        base = _config(min_timed_steps=6, drift_extra_factor=2.0)
        match = AdaptiveUnitVerification("optimizer_step", base, prior_expected_unit_ms=10.0)
        drift = AdaptiveUnitVerification("optimizer_step", base, prior_expected_unit_ms=3.0)
        trace = [10.0] * 60
        match_steps = drift_steps = None
        for i, t in enumerate(trace):
            if match_steps is None and match.feed(t) == "verified":
                match_steps = i + 1
            if match.is_terminal and match_steps is None:
                match_steps = i + 1
        for i, t in enumerate(trace):
            if drift.is_terminal:
                break
            if drift.feed(t) == "verified":
                drift_steps = i + 1
                break
        assert drift.prior_agreement == "verified_drift"
        assert match_steps is not None and drift_steps is not None
        assert drift_steps > match_steps  # extended measurement (§2.5)

    def test_invalid_prior_rejected(self):
        with pytest.raises(ValueError, match="prior_expected_unit_ms"):
            AdaptiveUnitVerification("optimizer_step", _config(), prior_expected_unit_ms=0.0)


class TestLifecycleContracts:
    def test_feed_after_terminal_raises(self):
        v = AdaptiveUnitVerification("optimizer_step", _config())
        _feed_until_terminal(v, [10.0] * 30)
        assert v.is_terminal
        with pytest.raises(RuntimeError, match="terminal"):
            v.feed(10.0)

    def test_finalize_detected_but_insufficient(self):
        cfg = _config(min_timed_steps=50)
        v = AdaptiveUnitVerification("optimizer_step", cfg)
        for t in [10.0] * 20:
            v.feed(t)
        assert v.finalize() == "failed_no_steady_state"
        assert v.failure_reason is not None and "insufficient_stability" in v.failure_reason

    def test_insufficient_reason_names_the_minimum_that_actually_failed(self):
        """Step 09.5a Gate-2 forensics (2026-08-20).

        Defect only this test catches: a diagnostic that reports a SATISFIED
        condition as the failure. The Gate's validation phase reported
        "26 steady observations, required 5" — which reads as a contradiction
        — while the real violation was the steady TIME floor. A reader who
        trusts that message investigates the wrong subsystem, and nothing else
        in the suite compares the message against which condition failed.

        Fails when the message stops distinguishing the two minimums: the
        count is deliberately satisfied here and the time floor deliberately
        is not.
        """
        cfg = _config(min_timed_steps=5, min_timed_ms=500.0, max_steps=30)
        v = AdaptiveUnitVerification("validation_sample", cfg)
        for t in [3.0] * 30:  # 30 x 3 ms = 90 ms total — far under 500 ms
            v.feed(t)
        assert v.finalize() == "failed_no_steady_state"
        reason = v.failure_reason
        assert reason is not None
        assert "unmet: steady_time_or_fast_count" in reason, reason
        assert "steady_count" not in reason.split("unmet:")[1].split(";")[0], reason
        assert "required 500.0 ms" in reason, reason
        assert "stable fast-phase suffix of 100 observations" in reason, reason

    def test_insufficient_reason_names_the_count_when_that_is_what_failed(self):
        """The other side of the same discrimination — anti-vacuity for the
        test above, which would pass a message that always said
        ``steady_time``."""
        cfg = _config(min_timed_steps=50, min_timed_ms=0.0)
        v = AdaptiveUnitVerification("optimizer_step", cfg)
        for t in [10.0] * 20:
            v.feed(t)
        assert v.finalize() == "failed_no_steady_state"
        reason = v.failure_reason
        assert reason is not None
        assert "unmet: steady_count" in reason, reason
        assert "steady_time" not in reason.split("unmet:")[1].split(";")[0], reason

    def test_finalize_empty_trace(self):
        v = AdaptiveUnitVerification("optimizer_step", _config())
        assert v.finalize() == "failed_no_steady_state"
        assert v.measurement() is None

    def test_finalize_after_verified_is_stable(self):
        v = AdaptiveUnitVerification("optimizer_step", _config())
        _feed_until_terminal(v, [10.0] * 30)
        assert v.finalize() == "verified"

    def test_nonpositive_unit_rejected(self):
        v = AdaptiveUnitVerification("optimizer_step", _config())
        with pytest.raises(ValueError, match="positive"):
            v.feed(0.0)

    def test_config_caps_must_allow_detection(self):
        with pytest.raises(ValueError, match="cannot accommodate"):
            AdaptiveVerificationConfig(steady=_STEADY, min_timed_steps=5, max_steps=6)


class TestPredictionShape:
    def test_extra_seconds_are_explicit_additive_term(self):
        v = AdaptiveUnitVerification("optimizer_step", _config())
        _feed_until_terminal(v, [10.0] * 30)
        pred = v.prediction(
            _WORKLOAD,
            "real_training_verification",
            extra_predicted_seconds=7.5,
            extra_detail={"epoch0_dataset_seconds": 2.5},
        )
        assert pred is not None
        assert pred.predicted_seconds == pytest.approx(10.0 + 7.5)
        assert pred.detail["extra_predicted_seconds"] == 7.5
        assert pred.detail["epoch0_dataset_seconds"] == 2.5

    def test_measurement_counts_stabilization_vs_steady(self):
        v = AdaptiveUnitVerification("optimizer_step", _config())
        _feed_until_terminal(v, [2000.0] + [10.0] * 30)
        m = v.measurement()
        assert m is not None
        assert m.steady_state_reached is True
        assert m.n_stabilization_units >= 1  # the trimmed transient
        assert m.n_measured_units + m.n_stabilization_units == len(m.raw_timings_ms)


def test_normalized_batch_rate_does_not_shrink_observed_wall_time():
    """Incident 2026-09-18: dividing validation timings by batch size hid evidence."""
    verifier = AdaptiveUnitVerification(
        "validation_sample", _config(min_timed_ms=500, max_wall_ms=10000)
    )
    for _ in range(30):
        verifier.feed(1.0, elapsed_ms=100.0)
        if verifier.is_terminal:
            break
    assert verifier.state == "verified"
    measurement = verifier.measurement()
    assert measurement is not None
    assert measurement.unit_time_ms_median == 1.0
    assert measurement.total_measurement_seconds >= 0.5
    workload = ResolvedPhaseWorkload(phase="validation", unit="validation_sample", unit_count=1000)
    prediction = verifier.prediction(workload, "real_validation_verification")
    assert prediction is not None
    assert prediction.predicted_seconds == 1.0


@pytest.mark.parametrize(
    ("batch_size", "median_batch_ms"),
    [(16, 1.6), (64, 0.36), (64, 2.55), (128, 1.2)],
)
def test_fast_heterogeneous_batches_verify_without_500ms_wall_time(batch_size, median_batch_ms):
    """Issue #565: faster hardware and varied batch sizes remain verifiable.

    Defect caught only here: heterogeneous fast observations repeatedly re-arm
    the relative-only detector, while 500 ms of evidence is unattainable inside
    the observation cap. The fallback must use a stable distribution suffix and
    retain the normalized rate at different physical scales and batch sizes.
    """
    rng = random.Random(batch_size + round(median_batch_ms * 100))
    batch_times_ms = [rng.uniform(0.4, 1.6) * median_batch_ms for _ in range(200)]
    verifier = AdaptiveUnitVerification("validation_sample", AdaptiveVerificationConfig())

    for batch_ms in batch_times_ms:
        state = verifier.feed(batch_ms / batch_size, elapsed_ms=batch_ms)
        if verifier.is_terminal:
            break

    assert state == "verified"
    measurement = verifier.measurement()
    assert measurement is not None
    assert measurement.n_measured_units >= 100
    assert measurement.total_measurement_seconds < 0.5
    assert measurement.detail["stability_evidence"] == "fast_distribution_suffix"
    assert measurement.detail["fast_phase_suffix_status"] == "accepted"
    prediction = verifier.prediction(
        ResolvedPhaseWorkload(phase="validation", unit="validation_sample", unit_count=442),
        "real_validation_verification",
    )
    assert prediction is not None
    assert 0.4 * median_batch_ms / batch_size <= prediction.ms_per_unit
    assert prediction.ms_per_unit <= 1.6 * median_batch_ms / batch_size


def test_submillisecond_count_path_still_rejects_sustained_pathological_slowdown():
    """Issue #565's permissive fast path must retain the slowdown fail-closed gate."""
    cfg = AdaptiveVerificationConfig(fast_phase_min_observations=100)
    verifier = AdaptiveUnitVerification("validation_sample", cfg)
    for _ in range(30):
        verifier.feed(0.005, elapsed_ms=0.32)
    assert verifier.state == "measuring"

    for _ in range(cfg.steady.stable_windows - 1):
        assert verifier.feed(0.075, elapsed_ms=4.8) != "failed_pathological_unit"
    assert verifier.feed(0.075, elapsed_ms=4.8) == "failed_pathological_unit"


def test_fast_distribution_suffix_does_not_accept_a_monotonic_trend():
    """The fast fallback distinguishes many noisy samples from a stable suffix.

    This fails if the implementation treats count alone as evidence: the
    observation count reaches 100, but the later-half median is materially
    above the earlier half and must not become a prediction.
    """
    verifier = AdaptiveUnitVerification("sample", AdaptiveVerificationConfig())
    for i in range(200):
        elapsed_ms = 0.1 * (1.01**i)
        verifier.feed(elapsed_ms, elapsed_ms=elapsed_ms)
        if verifier.is_terminal:
            break

    if not verifier.is_terminal:
        verifier.finalize()
    assert verifier.state == "failed_no_steady_state"
    assert "fast-phase suffix: distribution_drift:" in (verifier.failure_reason or "")
    assert verifier.prediction(_WORKLOAD, "real_training_verification") is None


@pytest.mark.parametrize(
    "phase, expected_observations, expected_median_ms",
    [("training", 99, 8.528033504262567), ("inference", 186, 2.722682023886591)],
)
def test_successful_tidmad_trace_keeps_legacy_verdict_and_measurement(
    phase, expected_observations, expected_median_ms
):
    """Issue #565 must not change the accepted slow-regime TIDMAD evidence.

    This replays a production H100 receipt. It fails if the fast-count path
    activates where 500 ms still fits inside the normal 200-observation cap,
    or if wall-time stability changes the retained normalized measurement.
    """
    fixture = Path(__file__).parent / "fixtures" / "runtime_observation_wave1_formal.json"
    payload = json.loads(fixture.read_text())
    raw = payload["components"][phase]["measurement"]["raw_timings_ms"]
    verifier = AdaptiveUnitVerification(f"{phase}_unit", AdaptiveVerificationConfig())

    for observed_ms in raw:
        verifier.feed(observed_ms)
        if verifier.is_terminal:
            break

    assert verifier.state == "verified"
    measurement = verifier.measurement()
    assert measurement is not None
    assert len(measurement.raw_timings_ms) == expected_observations
    assert measurement.unit_time_ms_median == pytest.approx(expected_median_ms)


def test_normalized_rate_cannot_bypass_measurement_wall_cap():
    verifier = AdaptiveUnitVerification(
        "validation_sample", _config(min_timed_ms=500, max_wall_ms=50)
    )
    verifier.feed(0.1, elapsed_ms=60)
    assert verifier.is_terminal
    assert verifier.verification_seconds == pytest.approx(0.06)


@pytest.mark.parametrize("unit_ms,batch", [(0.25, 1), (2.0, 1), (0.02, 16), (40.0, 1)])
def test_fast_stable_phases_collect_the_same_evidence_time(unit_ms, batch):
    """Fast phases may satisfy either the wall-time or observation evidence floor."""
    verifier = AdaptiveUnitVerification("sample", AdaptiveVerificationConfig())
    for _ in range(5000):
        if verifier.feed(unit_ms, elapsed_ms=unit_ms * batch) == "verified":
            break
        assert not verifier.is_terminal
    assert verifier.state == "verified"
    measurement = verifier.measurement()
    assert measurement is not None
    assert measurement.total_measurement_seconds >= 0.5 or measurement.n_measured_units >= 100


@pytest.mark.parametrize("unit_ms", [0.05, 2.0, 80.0])
def test_isolated_relative_delay_is_recorded_without_failure(unit_ms):
    """A single scheduling/I/O spike cannot establish persistent pathological speed."""
    cfg = _config(min_timed_ms=unit_ms * 200, max_wall_ms=unit_ms * 1000)
    verifier = AdaptiveUnitVerification("sample", cfg)
    for _ in range(20):
        verifier.feed(unit_ms)
    assert verifier.feed(unit_ms * 20) != "failed_pathological_unit"
    for _ in range(400):
        if verifier.is_terminal:
            break
        verifier.feed(unit_ms)
    assert verifier.state == "verified"
    assert verifier.measurement().detail["relative_slow_observation_indices"] == [20]


def test_fast_phase_extension_still_obeys_time_cap():
    """Stable extension must not turn an impossible time floor into unbounded sampling."""
    cfg = _config(max_steps=30, min_timed_ms=500, max_wall_ms=90)
    verifier = AdaptiveUnitVerification("sample", cfg)
    state = _feed_until_terminal(verifier, [1.0] * 600)
    assert state == "failed_no_steady_state"
    assert len(verifier.measurement().raw_timings_ms) <= 100


def test_pending_slow_observation_explains_rejection_with_satisfied_minimums():
    """2026-09-19 V4: count/time passed, but the diagnostic reported unmet:none."""
    cfg = _config(min_timed_ms=40, max_steps=21)
    verifier = AdaptiveUnitVerification("sample", cfg)
    for _ in range(20):
        assert not verifier.is_terminal
        verifier.feed(1.0)
    # A single final delay supplies enough wall time but requires a recovery
    # observation. The existing cap ends the probe before recovery is seen.
    assert verifier.feed(30.0) == "failed_no_steady_state"
    reason = verifier.failure_reason or ""
    assert "unmet: pending_slow_observation;" in reason
    assert "pending slow streak=1, sustained threshold=3" in reason
    assert "unmet: none" not in reason
    assert verifier.prediction(_WORKLOAD, "real_training_verification") is None


def test_fast_extension_stops_on_local_wall_time(monkeypatch):
    """Verifier CPU overhead also bounds tiny-unit traces, not just reported GPU time."""
    now = [0.0]
    monkeypatch.setattr("core.runtime_control.adaptive.time.monotonic", lambda: now[0])
    cfg = _config(max_steps=30, min_timed_ms=500, max_wall_ms=1000)
    verifier = AdaptiveUnitVerification("sample", cfg)
    for _ in range(40):
        assert not verifier.feed(0.1).startswith("failed")
    now[0] = 1.1
    assert verifier.feed(0.1) == "failed_no_steady_state"


def test_final_observation_cannot_verify_after_wall_deadline(monkeypatch):
    """Review regression: reaching evidence floors must not bypass the wall cap."""
    now = [0.0]
    monkeypatch.setattr("core.runtime_control.adaptive.time.monotonic", lambda: now[0])
    verifier = AdaptiveUnitVerification("sample", _config(min_timed_ms=1000, max_wall_ms=2000))
    while verifier._steady_elapsed_ms() < 990:
        assert not verifier.is_terminal
        verifier.feed(10)
    assert not verifier.is_terminal
    now[0] = 3.0
    assert verifier.feed(10) == "failed_no_steady_state"
    assert "wall-time cap exhausted" in verifier.failure_reason


def test_active_interval_exception_preserves_evidence_and_pauses(monkeypatch):
    """An aborted pass must not leave its clock running during unrelated work."""
    from types import SimpleNamespace

    import core.runtime_control.adaptive as module

    clock = [100.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    v = AdaptiveUnitVerification("validation_sample", _config(min_timed_ms=500, max_wall_ms=60000))
    with pytest.raises(ValueError, match="pass failed"):
        with v.active_interval():
            for _ in range(30):
                clock[0] += 0.006
                v.feed(0.75, elapsed_ms=6)
            raise ValueError("pass failed")
    clock[0] += 600
    with pytest.raises(RuntimeError, match="paused"):
        v.feed(0.75, elapsed_ms=6)
    with v.active_interval():
        for _ in range(70):
            clock[0] += 0.006
            v.feed(0.75, elapsed_ms=6)
            if v.is_terminal:
                break
    assert v.state == "verified"
    assert v.measurement().detail["verification_excluded_inactive_seconds"] == pytest.approx(600)


def test_continuous_verification_still_counts_wall_gaps(monkeypatch):
    """Unscoped training callers must retain protection against real stalls."""
    from types import SimpleNamespace

    import core.runtime_control.adaptive as module

    clock = [100.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    v = AdaptiveUnitVerification("optimizer_step", _config(max_wall_ms=60000))
    v.feed(1)
    clock[0] += 61
    v.feed(1)
    assert v.state == "failed_no_steady_state"
    assert "wall-time cap exhausted" in v.failure_reason
