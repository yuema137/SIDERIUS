"""Late evidence, noisy slowdown and retained prediction-window regressions."""

import random

import pytest

from core.runtime_control.adaptive import AdaptiveUnitVerification, AdaptiveVerificationConfig


def finish(verifier, rates):
    for value in rates:
        verifier.feed(value)
        if verifier.is_terminal:
            break
    verifier.finalize()
    return verifier


@pytest.mark.parametrize("scale", [0.01, 1.0, 100.0])
def test_late_distribution_uses_actual_remaining_opportunity(scale):
    rng = random.Random(0)
    rates = [rng.uniform(0.4, 1.6) * 5 * scale for _ in range(200)]
    verifier = finish(
        AdaptiveUnitVerification(
            "unit",
            AdaptiveVerificationConfig(min_timed_ms=500 * scale, max_wall_ms=60000 * scale),
        ),
        rates,
    )
    assert verifier.state == "verified"
    measured = verifier.measurement()
    assert measured.detail["stability_evidence"] == "fast_distribution_suffix"
    assert len(measured.raw_timings_ms) == 111
    assert measured.unit_time_ms_median / scale == pytest.approx(5, rel=0.15)


@pytest.mark.parametrize("seed", [0, 17])
@pytest.mark.parametrize("scale", [0.01, 1.0, 100.0])
def test_noisy_early_rate_cannot_be_forgotten_by_a_slow_stable_suffix(seed, scale):
    rng = random.Random(seed)
    rates = [rng.uniform(0.4, 1.6) * scale for _ in range(30)]
    rates += [15 * rng.uniform(0.4, 1.6) * scale for _ in range(250)]
    verifier = finish(
        AdaptiveUnitVerification(
            "unit",
            AdaptiveVerificationConfig(min_timed_ms=500 * scale, max_wall_ms=60000 * scale),
        ),
        rates,
    )
    assert verifier.state == "failed_pathological_unit"
    assert "sustained slowdown" in verifier.failure_reason


def test_prior_drift_counts_the_window_actually_used_for_prediction():
    verifier = finish(
        AdaptiveUnitVerification(
            "unit", AdaptiveVerificationConfig(min_timed_steps=60), prior_expected_unit_ms=1.0
        ),
        [0.1] * 200,
    )
    assert verifier.state == "verified"
    assert verifier.prior_agreement == "verified_drift"
    assert verifier.measurement().n_measured_units == 120


def test_earlier_reference_tolerates_an_isolated_delay_and_warmup():
    verifier = finish(
        AdaptiveUnitVerification("unit"), [2000.0] + [1.0] * 20 + [100.0] + [1.0] * 200
    )
    assert verifier.state == "verified"
    assert verifier.measurement().unit_time_ms_median == 1.0


@pytest.mark.parametrize("scale", [0.01, 1.0, 100.0])
@pytest.mark.parametrize("distribution", ["periodic", "bimodal", "lognormal"])
def test_recurring_expensive_units_are_not_a_new_slowdown(distribution, scale):
    """The initial PR falsely refused these stationary inputs at 20/75/49 units."""
    if distribution == "periodic":
        period = [2, 2, 2, 2, 0.1, 0.1, 0.1, 0.1, 2, 0.1, 2, 0.1, 0.1, 2, 2, 0.1]
        rates = period * 20
    elif distribution == "bimodal":
        rng = random.Random(7)
        rates = [0.1 if rng.random() < 0.6 else 2.0 for _ in range(300)]
    else:
        rng = random.Random(4)
        rates = [0.1 * rng.lognormvariate(0, 1.5) for _ in range(300)]
    verifier = finish(
        AdaptiveUnitVerification(
            "unit",
            AdaptiveVerificationConfig(min_timed_ms=500 * scale, max_wall_ms=60000 * scale),
        ),
        [value * scale for value in rates],
    )
    assert verifier.state == "verified"


@pytest.mark.parametrize("warmup", [None, 2000.0])
@pytest.mark.parametrize("seed", [88, 163])
def test_distribution_shift_survives_warmup_without_a_short_window_minimum(warmup, seed):
    """Catch biased-reference (88) and no half-median plateau (163) shifts."""
    rng = random.Random(seed)
    rates = [rng.uniform(0.4, 1.6) for _ in range(30)]
    rates += [15 * rng.uniform(0.4, 1.6) for _ in range(250)]
    if warmup is not None:
        rates.insert(0, warmup)
    verifier = finish(AdaptiveUnitVerification("unit"), rates)
    assert verifier.state == "failed_pathological_unit"
    assert "disjoint observed rate blocks" in verifier.failure_reason
