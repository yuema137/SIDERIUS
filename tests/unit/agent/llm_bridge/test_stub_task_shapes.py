"""Regression for #1393: numeric task inputs must not become embedding indices."""

import pytest
import torch

from agent.llm_bridge import StubLLMBridge
from agent.schemas.implementor import ImplementorInput
from agent.schemas.model_io_contract import ModelIOContract
from agent.schemas.proposal import ProposalOutput
from agent.schemas.task_config import ForwardContract
from agent.stub_model import UnsupportedStubShapeError, stub_model_code
from ml_models.models_format_sandbox import validate_semantic_loss_compatibility
from nodes.ml_model_implementor import MLModelImplementor, _assemble_plugin
from tests.helpers.probe_seed import PROBE_SEED
from workflows.task_config import bind_task_config


def _contract(input_shape: tuple, output_shape: tuple, class_axis: int | None) -> ModelIOContract:
    def tensor(shape: tuple, output: bool) -> dict:
        axes = []
        for index, extent in enumerate(shape):
            role = "batch" if index == 0 else "class" if output and index == class_axis else None
            dimension = {"fixed": extent} if isinstance(extent, int) else {"symbolic": extent}
            axes.append({"role": role, "dimension": dimension})
        return {"axes": axes, "dtype": {"admissible": ["float32"]}}

    return ModelIOContract.model_validate(
        {"input": tensor(input_shape, False), "output": tensor(output_shape, True)}
    )


@pytest.mark.parametrize(
    ("input_shape", "output_shape", "class_axis"),
    [
        (("B", 3, 144, 144), ("B", 37), 1),
        (("B", "T"), ("B", 256, "T"), 1),
        (("B", 1, 3800), ("B", 2), 1),
        (("B", 224, 11), ("B", 2), 1),
        (("B", 2, 24576), ("B", 1), None),
        (("B", 2, 1024), ("B", 1), None),
        (("B", 1, 1024), ("B", 1), None),
        (("B", "R", 68), ("B", "R", 3), 2),
        (("B", 3, 8, 128, 224), ("B", 3, 4, 128, 224), None),
    ],
)
def test_bound_stub_passes_candidate_check_and_runtime_shapes(
    input_shape: tuple, output_shape: tuple, class_axis: int | None
) -> None:
    """Old stub fails on negative inputs and emits the wrong output geometry."""
    contract = _contract(input_shape, output_shape, class_axis)
    forward = ForwardContract(model_io=contract)
    with bind_task_config({"forward_contract": forward.model_dump()}):
        bridge = StubLLMBridge()
        code = bridge._synthesise_json("implementor.code")
        inp = ImplementorInput(
            model_name="stub_shape_test",
            model_description="Synthetic shape witness",
            mathematical_definition="Scalar projection",
            forward_contract=forward,
            baseline_config=bridge._synthesise_json("proposer.proposing")["baseline_config"],
            output_type=contract.legacy_output_type,
        )
        assert MLModelImplementor._validate_code(code, inp, PROBE_SEED) is None
        namespace: dict = {}
        exec(_assemble_plugin(inp, code), namespace)
        model = namespace["PLUGIN_MODEL_CLASS"](
            namespace["PLUGIN_CONFIG_CLASS"](segmentation_size=7)
        )
        for batch, length in ((1, 7), (2, 13)):
            symbols = {"B": batch, "T": length, "R": length}
            shape = tuple(symbols.get(dim, dim) for dim in input_shape)
            expected = tuple(symbols.get(dim, dim) for dim in output_shape)
            output = model(torch.full(shape, -300.5))
            assert tuple(output.shape) == expected
            output.mean().backward()
            assert all(parameter.grad is not None for parameter in model.parameters())


def test_unresolved_output_symbol_is_named_before_plugin_execution() -> None:
    """Do not silently use the probe's arbitrary extent as a runtime output size."""
    contract = _contract(("B", 4), ("B", "unbound"), None)
    with pytest.raises(UnsupportedStubShapeError, match=r"output axis 1.*unbound"):
        stub_model_code(contract)


def _bound_stub(contract: ModelIOContract):
    """Assemble the pseudo plugin exactly as the implementor admits it."""
    forward = ForwardContract(model_io=contract)
    with bind_task_config({"forward_contract": forward.model_dump()}):
        bridge = StubLLMBridge()
        code = bridge._synthesise_json("implementor.code")
        inp = ImplementorInput(
            model_name="stub_dtype_test",
            model_description="Synthetic dtype witness",
            mathematical_definition="Scalar projection",
            forward_contract=forward,
            baseline_config=bridge._synthesise_json("proposer.proposing")["baseline_config"],
            output_type=contract.legacy_output_type,
        )
        failure = MLModelImplementor._validate_code(code, inp, PROBE_SEED)
    namespace: dict = {}
    exec(_assemble_plugin(inp, code), namespace)
    model = namespace["PLUGIN_MODEL_CLASS"](namespace["PLUGIN_CONFIG_CLASS"](segmentation_size=7))
    return failure, model


