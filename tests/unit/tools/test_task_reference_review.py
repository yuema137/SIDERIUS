"""Actual authoring/HTTP dispatch with typed owner observations, never scientific compatibility guesses."""

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.unit.workflows.reusable_fixture import reusable
from tools.candidate_console.editor import editor_router, task_reference_targets
from tools.candidate_console.models import TaskChoice
from tools.setup_review import composition_check
from tools.setup_review.composition_models import (
    CHILD_REQUEST_NAME,
    CHILD_RESULT_NAME,
    CompositionJob,
    CompositionResult,
    TaskCompositionSummary,
)
from tools.workflow_authoring.models import Project, ReviewRequest, SourceProposal
from tools.workflow_authoring.service import AuthoringError, WorkflowAuthoring
from tools.workflow_authoring.task_models import TaskReferenceUpdateProposal
from tools.workspace_sandbox.runner import ExecutionResult
from workflows.definition import TaskBinding, parse_workflow_source, render_workflow_source


@pytest.fixture
def configured(tmp_path):
    task = tmp_path / "task"
    task.mkdir()
    manifest = task / "task.yaml"
    manifest.write_text("trusted fixture declaration")
    llm = tmp_path / "agents.json"
    llm.write_text('{"tune": {"planner_strategy": "native-timing-v1"}}')
    scratch = tmp_path / "observations"
    scratch.mkdir()
    recovery = tmp_path / "recovery"
    recovery.mkdir(mode=0o700)
    source = tmp_path / "workflow.py"
    source.write_text(render_workflow_source(reusable()))
    project = Project(
        project_id="edit", project_root=tmp_path, source_file=source, recovery_directory=recovery
    )
    pin = TaskBinding(
        package_id="synthetic",
        revision="revision-one",
        task_data_path_id="synthetic_path",
        semantic_fingerprint="a" * 64,
    )
    choice = TaskChoice(
        task_id="selected",
        label="Synthetic revision one",
        task_manifest=str(manifest),
        data_root=str(tmp_path / "data"),
        llm_config_file=str(llm),
        task_read_only=(str(task),),
        preparation_root=str(scratch),
        candidate_root=str(tmp_path / "candidates"),
        preparation_timeout_seconds=10,
        candidate_timeout_seconds=10,
        candidate_network=False,
        candidate_devices=(),
        candidate_environment_names=(),
        task_revision=pin,
    )
    return project, choice


def child_result(profile, argv, *, fingerprint="a" * 64):
    job = CompositionJob.model_validate_json((profile.workspace / CHILD_REQUEST_NAME).read_bytes())
    facts = TaskCompositionSummary(
        semantic_fingerprint=fingerprint,
        task_data_path_id="synthetic_path",
        task_config={"forward_contract": {"shape": [3]}},
        dataset_profile={},
        primary_metric={"direction": "lower"},
        secondary_metrics=[],
        parameter_rules={},
        inference_preflight={},
        source_paths={},
        plugins=[],
        code_package_identity=None,
        prompt_renderer_identity=None,
        preflight_estimator_identity={},
        data_analysis_identity=None,
        task_health_declaration="fixture",
    )
    assert not profile.network and profile.devices == profile.environment_names == ()
    result = CompositionResult(
        request_sha256=job.digest,
        manifest_sha256=job.manifest_sha256,
        outcome="passed",
        task=facts,
        planner_strategy_identity={"fixture": True},
    )
    (profile.workspace / CHILD_RESULT_NAME).write_text(result.model_dump_json())
    return ExecutionResult(status="completed", returncode=0, elapsed_seconds=0.1)


def update(author, choice):
    return ReviewRequest(
        expected_sha256=author.read().sha256,
        proposal=TaskReferenceUpdateProposal(
            selected_choice_id=choice.task_id, expected_task_binding=choice.task_revision
        ),
    )


