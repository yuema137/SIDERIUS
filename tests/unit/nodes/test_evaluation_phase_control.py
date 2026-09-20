"""Phase extraction must preserve early attempt decisions and output cleanup."""

import importlib
from types import SimpleNamespace

import pytest

execution = importlib.import_module("nodes.ml_hyperparameter_tune_agent.execution")


@pytest.mark.parametrize("scope_failure", [False, True])
def test_evaluation_early_decision_reaches_caller_after_cleanup(monkeypatch, scope_failure):
    # Deleting the early return, copying only fields, or moving it outside the
    # finally would either unpack absent results or lose the cleanup event.
    outcome = (
        execution.AttemptExecution.end_round(scope_violation_reason="fixture scope refusal")
        if scope_failure
        else execution.AttemptExecution.next_attempt()
    )
    events = []

    def evaluate(*args, **kwargs):
        events.append("evaluation")
        return outcome

    monkeypatch.setattr(execution, "_run_local_evaluation_phase", evaluate)
    monkeypatch.setattr(
        execution, "finalize_attempt_outputs", lambda **kw: events.append("cleanup")
    )
    bindings = SimpleNamespace(
        agent_input=SimpleNamespace(retain_model_outputs=False),
        reference_scores=None,
        run_deliverable_naming=None,
        run_name="run",
        sandbox=SimpleNamespace(base_dir="outputs"),
        workspace="workspace",
        run_task_data_path=None,
    )
    prepared = SimpleNamespace(exp_id="attempt", model_type="model", plan=None)
    identity = SimpleNamespace(attempt_in_round=1, round_index=1)
    actual = execution.run_inference_scoring_health(
        bindings,
        prepared,
        identity,
        SimpleNamespace(name="training"),
        train_time=1.0,
        training_results=None,
    )
    assert actual is outcome
    assert events == ["evaluation", "cleanup"]
