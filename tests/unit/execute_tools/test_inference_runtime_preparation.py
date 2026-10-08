"""Issue #672: standalone inference must record real setup before admission."""

import pytest
import torch

from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from execute_tools.inference_runtime import InferenceRuntimeEvidence, InferenceRuntimePreparation


@pytest.mark.parametrize("resumed", [False, True], ids=["standalone", "resumed"])
@pytest.mark.parametrize("budget", [None, 25.0, 40.0])
def test_standalone_setup_is_measured_and_resumed_accounting_is_unchanged(
    tmp_path, monkeypatch, resumed, budget
):
    """Fresh setup is charged once; existing resumed timing scope is preserved."""
    clock = {"now": 0.0}
    monkeypatch.setattr("time.perf_counter", lambda: clock["now"])
    path = str(tmp_path / "runtime.json")
    policy = RuntimeControlPolicy(operator_budget_seconds=budget, safety_factor=2)
    previous_setup = None
    if resumed:
        previous = RuntimeVerificationSession(path, policy=policy)
        clock["now"] = 5.0
        previous.complete_setup(storage_provenance={})
        previous_setup = previous.observation.components["setup"]

    clock["now"] = 10.0
    preparation = InferenceRuntimePreparation(path, policy=policy, attempt_id="fixture")
    clock["now"] = 30.0  # Model loading and transfer took 20 seconds.
    preparation.finish()
    evidence = InferenceRuntimeEvidence(
        preparation.session,
        samples=1,
        device=torch.device("cpu"),
        started=clock["now"],
    )
    started = evidence.start_batch()
    clock["now"] = 37.0
    evidence.finish_batch(started, 1)
    rejected = budget == 25.0 and not resumed
    if rejected:
        with pytest.raises(RuntimeError, match="runtime admission refused inference"):
            evidence.finish()
    else:
        evidence.finish()

    observation = preparation.session.observation
    setup = observation.components["setup"]
    inference = observation.components["inference"]
    assert setup.actual_seconds == (5.0 if resumed else 20.0)
    assert inference.actual_seconds == 7.0
    assert observation.admission.decision == ("rejected" if rejected else "admitted")
    if resumed:
        assert setup == previous_setup
    else:
        assert "training" not in observation.components


@pytest.mark.parametrize("completion_policy", ["completed-workload-v1", "verified-prediction-v1"])
def test_resumed_prediction_and_actual_keep_the_existing_iteration_interval(
    tmp_path, monkeypatch, completion_policy
):
    """A 20s model load must not enter resumed inference's old 5s interval."""
    from core.runtime_control.adaptive import AdaptiveVerificationConfig
    from core.runtime_control.steady_state import SteadyStateConfig

    clock = {"now": 0.0}
    monkeypatch.setattr("time.perf_counter", lambda: clock["now"])
    path = str(tmp_path / "runtime.json")
    policy = RuntimeControlPolicy(
        runtime_completion_policy=completion_policy,
        verification=AdaptiveVerificationConfig(
            steady=SteadyStateConfig(window=2, stable_windows=2),
            min_timed_steps=1,
            min_timed_ms=0,
        ),
    )
    previous = RuntimeVerificationSession(path, policy=policy)
    clock["now"] = 5.0
    previous.complete_setup(storage_provenance={})
    original_setup = previous.observation.components["setup"]
    clock["now"] = 10.0
    preparation = InferenceRuntimePreparation(path, policy=policy, attempt_id="fixture")
    clock["now"] = 30.0
    preparation.finish()
    clock["now"] = 31.0  # The old interval includes one second of dataset setup.
    evidence = InferenceRuntimeEvidence(
        preparation.session, samples=4, device=torch.device("cpu"), started=30.0
    )
    for _ in range(4):
        started = evidence.start_batch()
        clock["now"] += 1.0
        evidence.finish_batch(started, 1)
    evidence.finish()

    component = preparation.session.observation.components["inference"]
    assert preparation.session.observation.components["setup"] == original_setup
    assert component.prediction.predicted_seconds == 5.0
    assert component.prediction.detail["extra_predicted_seconds"] == 1.0
    assert component.actual_seconds == 5.0
