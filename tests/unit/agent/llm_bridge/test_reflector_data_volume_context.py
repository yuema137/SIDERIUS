"""Issue #1472 — the reflector's Data Volume Context names the round's portion owner.

Rendered through the production path: ``invoke_reflection`` selects the
executed role from the retained timing facts built by the tuner's own
``build_timing_context``, and the prompt is captured at the no-network
``_chat_json`` boundary. Reverting the renderer to the historical
``trial_portion`` label and "Recommend increasing trial_portion" advice fails
the Formal cases.
"""

from types import SimpleNamespace

import pytest

from agent.schemas.execution_provenance import ExecutionProvenance
from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_hyperparameter_tune_agent.feedback import invoke_reflection
from nodes.ml_hyperparameter_tune_agent.timing_context import build_timing_context
from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge
from tests.unit.agent.llm_bridge.test_step00_prompt_goldens import (
    reflect_fixture_args,
    reflect_fixture_kwargs,
)


def _data_volume_block(tmp_path, *, mode: str, scope_source: str) -> str:
    inp = HyperparamTuningInput(
        model_type="punet",
        file_index=0,
        storage=StorageConfig(
            backend="local", local=LocalStorageConfig(workspace=str(tmp_path), run_name="volume")
        ),
        formal_training_scope_source=scope_source,
    )
    timing = build_timing_context(
        inp,
        trial_allowed=True,
        is_formal_round=mode == "formal",
        current_round=1,
        trial_winner=None,
        memory_history=[],
        scope_is_partial=False,
    )
    prepared = SimpleNamespace(
        hypothesis="More data helps.",
        execution_provenance=ExecutionProvenance(),
        timing_context=timing,
        trial_config=SimpleNamespace(mode=mode),
        # No validation ceiling: planning's before/after portion pair is equal.
        _planned_portions={"trial_portion": 0.05, "train_portion": 1.0, "eval_portion": 0.1},
        cfg_trial_portion=0.05,
        cfg_train_portion=1.0,
        cfg_eval_portion=0.1,
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
        **reflect_fixture_kwargs(),
    )
    user = bridge.captures[0][3]
    return user.split("### Data Volume Context:", 1)[1].split("### INSTRUCTIONS:", 1)[0]


def test_formal_round_names_operator_formal_portion_not_trial_portion(tmp_path):
    block = _data_volume_block(tmp_path, mode="formal", scope_source="operator")
    assert "  round_mode            : formal\n" in block
    assert (
        "  formal_portion        : 0.05  (training portion; operator-set formal_portion)" in block
    )
    assert (
        "  formal_eval_portion   : 0.1  (evaluation portion; operator-set formal_eval_portion)"
        in (block)
    )
    assert "trial_portion         :" not in block
    assert "Recommend increasing trial_portion" not in block
    assert "operator-set (formal_portion / formal_train_portion)" in block


def test_agent_scoped_formal_round_attributes_training_portion_to_the_plan(tmp_path):
    block = _data_volume_block(tmp_path, mode="formal", scope_source="agent")
    assert "  trial_portion         : 0.05  (training portion; planner-set plan.trial_portion)" in (
        block
    )
    # Formal evaluation stays operator-owned even when the plan sets training.
    assert (
        "  formal_eval_portion   : 0.1  (evaluation portion; operator-set formal_eval_portion)"
        in (block)
    )
    assert "formal_training_scope_source='agent'" in block
    assert "Recommend increasing\n     trial_portion" in block


@pytest.mark.parametrize("scope_source", ["operator", "agent"])
def test_trial_round_keeps_planner_trial_portion_advice(tmp_path, scope_source):
    block = _data_volume_block(tmp_path, mode="trial", scope_source=scope_source)
    assert "  round_mode            : trial\n" in block
    assert "  trial_portion         : 0.05  (training portion; planner-set plan.trial_portion)" in (
        block
    )
    assert "  eval_portion          : 0.1  (evaluation portion; planner-set plan.eval_portion)" in (
        block
    )
    assert "NOT bad hyperparameters. Recommend increasing trial_portion.\n" in block
