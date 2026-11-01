"""Inactive conditional rules survive real planning, persistence and planner history."""

import pytest

from agent.prompts import get_planner_user_prompt
from agent.schemas.hyperparam_tuning import ExperimentRecord
from agent.schemas.parameter_rules import ParameterRules
from tests.unit.agent.tune_ml_hyperparam_agent.test_physical_rejection_capture import (
    FAKE_VRAM_OK,
    _make_input,
    _make_oom_payload,
    _setup,
    agent_with_scripted_skill,
)

pytestmark = pytest.mark.usefixtures("synthetic_run_authorities")


@pytest.mark.parametrize("verdict", [FAKE_VRAM_OK, _make_oom_payload()])
def test_inactive_rule_is_recorded_and_visible_to_next_planner(
    tmp_path, agent_with_scripted_skill, verdict, capsys
):
    """Both success and preflight-refusal paths must retain the attempt's receipt."""
    agent, saved, _, cleanup = _setup(agent_with_scripted_skill, [verdict])
    inputs = _make_input(tmp_path, max_rounds=1)
    inputs.workflow_parameter_rules = ParameterRules.model_validate(
        {"loss_config.beta": {"exact": 2.0}}
    )
    try:
        output = agent.run(inputs)
    finally:
        cleanup()
    assert output.all_records
    record = saved[0]
    typed = ExperimentRecord.model_validate(record)
    (receipt,) = typed.inactive_parameter_rules
    assert (receipt.path, receipt.loss_type, receipt.owner) == (
        "loss_config.beta",
        "ce",
        "workflow",
    )
    assert receipt.rule.exact == 2.0
    assert "beta" not in record["params"]["loss_config"]
    assert "inactive_parameter_rules" not in record["params"]
    assert "inactive for this attempt" in capsys.readouterr().out
    for history in ([record], [record] * 5):
        prompt = get_planner_user_prompt(history, force_model="punet")
        assert '"inactive_parameter_rules"' in prompt
        assert '"inactive_for_selected_loss"' in prompt
        assert '"loss_config.beta"' in prompt
