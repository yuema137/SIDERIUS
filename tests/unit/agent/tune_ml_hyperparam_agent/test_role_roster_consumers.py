"""Actual effective-file resolution cannot launder UNKNOWN on consumer edges.

These are deterministic supplied-record tests, not evidence that a lifecycle
produced the records. Each consumer assertion detects a dropped roster value.
"""

from types import SimpleNamespace

import pytest
import yaml

from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningOutput
from execute_tools.health_checks.candidate_eligibility import formal_validity_of
from execute_tools.metric_order import MetricOrder
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    _best_trial_winner,
    _build_trial_validity_feedback,
    _resolve_run_gate_ids,
)
from nodes.result_interpretation_agent import tuning_output_to_model_run_summary
from tests.helpers.metric_fixtures import accuracy_like_spec


@pytest.mark.parametrize("roster", ["declared", "empty", "roleless"])
def test_effective_run_roster_reaches_selection_feedback_and_interpretation(tmp_path, roster):
    """Positive arms catch lost explicit policy; negative catches None→empty."""
    gate = {
        "id": "guard_recording",  # Misleading suffix must not override role.
        "gate_role": "blocking",
        "after_round": "every",
        "checks": [{"name": "synthetic_guard", "config": {"peek_file_indices": [2]}}],
        "on_pass": {"action": "continue"},
        "on_fail": {"action": "continue"},
    }
    if roster == "roleless":
        gate.pop("gate_role")
    path = tmp_path / "health_checks_effective.yaml"
    path.write_text(yaml.safe_dump({"health_gates": [] if roster == "empty" else [gate]}))
    ids = _resolve_run_gate_ids(
        SimpleNamespace(task_composition_ref=None, health_checks_config=str(path))
    )
    assert (
        ids
        == {"declared": frozenset({"guard_recording"}), "empty": frozenset(), "roleless": None}[
            roster
        ]
    )
    record = ExperimentRecord(
        exp_id="trial",
        status="success",
        model_type="synthetic",
        timestamp="2026-09-13",
        params={},
        is_trial=True,
        denoising_score=0.7,
        health_gate_results=[
            {
                "gate_name": "guard_recording",
                "execution_status": "passed",
                "check_passed": True,
                "would_invalidate_under_production_policy": False,
                "resolved_action": "continue",
            }
        ],
    )
    data = record.model_dump(mode="json")
    order = MetricOrder(accuracy_like_spec())
    winner = _best_trial_winner([data], order=order, required_gate_ids=ids)
    feedback = _build_trial_validity_feedback(
        [data],
        formal_skipped_for_no_valid_winner=True,
        healthgate_mode="blocking",
        required_gate_ids=ids,
    )
    output = HyperparamTuningOutput(
        run_name="roster",
        model_type="synthetic",
        file_index=2,
        status="completed",
        completed_rounds=1,
        total_attempts=1,
        all_records=[record],
        started_at="2026-09-13",
        finished_at="2026-09-13",
        best_denoising_score=0.7,
    )
    summary = tuning_output_to_model_run_summary(output, order=order, required_gate_ids=ids)
    assert summary.best_denoising_score == 0.7  # Raw reporting is independent of promotion.
    if roster == "roleless":
        assert winner is None
        assert feedback is not None and feedback.unknown_validity_count == 1
        assert feedback.invalid_count == 0
        assert summary.best_valid_denoising_score is None
        assert summary.round_health[0].health_validity.value == "unknown"
        assert formal_validity_of(data, config_path=str(path)) == "unknown"
    else:
        assert winner is not None and winner["exp_id"] == "trial"
        assert feedback is None
        assert summary.best_valid_denoising_score == 0.7
        assert summary.round_health[0].health_validity.value == "valid"
        assert formal_validity_of(data, config_path=str(path)) == "valid"
