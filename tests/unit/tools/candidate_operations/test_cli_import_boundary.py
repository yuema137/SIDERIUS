"""Read-only operation CLI must not bootstrap execution or import model plugins."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.candidate_operations.files import publish
from tools.candidate_operations.models import SpawnFailure
from tools.candidate_operations.store import claim, locked_store


@pytest.mark.parametrize("command", ["help", "status"])
def test_read_cli_avoids_execution_registry(admitted, tmp_path, command):
    """Importing the execution registry pollutes JSON and runs unrelated plugin code."""
    config, submission, record = admitted
    with locked_store(config) as store:
        path = claim(store, record)
        publish(
            path / "spawn_failure.json",
            SpawnFailure(operation_id=submission.request_id, request_digest=record.request_digest),
        )
    config_path = tmp_path / "store.json"
    config_path.write_text(config.model_dump_json())
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    sentinel = tmp_path / "plugin-imported"
    (plugins / "observable.py").write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('imported')\n"
        "print('UNEXPECTED PLUGIN IMPORT')\n"
    )
    # Explicit input makes the regression independent of a developer's home library.
    env = {**os.environ, "SIDERIUS_PLUGIN_DIRS": str(plugins)}
    argv = (
        ["--help"]
        if command == "help"
        else [
            "status",
            "--store-config",
            str(config_path),
            "--operation-id",
            str(submission.request_id),
        ]
    )
    probe = """
import runpy, sys
try:
    runpy.run_module('tools.candidate_operations', run_name='__main__')
except SystemExit:
    assert 'core.sandbox_executor' not in sys.modules
    assert 'ml_models.models_sandbox' not in sys.modules
    raise
"""
    result = subprocess.run(
        [sys.executable, "-c", probe, *argv],
        cwd=Path(__file__).resolve().parents[4],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert not sentinel.exists(), "read-only CLI executed a discoverable model plugin"
    if command == "help":
        assert result.stdout.startswith("usage:")
    else:
        observed = json.loads(result.stdout)
        assert observed["operation_id"] == str(submission.request_id)
        assert (observed["state"], observed["reason"]) == ("operation_failed", "spawn_failed")
