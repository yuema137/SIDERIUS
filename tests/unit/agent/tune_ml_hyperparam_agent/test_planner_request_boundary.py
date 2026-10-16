"""The request seam preserves ordering, authority routing and optional omission."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from execute_tools.metric_order import MetricOrder
from nodes.ml_hyperparameter_tune_agent.contracts import AttemptIdentity
from nodes.ml_hyperparameter_tune_agent.planning import _request_attempt_plan
from tests.helpers.metric_fixtures import shipped_spec


@pytest.mark.parametrize("direction", ["higher", "lower"])
@pytest.mark.parametrize("populated", [False, True])
@pytest.mark.parametrize("reserve", [None, 0.25])
def test_request_preserves_context_and_reads_history_once(tmp_path, direction, populated, reserve):
    inp = HyperparamTuningInput(
        model_type="punet",
        file_index=0,
        llm_provider="openai",
        llm_model_id="test",
        storage=StorageConfig(backend="local", local=LocalStorageConfig(workspace=str(tmp_path))),
        trial_max_epochs=7,
        formal_max_epochs=11,
        trial_time_budget_minutes=3.0,
        formal_time_budget_minutes=9.0,
        formal_round_strategy="independent",
        training_budget_reserve_fraction=reserve,
    )
    history = []
    if populated:
        history = [
            {
                "status": "success",
                "denoising_score": score,
                "score_table": {"rendered_markdown": str(score)},
            }
            for score in (0.2, 0.7)
        ]
        history.append(
            {
                "status": "failed",
                "denoising_score": 999,
                "score_table": {"rendered_markdown": "invalid"},
                "memory": {"time_mode": "trial", "time_estimate_minutes": 1.25},
            }
        )
    spec = shipped_spec().model_copy(update={"direction": direction})
    response = {"unparsed": "decision"}
    calls = []
    box = SimpleNamespace(get_summary=Mock(side_effect=lambda: calls.append("observe") or history))
    brain = SimpleNamespace(plan=Mock(side_effect=lambda *a, **k: calls.append("plan") or response))
    bindings = SimpleNamespace(
        agent_input=inp,
        sandbox=box,
        brain=brain,
        run_order=MetricOrder(spec),
        run_task_render=SimpleNamespace(loss_context=None),
        model_type_setting="punet",
        trial_allowed=True,
        scope_is_partial=populated,
        resolved_data_scope=[0, 2],
        expert_advice_str="advice",
        config_manual_data={},
        model_description="description",
        max_rounds=2,
        trial_vram_budget=4.0,
        formal_vram_budget=8.0,
        trial_time_budget=3.0,
        formal_time_budget=9.0,
        run_metric=SimpleNamespace(spec=spec),
        run_scientific_gate_ids=frozenset(),
        planner_strategy_identity=None,
        custom_loss_inventory=None,
    )
    result = _request_attempt_plan(
        bindings,
        identity=AttemptIdentity(round_index=2, attempt_in_round=1, is_formal_round=True),
        total_attempts=2,
        attempts_this_round=1,
        formal_trial_winner=None,
    )
    assert calls == ["observe", "plan"]
    box.get_summary.assert_called_once_with()
    assert result.decision is response and result.memory_history is history
    args, kwargs = brain.plan.call_args
    assert args == (history,)
    assert kwargs["timing_context"] is result.timing_context
    assert [r.epoch_cap for r in result.timing_context.roles] == [11]
    assert kwargs["resolved_data_scope"] == ([0, 2] if populated else None)
    assert kwargs["trial_max_epochs"] == 7 and kwargs["formal_max_epochs"] == 11
    assert kwargs["trial_time_budget_minutes"] == 3.0
    assert kwargs["formal_time_budget_minutes"] == 9.0
    assert kwargs["last_time_estimate_minutes"] == (1.25 if populated else None)
    expected_table = str(0.7 if direction == "higher" else 0.2) if populated else None
    assert kwargs["score_table_md"] == expected_table
    assert ("training_budget_reserve_fraction" in kwargs) == (reserve is not None)
    if reserve is not None:
        assert kwargs["training_budget_reserve_fraction"] == reserve
    brain.plan.side_effect = RuntimeError("planner unavailable")
    with pytest.raises(RuntimeError, match="planner unavailable"):
        _request_attempt_plan(
            bindings,
            identity=AttemptIdentity(round_index=1, attempt_in_round=1, is_formal_round=False),
            total_attempts=1,
            attempts_this_round=1,
            formal_trial_winner=None,
        )
