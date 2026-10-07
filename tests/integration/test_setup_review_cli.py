"""Offline CLI qualification from a fresh external user directory."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def test_external_cli_is_inert_and_outputs_exact_local_declaration(tmp_path):
    project = tmp_path / "user project <example>"
    project.mkdir()
    manifest = project / "task.yaml"
    manifest.write_text("plugin: ./task_plugin.py\n")
    plugin = project / "task_plugin.py"
    plugin.write_text("from pathlib import Path\nPath('PLUGIN_EXECUTED').touch()\n")
    advice = project / "advice.json"
    advice.write_text(json.dumps({"propose": '<script>not markup</script> & "advice"'}))
    llm = project / "llm.json"
    llm.write_text('{"implement":{"provider":"openai","model_id":"test-model"}}')
    args = [
        "--workspace",
        "runs",
        "--run_name",
        "example",
        "--start_iteration",
        "1",
        "--task_composition",
        "task.yaml",
        "--data_dir",
        "data",
        "--advice",
        "advice.json",
        "--llm_config",
        "llm.json",
    ]
    request = project / "request.json"
    request.write_text(json.dumps({"working_directory": str(project), "argv": args}))
    inputs = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in project.iterdir()}
    # In a new process these tripwires also catch imports hidden by pytest's
    # fixture imports. The caller never loads a task module or provider SDK.
    script = """
import importlib.abc
import runpy
import socket
import subprocess
import sys

forbidden_modules = (
    'workflows.run_one_iteration', 'workflows.model_exploration',
    'workflows.task_composition', 'agent.llm_bridge', 'dotenv',
    'openai', 'google.genai', 'google.generativeai', 'task_plugin',
)
class BlockExecution(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + '.')
               for name in forbidden_modules):
            raise AssertionError('effectful import: ' + fullname)
sys.meta_path.insert(0, BlockExecution())

def forbidden(*args, **kwargs):
    raise AssertionError('inspection attempted runtime, network or hardware work')

socket.socket.connect = forbidden
socket.create_connection = forbidden
original_popen = subprocess.Popen
def guarded_popen(argv, *args, **kwargs):
    # Existing h5py dependency import uses platform.processor(), which asks
    # uname for architecture metadata. Permit that exact read-only query only.
    if argv == ['uname', '-p']:
        return original_popen(argv, *args, **kwargs)
    return forbidden(argv, *args, **kwargs)
subprocess.Popen = guarded_popen
from core import hardware_context
hardware_context.discover = forbidden
sys.argv = ['tools.setup_review', '--request', 'request.json', '--output', sys.argv[1]]
runpy.run_module('tools.setup_review', run_name='__main__')
"""
    output = project / "review"
    environment = dict(
        os.environ, PYTHONDONTWRITEBYTECODE="1", OPENAI_API_KEY="never-print-test-key"
    )
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-c", script, str(output)],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((output / "report.json").read_text())
    html = (output / "index.html").read_text()
    assert report["request"] == {"working_directory": str(project), "argv": args}
    assert report["launch_argv"] == [sys.executable, "-m", "workflows.run_one_iteration", *args]
    assert report["outcome"] == "declaration_inspected"
    assert report["llm_review"] == "not_performed"
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "never-print-test-key" not in (output / "report.json").read_text() + html + result.stdout
    assert set(project.iterdir()) == set(inputs) | {output}
    assert all(
        hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in inputs.items()
    )
    assert not (project / "runs").exists()
    assert not (project / "PLUGIN_EXECUTED").exists()
