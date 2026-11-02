"""Draft validation must run inside repair, before any advisory observes it."""

from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from agent.schemas.proposal import ProposalOutput
from tests.unit.agent.ml_model_proposal_agent.test_preflight_advisory import (
    FAKE_COMPARISON_OUTPUT,
    FAKE_GOOD_DRAFT,
    FAKE_REASONING_OUTPUT,
    _agent,
    _legacy_input,
    _pipeline_input,
)

pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")
_PREFLIGHT = "nodes.ml_model_proposal_agent.ml_model_proposal_agent._run_preflight_check"


@pytest.mark.parametrize(
    "supplied, field",
    [
        ({"batch_size": 0}, "batch_size"),
        ({"batch_size": -1}, "batch_size"),
        ({"batch_size": []}, "batch_size"),
        ({"batch_size": True}, "batch_size"),
        ({"epochs": True}, "epochs"),
        ({"epochs": "invalid"}, "epochs"),
        ({"epochs": 0}, "epochs"),
        ({"epochs": None}, "epochs"),
        ({"drop_last": "invalid"}, "drop_last"),
        ({"drop_last": None}, "drop_last"),
        ({"lr_schedule": {"kind": "cosine", "horizon_epochs": 10, "min_lr": 0.01}}, "min_lr"),
        ({"optimizer_type": "unknown"}, "optimizer_type"),
        (None, "train_config"),
        ([], "train_config"),
    ],
)
@pytest.mark.parametrize("pipeline", [True, False])
def test_supplied_training_errors_are_repairable_before_preflight(
    tmp_path, supplied, field, pipeline
):
    """Revert leaks the bad draft to preflight or emits it without a repair call."""
    bad = deepcopy(FAKE_GOOD_DRAFT)
    bad["baseline_config"]["train_config"] = supplied
    bridge = MagicMock()
    bridge.generate_text.return_value = "reasoning"
    bridge.generate.side_effect = (
        [FAKE_COMPARISON_OUTPUT, FAKE_REASONING_OUTPUT, bad, FAKE_GOOD_DRAFT] if pipeline else [bad]
    )
    with patch(_PREFLIGHT, return_value=None) as preflight:
        if pipeline:
            output = _agent(bridge).run(_pipeline_input(tmp_path))
            assert bridge.generate.call_count == 4
            assert field in bridge.generate.call_args.args[1]
            assert output.baseline_config == FAKE_GOOD_DRAFT["baseline_config"]
            preflight.assert_called_once()
            assert preflight.call_args.args[1] is output
        else:
            with pytest.raises(ValidationError, match=field):
                _agent(bridge).run(_legacy_input(tmp_path))
            assert bridge.generate.call_count == 1
            preflight.assert_not_called()


@pytest.mark.parametrize("pipeline", [True, False])
def test_preflight_receives_normalized_supplied_values_without_filling_omissions(
    tmp_path, pipeline
):
    """Catches validating then forwarding raw values, and injecting owner defaults."""
    raw = deepcopy(FAKE_GOOD_DRAFT)
    supplied = {"batch_size": "8", "epochs": 2.0, "drop_last": "false", "extension": {"keep": 1}}
    raw["baseline_config"]["train_config"] = supplied
    bridge = MagicMock()
    bridge.generate_text.return_value = "reasoning"
    bridge.generate.side_effect = (
        [FAKE_COMPARISON_OUTPUT, FAKE_REASONING_OUTPUT, raw] if pipeline else [raw]
    )
    with patch(_PREFLIGHT, return_value=None) as preflight:
        output = _agent(bridge).run((_pipeline_input if pipeline else _legacy_input)(tmp_path))
    observed = preflight.call_args.args[1].baseline_config["train_config"]
    assert observed == {"batch_size": 8, "epochs": 2, "drop_last": False, "extension": {"keep": 1}}
    assert type(observed["batch_size"]) is int
    assert type(observed["epochs"]) is int
    assert observed["drop_last"] is False
    assert output.baseline_config["train_config"] == observed
    assert supplied["batch_size"] == "8"  # No mutation of the LLM response.


@pytest.mark.parametrize("baseline", [{}, {"train_config": {}}])
def test_omitted_training_fields_remain_omitted(baseline):
    raw = {**FAKE_GOOD_DRAFT, "baseline_config": baseline}
    assert ProposalOutput.model_validate(raw).baseline_config == baseline
