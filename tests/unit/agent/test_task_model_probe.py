"""Strict semantic models must not be rejected using invalid random fixtures."""

import shutil
from pathlib import Path
from uuid import uuid4

import pytest
import torch
import yaml

from agent.schemas.model_probe import ModelProbeSetupError
from agent.schemas.parameter_rules import ParameterRules
from agent.skills.task_model_probe import legal_probe_batches, task_model_probe_cases
from agent.skills.validator_probe_worker import run_bounded_probe
from nodes.ml_code_validator_agent.ml_code_validator_agent import (
    _check_instantiation_and_gradient,
    _run_tests,
)
from nodes.ml_model_implementor.ml_model_implementor import _assemble_test, _smoke_test_plugin
from workflows.task_composition import build_task_composition_ref, compose_run_task_bindings

ROOT = Path(__file__).resolve().parents[3]


def declared_task(
    tmp_path,
    body="return torch.full(request.input_shape, 0.25, dtype=torch.float32)",
    *,
    batch=1,
    packaged=False,
    batch_sizes=None,
):
    pack = tmp_path / "task"
    shutil.copytree(ROOT / "examples/quickstart", pack)
    plugin = pack / "plugins/_quickstart_task.py"
    task_id = "probe_" + uuid4().hex
    plugin.write_text(
        plugin.read_text().replace("quickstart_tabular", task_id)
        + f"""

def _model_validation_input(self, request):
    import torch
    {body}

QuickstartTaskDataPath.model_validation_input = _model_validation_input
"""
    )
    manifest = yaml.safe_load((ROOT / "configs/task_composition/quickstart.yaml").read_text())
    manifest_text = (
        yaml.safe_dump(manifest)
        .replace("../../examples/quickstart/", str(pack) + "/")
        .replace("quickstart_tabular", task_id)
    )
    manifest = yaml.safe_load(manifest_text)
    manifest["parameter_rules"] = {"train_config.batch_size": {"exact": batch}}
    if batch_sizes is not None:
        plugin.write_text(
            plugin.read_text()
            + f"\nQuickstartTaskDataPath.model_validation_batch_sizes = {batch_sizes!r}\n"
        )
    if packaged:
        (pack / "plugins/probe_fixture.py").write_text(
            "import torch\ndef build(shape):\n    return torch.full(shape, 0.25)\n"
        )
        manifest["code_package"] = {
            "root": str(pack),
            "files": [str(p.relative_to(pack)) for p in sorted((pack / "plugins").glob("*.py"))],
        }
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump(manifest))
    composition = compose_run_task_bindings(str(path))
    context = build_task_composition_ref(composition).model_probe_context
    assert context is not None
    return composition.forward_contract.model_io, context, plugin


def strict_model(
    tmp_path, predicate="torch.allclose(x.sum(-1), torch.ones(x.shape[0]))", *, broken=False
):
    models = tmp_path / "models"
    models.mkdir(exist_ok=True)
    source = f"""import torch
from torch import nn
from pydantic import BaseModel
PLUGIN_MODEL_TYPE = "strict_fixture_model"
PLUGIN_OUTPUT_TYPE = "classifier"
class Config(BaseModel):
    segmentation_size: int = 64
    batch_size: int = 1
class Model(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.head = nn.Linear(4, 2)
    def forward(self, x):
        if x.shape[0] != 1 or not ({predicate}):
            raise ValueError("invalid task input")
        return self.head(x){".detach()" if broken else ""}
PLUGIN_CONFIG_CLASS = Config
PLUGIN_MODEL_CLASS = Model
"""
    path = models / "strict_fixture_model.py"
    path.write_text(source)
    return path, source


@pytest.mark.parametrize(
    "body,predicate",
    [
        (
            "return torch.full(request.input_shape, 0.25, dtype=torch.float32)",
            "torch.allclose(x.sum(-1), torch.ones(x.shape[0]))",
        ),
        (
            "return torch.arange(4, dtype=torch.float32).expand(request.input_shape).clone()",
            "bool((x[:, 1:] > x[:, :-1]).all())",
        ),
    ],
)
def test_strict_semantic_models_pass_all_consumers_and_children(tmp_path, body, predicate):
    contract, context, _ = declared_task(tmp_path, body)
    path, source = strict_model(tmp_path, predicate)
    torch.manual_seed(0)
    assert "invalid task input" in _smoke_test_plugin(source, "strict_fixture_model", contract)
    assert (
        _smoke_test_plugin(source, "strict_fixture_model", contract, model_probe_context=context)
        is None
    )
    assert all(
        _check_instantiation_and_gradient(str(path), contract, model_probe_context=context)[:3]
    )
    assert all(run_bounded_probe(str(path), contract, model_probe_context=context)[:3])
    tests = tmp_path / "tests"
    tests.mkdir()
    test_file = tests / "test_model.py"
    test_file.write_text(
        _assemble_test("strict_fixture_model", contract, model_probe_context=context)
    )
    passed, output = _run_tests(str(test_file), context)
    assert passed, output


