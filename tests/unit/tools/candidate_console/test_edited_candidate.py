"""Saved source reaches admission; policy and review identity fail closed."""

import json
from pathlib import Path
from uuid import uuid4

import pytest

from tools.candidate_console.edited_candidate import (
    EditedCandidate,
    EditedRunLaunch,
    EditedRunSelection,
)
from tools.candidate_console.service import CandidateConsole
from tools.candidate_operations import read_prepared_candidate
from tools.candidate_operations.models import OperationFailure
from tools.workflow_authoring.models import Project
from tools.workflow_authoring.service import WorkflowAuthoring
from workflows.definition import WorkflowDocument, render_workflow_source


@pytest.fixture
def selection(selection):
    return selection.model_copy(update={"candidate_environment_names": ("OPENAI_API_KEY",)})


@pytest.fixture
def console_config(console_config, tmp_path):
    credentials = tmp_path / "offline-credentials.json"
    credentials.write_text(json.dumps({"OPENAI_API_KEY": "offline-test-key"}))
    credentials.chmod(0o600)
    return console_config.model_copy(update={"credential_file": str(credentials)})


@pytest.fixture
def edited(prepared, tmp_path, monkeypatch):
    console, selection, _ = prepared
    monkeypatch.setattr("tools.candidate_operations.submit.releasable", lambda *a: True)
    saved = read_prepared_candidate(console.config.operation_store, selection.operation_id)
    prepared_root = Path(saved.request.preview.project_root)
    root = tmp_path / "editor"
    root.mkdir()
    (root / "recovery").mkdir(mode=0o700)
    fields = saved.request.preview.document.model_dump(mode="json")
    for item in fields["definition"]["externals"]:
        location = prepared_root / item["location"]
        if item["contract"] == "proposal.input":
            copied = prepared_root / "edited_seed.json"
            copied.write_bytes(location.read_bytes())
            location = copied
        item["location"] = str(location)
    for item in fields["definition"]["nodes"]:
        if item["id"] == "propose":
            item["id"] = "edited_proposal"
        if item["request"]["kind"] == "protocol":
            for argument in item["request"]["arguments"]:
                if argument["source"].get("node") == "propose":
                    argument["source"]["node"] = "edited_proposal"
    document = WorkflowDocument.model_validate_json(json.dumps(fields))
    source = root / "workflow.py"
    source.write_text(render_workflow_source(document))
    project = Project(
        project_id="edited",
        project_root=root,
        source_file=source,
        recovery_directory=root / "recovery",
    )
    config = console.config.model_copy(
        update={"editor_projects": (project,), "runnable_editor_projects": ("edited",)}
    )
    adapter = EditedCandidate(CandidateConsole(config))
    selection = EditedRunSelection(
        prepare_operation_id=selection.operation_id,
        expected_source_sha256=WorkflowAuthoring(project).read().sha256,
    )
    return adapter, project, selection


def launch_selection(review, operation_id=None):
    return EditedRunLaunch(
        **review.selection.model_dump(),
        expected_review_digest=review.review_digest,
        candidate_operation_id=operation_id or uuid4(),
    )


def test_review_captures_edited_ids_and_preserves_prepared_config(edited):
    """Regeneration or rebasing llm.json to editor root loses selected source/config."""
    adapter, project, selection = edited
    review = adapter.review(project.project_id, selection)
    request = review.envelope.request
    assert request.preview.document.definition.nodes[0].id == "edited_proposal"
    assert request.workflow_source.source == project.source_file.read_text()
    assert Path(request.preview.llm_config_file).is_absolute()
    assert not Path(request.preview.document.definition.task.workspace).exists()


def test_stale_saved_source_and_external_refuse_before_credentials(edited, monkeypatch):
    """Launch must reconstruct review before loading credentials or admitting work."""
    adapter, project, selection = edited
    review = adapter.review(project.project_id, selection)
    monkeypatch.setattr(
        "tools.candidate_console.edited_candidate.credentials",
        lambda *a: pytest.fail("credentials read"),
    )
    seed = next(
        item for item in review.envelope.request.files if item.reference.startswith("external.")
    )
    path = Path(seed.path)
    original = path.read_text()
    path.write_text(original + "\n")
    with pytest.raises(OperationFailure, match="reviewed bindings changed"):
        adapter.launch(project.project_id, launch_selection(review))
    path.write_text(original)
    project.source_file.write_text(project.source_file.read_text() + "\n")
    with pytest.raises(OperationFailure, match="saved source changed"):
        adapter.launch(project.project_id, launch_selection(review))


