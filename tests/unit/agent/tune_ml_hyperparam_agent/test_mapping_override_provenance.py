"""Whole config replacements must explain omitted keys through the real tuner loop."""

import pytest

from agent.prompts import PLANNER_FULL_WINDOW, get_planner_user_prompt
from tests.unit.agent.tune_ml_hyperparam_agent.test_condensed_resolution_history import (
    _later,
    _planner_history,
    _run_one_attempt,
)
from tests.unit.agent.tune_ml_hyperparam_agent.test_physical_rejection_capture import (
    agent_with_scripted_skill,
)

pytestmark = pytest.mark.usefixtures("synthetic_run_authorities")


@pytest.mark.parametrize("outcome", ["success", "skip", "error"])
def test_train_mapping_replacement_explains_omitted_epochs(
    tmp_path, agent_with_scripted_skill, outcome, capsys
):
    """A partial lr override replaces epochs; it must not look like untracked data loss."""
    record = _run_one_attempt(
        tmp_path, agent_with_scripted_skill, outcome, {"train_config": {"lr": 0.002}}
    )
    assert "epochs" not in record["params"]["train_config"]
    event = next(e for e in record["resolution_events"] if e["field_path"] == "train_cfg.epochs")
    assert event == {
        "field_path": "train_cfg.epochs",
        "proposed": "5",
        "executed": "not supplied in the resolved configuration; plan_overrides uses whole-dictionary replacement",
        "authority": "operator_plan_overrides",
    }
    assert (
        "not supplied in the resolved configuration; plan_overrides uses whole-dictionary replacement"
        in capsys.readouterr().out
    )
    for history in ([record], [record] + [_later(i) for i in range(PLANNER_FULL_WINDOW)]):
        rendered = _planner_history(get_planner_user_prompt(history))[0]
        assert event in rendered["resolution_events"]


@pytest.mark.parametrize(
    ("field", "authored", "replacement", "removed_path"),
    [
        (
            "model_config",
            {"depth": 4, "segmentation_size": 40000, "batch_size": 1},
            {"segmentation_size": 40000, "batch_size": 1},
            "model_cfg.depth",
        ),
        ("loss_config", {"loss_type": "ce", "beta": 0.5}, {"loss_type": "ce"}, "loss_cfg.beta"),
    ],
)
def test_other_config_mappings_share_replacement_provenance(
    tmp_path, agent_with_scripted_skill, field, authored, replacement, removed_path
):
    """The same operator replacement boundary governs model and loss dictionaries."""
    record = _run_one_attempt(
        tmp_path,
        agent_with_scripted_skill,
        "success",
        {field: replacement},
        plan={field: authored},
    )
    assert removed_path.split(".")[-1] not in record["params"][field]
    event = next(e for e in record["resolution_events"] if e["field_path"] == removed_path)
    assert (
        event["executed"]
        == "not supplied in the resolved configuration; plan_overrides uses whole-dictionary replacement"
    )
    assert event["authority"] == "operator_plan_overrides"
