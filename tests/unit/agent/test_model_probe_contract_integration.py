"""Exercise declared probe geometry through real composition and child processes."""

import pytest

from agent.skills.task_model_validation import run_task_model_tests
from nodes.ml_code_validator_agent.ml_code_validator_agent import _check_instantiation_and_gradient
from nodes.ml_model_implementor.ml_model_implementor import _assemble_test, _smoke_test_plugin
from tests.unit.agent.test_task_model_probe import declared_task


def composed_fixture(tmp_path, *, binding="records"):
    declaration = {
        "description": "Full synthetic record set, with an explicit node-count field.",
        "symbolic_extent_config_field": binding,
        "config_fields": ["nodes"],
        "max_input_elements": 10000,
    }
    contract, context, _ = declared_task(
        tmp_path,
        input_axes=[
            {"role": "batch", "dimension": {"symbolic": "B"}},
            {"dimension": {"symbolic": "R"}},
            {"dimension": {"fixed": 4}},
        ],
        body="assert request.candidate_config == {'nodes': 11}\n"
        "    return torch.full(request.input_shape, 0.25, dtype=torch.float32)\n\n"
        f"QuickstartTaskDataPath.model_validation_contract = {declaration!r}\n",
    )
    return contract, context


def candidate(tmp_path, records):
    source = f'''import torch
from torch import nn
from pydantic import BaseModel
PLUGIN_MODEL_TYPE = "record_model"
PLUGIN_OUTPUT_TYPE = "classifier"
class Config(BaseModel):
    records: int = {records}
    nodes: int = 11
class Model(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.weights = nn.Parameter(torch.ones(config.records))
        self.head = nn.Linear(4, 2)
    def forward(self, x):
        assert tuple(x.shape) == (1, self.config.records, 4)
        return self.head((x * self.weights[None, :, None]).mean(1))
PLUGIN_CONFIG_CLASS = Config
PLUGIN_MODEL_CLASS = Model
'''
    models = tmp_path / "models"
    models.mkdir()
    path = models / "record_model.py"
    path.write_text(source)
    return path, source


@pytest.mark.parametrize("records", [137, 251])
def test_all_consumers_preserve_fixed_candidate_geometry_and_counts(tmp_path, records):
    contract, context = composed_fixture(tmp_path)
    path, source = candidate(tmp_path, records)
    assert _smoke_test_plugin(source, "record_model", contract, model_probe_context=context) is None
    verdict = _check_instantiation_and_gradient(str(path), contract, model_probe_context=context)
    assert all(verdict[:3]), verdict[3]
    assert verdict[4:] == (records + 10, records + 10)
    tests = tmp_path / "tests"
    tests.mkdir()
    generated = tests / "test_record_model.py"
    generated.write_text(_assemble_test("record_model", contract, model_probe_context=context))
    passed, output = run_task_model_tests(str(generated))
    assert passed, output


def test_missing_candidate_binding_remains_repairable_through_real_composition(tmp_path):
    contract, context = composed_fixture(tmp_path, binding="missing_field")
    path, source = candidate(tmp_path, 137)
    error = _smoke_test_plugin(source, "record_model", contract, model_probe_context=context)
    assert "missing_field" in error
    verdict = _check_instantiation_and_gradient(str(path), contract, model_probe_context=context)
    assert not verdict[0]
    assert "missing_field" in verdict[3]
