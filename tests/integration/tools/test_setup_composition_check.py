"""Actual offline task composition through a fresh namespace and user directory."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from core.layout import checkout_root
from tools.setup_review.composition_check import check_task
from tools.setup_review.composition_models import TaskCheckRequest, TaskCheckSettings
from tools.setup_review.models import SetupReviewRequest

pytestmark = pytest.mark.skipif(
    os.environ.get("SIDERIUS_TEST_WORKSPACE_SANDBOX") != "1",
    reason="requires explicit authorization for real bubblewrap namespaces",
)


def _request(tmp_path, monkeypatch, *, strategy="native-timing-v1"):
    monkeypatch.chdir(tmp_path)
    root = checkout_root()
    assert root is not None
    llm = tmp_path / "agents.json"
    llm.write_text(json.dumps({"tune": {"planner_strategy": strategy}}))
    manifest = root / "configs/task_composition/quickstart.yaml"
    return TaskCheckRequest(
        setup=SetupReviewRequest(
            working_directory=str(tmp_path),
            argv=[
                "--workspace",
                "real-run",
                "--run_name",
                "synthetic",
                "--start_iteration",
                "1",
                "--task_composition",
                str(manifest),
                "--data_dir",
                "unmounted-data",
                "--llm_config",
                str(llm),
            ],
        ),
        scratch=tmp_path / "scratch",
        output=tmp_path / "review",
        read_only=(),
        settings=TaskCheckSettings(timeout_seconds=30),
    )


@pytest.mark.parametrize("strategy", ["native-timing-v1", "missing-synthetic-provider", None])
def test_real_composition_preserves_inputs_and_reports_provider_failure(
    tmp_path, monkeypatch, strategy
):
    request = _request(tmp_path, monkeypatch, strategy=strategy)
    manifest = Path(request.setup.argv[request.setup.argv.index("--task_composition") + 1])
    before = hashlib.sha256(manifest.read_bytes()).hexdigest()
    monkeypatch.setenv("OPENAI_API_KEY", "never-forward-fixture-key")
    monkeypatch.setenv("SIDERIUS_GENERATED_LIBRARY_DIR", "/unavailable-ambient-library")
    report = check_task(request)
    assert report.execution is not None and report.execution.status == "completed"
    assert report.result.outcome == ("passed" if strategy == "native-timing-v1" else "failed")
    assert report.result.task is not None
    assert report.result.task.task_data_path_id == "quickstart_tabular"
    assert report.result.task.primary_metric["direction"] == "higher"
    if strategy != "native-timing-v1":
        assert report.result.failure.stage == "planner_strategy"
        assert "found 0" in report.result.failure.message
    assert not (tmp_path / "real-run").exists()
    assert not (tmp_path / "unmounted-data").exists()
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == before
    assert report.sandbox.network is False
    assert report.sandbox.environment_names == report.sandbox.devices == ()
    output = (request.output / "index.html").read_text()
    assert "Primary metric" in output and "Dataset profile" in output
    assert "Inference preflight policy" in output and "settings.html" in output
    assert "never-forward-fixture-key" not in output + (request.output / "report.json").read_text()
    assert sorted(path.name for path in request.output.iterdir()) == [
        "index.html",
        "report.json",
        "settings.html",
    ]


def _external_hook_request(tmp_path, monkeypatch, hook):
    request = _request(tmp_path, monkeypatch)
    root = checkout_root()
    assert root is not None
    task = tmp_path / "task"
    shutil.copytree(root / "examples/quickstart/declared", task / "declared")
    shutil.copytree(root / "examples/quickstart/plugins", task / "plugins")
    manifest = task / "task.yaml"
    manifest.write_text(
        (root / "configs/task_composition/quickstart.yaml")
        .read_text()
        .replace("../../examples/quickstart/", "")
    )
    source = task / "plugins/_quickstart_task.py"
    text = source.read_text().replace(
        "from __future__ import annotations\n", "from __future__ import annotations\n" + hook + "\n"
    )
    source.write_text(text)
    argv = list(request.setup.argv)
    argv[argv.index("--task_composition") + 1] = str(manifest)
    return request.model_copy(
        update={"setup": request.setup.model_copy(update={"argv": argv}), "read_only": (task,)}
    )


def test_real_external_bootstrap_keeps_sources_read_only_and_private_inputs_hidden(
    tmp_path, monkeypatch
):
    hidden = tmp_path / "private.txt"
    hidden.write_text("not-for-the-child")
    hook = f"""
