"""Two bounded real pytest children, using the production validator launch."""

from __future__ import annotations

import subprocess
import time

import pytest

from core.local_code import LocalCodeError, bind_code_package
from ml_models.plugin_binding import bind_run_model_plugins
from nodes import ml_code_validator_agent as validator
from tests.helpers.local_code_model import MODEL_TYPE, make_package
from tests.unit.core.test_local_code_transport import bind_workspace
from tests.unit.core.test_resume import isolated_registries

pytestmark = pytest.mark.usefixtures("isolated_registries")


@pytest.mark.parametrize("changed", [False, True])
def test_real_validator_pytest_child_uses_capture_and_refuses_changed_helper(
    tmp_path, monkeypatch, changed
):
    package, binding = make_package(tmp_path / "task")
    bind_workspace(tmp_path, monkeypatch)
    marker = tmp_path / "collected"
    test_file = tmp_path / "test_declared.py"
    test_file.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
        "from ml_models.models_sandbox import MODEL_REGISTRY\n"
        "from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY\n"
        "def test_helper_identity():\n"
        f" assert MODEL_REGISTRY[{MODEL_TYPE!r}].__module__.endswith('._helper')\n"
        f" assert PLUGIN_CONFIG_REGISTRY[{MODEL_TYPE!r}].__module__ == MODEL_REGISTRY[{MODEL_TYPE!r}].__module__\n"
    )
    if changed:
        (package.root / "_helper.py").write_text("raise AssertionError('changed code executed')\n")
    real_run = subprocess.run
    durations = []

    def bounded_run(*args, **kwargs):
        started = time.monotonic()
        try:
            return real_run(*args, **kwargs, timeout=60)
        finally:
            durations.append(time.monotonic() - started)
            print(f"cold validator child changed={changed}: {durations[-1]:.3f}s")

    monkeypatch.setattr(validator.subprocess, "run", bounded_run)
    with bind_code_package(package), bind_run_model_plugins(binding):
        if changed:
            with pytest.raises(LocalCodeError, match="mismatch"):
                validator._run_tests(str(test_file))
            assert not marker.exists()
        else:
            passed, output = validator._run_tests(str(test_file))
            assert passed, output
            assert marker.exists()
            assert "1 passed" in output
    assert len(durations) == 1
