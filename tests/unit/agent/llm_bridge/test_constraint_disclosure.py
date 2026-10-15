"""Capture native downstream prompts at the actual no-network provider boundary."""

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_hyperparameter_tune_agent.timing_context import build_timing_context
from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge
from tests.helpers.tuner_prompt_fixtures import planner_kwargs
from tests.unit.agent.llm_bridge.test_step00_prompt_goldens import (
    reflect_fixture_args,
    reflect_fixture_kwargs,
)
from tests.unit.agent.test_constraint_disclosure import locked_context


def test_planner_discloses_owner_timing_without_mutating_run_context(tmp_path):
    inp = HyperparamTuningInput(
        model_type="punet",
        file_index=0,
        storage=StorageConfig(
            backend="local", local=LocalStorageConfig(workspace=str(tmp_path), run_name="timing")
        ),
        formal_max_epochs=7,
        formal_eval_portion=0.29,
        plan_overrides={"eval_portion": 0.23},
    )
    timing = build_timing_context(
        inp,
        trial_allowed=True,
        is_formal_round=True,
        current_round=2,
        trial_winner=None,
        memory_history=[],
        scope_is_partial=False,
    )
    context = locked_context()
    bridge = BoundaryRecorderBridge()
    bridge.plan(**planner_kwargs(), timing_context=timing, constraint_context=context)
    user = bridge.captures[0][3]
    assert '"train_config.lr"' in user
    assert '"formal_eval_portion": 0.29' in user
    assert '"epoch_cap": 7' in user
    assert context.timing is None
    assert user.count("[CURRENT RUN EXECUTION CONSTRAINTS]") == 1


def test_reflector_receives_rules_at_actual_chat_json_boundary():
    bridge = BoundaryRecorderBridge()
    bridge.reflect(
        *reflect_fixture_args(), **reflect_fixture_kwargs(), constraint_context=locked_context()
    )
    method, label, _, user = bridge.captures[0]
    assert (method, label) == ("_chat_json", "tuner.reflector")
    assert '"train_config.lr"' in user
    assert "not corrections to historical results" in user


def test_absent_context_is_incomplete_not_fabricated_from_timing(tmp_path):
    inp = HyperparamTuningInput(
        model_type="punet",
        file_index=0,
        storage=StorageConfig(
            backend="local", local=LocalStorageConfig(workspace=str(tmp_path), run_name="absent")
        ),
        formal_max_epochs=7,
    )
    timing = build_timing_context(
        inp,
        trial_allowed=True,
        is_formal_round=True,
        current_round=2,
        trial_winner=None,
        memory_history=[],
        scope_is_partial=False,
    )
    bridge = BoundaryRecorderBridge()
    bridge.plan(**planner_kwargs(), timing_context=timing)
    shared = bridge.captures[0][3].split("[CURRENT RUN EXECUTION CONSTRAINTS]", 1)[1]
    assert "missing authority sections: task_rules, workflow_rules" in shared
    assert '"timing"' not in shared
    assert '"roles"' not in shared


def test_reflection_preserves_planning_inheritance_when_provenance_is_empty(tmp_path):
    from types import SimpleNamespace

    from agent.schemas.execution_provenance import ExecutionProvenance
    from nodes.ml_hyperparameter_tune_agent.feedback import invoke_reflection
    from tests.unit.agent.tune_ml_hyperparam_agent.test_valid_trial_winner_drives_formal import (
        _valid_trial_record,
    )

    inp = HyperparamTuningInput(
        model_type="punet",
        file_index=0,
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="reflection"),
        ),
    )
    winner = _valid_trial_record("previous-trial", 0.8, batch_size=8, lr=0.03)
    timing = build_timing_context(
        inp,
        trial_allowed=True,
        is_formal_round=True,
        current_round=2,
        trial_winner=winner,
        memory_history=[winner],
        scope_is_partial=False,
    )
    assert timing.inheritance_values
    prepared = SimpleNamespace(
        hypothesis="Same values as winner",
        execution_provenance=ExecutionProvenance(),
        timing_context=timing,
    )
    bridge = BoundaryRecorderBridge()
    exp_id, _, results, reflection_context = reflect_fixture_args()
    invoke_reflection(
        bridge,
        exp_id=exp_id,
        prepared=prepared,
        reflect_results=results,
        reflection_context=reflection_context,
        task_render=None,
        constraint_context=locked_context(),
        **reflect_fixture_kwargs(),
    )
    user = bridge.captures[0][3]
    assert '"inheritance_winner": "previous-trial"' in user
    assert '"lr": 0.03' in user
    assert '"inheritance_values"' in user
    historical = BoundaryRecorderBridge()
    invoke_reflection(
        historical,
        exp_id=exp_id,
        prepared=prepared,
        reflect_results=results,
        reflection_context=reflection_context,
        task_render=None,
        constraint_context=None,
        **reflect_fixture_kwargs(),
    )
    assert '"inheritance_values"' not in historical.captures[0][3]