import os
from pathlib import Path
from core.generated_library import generated_library_root, generated_library_is_workspace_bound
assert generated_library_is_workspace_bound()
assert Path(generated_library_root()).is_relative_to({str(tmp_path / "scratch")!r})
assert 'OPENAI_API_KEY' not in os.environ
assert not Path({str(hidden)!r}).exists()
try:
    Path(__file__).write_text('forbidden')
except OSError:
    pass
else:
    raise AssertionError('source write succeeded')
"""
    request = _external_hook_request(tmp_path, monkeypatch, hook)
    monkeypatch.setenv("OPENAI_API_KEY", "never-forward-synthetic-key")
    inputs = {path: path.read_bytes() for path in request.read_only[0].rglob("*") if path.is_file()}
    report = check_task(request)
    assert report.result.outcome == "passed", report.result.failure
    assert all(path.read_bytes() == payload for path, payload in inputs.items())
    assert hidden.read_text() == "not-for-the-child"


@pytest.mark.parametrize("contradiction", [False, True])
def test_real_task_settings_materialize_owner_defaults_without_running_health(
    tmp_path, monkeypatch, contradiction
):
    request = _external_hook_request(tmp_path, monkeypatch, "")
    task = request.read_only[0]
    (task / "health_plugin.py").write_text("""
from execute_tools.health_checks import register
from execute_tools.health_checks.schemas import CheckInputDeclaration
class Check:
    name = "setup_fixture_check"
    declaration = CheckInputDeclaration(consumes_view="setup.fixture_view")
    def run(self, ctx, config=None):
        raise AssertionError("setup inspection executed a Health check")
register(Check())
""")
    (task / "health.yaml").write_text("""
facts: {encoding_family: setup_fixture}
plugins:
  - {kind: file, ref: health_plugin.py}
roster:
  - gate_id: inspect_distribution
    check: setup_fixture_check
    disposition: recording
    reason: "<script>display as text</script>"
""")
    manifest = task / "task.yaml"
    payload = yaml.safe_load(manifest.read_text())
    payload["task_health"] = {"config": "health.yaml"}
    manifest.write_text(yaml.safe_dump(payload))
    argv = [
        *request.setup.argv,
        "--health_gate_files",
        "1",
        "--healthgate_mode",
        "observe_only",
        "--result_authority",
        "scientific" if contradiction else "diagnostic",
    ]
    request = request.model_copy(
        update={
            "setup": request.setup.model_copy(update={"argv": argv}),
            "resolve_task_settings": True,
        }
    )
    report = check_task(request)
    assert not (tmp_path / "real-run").exists()
    assert not (tmp_path / "unmounted-data").exists()
    assert report.sandbox.devices == report.sandbox.environment_names == ()
    if contradiction:
        assert report.result.failure.stage == "task_settings"
        assert report.result.failure.exception_type == "FormalLaunchPolicyError"
        assert report.result.task_settings is None
        assert not (request.scratch / "task-settings").exists()
        return
    assert report.result.outcome == "passed", report.result.failure
    settings = report.result.task_settings
    assert settings.resolved_data_scope == [0, 1, 2, 3]
    assert settings.analysis_enabled is False
    assert settings.formal_policy == "passed"
    gate = settings.health_config["health_gates"][0]
    assert gate["gate_role"] == "observational"
    assert gate["after_round"] == "every" and gate["short_circuit"] is False
    assert gate["on_fail"] == {"action": "continue"}
    assert gate["checks"][0]["config"]["peek_file_indices"] == [1]
    assert len(settings.health_config["resolved_plugins"]) == 1
    assert (request.scratch / "task-settings/health_checks_effective.yaml").is_file()
    html = (request.output / "index.html").read_text()
    assert "Selected data scope" in html and "Health gate 1" in html
    assert "&lt;script&gt;" in html and "<script>display" not in html
    assert "no Health materialization" not in html
    # The saved semantic boundary consumes facts, never the deleted execution paths.
    from tools.setup_review.semantic_models import SemanticReviewRequest
    from tools.setup_review.semantic_review import review_snapshot

    shutil.rmtree(request.scratch)
    shutil.rmtree(task)
    source = request.output / "report.json"
    receipt = review_snapshot(
        SemanticReviewRequest.model_validate(
            {
                "operation": {
                    "kind": "skip",
                    "report": str(source),
                    "expected_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "output": str(tmp_path / "skip-review"),
                    "input_max_bytes": 1024 * 1024,
                    "reason": "I will review these settings myself.",
                }
            }
        )
    )
    assert receipt.outcome == "skipped" and receipt.prompt_version == "setup-review/v2"
    packet = json.loads((tmp_path / "skip-review/packet.json").read_text())
    assert packet["resolved_task_settings"]["health_gates"][0]["on_fail"] == {"action": "continue"}
    assert packet["historical_declaration_limitations"] == report.declaration.unresolved
    assert packet["resolved_task_settings"]["analysis_enabled"] is False
    analysis = next(route for route in packet["routes"] if route["name"] == "data_analysis")
    assert analysis["applicability"] == "disabled"
    current_limits = " ".join(packet["unresolved"])
    assert "Task-dependent enablement" not in current_limits
    assert "task plugins" not in current_limits
    for unresolved in (
        "Hardware",
        "Dataset",
        "Agent-selected",
        "later launch",
        "authentication",
        "budgets",
    ):
        assert unresolved in current_limits
    assert "display as text" not in json.dumps(packet)


def test_factory_cannot_connect_to_host_loopback(tmp_path, monkeypatch):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        hook = f"""
import socket
socket.create_connection(('127.0.0.1', {port}), timeout=0.5)
raise AssertionError('host network unexpectedly reachable')
"""
        report = check_task(_external_hook_request(tmp_path, monkeypatch, hook))
    assert report.result.outcome == "failed"
    assert report.result.failure.stage == "composition"
    assert "host network unexpectedly reachable" not in report.result.failure.message
    assert (
        "refused" in report.result.failure.message.lower()
        or "unreachable" in report.result.failure.message.lower()
    )


def test_missing_declared_code_package_member_fails_composition(tmp_path, monkeypatch):
    request = _external_hook_request(tmp_path, monkeypatch, "")
    manifest = request.read_only[0] / "task.yaml"
    declaration = yaml.safe_load(manifest.read_text())
    declaration["code_package"] = {"root": ".", "files": ["missing.py"]}
    manifest.write_text(yaml.safe_dump(declaration))
    report = check_task(request)
    assert report.result.outcome == "failed"
    assert report.result.failure.stage == "composition"
    assert "missing.py" in report.result.failure.message
    assert not (tmp_path / "real-run").exists()


@pytest.mark.parametrize("sleep_after_spawn", [False, True])
def test_actual_factory_detached_child_stops_at_completion_or_timeout(
    tmp_path, monkeypatch, sleep_after_spawn
):
    heartbeat = tmp_path / "scratch/heartbeat"
    child = f"import time\nfrom pathlib import Path\nwhile True:\n Path({str(heartbeat)!r}).write_text(str(time.monotonic()))\n time.sleep(.02)"
    hook = f"""
