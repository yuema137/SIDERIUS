"""Issue #1197: relative timing jitter must also reach an absolute risk floor."""

import random

import pytest

from core.runtime_control.adaptive import AdaptiveUnitVerification, AdaptiveVerificationConfig
from core.runtime_control.session import RuntimeControlPolicy
from core.runtime_control.steady_state import SteadyStateConfig


def _finish(rates: list[float], config: AdaptiveVerificationConfig) -> AdaptiveUnitVerification:
    verifier = AdaptiveUnitVerification("validation_sample", config)
    for rate in rates:
        verifier.feed(rate)
        if verifier.is_terminal:
            break
    verifier.finalize()
    return verifier


@pytest.mark.parametrize("reference,slow", [(0.0156, 0.219), (0.162, 9.23), (0.0438, 0.986)])
@pytest.mark.parametrize("guard", ["streak", "distribution"])
def test_issue_1197_timing_pairs_require_absolute_slowdown_floor(
    reference: float, slow: float, guard: str
) -> None:
    """Reconstruct the reported pairs; the issue does not provide raw traces.

    Removing either floor guard makes its corresponding verified assertion fail.
    The scaled witness ensures a real slowdown still reaches that refusal path.
    """
    rng = random.Random(88)
    prefix = [reference] * 30
    if guard == "distribution":
        prefix = [reference * rng.uniform(0.4, 1.6) for _ in range(30)]
    trace = prefix + [slow] * 250
    config = AdaptiveVerificationConfig(
        min_timed_steps=30,
        steady=SteadyStateConfig(rel_spread_tol=0.00001 if guard == "distribution" else 0.1),
    )
    verifier = _finish(trace, config)
    assert verifier.state == "verified", verifier.failure_reason
    measurement = verifier.measurement()
    assert measurement is not None
    assert measurement.unit_time_ms_median == pytest.approx(slow)

    # Keep the earlier plateau below the evidence time minimum, but put the
    # later rate above 100 ms; only the absolute duration changes.
    scale = 200.0 / slow
    dangerous = _finish([rate * scale for rate in trace], config)
    assert dangerous.state == "failed_pathological_unit"
    reason = dangerous.failure_reason or ""
    assert ("consecutive" if guard == "streak" else "disjoint observed rate blocks") in reason


@pytest.mark.parametrize("guard", ["streak", "distribution"])
def test_runtime_policy_override_and_floor_boundary(guard: str) -> None:
    """Typed policy transport must honor an override, including equality.

    With either floor removed, the below-floor case fails. Ignoring the override
    or treating equality as exempt loses the at-floor refusal.
    """
    config = RuntimeControlPolicy.model_validate(
        {
            "verification": {
                "pathological_min_unit_ms": 20.0,
                "steady": {"rel_spread_tol": 0.00001 if guard == "distribution" else 0.1},
            }
        }
    ).verification
    rng = random.Random(88)
    prefix = [0.1] * 30
    if guard == "distribution":
        prefix = [0.1 * rng.uniform(0.4, 1.6) for _ in range(30)]
    assert _finish(prefix + [19.9] * 250, config).state == "verified"
    assert _finish(prefix + [20.0] * 250, config).state == "failed_pathological_unit"