def test_replay_uses_admitted_capture_after_source_and_workspace_change(edited, monkeypatch):
    """Same UUID recovery cannot rebuild against now nonfresh workspace or source."""
    adapter, project, selection = edited
    review = adapter.review(project.project_id, selection)
    launch = launch_selection(review)
    first = adapter.launch(project.project_id, launch)
    workspace = Path(review.envelope.request.preview.document.definition.task.workspace)
    workspace.mkdir()
    (workspace / "later").write_text("claimed")
    project.source_file.write_text("invalid later source")
    monkeypatch.setattr(
        "tools.candidate_console.edited_candidate.credentials",
        lambda *a: pytest.fail("replay credentials"),
    )
    replay = adapter.launch(project.project_id, launch)
    assert replay.observation == "existing"
    assert replay.request_digest == first.request_digest
    with pytest.raises(OperationFailure, match="another reviewed capture"):
        adapter.launch(
            project.project_id, launch.model_copy(update={"expected_review_digest": "0" * 64})
        )
    record = (
        Path(adapter.console.config.operation_store.state_root)
        / "operations"
        / str(launch.candidate_operation_id)
        / "request.json"
    )
    record.write_text("{}")
    with pytest.raises(ValueError):
        adapter.launch(project.project_id, launch)


def test_context_mismatch_and_disabled_project_refuse(edited):
    adapter, project, selection = edited
    # Mutate the declared workspace while preserving a supported full declaration.
    source = WorkflowAuthoring(project).read()
    fields = source.document.model_dump(mode="json")
    fields["definition"]["task"]["workspace"] += "-different"
    project.source_file.write_text(
        render_workflow_source(WorkflowDocument.model_validate_json(json.dumps(fields)))
    )
    selected = selection.model_copy(
        update={"expected_source_sha256": WorkflowAuthoring(project).read().sha256}
    )
    with pytest.raises(OperationFailure, match="workspace differs"):
        adapter.review(project.project_id, selected)
    with pytest.raises(OperationFailure, match="not enabled"):
        adapter.review("other", selection)


