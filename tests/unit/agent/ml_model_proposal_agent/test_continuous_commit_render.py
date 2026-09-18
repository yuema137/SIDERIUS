"""Regression: normalized continuous contracts crashed legacy commit rendering.

Without these checks, a declared regression request never reaches the commit
call because the renderer asks the candidate-probe authority for a classifier.
"""

import re

import pytest

from agent.schemas.model_io_contract import (
    Dimension,
    DtypeAdmissibility,
    ModelIOContract,
    TensorAxis,
    TensorContract,
)
from agent.schemas.task_config import ForwardContract
from agent.skills.model_io_probe_skill import ProbeConstructionError, declared_output_tensor
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import _render_commit_system_prompt


@pytest.mark.parametrize("dimensions", [("B", "T"), ("B", "C", "H", "W")])
@pytest.mark.parametrize("allowed", [None, ("regressor",)])
def test_continuous_commit_does_not_invent_a_classifier(dimensions, allowed):
    tensor = TensorContract(
        axes=tuple(TensorAxis(dimension=Dimension(symbolic=d)) for d in dimensions),
        dtype=DtypeAdmissibility(admissible=("float32",)),
    )
    model_io = ModelIOContract(input=tensor, output=tensor)
    contract = ForwardContract(
        model_io=model_io,
        input_shape=tensor.render(),
        input_description="synthetic measurement",
        output_shape=tensor.render(),
        output_description="continuous prediction",
    )

    prompt = _render_commit_system_prompt(contract, allowed_output_types=allowed)

    assert '"output_type": "regressor" — REQUIRED.' in prompt
    assert "task declares no classifier output form" in prompt
    assert tensor.render_shape() in prompt
    assert re.findall(r"\{[A-Z][A-Z_]*\}", prompt) == []
    with pytest.raises(ProbeConstructionError, match="no class-alphabet axis"):
        _render_commit_system_prompt(contract, allowed_output_types=("classifier",))
    # Rendering an available option must not weaken rejection of an actual
    # incompatible candidate or manufacture a class axis for the probe.
    with pytest.raises(ProbeConstructionError, match="no class-alphabet axis"):
        declared_output_tensor(model_io, "classifier")
