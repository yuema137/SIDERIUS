"""Measurement must construct the same contract-owned head as native training."""

from unittest.mock import Mock

import pytest
from pydantic import BaseModel

from agent.schemas.model_io_contract import ModelIOContract
from core.runtime_control import gpu_measurement_worker_main as worker
from tests.unit.core.test_gpu_measurement_worker import MODEL_TYPE, _spec


def _contract(*, class_axis=True):
    return ModelIOContract.model_validate(
        {
            "input": {
                "axes": [{"dimension": {"symbolic": "B"}, "role": "batch"}],
                "dtype": {"admissible": ["float32"]},
            },
            "output": {
                "axes": [
                    {"dimension": {"symbolic": "B"}, "role": "batch"},
                    {
                        "dimension": {"fixed": 3},
                        **({"role": "class"} if class_axis else {}),
                    },
                ],
                "dtype": {"admissible": ["float32"]},
            },
        }
    )


@pytest.fixture
def register(monkeypatch):
    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
    from ml_models.models_sandbox import MODEL_REGISTRY

    def install(config):
        monkeypatch.setitem(PLUGIN_CONFIG_REGISTRY, MODEL_TYPE, config)
        monkeypatch.setitem(MODEL_REGISTRY, MODEL_TYPE, object)

    return install


@pytest.mark.parametrize("phase", ["training", "inference"])
def test_prevalidation_derives_required_cardinality_before_either_builder(
    tmp_path, register, phase
):
    """A required config field must not reject a value owned by the contract."""

    class Config(BaseModel):
        num_classes: int

    register(Config)
    spec = _spec(tmp_path, None, model_config_payload={}, model_io_contract=_contract())
    spec = spec.model_copy(update={"request": spec.request.model_copy(update={"phase": phase})})
    before = spec.model_dump_json()
    assert worker.validate_candidate_configs(spec) is None
    assert spec.model_dump_json() == before, "derivation must not rewrite request identity"


@pytest.mark.parametrize("phase", ["training", "inference"])
def test_worker_reports_contract_conflict_before_model_or_data_work(
    tmp_path, register, monkeypatch, phase
):
    """A schema-valid but contradictory head must not enter setup in either phase."""

    class Config(BaseModel):
        num_classes: int = 5

    register(Config)
    spec = _spec(
        tmp_path, None, model_config_payload={"num_classes": 4}, model_io_contract=_contract()
    )
    spec = spec.model_copy(update={"request": spec.request.model_copy(update={"phase": phase})})
    build = Mock(side_effect=AssertionError("conflicting config reached model/data setup"))
    monkeypatch.setattr(worker, "build_production_components", build)
    report = worker.measure(spec)
    assert report.status == "CONFIG_REJECTED"
    assert "ContractCardinalityConflictError" in report.detail
    assert "num_classes=4" in report.detail
    assert "derives 3" in report.detail
    build.assert_not_called()


@pytest.mark.parametrize(
    ("contract_kind", "payload", "expected"),
    [
        ("classes", {}, 3),
        ("classes", {"num_classes": 3}, 3),
        ("no_class_axis", {}, 5),
        ("absent", {}, 5),
    ],
)
def test_training_constructor_receives_resolved_head_without_rewriting_request(
    tmp_path, register, monkeypatch, contract_kind, payload, expected
):
    """Fixing only prevalidation would still measure the plugin's wrong default."""
    from ml_models import models_sandbox

    class Config(BaseModel):
        num_classes: int = 5

    class ConstructorReached(Exception):
        pass

    received = []

    def construct(model_type, config, **kwargs):
        received.append(config.num_classes)
        raise ConstructorReached

    register(Config)
    monkeypatch.setattr(models_sandbox, "construct_registered_model", construct)
    contract = (
        None if contract_kind == "absent" else _contract(class_axis=contract_kind == "classes")
    )
    spec = _spec(tmp_path, None, model_config_payload=payload, model_io_contract=contract)
    before = spec.model_dump_json()
    with pytest.raises(ConstructorReached):
        worker.build_production_components(spec)()
    assert received == [expected]
    assert spec.model_dump_json() == before
