"""
RT2-C unit tests: AdaptiveUnitVerification over deterministic synthetic
traces (§2.5 B1/B2, §2.11, §2.12).

Scenario matrix from the design's validation plan (§8 "Steady state" +
"Training verification"): slow startup transient, fast-start drift
(re-arm), jitter, no steady state, pathological unit, prior
match/drift/absence, caps, finalize paths.
"""

from __future__ import annotations

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
        assert v.feed(200.0) == "failed_pathological_unit"  # > 10x median
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
        assert "unmet: steady_time" in reason, reason
        assert "steady_count" not in reason.split("unmet:")[1].split(";")[0], reason
        assert "required 500.0 ms" in reason, reason

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
