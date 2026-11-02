"""Reach the real offline consumer scenarios and inspect final provider arguments."""

import pytest

from tests.helpers.evaluation_rendering import evaluation_scope
from tests.unit.agent.ml_model_implementor.test_implementor_agent import (
    agent_with_mocks,
    inp,
    storage,
)
from tests.unit.agent.ml_model_implementor.test_implementor_agent import (
    test_constraints_reach_model_generation_and_repair as run_implementor,
)
from tests.unit.agent.ml_model_implementor.test_loss_generation_e2e import (
    agent_with_mocks as loss_agent,
)
from tests.unit.agent.ml_model_implementor.test_loss_generation_e2e import (
    custom_loss_spec,
    index_path,
    inp_loss_only,
)
from tests.unit.agent.ml_model_implementor.test_loss_generation_e2e import (
    test_constraints_reach_loss_generation_and_numerical_repair as run_loss,
)
from tests.unit.agent.ml_model_proposal_agent.test_proposal_agent import (
    agent,
)
from tests.unit.agent.ml_model_proposal_agent.test_proposal_agent import (
    test_legacy_reasoning_and_commit_receive_same_constraint_context as run_legacy,
)

pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")


def assert_evaluation(user):
    assert user.count("[TASK EVALUATION]") == 1
    assert "Fraction of correct predictions on the evaluation split." in user
    assert "validation_accuracy; maximize (higher is better)" in user
    assert "Mean absolute voltage error" in user
    assert "Constraints:\n- None declared." in user


def mock_prompts(bridge):
    calls = bridge.generate.call_args_list + bridge.generate_text.call_args_list
    assert calls
    for call in calls:
        assert_evaluation(call.args[1])
        assert "[TASK EVALUATION]\n" not in call.args[0]


def test_implementor_reasoning_code_and_repair(tmp_path, agent_with_mocks, inp, monkeypatch):
    with evaluation_scope(tmp_path):
        run_implementor(agent_with_mocks, inp, monkeypatch)
    mock_prompts(agent_with_mocks.bridge)


def test_proposer_legacy_reasoning_and_commit(tmp_path, agent):
    with evaluation_scope(tmp_path):
        run_legacy(agent, tmp_path)
    mock_prompts(agent.bridge)


def test_proposer_pipeline_and_causal_correction(tmp_path, monkeypatch):
    from tests.unit.agent.ml_model_proposal_agent import test_causal_stage_validation as scenario

    bridges = []
    original = scenario._agent

    def capture(bridge):
        bridges.append(bridge)
        return original(bridge)

    monkeypatch.setattr(scenario, "_agent", capture)
    with evaluation_scope(tmp_path):
        scenario.test_constraints_survive_causal_correction_and_proposing(tmp_path)
    assert len(bridges) == 1
    mock_prompts(bridges[0])
    for call in bridges[0].generate.call_args_list:
        if call.kwargs["label"] in ("proposer.comparison", "proposer.causal_reasoning"):
            assert "Every score in this prompt is on" not in call.args[0]


def test_tuner_planner_and_reflector(tmp_path):
    from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge
    from tests.helpers.tuner_prompt_fixtures import planner_kwargs
    from tests.unit.agent.llm_bridge.test_step00_prompt_goldens import (
        reflect_fixture_args,
        reflect_fixture_kwargs,
    )

    bridge = BoundaryRecorderBridge()
    with evaluation_scope(tmp_path):
        bridge.plan(**planner_kwargs())
        bridge.reflect(*reflect_fixture_args(), **reflect_fixture_kwargs())
    assert len(bridge.captures) == 2
    for _, _, _, user in bridge.captures:
        assert_evaluation(user)


@pytest.mark.parametrize("brief", [False, True])
def test_interpreter_primary_and_analysis_brief(tmp_path, monkeypatch, brief):
    from tests.unit.agent.result_interpretation_agent import (
        test_analysis_brief_generation as scenario,
    )

    bridges = []
    name = "_BriefBridge" if brief else "_LegacyBridge"
    factory = getattr(scenario, name)

    def capture(*args):
        bridge = factory(*args)
        bridges.append(bridge)
        return bridge

    monkeypatch.setattr(scenario, name, capture)
    with evaluation_scope(tmp_path):
        if brief:
            scenario.test_constraint_change_rejects_brief_reuse_and_receipt_hashes_sent_text(
                tmp_path
            )
        else:
            scenario.test_constraints_reach_primary_interpretation_calls(tmp_path)
    assert bridges
    if not brief:
        assert any(
            "Worst recorded score :" in user for bridge in bridges for _, _, user in bridge.calls
        )
    for bridge in bridges:
        for _, _, user in bridge.calls:
            assert_evaluation(user)
            assert "Worst denoising score:" not in user


def test_literature_search_and_synthesis_exclude_extraction(tmp_path, monkeypatch):
    from tests.unit.agent.ml_literature_review import test_node as scenario

    bridges = []
    factory = scenario.FakeBridge

    def capture(*args, **kwargs):
        bridge = factory(*args, **kwargs)
        bridges.append(bridge)
        return bridge

    monkeypatch.setattr(scenario, "FakeBridge", capture)
    with evaluation_scope(tmp_path):
        scenario.test_constraints_reach_search_and_synthesis_without_rewriting_source_facts(
            tmp_path, monkeypatch
        )
    assert bridges
    for bridge in bridges:
        for label, _, user in bridge.prompts:
            if label == "lit_review.paper_extract":
                assert "[TASK EVALUATION]" not in user
            else:
                assert_evaluation(user)


def test_validator_review(tmp_path):
    from unittest.mock import MagicMock

    from tests.unit.agent.ml_code_validator_agent import test_validator_agent as scenario

    agent = scenario.MLCodeValidatorAgent.__new__(scenario.MLCodeValidatorAgent)
    agent.bridge = MagicMock()
    agent.bridge.generate.return_value = scenario.FAKE_LLM_REVIEW
    with evaluation_scope(tmp_path):
        agent._llm_review(scenario.make_input(tmp_path), "class Model: pass")
    assert_evaluation(agent.bridge.generate.call_args.args[1])


def test_data_analysis_and_repair(tmp_path):
    from pydantic import BaseModel

    from agent.data_analysis.structured_output import generate_validated

    class Output(BaseModel):
        value: int

    class Bridge:
        def __init__(self):
            self.calls = []

        def generate(self, system, user, *, label):
            self.calls.append(user)
            return {"value": "bad"} if len(self.calls) == 1 else {"value": 3}

    class Store:
        def append_structured_output_receipt(self, receipt):
            pass

    bridge = Bridge()
    with evaluation_scope(tmp_path):
        result = generate_validated(
            bridge,
            store=Store(),
            model_type=Output,
            system="schema",
            user="choose",
            label="analysis",
            semantic_projection=lambda _: "same",
        )
    assert result.value == 3
    assert len(bridge.calls) == 2
    for user in bridge.calls:
        assert_evaluation(user)


def test_custom_loss_reasoning_code_and_numerical_repair(tmp_path, loss_agent, inp_loss_only):
    with evaluation_scope(tmp_path):
        run_loss(loss_agent, inp_loss_only)
    mock_prompts(loss_agent.bridge)
