"""RT2a — adaptive steady-state detection + structured RuntimePrediction.

Design: docs/design/runtime_estimation_and_watchdog.md §2/§2b (rev 4 +
RT2 kickoff). Synthetic traces model the empirically observed shapes:
slow first steps (CUDA context init, autotune, kernel compilation,
clock ramp) decaying into a jittery plateau.
"""

from __future__ import annotations

import random
import statistics
from typing import ClassVar

import pytest
from pydantic import ValidationError

from core.runtime_control.records import RuntimePrediction
from core.runtime_control.steady_state import (
    SteadyStateConfig,
    SteadyStateDetector,
    detect_steady_state,
)


def _plateau_trace(
    n_warm: int, n_flat: int, warm_start: float, flat: float, jitter: float, seed: int = 0
) -> list[float]:
    """Geometric decay from warm_start to flat over n_warm steps, then a
    jittery plateau — the shape real GPU warm-up traces take."""
    rng = random.Random(seed)
    trace = []
    for i in range(n_warm):
        frac = i / max(1, n_warm)
        trace.append(flat + (warm_start - flat) * (1 - frac) ** 2)
    for _ in range(n_flat):
        trace.append(flat * (1 + rng.uniform(-jitter, jitter)))
    return trace


class TestDetection:
    def test_ramp_then_plateau_detected_after_ramp(self):
        trace = _plateau_trace(n_warm=25, n_flat=60, warm_start=400.0, flat=44.0, jitter=0.03)
        det = detect_steady_state(trace)
        assert det.reached and det.reason == "stable_spread"
        # Steady region must exclude the strongly-transient early ramp…
        assert det.steady_from_step >= 10
        # …and the steady median must reflect the plateau, not the ramp.
        assert det.steady_median_ms == pytest.approx(44.0, rel=0.06)

    def test_flat_from_start_detects_at_minimum_steps(self):
        cfg = SteadyStateConfig()
        detector = SteadyStateDetector(cfg)
        n_fed = 0
        while not detector.observe(10.0):
            n_fed += 1
        # observe() count includes the detecting step.
        assert n_fed + 1 == cfg.min_steps_to_detect
        det = detector.result()
        assert det.reached
        assert det.steady_from_step == 0
        assert det.steady_median_ms == pytest.approx(10.0)
        assert det.steady_mad_ms == pytest.approx(0.0)

    def test_monotonic_ramp_never_declared_steady(self):
        # 20%/step growth keeps rolling medians drifting apart — a
        # detector that assumed "N steps then steady" would be fooled.
        trace = [10.0 * (1.2**i) for i in range(60)]
        det = detect_steady_state(trace, SteadyStateConfig(max_steps=60))
        assert not det.reached
        assert det.reason == "budget_exhausted"
        assert det.steady_from_step is None and det.steady_median_ms is None

    def test_heavy_jitter_beyond_tolerance_not_declared(self):
        rng = random.Random(1)
        trace = [30.0 * (1 + rng.uniform(-0.6, 0.6)) for _ in range(80)]
        det = detect_steady_state(
            trace, SteadyStateConfig(window=4, rel_spread_tol=0.02, max_steps=80)
        )
        assert not det.reached

    def test_leading_spike_trimmed_from_steady_region(self):
        """Observed on the H100: step 0 at 2307 ms vs a 28 ms plateau.
        The rolling median absorbs the spike (detection is undisturbed)
        but the transient step must be TRIMMED from the steady region."""
        trace = [2307.4] + [28.0] * 30
        det = detect_steady_state(trace)
        assert det.reached
        assert det.steady_from_step == 1  # spike excluded
        assert det.steady_median_ms == pytest.approx(28.0)

    def test_jitter_within_tolerance_declared(self):
        trace = _plateau_trace(n_warm=0, n_flat=40, warm_start=0.0, flat=20.0, jitter=0.02)
        det = detect_steady_state(trace)
        assert det.reached

    def test_short_trace_reports_insufficient_steps(self):
        cfg = SteadyStateConfig()
        det = detect_steady_state([5.0] * (cfg.min_steps_to_detect - 1), cfg)
        assert not det.reached and det.reason == "insufficient_steps"

    def test_budget_bounds_detection_not_extension(self):
        # Not steady within max_steps → budget_exhausted even though the
        # trace stabilises later (the online loop would have stopped).
        trace = [10.0 * (1.5**i) for i in range(30)] + [40.0] * 100
        det = detect_steady_state(trace, SteadyStateConfig(max_steps=20))
        assert not det.reached and det.reason == "budget_exhausted"
        assert det.steps_observed == 20


