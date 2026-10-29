"""Independent output geometry must survive every candidate acceptance route.

These regressions execute production consumers, including their generated pytest
and bounded child. Reintroducing a guessed output extent rejects the legal
candidates; dropping fixed/shared/batch checks admits the invalid candidates.
"""

import pytest

from agent.schemas.model_io_contract import ModelIOContract
from agent.skills.task_model_validation import run_task_model_tests
from core.probe_seeds import probe_seed_env
from nodes.ml_code_validator_agent.ml_code_validator_agent import _check_instantiation_and_gradient
from nodes.ml_model_implementor.ml_model_implementor import _assemble_test, _smoke_test_plugin
from tests.helpers.probe_seed import PROBE_SEED
from tests.unit.agent.test_task_model_probe import declared_task


def contract(*, output_dimension=None):
    batch = {"role": "batch", "dimension": {"symbolic": "B"}}
    return ModelIOContract.model_validate(
        {
            "input": {
                "axes": [
                    batch,
                    {"dimension": {"symbolic": "L"}, "role": "temporal"},
                    {"dimension": {"fixed": 4}},
                ],
                "dtype": {"admissible": ["float32"]},
            },
            "output": {
                "axes": [
                    batch,
                    {"dimension": output_dimension or {"symbolic": "K"}},
                    {"dimension": {"fixed": 2}},
                ],
                "dtype": {"admissible": ["float32"]},
            },
        }
    )


def candidate(tmp_path, *, rows=7, length=37, expression=None, require_fixture=False):
    expression = expression or "self.bias.expand(x.shape[0], self.rows, 2)"
    source = f"""import torch
from torch import nn
from pydantic import BaseModel
PLUGIN_MODEL_TYPE = "output_geometry_candidate"
PLUGIN_OUTPUT_TYPE = "regressor"
class Config(BaseModel):
    segmentation_size: int = {length}
class Model(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.rows = {rows}
        self.bias = nn.Parameter(torch.ones(()))
    def forward(self, x):
        {"assert torch.all(x == 0.25), 'illegal task fixture'" if require_fixture else "pass"}
        return {expression}
PLUGIN_CONFIG_CLASS = Config
PLUGIN_MODEL_CLASS = Model
"""
    models = tmp_path / "models"
    models.mkdir(exist_ok=True)
    path = models / "output_geometry_candidate.py"
    path.write_text(source)
    return path, source


def verdicts(tmp_path, io, *, context=None, **candidate_kwargs):
    path, source = candidate(tmp_path, **candidate_kwargs)
    smoke = _smoke_test_plugin(
        source, path.stem, io, model_probe_context=context, probe_seed=PROBE_SEED
    )
    direct = _check_instantiation_and_gradient(
        str(path), io, model_probe_context=context, probe_seed=PROBE_SEED
    )
    tests = tmp_path / "tests"
    tests.mkdir(exist_ok=True)
    generated = tests / "test_output_geometry_candidate.py"
    generated.write_text(_assemble_test(path.stem, io, model_probe_context=context))
    passed, output = run_task_model_tests(str(generated), seed_env=probe_seed_env(PROBE_SEED))
    return smoke, direct, passed, output


@pytest.mark.parametrize("rows,length", [(7, 37), (100, 71), (5000, 113)])
def test_independent_output_slots_pass_all_generic_consumers(tmp_path, rows, length):
    smoke, direct, passed, output = verdicts(tmp_path, contract(), rows=rows, length=length)
    assert smoke is None, smoke
    assert direct[:4] == (True, True, True, None), direct
    assert passed, output


@pytest.mark.parametrize(
    "dimension,expression",
    [
        ({"symbolic": "L"}, "self.bias.expand(x.shape[0], x.shape[1] + 1, 2)"),
        ({"fixed": 9}, "self.bias.expand(x.shape[0], 7, 2)"),
        ({"symbolic": "K"}, "self.bias.expand(x.shape[0] + 1, 7, 2)"),
        ({"symbolic": "K"}, "self.bias.expand(x.shape[0], 7, 3)"),
        ({"symbolic": "K"}, "self.bias.expand(x.shape[0], 7)"),
    ],
    ids=["shared-symbol", "fixed-slots", "batch", "fixed-features", "rank"],
)
def test_invalid_geometry_fails_all_generic_consumers(tmp_path, dimension, expression):
    smoke, direct, passed, output = verdicts(
        tmp_path, contract(output_dimension=dimension), expression=expression
    )
    assert smoke is not None
    assert not direct[0], direct
    assert not passed, output


@pytest.mark.parametrize("bounded", [False, True], ids=["fixture", "bounded-fixture"])
def test_task_owned_inputs_accept_independent_output_slots(tmp_path, bounded):
    body = "return torch.full(request.input_shape, 0.25, dtype=torch.float32)"
    if bounded:
        declaration = {
            "description": "Synthetic full sequence with independent output cardinality.",
            "symbolic_extent_config_field": "segmentation_size",
            "max_input_elements": 10000,
        }
        body += f"\n\nQuickstartTaskDataPath.model_validation_contract = {declaration!r}\n"
    io = contract()
    io, context, _ = declared_task(
        tmp_path,
        body=body,
        input_axes=io.model_dump(mode="json")["input"]["axes"],
        output_axes=io.model_dump(mode="json")["output"]["axes"],
    )
    smoke, direct, passed, output = verdicts(
        tmp_path, io, context=context, rows=100, length=71, require_fixture=True
    )
    assert smoke is None, smoke
    assert direct[:4] == (True, True, True, None), direct
    assert passed, output


def test_variable_output_cardinality_does_not_hide_broken_gradient(tmp_path):
    _, direct, passed, output = verdicts(
        tmp_path, contract(), expression="self.bias.detach().expand(x.shape[0], 7, 2)"
    )
    assert not direct[1], direct
    assert not passed, output


@pytest.mark.parametrize("dimension", [{"dynamic": True}, {"symbolic": "K"}])
def test_output_cardinality_can_change_between_generated_probe_calls(tmp_path, dimension):
    # Generated tests use both batch sizes. A symbol binding cached across
    # forwards would reject the second legal, differently sized event set.
    smoke, direct, passed, output = verdicts(
        tmp_path,
        contract(output_dimension=dimension),
        expression="self.bias.expand(x.shape[0], 7 * x.shape[0], 2)",
    )
    assert smoke is None, smoke
    assert direct[:4] == (True, True, True, None), direct
    assert passed, output
