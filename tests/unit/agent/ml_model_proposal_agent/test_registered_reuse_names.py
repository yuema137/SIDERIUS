"""A verified reuse selector exempts only its own name from generation collisions."""

from unittest.mock import MagicMock, patch

import pytest

from agent.schemas.parameter_rules import ParameterRules
from agent.schemas.proposal import ProposalOutput

from .test_generated_config_contract import agent_for, input_for, proposal
from .test_pipeline_runner import FAKE_COMPARISON_OUTPUT, FAKE_REASONING_OUTPUT

pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")


@pytest.mark.parametrize("pipeline", [False, True])
@pytest.mark.parametrize(
    "selector, registered, accepted",
    [
        ("saved_model", ["saved_model"], True),
        (None, ["saved_model"], False),
        ("other_model", ["saved_model", "other_model"], False),
        ("saved_model", [], False),
    ],
)
def test_live_reuse_exception_is_registry_and_identity_bound(
    tmp_path, pipeline, selector, registered, accepted
):
    raw = proposal({"model_name": selector, "width": 32})
    raw["model_name"] = "saved_model"
    # Reading old records is separate from validating a new live selection.
    assert ProposalOutput.model_validate(raw).model_name == "saved_model"
    bridge = MagicMock()
    bridge.generate_text.return_value = "Reasoning"
    bridge.generate.side_effect = (
        [FAKE_COMPARISON_OUTPUT, FAKE_REASONING_OUTPUT, raw, raw, raw] if pipeline else [raw]
    )
    inp = input_for(tmp_path, pipeline=pipeline)
    inp.existing_model_types = ["saved_model"]
    with patch(
        "nodes.ml_model_proposal_agent.ml_model_proposal_agent._live_model_registry_names",
        return_value=registered,
    ):
        if accepted:
            result = agent_for(bridge, tmp_path).run(inp)
            assert result.model_name == "saved_model"
            assert result.baseline_config["model_config"]["model_name"] == "saved_model"
        else:
            with pytest.raises(
                RuntimeError if pipeline else ValueError, match=r"already exists|Phantom Branch B"
            ):
                agent_for(bridge, tmp_path).run(inp)
    expected_calls = (3 if accepted else 5) if pipeline else 1
    assert bridge.generate.call_count == expected_calls


@pytest.mark.parametrize("pipeline", [False, True])
def test_name_validation_uses_resolved_parameter_rules(tmp_path, pipeline):
    raw = proposal({"width": 32})
    raw["model_name"] = "saved_model"
    bridge = MagicMock()
    bridge.generate_text.return_value = "Reasoning"
    bridge.generate.side_effect = (
        [FAKE_COMPARISON_OUTPUT, FAKE_REASONING_OUTPUT, raw] if pipeline else [raw]
    )
    inp = input_for(tmp_path, pipeline=pipeline)
    inp.existing_model_types = ["saved_model"]
    inp.workflow_parameter_rules = ParameterRules.model_validate(
        {"model_config.model_name": {"exact": "saved_model"}}
    )
    with patch(
        "nodes.ml_model_proposal_agent.ml_model_proposal_agent._live_model_registry_names",
        return_value=["saved_model"],
    ):
        result = agent_for(bridge, tmp_path).run(inp)
    assert result.baseline_config["model_config"]["model_name"] == "saved_model"
    assert bridge.generate.call_count == (3 if pipeline else 1)
