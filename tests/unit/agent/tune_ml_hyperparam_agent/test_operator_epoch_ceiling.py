"""Explicit epoch ceilings must survive planning through execution above 100."""

import json
from pathlib import Path

import pytest

from tests.helpers._pseudo_data import load_pseudo_data
from tests.helpers.recording_llm_bridge import RecordingLLMBridge
from tests.helpers.step00_pseudo_iteration import (
    PSEUDO_AGENT_FOLDER,
    run_bounded_pseudo_iteration,
)

pytestmark = pytest.mark.usefixtures("synthetic_run_authorities")


@pytest.mark.parametrize(
    "overrides,expected",
    [
        (
            {
                "max_epochs": 350,
                "trial_max_epochs": 300,
                "formal_max_epochs": 250,
                "plan_overrides": {"train_config": {"epochs": 600}},
            },
            (300, 250),
        ),
        ({"max_epochs": 400}, (400, 400)),
        ({"max_epochs": None}, (500, 500)),
    ],
)
def test_large_plan_reaches_execution_under_resolved_role_caps(
    tmp_path, monkeypatch, overrides, expected
):
    """The real tuner validates the execution config after overrides/full_clone.

    The preflight and training tools are canned; this checks configuration
    delivery, not actual training time or GPU admission.
    """
    responses = load_pseudo_data("api_call_outputs", PSEUDO_AGENT_FOLDER)
    for plan in responses["generate"]:
        plan["train_config"]["epochs"] = 500
    if "plan_overrides" in overrides:
        # plan_overrides replaces a complete section, rather than deep-merging it.
        overrides = {
            **overrides,
            "plan_overrides": {
                "train_config": {**responses["generate"][0]["train_config"], "epochs": 600}
            },
        }
    preflight = json.loads(
        Path(__file__).with_name("fixtures").joinpath("step00_preflight_results.json").read_text()
    )["results"]
    output, _, sandbox, _ = run_bounded_pseudo_iteration(
        tmp_path,
        monkeypatch,
        preflight_results=preflight,
        bridge=RecordingLLMBridge(responses=responses),
        input_overrides=overrides,
    )
    successes = [record for record in output.all_records if record.status == "success"]
    trials = [record for record in successes if record.is_trial]
    formals = [record for record in successes if not record.is_trial]
    assert trials and formals
    assert {record.params["train_config"]["epochs"] for record in trials} == {expected[0]}
    assert {record.params["train_config"]["epochs"] for record in formals} == {expected[1]}

    executed = {call[1]: call[4] for call in sandbox.calls if call[0] == "execute_training"}
    assert set(executed) == {record.exp_id for record in successes}
    for record in successes:
        assert executed[record.exp_id]["epochs"] == expected[0 if record.is_trial else 1]


def test_training_tool_and_planner_manual_agree_with_executor_for_large_schedules():
    """An executor-supported schedule must also be expressible to its planner."""
    from agent.skills.check_config_format_skill.wrapper import run_skill
    from ml_models.models_format_sandbox import TrainConfig

    root = Path(__file__).resolve().parents[4]
    tool = json.loads((root / "src/agent/skills/training_skill/skill_config.json").read_text())
    tool_training = tool["parameters"]["properties"]["train_config"]
    manual_training = run_skill(None)["data"]["schemas"]["TrainConfig"]
    supplied = {"lr": 0.001, "batch_size": 4, "epochs": 500}
    tool_epochs = tool_training["properties"]["epochs"]
    manual_epochs = manual_training["properties"]["epochs"]
    assert tool_epochs == {"type": "integer", "minimum": 1}
    assert manual_epochs == {**tool_epochs, "default": 10, "title": "Epochs"}
    assert TrainConfig.model_validate(supplied).epochs == 500
    for invalid in (0, -1, 1.5):
        with pytest.raises(ValueError):
            TrainConfig.model_validate({**supplied, "epochs": invalid})
