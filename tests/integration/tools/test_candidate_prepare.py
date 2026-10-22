"""Real offline preparation process, then the unchanged native worker boundary."""

import importlib
import inspect
import json
import os
import sys
from pathlib import Path

import pytest

from tests.unit.tools.candidate_prepare.conftest import selection
from tests.unit.tools.candidate_worker.test_native import Provider
from tools.candidate_prepare import prepare_candidate
from tools.candidate_worker import CandidateRunRequest, launch_candidate
from tools.workspace_sandbox.runner import run

pytestmark = pytest.mark.skipif(
    os.environ.get("SIDERIUS_TEST_WORKSPACE_SANDBOX") != "1",
    reason="requires explicit bubblewrap-capable host opt-in",
)


@pytest.mark.parametrize("staged", [False, True])
def test_real_offline_preparation_and_materialization(selection, monkeypatch, staged):
    """Actual mount/import binding, no credentials/provider construction, native transport."""
    from workflows.llm_config import WorkflowLLMConfig

    if staged:
        Path(selection.llm_config_file).write_text(WorkflowLLMConfig.default().model_dump_json())
    harness = Path(selection.output_dir).parent / "preparation_harness.py"
    harness.write_text("""import builtins, os, runpy, sys
from pathlib import Path
output = Path(sys.argv[1]).parent.parent
assert not any(os.environ.get(key) for key in ('OPENAI_API_KEY', 'GEMINI_API_KEY', 'DEEPSEEK_API_KEY'))
original = builtins.__import__
class ForbiddenBridge:
    def __init__(self, *args, **kwargs):
        raise AssertionError('preparation constructed a provider')
def guarded(name, globals=None, locals=None, fromlist=(), level=0):
    if name.startswith(('ml_models', 'nodes.result_', 'workflows.task_composition')):
        assert os.environ.get('SIDERIUS_GENERATED_LIBRARY_DIR') == str(output / 'generated_library'), name
    result = original(name, globals, locals, fromlist, level)
    if name == 'agent.llm_bridge':
        sys.modules[name].LLMBridge = ForbiddenBridge
    return result
builtins.__import__ = guarded
sys.argv = ['tools.candidate_prepare.child', sys.argv[1]]
runpy.run_module('tools.candidate_prepare.child', run_name='__main__')
""")
    launch_module = importlib.import_module("tools.candidate_prepare.launch")

    def supervised(profile, argv):
        profile = profile.model_copy(update={"read_only": (*profile.read_only, harness)})
        return run(profile, [sys.executable, str(harness), argv[-1]])

    monkeypatch.setattr(launch_module, "run", supervised)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-pass")
    receipt = prepare_candidate(selection)
    log = Path(receipt.log_path).read_text() if Path(receipt.log_path).exists() else ""
    assert receipt.status == "prepared", (receipt.error, log)
    output = Path(selection.output_dir)
    assert not Path(selection.candidate_workspace).exists()
    interpreted = json.loads((output / "interpretation.json").read_text())
    seed = json.loads((output / "proposal.json").read_text())
    inp = json.loads((output / "preparation/interpretation_input.json").read_text())
    assert inp["cold_start"] and inp["summaries"] == [] and inp["model_knowledge_cache"] == {}
    assert interpreted["total_experiments"] == 0 and interpreted["model_types"] == []
    assert interpreted["metric_identity"] == {
        "metric_id": "accuracy",
        "direction": "higher",
    }
    assert seed["existing_model_types"] == [] and seed["cold_start"] is True
    assert "Check all four input features." in json.dumps(seed["expert_context"])
    pipeline = seed.get("reasoning_pipeline")
    assert ([stage["name"] for stage in pipeline["stages"]] if pipeline else None) == (
        ["comparison", "causal_reasoning"] if staged else []
    )
    assert json.loads((output / "preview.json").read_text())["execution_ready"] is False
    request = CandidateRunRequest.model_validate_json(
        (output / "candidate_request.json").read_bytes()
    )
    assert request.implementation_advice == "Keep code small."
    assert request.validation_advice == "Check the declared shape."
    assert request.timeout_seconds == 60.0
    # Materialize from saved JSON in a bound process before constructing any node.
    materializer = output / "materialize_check.py"
    materializer.write_text("""import sys
from pathlib import Path
from core.generated_library import bind_generated_library_to_workspace
from tools.candidate_worker import CandidateRunRequest
from tools.workflow_preview.config import parse_config
request = CandidateRunRequest.model_validate_json(Path(sys.argv[1]).read_bytes())
workspace = Path(sys.argv[2])
bind_generated_library_to_workspace(str(workspace))
from tools.candidate_worker.inputs import materialize
from workflows.task_composition import compose_run_task_bindings, bind_run_task_composition
control = workspace / 'candidate_run'
control.mkdir(parents=True)
for i, item in enumerate(request.files):
    (control / f'input_{i:03}.snapshot').write_bytes(Path(item.path).read_bytes())
composition = compose_run_task_bindings(request.preview.document.definition.task.manifest)
config = parse_config((Path(request.preview.project_root) / 'llm.json').read_bytes())
with bind_run_task_composition(composition, physical_data_root=request.preview.document.definition.task.data_root):
    native = materialize(request, workspace, composition, config)
    assert native.proposal.cold_start
    assert native.proposal.task_composition_ref.semantic_fingerprint == sys.argv[3]
    assert [stage.name for stage in native.proposal.reasoning_pipeline.stages] == (['comparison', 'causal_reasoning'] if sys.argv[4] == 'True' else [])
""")
    # Use the actual selected future workspace solely for worker materialization.
    # This is a separate downstream action after proving preparation left it absent.
    import subprocess

    checked = subprocess.run(
        [
            sys.executable,
            str(materializer),
            receipt.candidate_request_path,
            selection.candidate_workspace,
            receipt.composition_fingerprint,
            str(staged),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr


def test_prepared_bundle_reaches_real_native_worker(selection, monkeypatch):
    """One saved bundle reaches native proposal/implementation/CPU validation unchanged."""
    receipt = prepare_candidate(selection)
    assert receipt.status == "prepared", receipt.error
    request = CandidateRunRequest.model_validate_json(
        Path(receipt.candidate_request_path).read_bytes()
    )
    output = Path(selection.output_dir)
    harness = output / "offline_provider_harness.py"
    harness.write_text(f"""import builtins, runpy, sys
from typing import ClassVar
{inspect.getsource(Provider)}
original = builtins.__import__
def offline_import(name, globals=None, locals=None, fromlist=(), level=0):
    result = original(name, globals, locals, fromlist, level)
    if name == 'agent.llm_bridge':
        sys.modules[name].LLMBridge = Provider
    return result
builtins.__import__ = offline_import
sys.argv = ['tools.candidate_worker.child', sys.argv[1]]
runpy.run_module('tools.candidate_worker.child', run_name='__main__')
""")

    def supervised(profile, argv):
        return run(profile, [sys.executable, str(harness), argv[-1]])

    monkeypatch.setattr(importlib.import_module("tools.candidate_worker.launch"), "run", supervised)
    result = launch_candidate(request)
    log = Path(result.log_path).read_text() if Path(result.log_path).exists() else ""
    assert result.status == "accepted", (result.error, log)
    validation = json.loads(Path(result.native_output_paths[-1]).read_text())
    assert (
        validation["tests_passed"]
        and validation["instantiation_passed"]
        and validation["gradient_check_passed"]
    )


def test_real_preparation_timeout_preserves_partial_evidence(selection, monkeypatch):
    """Actual elapsed process supervision dominates a child's partial artifacts."""
    selection = selection.model_copy(update={"preparation_timeout_seconds": 0.5})

    def stalled(profile, argv):
        return run(
            profile,
            [
                sys.executable,
                "-c",
                "from pathlib import Path; import time; Path('preparation/worker.log').write_text('started\\n'); time.sleep(30)",
            ],
        )

    monkeypatch.setattr(importlib.import_module("tools.candidate_prepare.launch"), "run", stalled)
    result = prepare_candidate(selection)
    assert result.status == "timed_out"
    assert Path(result.log_path).read_text() == "started\n"
    assert not Path(selection.candidate_workspace).exists()
    assert result.candidate_request_path is None


def test_explicit_legacy_source_mount_and_edit_rejection(selection, monkeypatch):
    """Uncaptured task helpers need mounts; declared legacy plugin edits invalidate native refs."""
    import shutil

    from tests.unit.tools.candidate_prepare.conftest import REPO

    root = Path(selection.output_dir).parent
    package = root / "task-package"
    manifest_dir = package / "configs/task_composition"
    manifest_dir.mkdir(parents=True)
    shutil.copytree(REPO / "examples/quickstart", package / "examples/quickstart")
    manifest = manifest_dir / "quickstart.yaml"
    shutil.copyfile(REPO / "configs/task_composition/quickstart.yaml", manifest)
    missing = selection.model_copy(update={"task_manifest": str(manifest)})
    refused = prepare_candidate(missing)
    assert refused.status == "failed"
    assert not Path(selection.candidate_workspace).exists()
    selected = missing.model_copy(
        update={"output_dir": str(root / "mounted-bundle"), "task_read_only": (str(package),)}
    )
    prepared = prepare_candidate(selected)
    assert prepared.status == "prepared", prepared.error
    plugin = package / "examples/quickstart/plugins/_quickstart_metrics.py"
    plugin.write_text(plugin.read_text() + "\n# changed declared plugin bytes\n")
    request = CandidateRunRequest.model_validate_json(
        Path(prepared.candidate_request_path).read_bytes()
    )
    result = launch_candidate(request)
    log = Path(result.log_path).read_text()
    assert result.status == "failed"
    assert "task_composition_ref disagrees with composed task" in log
    assert not list(Path(selected.candidate_workspace).rglob("proposal_candidate.json"))