class TestOnlineDetector:
    def test_online_matches_offline(self):
        trace = _plateau_trace(n_warm=15, n_flat=40, warm_start=200.0, flat=30.0, jitter=0.04)
        offline = detect_steady_state(trace)
        detector = SteadyStateDetector()
        for t in trace:
            detector.observe(t)
        online = detector.result()
        assert online.reached == offline.reached
        assert online.steady_from_step == offline.steady_from_step

    def test_post_detection_same_level_extends_steady_region(self):
        detector = SteadyStateDetector()
        cfg = detector.config
        for _ in range(cfg.min_steps_to_detect):
            detector.observe(10.0)
        assert detector.detected
        for _ in range(20):  # phase-2 timed loop reuses the detector
            detector.observe(10.3)  # within rel_spread_tol of the level
        assert detector.detected
        steady = detector.steady_times_ms()
        assert len(steady) == cfg.min_steps_to_detect + 20
        assert detector.result().steady_median_ms == pytest.approx(statistics.median(steady))

    def test_post_detection_drift_rearms_and_redeclares_at_new_plateau(self):
        """Observed on the H100: a run can start fast (boosted clocks,
        cached kernels, ~8 ms/step), satisfy the stability criterion,
        then drift up to its true sustained plateau (~29 ms/step). The
        phase-2 loop must catch the drift (re-arm) and re-declare at the
        new level — an early-exit that trusted the first declaration
        would underpredict ~3x."""
        detector = SteadyStateDetector()
        cfg = detector.config
        for _ in range(cfg.min_steps_to_detect):
            detector.observe(8.0)
        assert detector.detected  # premature declaration at the fast level
        for t in [10.0, 12.0, 15.0, 19.0, 23.0, 26.0, 28.0]:  # upward drift
            detector.observe(t)
        assert not detector.detected  # drift re-armed detection
        while not detector.observe(29.0):
            pass  # re-declares once the true plateau stabilises
        det = detector.result()
        assert det.reached
        # The steady region must reflect the sustained plateau, not the
        # premature fast level.
        assert det.steady_median_ms == pytest.approx(29.0, rel=0.05)

    def test_non_positive_step_time_raises(self):
        with pytest.raises(ValueError, match="positive"):
            SteadyStateDetector().observe(0.0)

    def test_config_budget_must_allow_detection(self):
        with pytest.raises(ValidationError):
            SteadyStateConfig(window=8, stable_windows=4, max_steps=5)


class TestRuntimePredictionContract:
    """Rev-4 admission invariant is enforced by the schema itself."""

    _MEASURED: ClassVar[dict] = dict(
        predicted_seconds=2520.0,
        source="real_dataset_warmup",
        formal_execution_eligible=True,
        steady_state=True,
        verification="passed",
        confidence="high",
        ms_per_unit=44.3,
        n_steady_units=50,
        unit_count=480_000,
        safety_factor=1.5,
    )

    def test_verified_warmup_prediction_is_formal_eligible(self):
        p = RuntimePrediction(**self._MEASURED)
        assert p.formal_execution_eligible
        assert p.predicted_minutes == pytest.approx(42.0)

    def test_static_source_cannot_be_formal_eligible(self):
        with pytest.raises(ValidationError, match="admission"):
            RuntimePrediction(**{**self._MEASURED, "source": "static_uncalibrated"})

    def test_failed_verification_cannot_be_formal_eligible(self):
        with pytest.raises(ValidationError, match="admission"):
            RuntimePrediction(**{**self._MEASURED, "verification": "failed"})

    def test_non_steady_measurement_cannot_be_formal_eligible(self):
        with pytest.raises(ValidationError, match="steady_state"):
            RuntimePrediction(**{**self._MEASURED, "steady_state": False})

    def test_missing_measurement_provenance_cannot_be_formal_eligible(self):
        with pytest.raises(ValidationError, match="provenance"):
            RuntimePrediction(**{**self._MEASURED, "ms_per_unit": None})

    def test_static_screen_prediction_is_valid_but_ineligible(self):
        p = RuntimePrediction(
            predicted_seconds=1248.0,
            source="static_uncalibrated",
            formal_execution_eligible=False,
            steady_state=False,
            verification="not_attempted",
            confidence="low",
            safety_factor=1.3,
        )
        assert not p.formal_execution_eligible

    def test_prior_fields_must_come_together(self):
        with pytest.raises(ValidationError, match="together"):
            RuntimePrediction(**{**self._MEASURED, "prior_agreement_ratio": 1.05})
