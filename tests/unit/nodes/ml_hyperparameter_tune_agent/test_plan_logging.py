"""Console provenance must describe the prepared request, not stale planner prose."""

import pytest

from agent.schemas.hyperparam_tuning import ExperimentPlan
from nodes.ml_hyperparameter_tune_agent.plan_logging import render_effective_plan
from nodes.ml_hyperparameter_tune_agent.provenance import ResolutionTracker
from tests.unit.nodes.ml_hyperparameter_tune_agent.test_training_batch_plan import _prepare


@pytest.mark.parametrize("rows", [100, 2_010_000_000])
def test_full_clone_log_matches_effective_request(tmp_path, capsys, rows):
    """Reverting the production rendering call loses the batch 8 -> 4 witness."""
    winner = {
        "exp_id": "winning_trial",
        "denoising_score": 1.0,
        "params": {
            "model_config": {"multi": 16, "depth": 2, "embedding_dim": 8},
            "train_config": {"batch_size": 4, "epochs": 1, "lr": 0.001},
            "loss_config": {"loss_type": "ce"},
        },
    }
    prepared, _ = _prepare(tmp_path, rows, authored_batch=8, winner=winner)
    output = capsys.readouterr().out
    batch = prepared.active_params["train_config"]["batch_size"]
    assert batch == 4
    assert f"train_cfg.batch_size: proposed 8 -> effective {batch}" in output
    assert "authority: round-mode override chain (trial lockout / formal inheritance)" in output
    assert "strategy=full_clone winner='winning_trial'" in output
    assert "Authored proposal (superseded by the effective configuration above" in output
    assert f"Proposal hypothesis: {prepared.hypothesis}" in output
    assert f"Proposal reasoning: {prepared.plan.reasoning}" in output
    assert "prepared request; execution/results pending" in output
    assert "\nHypothesis:" not in output and "\nReasoning:" not in output


def test_operator_override_log_uses_final_provenance(tmp_path, capsys):
    """A different authority must render through the same production boundary."""
    prepared, _ = _prepare(
        tmp_path, 100, authored_batch=8, overrides={"train_config": {"batch_size": 2}}
    )
    output = capsys.readouterr().out
    batch = prepared.active_params["train_config"]["batch_size"]
    assert batch == 2
    assert (
        f"train_cfg.batch_size: proposed 8 -> effective {batch} "
        "[authority: operator plan_overrides lock]"
    ) in output
    for event in prepared.execution_provenance.events:
        assert (
            f"{event.field_path}: proposed {event.proposed} -> effective {event.executed}" in output
        )
    assert "Authored proposal (superseded" in output


def test_unchanged_plan_is_still_a_proposal_not_a_result():
    """No differences must not falsely label an unchanged proposal superseded."""
    plan = ExperimentPlan(hypothesis="Batch 8 may improve throughput", reasoning="Try batch 8")
    before = plan.model_dump()
    output = render_effective_plan(
        exp_id="attempt_001",
        model_type=plan.model_type,
        plan=plan,
        provenance=ResolutionTracker(plan).finish(plan),
    )
    assert "No authored configuration values were overridden." in output
    assert "Authored proposal (not observed execution/results):" in output
    assert "superseded" not in output
    assert f"Proposal hypothesis: {plan.hypothesis}" in output
    assert f"Proposal reasoning: {plan.reasoning}" in output
    assert plan.model_dump() == before