def test_legacy_persisted_record_load_and_retry_keep_old_digest(edited):
    """Absent source in old request.json must verify and return its existing UUID."""
    import hashlib

    from tools.candidate_operations import (
        CandidateOperation,
        lookup_operation_request,
        submit_operation,
    )
    from tools.candidate_worker.models import CandidateRunRequest

    adapter, project, selection = edited
    request = adapter.review(project.project_id, selection).envelope.request
    fields = request.model_dump(mode="json")
    fields.pop("workflow_source")
    old_digest = hashlib.sha256(
        json.dumps(
            {"kind": "candidate", "request": fields}, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    submission = CandidateOperation(
        request_id=uuid4(), request=CandidateRunRequest.model_validate_json(json.dumps(fields))
    )
    config = adapter.console.config.operation_store
    first = submit_operation(
        config, submission, launch_environment={"OPENAI_API_KEY": "offline-test-key"}
    )
    record = Path(config.state_root) / "operations" / str(first.operation_id) / "request.json"
    saved = json.loads(record.read_text())
    saved["submission"]["request"].pop("workflow_source")
    saved["request_digest"] = old_digest
    record.write_text(json.dumps(saved))
    assert lookup_operation_request(config, first.operation_id) == submission
    retried = submit_operation(config, submission, launch_environment={})
    assert retried.request_digest == old_digest and retried.observation == "existing"


def test_http_review_launch_and_exact_id_recovery(edited):
    """HTTP must use edited adapter, expose safe effects, and recover same capture."""
    from tests.unit.tools.candidate_console.test_http import client

    adapter, project, selection = edited
    with client(adapter.console.config) as http:
        choices = http.get("/api/editor/projects").json()
        assert choices == [{"project_id": project.project_id, "candidate_run_enabled": True}]
        response = http.post(
            f"/api/editor/{project.project_id}/candidate-review",
            json=selection.model_dump(mode="json"),
        )
        assert response.status_code == 200, response.text
        reviewed = response.json()
        assert "envelope" not in reviewed and "bridge_arguments" not in response.text
        assert reviewed["effects"]["nodes"][0] == ["edited_proposal", "proposal"]
        launch = {
            **selection.model_dump(mode="json"),
            "candidate_operation_id": str(uuid4()),
            "expected_review_digest": reviewed["review_digest"],
        }
        started = http.post(f"/api/editor/{project.project_id}/candidate-launch", json=launch)
        assert started.status_code == 202, started.text
        project.source_file.write_text("changed after admission")
        replay = http.post(f"/api/editor/{project.project_id}/candidate-launch", json=launch)
        assert replay.status_code == 202 and replay.json()["observation"] == "existing"
        assert replay.json()["request_digest"] == started.json()["request_digest"]


def test_external_outside_prepared_mount_refuses_before_preview(edited, monkeypatch):
    """Browser-authored external references cannot widen native read-only roots."""
    adapter, project, selection = edited
    source = WorkflowAuthoring(project).read()
    fields = source.document.model_dump(mode="json")
    fields["definition"]["externals"][0]["location"] = str(
        project.project_root / "outside-mount.json"
    )
    project.source_file.write_text(
        render_workflow_source(WorkflowDocument.model_validate_json(json.dumps(fields)))
    )
    selected = selection.model_copy(
        update={"expected_source_sha256": WorkflowAuthoring(project).read().sha256}
    )
    monkeypatch.setattr(
        "tools.candidate_console.edited_candidate.preview_workflow",
        lambda *a: pytest.fail("preview read forbidden external"),
    )
    with pytest.raises(OperationFailure) as refused:
        adapter.review(project.project_id, selected)
    assert refused.value.detail.code == "unsupported"
    assert "explicit read-only mount" in str(refused.value.__cause__)


def test_edited_readiness_does_not_change_review_identity_or_precede_digest(edited, monkeypatch):
    """Readiness is ephemeral, and stale edited launch refuses before private access."""
    adapter, project, selection = edited
    first = adapter.review(project.project_id, selection)
    assert first.credential_readiness.ready
    Path(adapter.console.config.credential_file).write_text("{}")
    second = adapter.review(project.project_id, selection)
    assert second.review_digest == first.review_digest
    assert not second.credential_readiness.ready
    assert "credential_readiness" not in second.envelope.model_dump_json()
    monkeypatch.setattr(
        "tools.candidate_console.files.private_bytes",
        lambda *a: pytest.fail("private read before digest"),
    )
    with pytest.raises(OperationFailure, match="reviewed bindings changed"):
        adapter.launch(
            project.project_id,
            launch_selection(first).model_copy(update={"expected_review_digest": "0" * 64}),
        )


def test_reusable_saved_source_refuses_legacy_launch_before_preview(edited, monkeypatch):
    """The actual edited-run entry must refuse v2 before any input observation."""
    from tests.unit.workflows.reusable_fixture import EXAMPLE

    adapter, project, selection = edited
    project.source_file.write_text(EXAMPLE.read_text())
    selected = EditedRunSelection(
        prepare_operation_id=selection.prepare_operation_id,
        expected_source_sha256=WorkflowAuthoring(project).read().sha256,
    )
    monkeypatch.setattr(
        "tools.candidate_console.edited_candidate.preview_workflow",
        lambda *args: pytest.fail("v2 reached legacy preview"),
    )
    with pytest.raises(OperationFailure) as error:
        adapter.review(project.project_id, selected)
    assert error.value.detail.code == "unsupported"
    assert "reusable declarations" in str(error.value)


def test_reviewed_resources_bind_the_launch_and_replay_idempotently(edited):
    """B3-4c: the reservation is reviewed. A retried launch carrying it replays as the
    same operation; a launch that changes it after review is stale."""
    from tools.candidate_operations.models import OperationResources

    adapter, project, selection = edited
    resources = OperationResources(
        gpu_count=0, host_memory_gib=2.0, cpu_slots=1, time_budgeted=False
    )
    plain = adapter.review(project.project_id, selection)
    review = adapter.review(
        project.project_id, selection.model_copy(update={"resources": resources})
    )
    assert review.selection.resources == resources
    assert review.review_digest != plain.review_digest
    launch = launch_selection(review)
    first = adapter.launch(project.project_id, launch)
    replay = adapter.launch(project.project_id, launch)
    assert replay.observation == "existing" and replay.request_digest == first.request_digest
    changed = launch.model_copy(
        update={
            "candidate_operation_id": uuid4(),
            "resources": resources.model_copy(update={"cpu_slots": 2}),
        }
    )
    with pytest.raises(OperationFailure, match="review again"):
        adapter.launch(project.project_id, changed)
