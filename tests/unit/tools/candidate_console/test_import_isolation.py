"""Importing the console must never execute generated model plugins.

Defect caught: a module-scope import that pulls ``ml_models.models_sandbox``
into the console's import graph. That module's import tail scans the global
generated library (``SIDERIUS_GENERATED_LIBRARY_DIR``) and executes every
plugin file it finds, so the console would run unrelated generated code, vary
with the developer's machine, and print ``[PluginLoader]`` lines to stdout
(which the browser harnesses parse as JSON). The regression entered through
``tools.candidate_console.graph_results`` -> ``tools.candidate_worker.
loop_evidence`` -> ``core.resume`` -> ``core.sandbox_executor``.

Failure mode: the sentinel plugin writes its marker file and/or
``ml_models.models_sandbox`` appears in the child's ``sys.modules``. The
positive control fails if the sentinel stops being reachable by the loader,
so the isolation assertions cannot pass vacuously.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

_PROBE = """
import importlib, json, sys
module = importlib.import_module(sys.argv[1])
print(json.dumps({
    "file": module.__file__,
    "models_sandbox": "ml_models.models_sandbox" in sys.modules,
}))
"""


def _sentinel_library(tmp_path: Path) -> tuple[Path, Path]:
    library = tmp_path / "library"
    (library / "models").mkdir(parents=True)
    marker = tmp_path / "sentinel_executed"
    (library / "models" / "sentinel_probe.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
    )
    return library, marker


def _import_in_child(module: str, library: Path) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key != "SIDERIUS_PLUGIN_DIRS"}
    env["SIDERIUS_GENERATED_LIBRARY_DIR"] = str(library)
    return subprocess.run(
        [sys.executable, "-c", _PROBE, module],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize(
    "module", ["tools.candidate_console.app", "tools.candidate_worker.loop_evidence"]
)
def test_console_import_does_not_execute_generated_plugins(module, tmp_path):
    library, marker = _sentinel_library(tmp_path)
    result = _import_in_child(module, library)

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert len(lines) == 1, f"import wrote to stdout: {result.stdout!r}"
    report = json.loads(lines[0])
    assert Path(report["file"]).resolve().is_relative_to(REPO_ROOT / "src")
    assert report["models_sandbox"] is False
    assert not marker.exists(), "importing the console executed a generated plugin"


def test_sentinel_is_reachable_by_the_plugin_loader(tmp_path):
    library, marker = _sentinel_library(tmp_path)
    result = _import_in_child("ml_models.models_sandbox", library)

    assert result.returncode == 0, result.stderr
    assert marker.read_text() == "executed"
