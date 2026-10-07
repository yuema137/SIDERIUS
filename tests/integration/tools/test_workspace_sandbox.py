"""Real Linux namespaces; opt in on a host authorized to run bubblewrap."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools.workspace_sandbox.__main__ import _probe
from tools.workspace_sandbox.profile import SandboxProfile
from tools.workspace_sandbox.runner import run

pytestmark = pytest.mark.skipif(
    os.environ.get("SIDERIUS_TEST_WORKSPACE_SANDBOX") != "1",
    reason="set SIDERIUS_TEST_WORKSPACE_SANDBOX=1 on a bubblewrap-capable host",
)


def _profile(tmp_path, **overrides):
    work = tmp_path / "project with spaces"
    work.mkdir(exist_ok=True)
    return SandboxProfile.model_validate(
        {
            "workspace": work,
            "network": False,
            "timeout_seconds": 10,
            **overrides,
        }
    )


def test_real_python_and_mount_probe(tmp_path):
    config = _profile(tmp_path)
    assert run(config, _probe(config)).status == "completed"
    assert list(config.workspace.iterdir()) == []


def test_real_write_and_visibility_boundaries(tmp_path):
    config = _profile(tmp_path)
    frozen = config.workspace / "selected task"
    frozen.mkdir()
    original = frozen / "input.txt"
    original.write_text("do not change")
    hidden = tmp_path / "undeclared.txt"
    hidden.write_text("host-only")
    config = _profile(tmp_path, read_only=(frozen,))
    code = f"""
from pathlib import Path
import os, sys
assert not Path({str(hidden)!r}).exists()
for path in [{str(original)!r}, str(Path(sys.prefix) / 'unexpected-write'), '/unexpected-write']:
    try:
        with open(path, 'w') as f:
            f.write('wrong')
    except OSError:
        pass
    else:
        raise AssertionError('write was allowed: ' + path)
Path('result.txt').write_text('completed')
"""
    assert run(config, [sys.executable, "-c", code]).status == "completed"
    assert original.read_text() == "do not change"
    assert (config.workspace / "result.txt").read_text() == "completed"


def test_real_environment_and_network_namespace(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_ACCESS_KEY", "fake-key-only")
    monkeypatch.setenv("DO_NOT_FORWARD", "hidden")
    config = _profile(tmp_path, environment_names=("DEMO_ACCESS_KEY",))
    parent_namespace = os.readlink("/proc/self/ns/net")
    code = f"""
import os
assert os.environ['DEMO_ACCESS_KEY'] == 'fake-key-only'
assert 'DO_NOT_FORWARD' not in os.environ
assert os.readlink('/proc/self/ns/net') != {parent_namespace!r}
"""
    assert run(config, [sys.executable, "-c", code]).status == "completed"
    enabled = _profile(tmp_path, network=True)
    assert (
        run(
            enabled,
            [
                sys.executable,
                "-c",
                f"import os; assert os.readlink('/proc/self/ns/net') == {parent_namespace!r}",
            ],
        ).status
        == "completed"
    )


def test_child_exit_is_preserved(tmp_path):
    outcome = run(_profile(tmp_path), [sys.executable, "-c", "raise SystemExit(7)"])
    assert outcome.status == "failed"
    assert outcome.returncode == 7


@pytest.mark.parametrize("parent_sleeps", [False, True])
def test_detached_descendant_dies_on_completion_or_timeout(tmp_path, parent_sleeps):
    config = _profile(tmp_path, timeout_seconds=0.8)
    heartbeat = config.workspace / "heartbeat"
    child = f"import time; from pathlib import Path\nwhile True:\n Path({str(heartbeat)!r}).write_text(str(time.monotonic()))\n time.sleep(0.02)"
    code = f"""
import subprocess, sys, time
from pathlib import Path
subprocess.Popen([sys.executable, '-c', {child!r}], start_new_session=True)
while not Path({str(heartbeat)!r}).exists():
    time.sleep(0.01)
{"time.sleep(30)" if parent_sleeps else ""}
"""
    result = run(config, [sys.executable, "-c", code])
    assert result.status == ("timed_out" if parent_sleeps else "completed")
    assert heartbeat.exists()
    before = heartbeat.read_text()
    time.sleep(0.15)
    assert heartbeat.read_text() == before


def test_cli_check_from_foreign_directory(tmp_path):
    config = _profile(tmp_path)
    path = tmp_path / "profile.json"
    path.write_text(config.model_dump_json())
    checked = subprocess.run(
        [sys.executable, "-m", "tools.workspace_sandbox", "check", str(path)],
        cwd="/",
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr
    assert '"status": "passed"' in checked.stdout


def test_cli_sigterm_cleans_detached_child(tmp_path):
    config = _profile(tmp_path, timeout_seconds=30)
    path = tmp_path / "profile.json"
    path.write_text(config.model_dump_json())
    heartbeat = config.workspace / "heartbeat"
    child = f"import time; from pathlib import Path\nwhile True:\n Path({str(heartbeat)!r}).write_text(str(time.monotonic()))\n time.sleep(0.02)"
    code = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {child!r}], start_new_session=True); time.sleep(30)"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tools.workspace_sandbox",
            "run",
            str(path),
            "--",
            sys.executable,
            "-c",
            code,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        until = time.monotonic() + 10
        while not heartbeat.exists() and time.monotonic() < until:
            assert process.poll() is None
            time.sleep(0.02)
        assert heartbeat.exists()
        process.terminate()
        _, stderr = process.communicate(timeout=10)
        assert process.returncode == 143, stderr
        before = heartbeat.read_text()
        time.sleep(0.15)
        assert heartbeat.read_text() == before
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_exact_frozen_environment_imports_native_dependencies(tmp_path):
    config = _profile(tmp_path)
    code = """
import sys
import torch
import pydantic
from workflows.task_composition import compose_run_task_bindings
assert torch.__file__.startswith(sys.prefix)
assert pydantic.__file__.startswith(sys.prefix)
"""
    assert run(config, [sys.executable, "-c", code]).status == "completed"
