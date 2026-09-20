"""Persisted role evidence must survive the tuner-to-interpreter boundary."""

import pytest

from agent.prompt_templates.interpretation.rendering import _build_per_model_prompt
from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningOutput
from execute_tools.metric_order import MetricOrder
from nodes.result_interpretation_agent import tuning_output_to_model_run_summary
from tests.helpers.metric_fixtures import accuracy_like_spec


@pytest.mark.parametrize("roles", [(False,), (True, False)])
def test_record_roles_reach_prompt_even_when_scores_are_identical(roles):
    """2026-09-19: one Formal aggregate was interpreted as a replicated Trial."""
    records = [
        ExperimentRecord(
            exp_id=f"record-{i}",
            status="success",
            model_type="synthetic",
            timestamp="2026-09-19",
            params={},
            is_trial=role,
            denoising_score=0.7,
        )
        for i, role in enumerate(roles)
    ]
    output = HyperparamTuningOutput(
        run_name="roles",
        model_type="synthetic",
        file_index=0,
        status="completed",
        completed_rounds=len(records),
        total_attempts=len(records),
        all_records=records,
        started_at="2026-09-19",
        finished_at="2026-09-19",
        best_denoising_score=0.7,
    )
    order = MetricOrder(accuracy_like_spec())
    summary = tuning_output_to_model_run_summary(output, order=order, required_gate_ids=frozenset())
    assert summary.round_is_trial == list(roles)
    prompt = _build_per_model_prompt(summary, None, order=order)
    expected = "Trial=0, Formal=1" if len(roles) == 1 else "Trial=1, Formal=1"
    assert f"Persisted record roles: {expected}" in prompt
    assert prompt.count("role=Formal") == 1
    assert prompt.count("role=Trial") == (0 if len(roles) == 1 else 1)
    assert "equal values are not independent replication evidence" in prompt
    # Cached summaries predating this carrier retain unknown roles, even with
    # a Formal score. Never synthesize a second experiment from equal scores.
    legacy = summary.model_copy(update={"round_is_trial": []})
    prompt = _build_per_model_prompt(legacy, None, order=order)
    assert "Persisted record roles: unavailable" in prompt
    assert "role=Trial" not in prompt and "role=Formal" not in prompt