def _with_output_dtypes(contract: ModelIOContract, admissible: list[str]) -> ModelIOContract:
    raw = contract.model_dump(mode="json")
    raw["output"]["dtype"] = {"admissible": admissible}
    return ModelIOContract.model_validate(raw)


@pytest.mark.parametrize(
    ("admissible", "expected"),
    [(["float64"], torch.float64), (["int64", "bfloat16", "float32"], torch.bfloat16)],
)
def test_stub_emits_the_first_admissible_floating_output_dtype(admissible, expected) -> None:
    """A float32-only stub fails the candidate check for float64-only contracts."""
    contract = _with_output_dtypes(_contract(("B", 2, 16), ("B", 1), None), admissible)
    failure, model = _bound_stub(contract)
    assert failure is None
    output = model(torch.zeros(2, 2, 16))
    assert output.dtype == expected
    output.float().mean().backward()


def test_stub_refuses_a_non_floating_output_contract_before_plugin_code() -> None:
    """Otherwise the refusal only surfaces through a repeated smoke/repair cycle."""
    contract = _with_output_dtypes(_contract(("B", 4), ("B", 3), 1), ["int64", "uint8"])
    with pytest.raises(UnsupportedStubShapeError, match=r"output dtype \['int64', 'uint8'\]"):
        stub_model_code(contract)


def test_stub_output_owns_storage_for_in_place_loss_steps() -> None:
    """An expanded scalar aliases one element; in-place writes on it raise."""
    _, model = _bound_stub(_contract(("B", "T"), ("B", 256, "T"), 1))
    output = model(torch.zeros(2, 5))
    with torch.no_grad():
        output[:, 0] = 1.0
    assert output[:, 1:].abs().max().item() == 0.0


@pytest.mark.usefixtures("synthetic_dataset_profile")
@pytest.mark.parametrize(
    ("input_shape", "output_shape", "class_axis"),
    [
        (("B", 2, 1024), ("B", 1), None),
        (("B", "R", 68), ("B", "R", 3), None),
        (("B", 3, 8, 128, 224), ("B", 3, 4, 128, 224), None),
        (("B", 3, 144, 144), ("B", 37), 1),
        (("B", "T"), ("B", 256, "T"), 1),
    ],
)
def test_proposal_semantics_reach_the_implementor_and_loss_authority(
    input_shape: tuple, output_shape: tuple, class_axis: int | None
) -> None:
    """#1403: a classifier proposal for a continuous contract fails the probe.

    The implementor receives ``output_type`` from the synthesised proposal, not
    from the test, and both proposal and planner losses must pass the loss
    authority for the contract's own output semantic.
    """
    contract = _contract(input_shape, output_shape, class_axis)
    forward = ForwardContract(model_io=contract)
    with bind_task_config({"forward_contract": forward.model_dump()}):
        bridge = StubLLMBridge()
        proposal = ProposalOutput.model_validate(bridge._synthesise_json("proposer.proposing"))
        planner_loss = bridge._synthesise_json("tuner.planner")["loss_config"]["loss_type"]
        inp = ImplementorInput(
            model_name=proposal.model_name,
            model_description=proposal.model_description,
            mathematical_definition=proposal.mathematical_definition,
            forward_contract=forward,
            baseline_config=proposal.baseline_config,
            output_type=proposal.output_type,
        )
        code = bridge._synthesise_json("implementor.code")
        assert MLModelImplementor._validate_code(code, inp, PROBE_SEED) is None
    for loss in (proposal.baseline_config["loss_config"]["loss_type"], planner_loss):
        validate_semantic_loss_compatibility(
            contract.output_semantic,
            loss,
            model_type=proposal.model_name,
            output_has_temporal_axis=contract.output_has_temporal_axis,
        )
    narrative = (proposal.model_description, proposal.mathematical_definition)
    assert all(contract.output.render_shape() in text for text in narrative)
    assert "Embedding" not in proposal.model_description


@pytest.mark.usefixtures("synthetic_dataset_profile")
def test_unbound_fixtures_keep_the_legacy_sequence_narrative() -> None:
    """Unbound bridge fixtures have no contract to describe; their bytes stay put."""
    proposal = ProposalOutput.model_validate(StubLLMBridge()._synthesise_json("proposer.proposing"))
    assert proposal.output_type == "classifier"
    assert proposal.baseline_config["loss_config"]["loss_type"] == "ce"
    assert proposal.model_description.startswith("Stub architecture: nn.Embedding(256, hidden_dim)")