@pytest.mark.parametrize(
    "body",
    [
        "return torch.zeros(request.input_shape, dtype=torch.int64)",
        "return torch.zeros((1, 3))",
        "return torch.full(request.input_shape, float('nan'))",
        "raise RuntimeError('broken fixture provider')",
    ],
)
def test_bad_provider_is_setup_error_instead_of_candidate_repair(tmp_path, body):
    contract, context, _ = declared_task(tmp_path, body)
    path, source = strict_model(tmp_path)
    with pytest.raises(ModelProbeSetupError):
        _smoke_test_plugin(source, "strict_fixture_model", contract, model_probe_context=context)
    with pytest.raises(ModelProbeSetupError):
        _check_instantiation_and_gradient(str(path), contract, model_probe_context=context)


def test_changed_task_identity_is_rejected_in_pytest_and_worker(tmp_path):
    contract, context, plugin = declared_task(tmp_path)
    path, _ = strict_model(tmp_path)
    tests = tmp_path / "tests"
    tests.mkdir()
    test_file = tests / "test_model.py"
    test_file.write_text(
        _assemble_test("strict_fixture_model", contract, model_probe_context=context)
    )
    task_id = "probe_" + uuid4().hex
    plugin.write_text(
        plugin.read_text().replace("quickstart_tabular", task_id)
        + "\n# Changed task implementation\n"
    )
    with pytest.raises(ModelProbeSetupError, match="identity"):
        _run_tests(str(test_file), context)
    with pytest.raises(ModelProbeSetupError, match="identity"):
        run_bounded_probe(str(path), contract, model_probe_context=context)


def test_broken_candidate_still_fails_gradient_check(tmp_path):
    contract, context, _ = declared_task(tmp_path)
    path, _ = strict_model(tmp_path, broken=True)
    verdict = _check_instantiation_and_gradient(str(path), contract, model_probe_context=context)
    assert verdict[:3] == (True, False, True)
    assert "Backward pass failed" in verdict[3]


def test_existing_rule_owner_controls_batches_without_task_specific_values(tmp_path):
    contract, context, _ = declared_task(tmp_path)
    assert [
        case.input.shape[0] for case in task_model_probe_cases(context, contract, "classifier")
    ] == [1]
    assert legal_probe_batches(
        contract, ParameterRules.model_validate({"train_config.batch_size": {"exact": 7}})
    ) == (7,)
    assert legal_probe_batches(
        contract,
        ParameterRules.model_validate({"train_config.batch_size": {"range": {"min": 3, "max": 4}}}),
    ) == (3,)
    assert legal_probe_batches(
        contract, ParameterRules.model_validate({"train_config.batch_size": {"allowed": [5, 7]}})
    ) == (5, 7)


def test_setup_failure_stops_validator_before_llm_review(tmp_path):
    from unittest.mock import MagicMock

    from agent.schemas.storage import LocalStorageConfig, StorageConfig
    from agent.schemas.validator import ValidatorInput
    from nodes.ml_code_validator_agent.ml_code_validator_agent import MLCodeValidatorAgent
    from workflows.model_exploration import _proposal_attempt_failure

    contract, context, _ = declared_task(tmp_path, "raise ValueError('fixture is invalid')")
    path, _ = strict_model(tmp_path)
    description = tmp_path / "description.md"
    description.write_text("A strict model for a deterministic probe setup failure test.")
    bridge = MagicMock()
    agent = MLCodeValidatorAgent(bridge_factory=lambda **kwargs: bridge)
    inp = ValidatorInput(
        model_type="strict_fixture_model",
        model_file_path=str(path),
        test_file_path="",
        description_file_path=str(description),
        config_fields={},
        model_description="strict fixture",
        mathematical_definition="linear",
        model_io_contract=contract,
        model_probe_context=context,
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="setup_failure"),
        ),
    )
    with pytest.raises(ModelProbeSetupError, match="fixture is invalid") as error:
        agent.run(inp)
    bridge.generate.assert_not_called()
    with pytest.raises(ModelProbeSetupError):
        _proposal_attempt_failure(error.value)


