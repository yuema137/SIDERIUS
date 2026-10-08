"""Issue #672: standalone inference must record real setup before admission."""

import pytest
import torch

from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from execute_tools.inference_runtime import InferenceRuntimeEvidence, InferenceRuntimePreparation


@pytest.mark.parametrize("resumed", [False, True], ids=["standalone", "resumed"])
@pytest.mark.parametrize("budget", [None, 25.0, 40.0])
def test_preparation_is_counted_once_and_cannot_escape_budget(
    tmp_path, monkeypatch, resumed, budget
):
    """Losing preparation admits the 25s budget; counting it twice rejects 40s."""
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
    prior_seconds = preparation.finish()
    evidence = InferenceRuntimeEvidence(
        preparation.session,
        samples=1,
        device=torch.device("cpu"),
        started=clock["now"],
        preparation_seconds=prior_seconds,
    )
    started = evidence.start_batch()
    clock["now"] = 37.0
    evidence.finish_batch(started, 1)
    if budget == 25.0:
        with pytest.raises(RuntimeError, match="runtime admission refused inference"):
            evidence.finish()
    else:
        evidence.finish()

    observation = preparation.session.observation
    setup = observation.components["setup"]
    inference = observation.components["inference"]
    assert setup.actual_seconds == (5.0 if resumed else 20.0)
    assert inference.actual_seconds == (27.0 if resumed else 7.0)
    assert observation.admission.decision == ("rejected" if budget == 25.0 else "admitted")
    if resumed:
        assert setup == previous_setup
    else:
        assert "training" not in observation.components
