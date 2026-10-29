"""Issue #1047: prepare_attempt judges model rules against the executed model.

The LLM plan names ``wavenet``; ``force_model`` executes ``punet``. A valid
PUNet lock must be accepted. If planning judged the plan's own model_type,
``model_config.depth`` (a PUNetConfig field WaveNetConfig lacks) would be
refused.
"""

from __future__ import annotations

from agent.schemas.hyperparam_tuning import HyperparamTuningInput, TaskCompositionRef
from agent.schemas.parameter_rules import ParameterRules
from execute_tools.task_data_path import bind_task_data_path
from nodes.ml_hyperparameter_tune_agent.contracts import AttemptIdentity, AttemptOrdering
from nodes.ml_hyperparameter_tune_agent.planning import prepare_attempt
from tests.helpers.run_seed import TEST_RUN_SEED
from tests.unit.nodes.ml_hyperparameter_tune_agent.test_c12p_b11_composed_seg_size_authoring import (
    _bindings,
    _ScopeRecorder,
)


def test_force_model_lock_is_accepted_when_the_llm_plan_names_another_model(tmp_path):
    """Fails if prepare_attempt checks rules against the plan's model_type, not force_model."""
    agent_input = HyperparamTuningInput(
        run_seed=TEST_RUN_SEED,
        planner_strategy="native-timing-v1",
        model_type="punet",
        task_composition_ref=TaskCompositionRef(
            semantic_fingerprint="c12p-b11-fingerprint",
            task_data_path_id="c12p_b11_recorder",
            task_health_binding=None,
        ),
        workflow_parameter_rules=ParameterRules.model_validate(
            {"model_config.depth": {"exact": 3}}
        ),
    )
    recorder = _ScopeRecorder()
    bindings = _bindings(agent_input, tmp_path, recorder)
    object.__setattr__(bindings, "model_type_setting", "punet")
    assert bindings.brain.plan([])["model_type"] == "wavenet"

    with bind_task_data_path(recorder):
        prepared = prepare_attempt(
            bindings,
            attempt_ordering=AttemptOrdering(),
            identity=AttemptIdentity(round_index=1, attempt_in_round=1, is_formal_round=False),
            total_attempts=1,
            attempts_this_round=1,
            formal_trial_winner=None,
        )

    assert prepared.model_type == "punet"
    assert prepared.model_config["depth"] == 3
