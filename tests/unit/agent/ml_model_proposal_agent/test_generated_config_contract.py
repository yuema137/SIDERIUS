"""Reject contradictory generated defaults before spending implementation calls."""

from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from agent.schemas.implementor import ImplementorInput
from agent.schemas.parameter_rules import ParameterRules
from agent.schemas.proposal import (
    CustomLossSpec,
    ProposalInput,
    ProposalOutput,
    ReasoningPipelineConfig,
    ReasoningStage,
)
from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import local_full_spec
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from ml_models.models_format_sandbox import AEConfig
from nodes.ml_model_implementor import MLModelImplementor
from nodes.ml_model_proposal_agent import MLModelProposalAgent

from .test_pipeline_runner import (
    FAKE_COMPARISON_OUTPUT,
    FAKE_PROPOSING_OUTPUT,
    FAKE_REASONING_OUTPUT,
)


def proposal(config):
    raw = deepcopy(FAKE_PROPOSING_OUTPUT)
    raw["baseline_config"]["model_config"] = config
    return raw


def storage(tmp_path):
    return StorageConfig(
        backend="local", local=LocalStorageConfig(workspace=str(tmp_path), run_name="contract")
    )


@pytest.mark.parametrize("value", [[2, 2, 3], {"layers": 3}, "64", None])
def test_live_generation_rejects_structured_defaults_but_archives_remain_readable(value, tmp_path):
    raw = proposal({"model_type": "novel", "blocks_per_stage": value})
    raw["custom_loss_spec"] = CustomLossSpec(
        loss_name="custom_objective",
        description="Mean squared prediction error.",
        mathematical_definition="mean((prediction - target) ** 2)",
    ).model_dump()
    raw["baseline_config"]["loss_config"] = {"loss_type": "custom", "loss_name": "custom_objective"}
    archived = ProposalOutput.model_validate(raw)
    assert archived.baseline_config == raw["baseline_config"]
    with pytest.raises(ValidationError, match=r"model_config.blocks_per_stage"):
        ProposalOutput.model_validate(raw, context={"implementation_bound": True})
    # Transport/deserialization preserve archives; actual execution refuses them.
    transported = local_full_spec(archived, storage(tmp_path))
    reloaded = ImplementorInput.model_validate_json(transported.model_dump_json())
    assert reloaded.baseline_config == raw["baseline_config"]
    bridge = MagicMock()
    implementor = MLModelImplementor(
        bridge_factory=lambda **kw: bridge,
        capability_index_path=str(tmp_path / "capabilities.json"),
    )
    implementor._generate_loss = MagicMock()
    before = sorted(tmp_path.rglob("*"))
    with pytest.raises(ValueError, match=r"model_config.blocks_per_stage"):
        implementor.run(reloaded)
    assert not bridge.mock_calls
    implementor._generate_loss.assert_not_called()
    assert sorted(tmp_path.rglob("*")) == before


def test_scalar_defaults_and_routing_identifiers_are_preserved(tmp_path):
    config = {"model_type": "novel", "model_name": None, "width": 64, "dropout": 0.2, "bias": True}
    output = ProposalOutput.model_validate(proposal(config), context={"implementation_bound": True})
    assert local_full_spec(output, storage(tmp_path)).baseline_config["model_config"] == config


def test_reuse_keeps_structured_values_but_model_type_alone_is_not_reuse(tmp_path):
    config = {"model_type": "fcnet", "latent_dims": [64, 16]}
    assert AEConfig(**config).latent_dims == [64, 16]
    with pytest.raises(ValidationError, match="latent_dims"):
        ProposalOutput.model_validate(proposal(config), context={"implementation_bound": True})
    config["model_name"] = "registered_plugin"
    output = ProposalOutput.model_validate(
        proposal(config),
        context={"implementation_bound": True, "model_registry_names": ["registered_plugin"]},
    )
    transported = local_full_spec(output, storage(tmp_path))
    transported.validate_for_implementation()
    assert transported.baseline_config["model_config"] == config
    with pytest.raises(ValidationError, match="Phantom Branch B"):
        ProposalOutput.model_validate(
            proposal(config), context={"implementation_bound": True, "model_registry_names": []}
        )


def input_for(tmp_path, *, pipeline):
    return ProposalInput(
        interpretation_evidence={},
        forward_contract={
            "input_shape": "[B, T]",
            "output_shape": "[B, T]",
            "output_description": "continuous targets",
        },
        reasoning_pipeline=ReasoningPipelineConfig(
            stages=[
                ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
                ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
            ]
            if pipeline
            else []
        ),
        storage=storage(tmp_path),
    )


def agent_for(bridge, tmp_path):
    return MLModelProposalAgent(
        bridge_factory=lambda **kw: bridge,
        capability_index_path=str(tmp_path / "capabilities.json"),
    )


def test_pipeline_repairs_the_offending_path_and_transports_only_corrected_defaults(tmp_path):
    bridge = MagicMock()
    bad = proposal({"blocks_per_stage": [2, 2, 3]})
    good = proposal({"stage_one_blocks": 2, "stage_two_blocks": 2, "stage_three_blocks": 3})
    bridge.generate.side_effect = [FAKE_COMPARISON_OUTPUT, FAKE_REASONING_OUTPUT, bad, good]
    inp = input_for(tmp_path, pipeline=True)
    result = agent_for(bridge, tmp_path).run(inp)
    assert bridge.generate.call_count == 4
    retry_prompt = bridge.generate.call_args_list[-1].args[1]
    assert "baseline_config.model_config.blocks_per_stage" in retry_prompt
    for call in bridge.generate.call_args_list:
        assert "Generated model configuration contract" in call.args[1]
    assert local_full_spec(result, inp.storage).baseline_config == good["baseline_config"]


def test_legacy_refuses_once_and_explains_contract_to_both_calls(tmp_path):
    bridge = MagicMock()
    bridge.generate_text.return_value = "Reasoning"
    bridge.generate.return_value = proposal({"widths": [32, 64]})
    with pytest.raises(ValidationError, match=r"model_config\.widths"):
        agent_for(bridge, tmp_path).run(input_for(tmp_path, pipeline=False))
    assert bridge.generate.call_count == 1
    assert "Generated model configuration contract" in bridge.generate.call_args.args[1]
    assert "Generated model configuration contract" in bridge.generate_text.call_args.args[1]


def test_exact_rule_is_validated_after_resolution(tmp_path):
    bridge = MagicMock()
    bridge.generate_text.return_value = "Reasoning"
    bridge.generate.return_value = proposal({"width": 64})
    inp = input_for(tmp_path, pipeline=False)
    inp.workflow_parameter_rules = ParameterRules.model_validate(
        {"model_config.width": {"exact": [32, 64]}}
    )
    with pytest.raises(ValidationError, match=r"model_config\.width"):
        agent_for(bridge, tmp_path).run(inp)


pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")


def test_template_absence_and_other_configuration_envelopes_are_unchanged(tmp_path):
    raw = proposal({"model_type": "novel", "segmentation_size": None, "width": 64})
    raw["baseline_config"]["train_config"]["lr_schedule"] = {"kind": "step", "gamma": 0.5}
    raw["baseline_config"]["loss_config"]["weights"] = [1.0, 2.0]
    result = ProposalOutput.model_validate(raw, context={"implementation_bound": True})
    assert local_full_spec(result, storage(tmp_path)).baseline_config == raw["baseline_config"]
