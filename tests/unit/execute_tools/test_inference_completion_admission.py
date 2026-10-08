"""Inference writer completion must enforce actual time before returning success."""

import pytest
import torch

from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from execute_tools.inference_runtime import InferenceRuntimeEvidence


@pytest.mark.parametrize("budget", [1, 100])
def test_completed_inference_uses_actual_total_and_preserves_failed_evidence(
    tmp_path, monkeypatch, budget
):
    clock = [10.0]
    monkeypatch.setattr("execute_tools.inference_runtime.time.perf_counter", lambda: clock[0])
    session = RuntimeVerificationSession(
        str(tmp_path / "rv.json"), policy=RuntimeControlPolicy(operator_budget_seconds=budget)
    )
    session.complete_setup(storage_provenance={})
    evidence = InferenceRuntimeEvidence(session, samples=2, device=torch.device("cpu"), started=10)
    clock[0] = 10.1
    evidence.finish_batch(10.0, 1)
    clock[0] = 10.2
    evidence.finish_batch(10.1, 1)
    clock[0] = 12.0
    if budget == 1:
        with pytest.raises(RuntimeError, match="admission refused inference"):
            evidence.finish()
        assert session.observation.admission.reason_code == "budget_exceeded"
        assert session.observation.admission.avoided_predicted_runtime_seconds is None
        assert session.observation.final_status == "rejected"
    else:
        evidence.finish()
        assert session.observation.final_status == "inference_complete"
    component = session.observation.components["inference"]
    assert component.actual_seconds == 2
    assert component.prediction is None
    assert component.completion.verification_basis == "workload_exhausted"


def test_incomplete_writer_consumption_cannot_assert_completion(tmp_path):
    session = RuntimeVerificationSession(str(tmp_path / "rv.json"))
    evidence = InferenceRuntimeEvidence(session, samples=2, device=torch.device("cpu"), started=0)
    with pytest.raises(ValueError, match="completed count"):
        evidence.finish()
    assert session.observation.components["inference"].completion is None
