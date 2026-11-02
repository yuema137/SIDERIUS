"""Editor HTTP projections must sanitize both native observations and error proposals."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.unit.tools.candidate_console.test_editor import editor_config as editor_config
from tools.candidate_console.app import create_app
from tools.setup_review.composition_models import (
    CompositionJob,
    CompositionObservation,
    CompositionResult,
    TaskCheckSettings,
)
from tools.workflow_authoring.models import ReviewView
from tools.workflow_authoring.service import AuthoringError, WorkflowAuthoring
from tools.workflow_authoring.task_models import TaskReferenceReview
from tools.workspace_sandbox.profile import SandboxProfile
from workflows.definition import TaskBinding

SECRET = "private-editor-secret-sentinel"


def failed_review(review: ReviewView, workspace: Path, secret: str) -> ReviewView:
    """Native diagnostic fixture shared with the offline browser witness."""
    job = CompositionJob(
        manifest=str(workspace / "task.yaml"),
        manifest_sha256="a" * 64,
        planner_strategy=None,
        scratch=str(workspace),
        settings=TaskCheckSettings(timeout_seconds=30),
    )
    observation = CompositionObservation(
        job=job,
        sandbox=SandboxProfile(
            workspace=workspace,
            read_only=(),
            network=False,
            devices=(),
            environment_names=(),
            timeout_seconds=30,
        ),
        execution=None,
        result=CompositionResult.failed(job, "composition", ValueError(secret)),
        limitations=(),
    )
    # A task-defined class name can itself carry private content.
    current = observation.model_copy(
        update={
            "result": CompositionResult.failed(
                job, "planner_strategy", type(secret, (RuntimeError,), {})(secret)
            )
        }
    )
    binding = TaskBinding(
        package_id="fixture",
        revision="r1",
        task_data_path_id="fixture",
        semantic_fingerprint="a" * 64,
    )
    task = TaskReferenceReview(
        selected_choice_id="synthetic",
        previous_binding=None,
        target_binding=binding,
        observation=observation,
        current_observation=current,
        findings=(),
    )
    return review.model_copy(update={"task_reference_update": task})


@pytest.mark.parametrize("surface", ["review", "proposal"])
def test_editor_observations_are_safe_only_at_http_boundary(
    editor_config, monkeypatch, caplog, surface
):
    """Both review and refused-save proposals used to serialize nested raw causes."""
    original = WorkflowAuthoring.review
    observed = []

    def review(service, request):
        result = failed_review(original(service, request), service.project.project_root, SECRET)
        observed.append(result)
        if surface == "proposal":
            error = AuthoringError("blocked", "Review is blocked")
            error.proposal = result
            raise error
        return result

    monkeypatch.setattr(WorkflowAuthoring, "review", review)
    headers = {
        "Authorization": "Bearer " + Path(editor_config.auth_token_file).read_text(),
        "Origin": editor_config.browser_origin,
    }
    with TestClient(create_app(editor_config), base_url=editor_config.browser_origin) as client:
        current = client.get("/api/editor/example", headers=headers).json()
        response = client.post(
            "/api/editor/example/review",
            headers=headers,
            json={
                "expected_sha256": current["sha256"],
                "proposal": {"kind": "source", "source": current["source"]},
            },
        )
    assert response.status_code == (200 if surface == "review" else 409)
    assert SECRET not in response.text
    body = response.json() if surface == "review" else response.json()["proposal"]
    task = body["task_reference_update"]
    assert task["observation"]["result"]["failure"]["message"].startswith("Invalid value")
    assert task["current_observation"]["result"]["failure"]["message"].startswith(
        "Unexpected error"
    )
    assert SECRET in caplog.text
    assert SECRET in observed[0].model_dump_json(), "Do not mutate native authoring diagnostics"


@pytest.mark.parametrize("surface", ["document", "source"])
@pytest.mark.parametrize(
    "portion, expected", [(0.2, "trial_override_schedule"), (-1, "validation")]
)
def test_editor_preserves_only_the_native_trial_schedule_code(
    editor_config, surface, portion, expected
):
    """A one-round draft with an unrelated bad portion must not receive schedule advice."""
    import json

    from tests.unit.workflows.test_reusable_training import training_document
    from workflows.definition import render_workflow_source

    document = training_document({"launch": {"max_rounds": 2, "trial_portion": 0.2}})
    source = render_workflow_source(document)
    editor_config.editor_projects[0].source_file.write_text(source)
    headers = {
        "Authorization": "Bearer " + Path(editor_config.auth_token_file).read_text(),
        "Origin": editor_config.browser_origin,
    }
    with TestClient(create_app(editor_config), base_url=editor_config.browser_origin) as client:
        current = client.get("/api/editor/example", headers=headers).json()
        if surface == "document":
            payload = json.loads(document.model_dump_json())
            payload["training_settings"]["launch"] = {
                "max_rounds": 1,
                "trial_portion" if portion > 0 else "formal_portion": portion,
            }
            proposal = {"kind": "document", "document": payload}
        else:
            proposed = source.replace("'max_rounds': 2", "'max_rounds': 1")
            field = "trial_portion" if portion > 0 else "formal_portion"
            proposed = proposed.replace("'trial_portion': 0.2", f"'{field}': {portion}")
            assert proposed != source
            proposal = {"kind": "source", "source": proposed}
        response = client.post(
            "/api/editor/example/review",
            headers=headers,
            json={"expected_sha256": current["sha256"], "proposal": proposal},
        )
    assert response.status_code == 422, response.text
    body = response.json()
    code = body["error"]["code"] if surface == "document" else body["diagnostics"][0]["code"]
    assert code == expected
    assert "plan_overrides" not in response.text
    assert editor_config.editor_projects[0].source_file.read_text() == source
