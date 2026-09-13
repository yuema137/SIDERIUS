"""Delayed declared callbacks must survive config/admission classifiers."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from core.local_code import (
    CodePackageDeclaration,
    LocalCodeError,
    acquire_module,
    bind_code_package,
    capture_package,
)
from core.runtime_control.gpu_measurement_worker_main import validate_candidate_configs
from execute_tools.task_data_path import bind_task_data_path
from tests.unit.core.test_gpu_measurement_runner import _spec


@pytest.mark.parametrize("boundary", ["config", "guardrail"])
@pytest.mark.parametrize("integrity", [True, False])
def test_delayed_callback_keeps_named_identity_and_ordinary_classification(
    tmp_path, monkeypatch, boundary, integrity
):
    source = tmp_path / "callbacks.py"
    refusal = (
        "from .undeclared import value"
        if integrity
        else "raise ValueError('ordinary invalid input')"
    )
    source.write_text(
        "from pydantic import BaseModel, model_validator\n"
        f"def fail():\n {refusal}\n"
        "class Config(BaseModel):\n"
        " @model_validator(mode='before')\n"
        " @classmethod\n"
        " def validate_input(cls, value): return fail()\n"
        "class Task:\n"
        " task_data_path_id = 'local-code-refusal'\n"
        " def training_dataset(self, scope, params): return fail()\n"
    )
    package = capture_package(CodePackageDeclaration(root=".", files=("callbacks.py",)), tmp_path)
    with bind_code_package(package), acquire_module(source) as module:
        if boundary == "config":
            monkeypatch.setattr(
                "ml_models.models_format_sandbox.get_config_class", lambda _name: module.Config
            )

            def invoke():
                return validate_candidate_configs(_spec(tmp_path))
        else:
            runtime = importlib.import_module("nodes.ml_hyperparameter_tune_agent.runtime")

            def invoke():
                return runtime._resolve_task_scope_guardrail_steps(
                    task_scopes=SimpleNamespace(training={"rows": [1]}),
                    data_dir=str(tmp_path),
                    train_cfg={"epochs": 1, "batch_size": 1},
                    train_portion=1.0,
                    max_samples=None,
                )

        with bind_task_data_path(module.Task()):
            if integrity:
                with pytest.raises(LocalCodeError, match="undeclared relative import"):
                    invoke()
            else:
                result = invoke()
                if boundary == "config":
                    assert "ordinary invalid input" in result
                else:
                    assert result is None
