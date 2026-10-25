"""Explicit HTTP task-reference review reaches the existing real offline composition child."""

import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.integration.tools.test_setup_composition_check import _request
from tests.unit.workflows.reusable_fixture import reusable
from tools.candidate_console.editor import editor_router
from tools.setup_review.composition_check import check_task
from tools.workflow_authoring.models import Project, ReviewRequest
from tools.workflow_authoring.service import WorkflowAuthoring
from tools.workflow_authoring.task_models import TaskReferenceTarget, TaskReferenceUpdateProposal
from workflows.definition import TaskBinding, render_workflow_source

pytestmark = pytest.mark.skipif(
    os.environ.get("SIDERIUS_TEST_WORKSPACE_SANDBOX") != "1",
    reason="requires explicit authorization for real bubblewrap namespaces",
)


def test_explicit_review_uses_original_composition_owner_and_never_publishes(tmp_path, monkeypatch):
    """Accepted setup observation supplies the configured pin; HTTP independently re-observes it."""
    setup = _request(tmp_path, monkeypatch)
    baseline = check_task(setup)
    assert baseline.result.outcome == "passed", baseline.result.failure
    facts = baseline.result.task
    pin = TaskBinding(
        package_id="quickstart",
        revision="explicit-local-snapshot",
        task_data_path_id=facts.task_data_path_id,
        semantic_fingerprint=facts.semantic_fingerprint,
    )
    source = tmp_path / "workflow.py"
    source.write_text(render_workflow_source(reusable()))
    recovery = tmp_path / "recovery"
    recovery.mkdir(mode=0o700)
    observations = tmp_path / "observations"
    observations.mkdir()
    project = Project(
        project_id="explicit",
        project_root=tmp_path,
        source_file=source,
        recovery_directory=recovery,
    )
    target = TaskReferenceTarget(
        choice_id="quickstart-local",
        binding=pin,
        manifest=Path(baseline.job.manifest),
        data_root=tmp_path / "unmounted-data",
        llm_config_file=tmp_path / "agents.json",
        inspection_root=observations,
        read_only=(),
        settings=setup.settings,
    )
    author = WorkflowAuthoring(project, (target,))
    request = ReviewRequest(
        expected_sha256=author.read().sha256,
        proposal=TaskReferenceUpdateProposal(
            selected_choice_id=target.choice_id, expected_task_binding=pin
        ),
    )
    before = source.read_bytes()
    monkeypatch.setenv("OPENAI_API_KEY", "never-forward-task-review-fixture")
    app = FastAPI()
    app.include_router(editor_router((project,), task_targets=(target,)))
    with TestClient(app) as client:
        response = client.post("/api/editor/explicit/review", json=request.model_dump(mode="json"))
    assert response.status_code == 200, response.text
    review = response.json()["task_reference_update"]
    observed = review["observation"]
    assert observed["execution"]["status"] == "completed"
    assert observed["result"]["outcome"] == "passed"
    assert observed["result"]["task"]["semantic_fingerprint"] == pin.semantic_fingerprint
    assert observed["result"]["task"]["primary_metric"] == facts.primary_metric
    assert observed["sandbox"]["network"] is False
    assert observed["sandbox"]["devices"] == observed["sandbox"]["environment_names"] == []
    assert review["findings"][0]["code"] == "identity_verified"
    assert {finding["code"] for finding in review["findings"] if finding["state"] == "blocked"} == {
        "compatibility_unresolved",
    }
    assert not review["save_supported"] and not review["execution_ready"]
    assert "never-forward-task-review-fixture" not in response.text
    assert source.read_bytes() == before and not tuple(recovery.iterdir())
    assert not (tmp_path / "unmounted-data").exists()
    assert len(tuple(observations.iterdir())) == 1
