"""Issue #437: cold entry must bind before real model-plugin discovery.

Warm runner tests cannot catch import-time contamination: their mocks import
the workflow owner before main. These children use the current installation,
real argv/main and real registry loading from temporary plugin files. Only
the lightweight loader's legacy path constant is redirected; no source path,
registry function, workspace binder or workflow implementation is replaced.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_RUNNER = _REPO / "src/workflows/run_one_iteration.py"
_REPORT_PREFIX = "BOOTSTRAP_REPORT="

_CHILD = """
import json
import os
import runpy
import sys

from ml_models import plugin_loader

route, runner, legacy, *argv = sys.argv[1:]
plugin_loader.AGENT_GENERATED_DIR = legacy
assert "ml_models.models_sandbox" not in sys.modules
assert "core.resume" not in sys.modules
assert "workflows.model_exploration" not in sys.modules
status = 0
sys.argv = [runner, *argv]
try:
    if route == "unbound":
        import ml_models.models_sandbox
    elif route == "script":
        runpy.run_path(runner, run_name="__main__")
    else:
        runpy.run_module("workflows.run_one_iteration", run_name="__main__")
except SystemExit as exc:
    status = exc.code

# Observe the loaded module without importing it after an early CLI refusal.
models = sys.modules.get("ml_models.models_sandbox")
registry = {} if models is None else models.MODEL_REGISTRY
print("BOOTSTRAP_REPORT=" + json.dumps({
    "legacy_registered": "bootstrap_legacy" in registry,
    "selected_registered": "bootstrap_selected" in registry,
    "models_imported": models is not None,
    "resume_imported": "core.resume" in sys.modules,
    "workflow_imported": "workflows.model_exploration" in sys.modules,
    "library_root": os.environ.get("SIDERIUS_GENERATED_LIBRARY_DIR"),
    "chain_workspace": os.environ.get("SIDERIUS_CHAIN_WORKSPACE"),
}))
sys.exit(status)
"""


def _write_sentinel(directory: Path, name: str, marker: Path) -> None:
    """Write a loadable plugin whose import is visible without constructing it."""
    directory.mkdir(parents=True)
    (directory / f"{name}.py").write_text(
        textwrap.dedent(f"""\
            from pathlib import Path
            from pydantic import BaseModel
            from torch.nn import Module

            Path({str(marker)!r}).write_text("imported", encoding="utf-8")
            PLUGIN_MODEL_TYPE = {name!r}
            PLUGIN_CONFIG_CLASS = BaseModel
            PLUGIN_MODEL_CLASS = Module
            PLUGIN_OUTPUT_TYPE = "regressor"
            """),
        encoding="utf-8",
    )


@pytest.mark.parametrize("route", ["unbound", "script", "module", "help", "missing-workspace"])
def test_cold_entry_selects_workspace_before_registry_loading(tmp_path: Path, route: str) -> None:
    """Fails on eager import or missing bind; disabling discovery fails positives.

    Unbound loading proves the legacy sentinel is real. Both supported main
    routes must exclude it AND register the selected-workspace sentinel.
    Help/missing-workspace must exit before either sentinel can be imported.
    """
    workspace = tmp_path / "selected-workspace"
    legacy = tmp_path / "legacy-models"
    legacy_marker = tmp_path / "legacy-imported"
    selected_marker = tmp_path / "selected-imported"
    _write_sentinel(legacy, "bootstrap_legacy", legacy_marker)
    _write_sentinel(workspace / "generated_library/models", "bootstrap_selected", selected_marker)
    neutral_cwd = tmp_path / "neutral"
    neutral_cwd.mkdir()
    argv = [
        "--workspace",
        str(workspace),
        "--run_name",
        "bootstrap",
        "--start_iteration",
        "1",
        "--task_composition",
        str(_REPO / "configs/task_composition/quickstart.yaml"),
        "--data_dir",
        str(neutral_cwd),
        "--healthgate_mode",
        "blocking",
        "--result_authority",
        "scientific",
        "--no-runtime_watchdog",  # Do not discover/probe hardware for a config view.
        "--print_resolved_launch_config",
    ]
    if route == "help":
        argv = ["--help"]
    elif route == "missing-workspace":
        argv = argv[2:]
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("SIDERIUS_")
        and key not in {"PYTHONPATH", "OPENAI_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY"}
    }
    # A stale root alone is not a workspace binding. main must replace it;
    # the unbound control must still load the legacy fallback beside it.
    env["SIDERIUS_GENERATED_LIBRARY_DIR"] = str(tmp_path / "stale-library")
    env["CUDA_VISIBLE_DEVICES"] = ""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            _CHILD,
            route if route in {"script", "unbound"} else "module",
            str(_RUNNER),
            str(legacy),
            *argv,
        ],
        cwd=neutral_cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == (2 if route == "missing-workspace" else 0), (
        result.stdout + result.stderr
    )
    reports = [
        line.removeprefix(_REPORT_PREFIX)
        for line in result.stdout.splitlines()
        if line.startswith(_REPORT_PREFIX)
    ]
    assert len(reports) == 1, result.stdout + result.stderr
    report = json.loads(reports[0])
    bound = route in {"script", "module"}
    assert legacy_marker.exists() is (route == "unbound")
    assert report["legacy_registered"] is (route == "unbound")
    assert selected_marker.exists() is bound
    assert report["selected_registered"] is bound
    assert report["models_imported"] is (bound or route == "unbound")
    assert report["resume_imported"] is bound
    assert report["workflow_imported"] is bound
    if bound:
        assert report["library_root"] == str(workspace / "generated_library")
        assert report["chain_workspace"] == str(workspace)
        assert '"workspace":' in result.stdout  # The actual config-view exit was reached.
    elif route == "help":
        assert "--workspace" in result.stdout
    elif route == "missing-workspace":
        assert "the following arguments are required: --workspace" in result.stderr
