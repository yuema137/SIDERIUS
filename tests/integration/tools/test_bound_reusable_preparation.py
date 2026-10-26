"""Real offline bound preparation and existing HTTP consumption without native launch."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from tests.integration.tools.test_setup_composition_check import _external_hook_request
from tests.unit.tools.candidate_console.conftest import console_config as console_config
from tests.unit.tools.candidate_console.test_http import client
from tests.unit.tools.candidate_prepare.conftest import selection as selection
from tests.unit.tools.candidate_prepare.test_reusable_preparation import (
    reusable as reusable_fixture,
)
from tests.unit.tools.candidate_prepare.test_task_binding import bind_source
from tools.candidate_console.reusable_candidate import ReusableCandidate
from tools.candidate_console.reusable_models import ReusableCaptureChoice
from tools.candidate_console.service import CandidateConsole
from tools.candidate_prepare import (
    preflight_reusable_candidate,
    prepare_reusable_candidate,
    select_reusable_preparation,
    verify_reusable_preparation,
)
from tools.candidate_prepare.reusable_models import ReusablePreparationControl
from tools.candidate_prepare.reusable_verify import verify_reusable_bundle
from tools.setup_review.composition_check import check_task
from tools.workflow_authoring.models import Project
from workflows.definition import TaskBinding

pytestmark = pytest.mark.skipif(
    os.environ.get("SIDERIUS_TEST_WORKSPACE_SANDBOX") != "1",
    reason="requires explicit authorization for real bubblewrap namespaces",
)


@pytest.fixture
def bound(tmp_path, monkeypatch, selection):
    setup = _external_hook_request(tmp_path, monkeypatch, "")
    baseline = check_task(setup)
    assert baseline.result.outcome == "passed", baseline.result.failure
    facts = baseline.result.task
    selected = selection.model_copy(
        update={
            "task_manifest": baseline.job.manifest,
            "llm_config_file": str(tmp_path / "agents.json"),
            "task_read_only": tuple(str(path) for path in setup.read_only),
        }
    )
    request = reusable_fixture.__wrapped__(selected)
    pin = TaskBinding(
        package_id="external-synthetic",
        revision="observed-snapshot",
        task_data_path_id=facts.task_data_path_id,
        semantic_fingerprint=facts.semantic_fingerprint,
    )
    request = bind_source(request, pin)
    return request, pin


def bound_console_config(request, pin, console_config, tmp_path):
    """Expose the same explicit bound project through existing console transport."""
    plan = preflight_reusable_candidate(request)
    recovery = tmp_path / "recovery"
    recovery.mkdir(mode=0o700)
    project = Project(
        project_id="bound",
        project_root=Path(request.project_root),
        source_file=Path(request.source_path),
        recovery_directory=recovery,
    )
    task = console_config.tasks[0].model_copy(
        update={
            **plan.binding.request.model_dump(
                include={
                    "task_manifest",
                    "data_root",
                    "llm_config_file",
                    "task_read_only",
                    "preparation_timeout_seconds",
                    "candidate_timeout_seconds",
                    "candidate_network",
                    "candidate_devices",
                    "candidate_environment_names",
                }
            ),
            "reusable_runs_root": request.runs_root,
            "allowed_output_types": None,
            "task_revision": pin,
        }
    )
    store = console_config.operation_store.model_copy(
        update={
            "preparation_roots": (
                *console_config.operation_store.preparation_roots,
                request.runs_root,
            ),
            "candidate_roots": (*console_config.operation_store.candidate_roots, request.runs_root),
        }
    )
    config = console_config.model_copy(
        update={
            "tasks": (task,),
            "operation_store": store,
            "editor_projects": (project,),
            "runnable_editor_projects": (project.project_id,),
        }
    )
    return config, project, task


def test_bound_preparation_http_review_and_parent_forgery_refusal(bound, console_config, tmp_path):
    """Real child agrees with captured pin; HTTP/code share a verified capture; forged index cannot repin it."""
    request, pin = bound
    source = Path(request.source_path).read_bytes()
    plan = preflight_reusable_candidate(request)
    config, project, task = bound_console_config(request, pin, console_config, tmp_path)
    receipt = prepare_reusable_candidate(request)
    assert receipt.status == "prepared", receipt.error
    envelope = Path(receipt.envelope)
    output = envelope / "inputs"
    assert (envelope / "workflow.py.snapshot").read_bytes() == source
    assert not (envelope / "workspace").exists()
    proposal_path = output / "proposal.json"
    original_proposal = proposal_path.read_bytes()
    proposal = json.loads(original_proposal)
    assert proposal["task_composition_ref"]["semantic_fingerprint"] == pin.semantic_fingerprint
    assert proposal["task_composition_ref"]["task_data_path_id"] == pin.task_data_path_id
    verified = verify_reusable_preparation(select_reusable_preparation(str(envelope)))
    assert verified.composition_fingerprint == pin.semantic_fingerprint

    adapter = ReusableCandidate(CandidateConsole(config))
    choice = ReusableCaptureChoice(task_id=task.task_id, run_id=request.run_id)
    expected = adapter.review(project.project_id, adapter.select(project.project_id, choice))
    with client(config) as http:
        base = "/api/editor/bound/reusable-captures"
        selected = http.post(base + "/select", json=choice.model_dump(mode="json"))
        assert selected.status_code == 200, selected.text
        reviewed = http.post(base + "/review", json=selected.json())
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json() == expected.model_dump(mode="json")
    assert Path(request.source_path).read_bytes() == source

    control = ReusablePreparationControl.model_validate_json(
        (output / "preparation/request.json").read_bytes()
    )
    index_path = output / "preparation/child.json"
    original_index = index_path.read_bytes()
    for field, value in (("semantic_fingerprint", "b" * 64), ("task_data_path_id", "other_path")):
        forged = json.loads(original_proposal)
        forged["task_composition_ref"][field] = value
        proposal_path.write_text(json.dumps(forged))
        index = json.loads(original_index)
        index["composition_fingerprint"] = forged["task_composition_ref"]["semantic_fingerprint"]
        for item in index["files"]:
            payload = Path(item["path"]).read_bytes()
            item.update(sha256=hashlib.sha256(payload).hexdigest(), size_bytes=len(payload))
        index_path.write_text(json.dumps(index))
        with pytest.raises(ValueError, match="parent-captured workflow task binding"):
            verify_reusable_bundle(plan, source, control)
    proposal_path.write_bytes(original_proposal)
    index_path.write_bytes(original_index)


@pytest.mark.parametrize("fault", ["plugin_drift", "data_path"])
def test_native_refusal_precedes_native_payload_publication(bound, fault):
    """Manifest bytes can stay unchanged while factory source drifts; original native ref detects it."""
    request, pin = bound
    manifest = Path(preflight_reusable_candidate(request).binding.request.task_manifest)
    before_manifest = manifest.read_bytes()
    if fault == "plugin_drift":
        plugin = manifest.parent / "plugins/_quickstart_task.py"
        plugin.write_text(plugin.read_text() + "\n# plugin changed after pin acceptance\n")
    else:
        request = bind_source(request, pin.model_copy(update={"task_data_path_id": "other_path"}))
    source = Path(request.source_path).read_bytes()
    receipt = prepare_reusable_candidate(request)
    assert receipt.status == "failed" and receipt.candidate_request_path is None
    envelope = Path(receipt.envelope)
    output = envelope / "inputs"
    assert manifest.read_bytes() == before_manifest
    assert (envelope / "workflow.py.snapshot").read_bytes() == source
    assert not (envelope / "workspace").exists()
    for name in ("proposal.json", "interpretation.json", "storage.json", "candidate_request.json"):
        assert not (output / name).exists(), name
    assert (
        "native task composition differs from accepted workflow binding"
        in (output / "preparation/worker.log").read_text()
    )
