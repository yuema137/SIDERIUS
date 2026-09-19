"""A legal declared-length model must not be rejected by a shorter smoke input.

Both production consumers execute real forward passes: reverting either wiring
makes the reflection fixture fail before training. Fixed extents also exercise
required config construction, not merely a schema/default assertion.
"""

import importlib

import pytest

from agent.schemas.model_io_contract import (
    AxisRole,
    Dimension,
    DtypeAdmissibility,
    ModelIOContract,
    TensorAxis,
    TensorContract,
)

_impl = importlib.import_module("nodes.ml_model_implementor.ml_model_implementor")
_val = importlib.import_module("nodes.ml_code_validator_agent.ml_code_validator_agent")


def contract(fixed=None):
    tensor = TensorContract(
        axes=(
            TensorAxis(dimension=Dimension(symbolic="B"), role=AxisRole.BATCH),
            TensorAxis(
                dimension=Dimension(fixed=fixed) if fixed else Dimension(symbolic="L"),
                role=AxisRole.TEMPORAL,
            ),
        ),
        dtype=DtypeAdmissibility(admissible=("float32",)),
    )
    return ModelIOContract(input=tensor, output=tensor)


def plugin(length):
    field = "Field(ge=1)" if length is None else str(length)
    return f"""import torch
from torch import nn
from pydantic import BaseModel, Field
PLUGIN_MODEL_TYPE = "reflection_probe"
PLUGIN_OUTPUT_TYPE = "regressor"
class Config(BaseModel):
    segmentation_size: int = {field}
class Model(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.length = config.segmentation_size
        self.bias = nn.Parameter(torch.zeros(()))
    def forward(self, x):
        assert x.shape[-1] == self.length, "probe and config lengths disagree"
        y = torch.nn.functional.pad(x.unsqueeze(1), (96,96), mode="reflect")
        return y[:,0,96:-96] + self.bias
PLUGIN_CONFIG_CLASS = Config
PLUGIN_MODEL_CLASS = Model
"""


@pytest.mark.parametrize("length,fixed", [(192, None), (384, None), (None, 192)])
def test_both_nodes_accept_legal_declared_length(tmp_path, length, fixed):
    source = plugin(length)
    path = tmp_path / "reflection_probe.py"
    path.write_text(source)
    declaration = contract(fixed)
    assert _impl._smoke_test_plugin(source, "reflection_probe", declaration) is None
    result = _val._check_instantiation_and_gradient(str(path), declaration)
    assert result[:4] == (True, True, True, None), result


def test_probe_config_conflict_is_diagnosed_before_model_forward(tmp_path):
    source = plugin(384)
    path = tmp_path / "reflection_probe.py"
    path.write_text(source)
    for error in (
        _impl._smoke_test_plugin(source, "reflection_probe", contract(192)),
        _val._check_instantiation_and_gradient(str(path), contract(192))[3],
    ):
        assert error and "Probe contract conflict" in error
        assert "192" in error and "384" in error
