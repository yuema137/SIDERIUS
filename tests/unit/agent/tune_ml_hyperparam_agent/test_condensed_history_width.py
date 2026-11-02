"""Condensed history summarizes each value, while retaining every event and path."""

from copy import deepcopy

import pytest

from agent.prompts import PLANNER_FULL_WINDOW, get_planner_user_prompt
from agent.schemas.hyperparam_tuning import ExperimentPlan
from nodes.ml_hyperparameter_tune_agent.parameter_rule_receipts import (
    attach_attempt_receipts,
    resolution_event_record,
)
from nodes.ml_hyperparameter_tune_agent.provenance import ResolutionTracker
from tests.unit.agent.tune_ml_hyperparam_agent.test_condensed_resolution_history import (
    _later,
    _planner_history,
)


@pytest.mark.parametrize("fields", [1, 256])
def test_many_resolution_events_keep_paths_and_summarize_each_value(fields):
    """Wide LLM model configs have no aggregate entry cap or silent event omissions."""
    keys = [f"layer_{i:03d}_" + "parameter_" * 50 for i in range(fields)]
    authored = ExperimentPlan(model_cfg={key: "old" * 1000 for key in keys})
    resolved = authored.model_copy(update={"model_cfg": {key: "new" * 1000 for key in keys}})
    record = {
        "exp_id": "wide_model",
        "status": "success",
        "params": resolution_event_record(ResolutionTracker(authored).finish(resolved)),
        "memory": {"hypothesis": "many model fields", "round_index": 1},
    }
    attach_attempt_receipts(record)
    history = [record] + [_later(i) for i in range(PLANNER_FULL_WINDOW)]
    original = deepcopy(history)
    condensed = _planner_history(get_planner_user_prompt(history))[0]
    assert "params" not in condensed
    events = condensed["resolution_events"]
    assert [event["field_path"] for event in events] == [f"model_cfg.{key}" for key in keys]
    for event in events:
        assert event["authority"] == "unattributed"
        for name, token in (("proposed", "old"), ("executed", "new")):
            whole = repr(token * 1000)
            assert event[name] == (
                f"{whole[:60]} … (3002 chars; full value in the persisted record) … {whole[-20:]}"
            )
    recent = _planner_history(get_planner_user_prompt([record]))[0]
    assert recent["resolution_events"] == record["resolution_events"]
    assert history == original