def test_context_travels_through_protocol_and_absence_does_not_change_records(tmp_path):
    from agent.schemas.implementor import ImplementorOutput
    from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import local_all_fields
    from agent.schemas.storage import LocalStorageConfig, StorageConfig
    from agent.schemas.validator import ValidatorInput

    contract, context, _ = declared_task(tmp_path)
    output = ImplementorOutput(
        model_type="fixture",
        model_file_path="/model.py",
        test_file_path="/test.py",
        description_file_path="/description.md",
        config_fields={},
        model_description="fixture",
        mathematical_definition="linear",
        model_io_contract=contract,
    )
    storage = StorageConfig(
        backend="local", local=LocalStorageConfig(workspace=str(tmp_path), run_name="protocol")
    )
    assert "model_probe_context" not in output.model_dump()
    assert "model_probe_context" not in local_all_fields(output, storage).model_dump()
    output.model_probe_context = context
    restored = ImplementorOutput.model_validate_json(output.model_dump_json())
    forwarded = local_all_fields(restored, storage)
    assert (
        ValidatorInput.model_validate_json(forwarded.model_dump_json()).model_probe_context
        == context
    )


def test_captured_task_helper_is_used_by_parent_and_children(tmp_path):
    from core.local_code.binding import bind_code_package

    contract, context, plugin = declared_task(
        tmp_path,
        "from .probe_fixture import build; return build(request.input_shape)",
        packaged=True,
    )
    path, source = strict_model(tmp_path)
    assert (
        _smoke_test_plugin(source, "strict_fixture_model", contract, model_probe_context=context)
        is None
    )
    assert all(run_bounded_probe(str(path), contract, model_probe_context=context)[:3])
    tests = tmp_path / "tests"
    tests.mkdir()
    test_file = tests / "test_model.py"
    test_file.write_text(
        _assemble_test("strict_fixture_model", contract, model_probe_context=context)
    )
    passed, output = _run_tests(str(test_file), context)
    assert passed, output
    composition = compose_run_task_bindings(context.manifest_path)
    with bind_code_package(composition.code_package):
        (plugin.parent / "probe_fixture.py").write_text(
            "raise RuntimeError('mutable host source')\n"
        )
        assert (
            _smoke_test_plugin(
                source, "strict_fixture_model", contract, model_probe_context=context
            )
            is None
        )


def test_wrong_candidate_output_declaration_is_not_a_setup_failure(tmp_path):
    from agent.skills.task_model_validation import check_task_model
    from tests.helpers.step04a_fixtures import regressor_model_io

    _, context, _ = declared_task(tmp_path)
    verdict = check_task_model(
        torch.nn.Linear(4, 2), object(), regressor_model_io(), context, "classifier", gradients=True
    )
    assert verdict[:3] == (False, False, False)
    assert "class-alphabet" in verdict[3]


def test_explicit_probe_batches_support_task_predicates(tmp_path):
    from agent.schemas.parameter_rules import register_parameter_predicate

    name = "probe_three_" + uuid4().hex
    register_parameter_predicate(name, lambda value: value == 3)
    contract, context, _ = declared_task(tmp_path, batch_sizes=(3,))
    manifest_path = Path(context.manifest_path)
    raw = yaml.safe_load(manifest_path.read_text())
    raw["parameter_rules"] = {"train_config.batch_size": {"predicate": name}}
    manifest_path.write_text(yaml.safe_dump(raw))
    composition = compose_run_task_bindings(str(manifest_path))
    context = build_task_composition_ref(composition).model_probe_context
    assert [
        case.input.shape[0] for case in task_model_probe_cases(context, contract, "classifier")
    ] == [3]


@pytest.mark.parametrize("batches", [(), (True,), (0,), "3"])
def test_invalid_explicit_probe_batches_refuse_without_fallback(tmp_path, batches):
    contract, context, _ = declared_task(tmp_path, batch_sizes=batches)
    with pytest.raises(ModelProbeSetupError, match="model_validation_batch_sizes"):
        task_model_probe_cases(context, contract, "classifier")
