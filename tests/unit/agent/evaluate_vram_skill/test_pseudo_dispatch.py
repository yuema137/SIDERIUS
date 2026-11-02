"""The tuner must select synthetic admission from the actual sandbox type."""

import importlib
from unittest.mock import MagicMock

import pytest

from core.stub_sandbox import StubSandbox
from execute_tools.data_paths import bind_physical_data_root

execution = importlib.import_module("nodes.ml_hyperparameter_tune_agent.execution")


@pytest.mark.parametrize("pseudo", [True, False])
def test_tuner_dispatches_only_stub_sandbox(tmp_path, monkeypatch, pseudo):
    """Forcing pseudo_training=False loses the stub witness; True loses the real one."""
    with bind_physical_data_root(str(tmp_path)):
        sandbox = StubSandbox(workspace=str(tmp_path)) if pseudo else MagicMock()
    bindings = MagicMock(sandbox=sandbox)
    prepared = MagicMock()
    monkeypatch.setattr(execution, "_check_and_record_guardrail_skip", lambda **kw: False)
    monkeypatch.setattr(execution, "build_attempt_task_probe_data", lambda **kw: None)
    seen = []

    class ReachedAdapter(Exception):
        pass

    def capture(**kwargs):
        seen.append(kwargs["pseudo_training"])
        raise ReachedAdapter

    monkeypatch.setattr(execution, "run_production_preflight", capture)
    with pytest.raises(ReachedAdapter):
        execution.run_admission_preflight(
            bindings,
            prepared,
            MagicMock(),
            MagicMock(),
            formal_trial_winner=None,
            physical_rejections_buffer=[],
        )
    assert seen == [pseudo]
