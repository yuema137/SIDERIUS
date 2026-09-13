"""Real CPU-only guarded children through the production observed-parent seam."""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest

from core.local_code import LocalCodeError, bind_code_package
from core.sandbox_executor import _run_observed_subprocess
from core.subprocess_env import subprocess_env
from tests.unit.core.test_local_code_failure import package_and_env


@pytest.mark.parametrize("integrity", [True, False])
def test_real_parent_refusal_reaches_runtime_without_ordinary_error_conversion(
    tmp_path, monkeypatch, integrity
):
    runtime = importlib.import_module("nodes.ml_hyperparameter_tune_agent.runtime")
    skill = importlib.import_module("agent.skills.training_skill.wrapper")
    package = package_and_env(tmp_path, monkeypatch)
    target = tmp_path / "target.py"
    target.write_text("raise SystemExit(78)\n")

    def execute_training(**kwargs):
        env = subprocess_env()
        if integrity:
            (tmp_path / "helper.py").write_text("VALUE = 4\n")
        return _run_observed_subprocess(
            [sys.executable, str(target)],
            env=env,
            preexec_fn=None,
            capture_stdout=True,
        )

    monkeypatch.setattr(skill, "run_skill", lambda sandbox, **kw: sandbox.execute_training(**kw))
    sandbox = SimpleNamespace(execute_training=execute_training)
    with bind_code_package(package):
        if integrity:
            with pytest.raises(LocalCodeError, match="digest mismatch") as raised:
                runtime._run_skill("training_skill", sandbox)
            assert raised.value.report.package_digest == package.identity.digest
        else:
            result = runtime._run_skill("training_skill", sandbox)
            assert result["status"] == "error"
            assert "non-zero exit status 1" in result["message"]