import subprocess, sys, time
from pathlib import Path
subprocess.Popen([sys.executable, '-c', {child!r}], start_new_session=True)
while not Path({str(heartbeat)!r}).exists():
    time.sleep(.01)
{"time.sleep(60)" if sleep_after_spawn else ""}
"""
    request = _external_hook_request(tmp_path, monkeypatch, hook)
    request = request.model_copy(update={"settings": TaskCheckSettings(timeout_seconds=6)})
    report = check_task(request)
    assert report.execution.status == ("timed_out" if sleep_after_spawn else "completed")
    assert report.result.outcome == ("failed" if sleep_after_spawn else "passed")
    assert heartbeat.exists()
    before = heartbeat.read_text()
    time.sleep(0.15)
    assert heartbeat.read_text() == before


def test_cold_parent_cli_never_imports_task_or_provider_code(tmp_path, monkeypatch):
    request = _request(tmp_path, monkeypatch)
    path = tmp_path / "request.json"
    path.write_text(request.setup.model_dump_json())
    script = """
import importlib.abc, runpy, sys
class NoTaskImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        forbidden = ('workflows.task_composition', 'workflows.run_one_iteration', 'workflows.model_exploration', 'agent.llm_bridge', 'agent.planner_strategy', 'ml_models.models_sandbox', 'ml_models.loss_models_sandbox', 'ml_models.plugin_loader', 'ml_models.loss_plugin_loader', 'openai', 'dotenv')
        if any(fullname == name or fullname.startswith(name + '.') for name in forbidden):
            raise AssertionError('effectful parent import: ' + fullname)
sys.meta_path.insert(0, NoTaskImports())
sys.argv = ['tools.setup_review.check_task', *sys.argv[1:]]
runpy.run_module('tools.setup_review.check_task', run_name='__main__')
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            "--request",
            str(path),
            "--scratch",
            str(request.scratch),
            "--output",
            str(request.output),
            "--timeout-seconds",
            "30",
        ],
        capture_output=True,
        text=True,
        timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    saved = json.loads((request.output / "report.json").read_text())
    assert saved["declaration"]["launch_argv"] == [
        sys.executable,
        "-m",
        "workflows.run_one_iteration",
        *request.setup.argv,
    ]