def test_http_review_consumes_configured_target_and_preserves_graph(configured, monkeypatch):
    """A dropped proposal dispatch or silent native mismatch loses the typed owner observation."""
    project, choice = configured
    monkeypatch.setattr(composition_check, "run", child_result)
    author = WorkflowAuthoring(project, task_reference_targets((choice,)))
    before = project.source_file.read_bytes()
    app = FastAPI()
    app.include_router(editor_router((project,), task_targets=task_reference_targets((choice,))))
    with TestClient(app) as client:
        response = client.post(
            "/api/editor/edit/review", json=update(author, choice).model_dump(mode="json")
        )
    assert response.status_code == 200, response.text
    value = response.json()
    report = value["task_reference_update"]
    assert report["observation"]["result"]["task"]["task_config"] == {
        "forward_contract": {"shape": [3]}
    }
    assert report["save_supported"] is report["execution_ready"] is False
    assert [(f["code"], f["state"]) for f in report["findings"]] == [
        ("identity_verified", "retained"),
        ("compatibility_unresolved", "blocked"),
        ("current_snapshot_adoption", "requires_review"),
    ]
    proposed = parse_workflow_source(value["source"])
    original = parse_workflow_source(before.decode())
    assert proposed.definition.nodes == original.definition.nodes
    assert proposed.definition.externals == original.definition.externals
    assert proposed.positions == original.positions
    assert proposed.task_binding == choice.task_revision
    assert proposed.definition.task.manifest == choice.task_manifest
    assert project.source_file.read_bytes() == before and not tuple(
        project.recovery_directory.iterdir()
    )


def test_same_revision_changed_contents_blocks_without_repinning(configured, monkeypatch):
    project, choice = configured
    monkeypatch.setattr(
        composition_check,
        "run",
        lambda profile, argv: child_result(profile, argv, fingerprint="b" * 64),
    )
    author = WorkflowAuthoring(project, task_reference_targets((choice,)))
    review = author.review(update(author, choice))
    assert review.task_reference_update.target_binding == choice.task_revision
    assert review.task_reference_update.observation.result.task.semantic_fingerprint == "b" * 64
    assert review.task_reference_update.findings[0].code == "identity_mismatch"
    assert review.task_reference_update.findings[0].state == "blocked"
    assert author.read().document.task_binding is None


def test_client_cannot_override_target_or_trigger_inspection_by_read(configured, monkeypatch):
    project, choice = configured
    author = WorkflowAuthoring(project, task_reference_targets((choice,)))
    monkeypatch.setattr(
        composition_check, "run", lambda *args: pytest.fail("implicit or unconfigured inspection")
    )
    author.read()
    author.review(
        ReviewRequest(
            expected_sha256=author.read().sha256,
            proposal=SourceProposal(kind="source", source=project.source_file.read_text()),
        )
    )
    forged = update(author, choice).model_copy(
        update={
            "proposal": TaskReferenceUpdateProposal(
                selected_choice_id=choice.task_id,
                expected_task_binding=choice.task_revision.model_copy(
                    update={"semantic_fingerprint": "b" * 64}
                ),
            )
        }
    )
    with pytest.raises(AuthoringError, match="configured task selection changed"):
        author.review(forged)
    unversioned = choice.model_copy(update={"task_revision": None})
    assert task_reference_targets((unversioned,)) == ()
    assert not tuple(Path(choice.preparation_root).iterdir())


def test_source_changed_during_explicit_inspection_preserves_draft(configured, monkeypatch):
    project, choice = configured
    author = WorkflowAuthoring(project, task_reference_targets((choice,)))
    request = update(author, choice)
    original = project.source_file.read_text()

    def race(profile, argv):
        result = child_result(profile, argv)
        project.source_file.write_text(original + "\n# agent edit during inspection\n")
        return result

    monkeypatch.setattr(composition_check, "run", race)
    with pytest.raises(AuthoringError, match="source changed") as failure:
        author.review(request)
    assert failure.value.proposal.task_reference_update is not None
    assert "agent edit" in failure.value.current.source
    assert not tuple(project.recovery_directory.iterdir())


def test_observation_refuses_misspelled_llm_config_key_before_inspection(tmp_path, monkeypatch):
    """Observation parses the explicit profile with the strict loader: a typo fails before any inspection."""
    from tools.workflow_authoring import task_observation
    from tools.workflow_authoring.task_models import TaskReferenceTarget

    profile = tmp_path / "agents.json"
    profile.write_text(
        json.dumps({"interpet": {"provider": "openai", "model_id": "gpt-4o-mini"}}),
        encoding="utf-8",
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("inspection reached before the profile was refused")

    monkeypatch.setattr(task_observation, "observe_composition", forbidden)
    monkeypatch.setattr(task_observation, "manifest_digest", forbidden)
    target = TaskReferenceTarget.model_construct(
        manifest=tmp_path / "manifest.yaml",
        data_root=tmp_path / "data",
        llm_config_file=profile,
        inspection_root=tmp_path,
        read_only=(),
        settings=None,
    )
    with pytest.raises(ValueError, match=r"unknown configuration keys: \['interpet'\]"):
        task_observation.observe_target(target)
