"""Regression for #1393: numeric task inputs must not become embedding indices."""

import pytest
import torch

from agent.llm_bridge import StubLLMBridge
from agent.schemas.implementor import ImplementorInput
from agent.schemas.model_io_contract import ModelIOContract
from agent.schemas.task_config import ForwardContract
from agent.stub_model import UnsupportedStubShapeError, stub_model_code
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
