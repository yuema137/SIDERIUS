"""Fresh policy before content reads and exact recovery before mutable source access."""

from pathlib import Path
from uuid import uuid4

import pytest

from tests.unit.tools.candidate_prepare.test_reusable_preparation import reusable
from tools.candidate_console.reusable_preparation import (
    NewRunIntent,
    NewRunSelection,
    ReusablePreparation,
)
from tools.candidate_console.service import CandidateConsole
from tools.candidate_operations.models import OperationFailure
from tools.workflow_authoring.models import Project


@pytest.fixture
def selection(selection, tmp_path):
    # These tests exercise inert admission, not task imports. All mutable input
    # bytes belong to this test, including the otherwise checkout-owned manifest.
    manifest = tmp_path / "task.yaml"
    manifest.write_bytes(Path(selection.task_manifest).read_bytes())
    return selection.model_copy(update={"task_manifest": str(manifest)})


@pytest.fixture
def fresh(reusable, console_config):
    root = Path(reusable.project_root)
    recovery = root / "recovery"
    recovery.mkdir(mode=0o700)
    project = Project(
        project_id="fresh",
        project_root=root,
        source_file=Path(reusable.source_path),
        recovery_directory=recovery,
    )
    store = console_config.operation_store.model_copy(
        update={
            "preparation_roots": (
                *console_config.operation_store.preparation_roots,
                reusable.runs_root,
            ),
            "candidate_roots": (
                *console_config.operation_store.candidate_roots,
                reusable.runs_root,
            ),
        }
    )
    task = console_config.tasks[0].model_copy(update={"reusable_runs_root": reusable.runs_root})
    config = console_config.model_copy(
        update={
            "operation_store": store,
            "tasks": (task,),
            "editor_projects": (project,),
            "runnable_editor_projects": ("fresh",),
        }
    )
    adapter = ReusablePreparation(CandidateConsole(config))
    selection = NewRunSelection(
        task_id=task.task_id,
        run_name="new-run",
        run_id=uuid4(),
        preparation_operation_id=uuid4(),
        expected_source_sha256=reusable.expected_source_sha256,
    )
    return adapter, selection, project


def intent(review):
    return NewRunIntent(selection=review.selection, expectation=review.expectation)


def test_review_no_effect_and_recovery_without_source(fresh, monkeypatch):
    adapter, selection, project = fresh
    review = adapter.review("fresh", selection)
    assert not Path(review.inputs).parent.exists()
    calls = []
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", lambda *args: calls.append(args))
    first = adapter.prepare("fresh", intent(review))
    project.source_file.unlink()
    monkeypatch.setattr(
        "tools.candidate_console.reusable_preparation.inspect_reusable_source",
        lambda *args: pytest.fail("recovery read source"),
    )
    second = adapter.prepare("removed-project", intent(review))
    assert first.operation_id == second.operation_id == selection.preparation_operation_id
    assert len(calls) == 1
    wrong = intent(review).model_copy(
        update={"expectation": review.expectation.model_copy(update={"request_digest": "0" * 64})}
    )
    with pytest.raises(OperationFailure, match="reviewed intent"):
        adapter.prepare("fresh", wrong)


def test_policy_before_external_content_on_review_and_prepare(fresh, monkeypatch):
    adapter, selection, project = fresh
    review = adapter.review("fresh", selection)
    config = adapter.console.config
    task = config.tasks[0].model_copy(
        update={"task_manifest": str(project.project_root / "forbidden")}
    )
    adapter.console.config = config.model_copy(update={"tasks": (task,)})
    monkeypatch.setattr(
        "tools.candidate_prepare.reusable_admission.admit",
        lambda *args, **kwargs: pytest.fail("external content before policy"),
    )
    for action in (
        lambda: adapter.review("fresh", selection),
        lambda: adapter.prepare("fresh", intent(review)),
    ):
        with pytest.raises(OperationFailure, match="policy"):
            action()
    assert not Path(review.inputs).parent.exists()


@pytest.mark.parametrize("which", ["source", "manifest", "config"])
def test_reviewed_observation_drift_never_dispatches(fresh, monkeypatch, which):
    adapter, selection, _ = fresh
    review = adapter.review("fresh", selection)
    observed = getattr(review.expectation.observations, which)
    with Path(observed.path).open("a") as stream:
        stream.write("\n# changed\n")
    monkeypatch.setattr(
        "tools.candidate_operations.submit.spawn",
        lambda *args: pytest.fail("dispatch after reviewed input drift"),
    )
    with pytest.raises(OperationFailure):
        adapter.prepare("fresh", intent(review))
    assert not Path(review.inputs).parent.exists()


def test_http_code_parity_and_presubmit_marker_boundary(fresh, monkeypatch):
    from tests.unit.tools.candidate_console.test_http import client

    adapter, selection, project = fresh
    http = client(adapter.console.config)
    path = "/api/editor/fresh/reusable-preparations/"
    review = adapter.review("fresh", selection)
    response = http.post(path + "review", json=selection.model_dump(mode="json"))
    assert response.status_code == 200
    assert response.json() == review.model_dump(mode="json")
    assert not Path(review.inputs).parent.exists()
    # Untrusted browser path/resource fields never reach native inspection.
    invalid = selection.model_dump(mode="json") | {"source_path": "/forbidden"}
    assert http.post(path + "review", json=invalid).status_code == 422
    project.source_file.write_text("# changed")
    response = http.post(path + "prepare", json=intent(review).model_dump(mode="json"))
    assert response.status_code == 409
    assert response.json()["error"]["admission_not_attempted"] is True


def test_recovery_rejects_changed_run_metadata(fresh, monkeypatch):
    adapter, selection, _ = fresh
    review = adapter.review("fresh", selection)
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", lambda *args: None)
    adapter.prepare("fresh", intent(review))
    for change in (
        {"run_id": uuid4()},
        {"run_name": "different"},
        {"expected_source_sha256": "0" * 64},
    ):
        changed = intent(review).model_copy(
            update={"selection": selection.model_copy(update=change)}
        )
        with pytest.raises(OperationFailure, match="retained selection"):
            adapter.prepare("fresh", changed)


def test_source_task_escape_refused_before_content_reader(fresh, monkeypatch):
    import hashlib

    from workflows.definition import (
        ReusableWorkflowDocument,
        parse_workflow_source,
        render_workflow_source,
    )

    adapter, selection, project = fresh
    document = parse_workflow_source(project.source_file.read_text()).model_dump()
    forbidden = project.project_root / "unconfigured.yaml"
    forbidden.write_text("not authorized to read this content")
    document["definition"]["task"]["manifest"] = str(forbidden)
    project.source_file.write_text(
        render_workflow_source(ReusableWorkflowDocument.model_validate(document))
    )
    changed = selection.model_copy(
        update={
            "expected_source_sha256": hashlib.sha256(project.source_file.read_bytes()).hexdigest()
        }
    )
    monkeypatch.setattr(
        "tools.candidate_prepare.admission.observe_file",
        lambda *args: pytest.fail("read external content before configured policy"),
    )
    with pytest.raises(OperationFailure, match="policy"):
        adapter.review("fresh", changed)


def test_submit_failure_is_not_presubmit_refusal(fresh, monkeypatch):
    from tests.unit.tools.candidate_console.test_http import client

    adapter, selection, _ = fresh
    review = adapter.review("fresh", selection)

    def fail(*args, **kwargs):
        raise OperationFailure("busy", "fixture owner already entered")

    monkeypatch.setattr("tools.candidate_console.reusable_preparation.submit_operation", fail)
    response = client(adapter.console.config).post(
        "/api/editor/fresh/reusable-preparations/prepare",
        json=intent(review).model_dump(mode="json"),
    )
    assert response.status_code == 409
    assert "admission_not_attempted" not in response.json()["error"]


def test_review_shows_recorded_version_name_without_changing_identity(fresh):
    """Fails if the Save name is not projected for the bound SHA or alters the expectation."""
    from tools.workflow_authoring.versions import VersionRecord, encode_record, version_record_path

    adapter, selection, project = fresh
    unnamed = adapter.review("fresh", selection)
    assert unnamed.source_version_name is None
    record = VersionRecord.model_validate(
        {
            "source_name": project.source_file.name,
            "versions": [
                {
                    "sha256": selection.expected_source_sha256,
                    "name": "baseline",
                    "recorded_at": "2026-10-27T00:00:00Z",
                    "origin": "saved",
                }
            ],
        }
    )
    version_record_path(project.source_file).write_bytes(encode_record(record))
    named = adapter.review("fresh", selection)
    assert named.source_version_name == "baseline"
    assert named.expectation == unnamed.expectation
    assert "source_version_name" not in intent(named).model_dump()


def test_preparation_review_prechecks_configured_credential_names(fresh, tmp_path):
    """R-5: before Prepare the server reports which configured names are absent, and a
    missing file is distinguished from an unreadable one; values never leave the process."""
    adapter, selection, _ = fresh
    task = adapter.console.config.tasks[0].model_copy(
        update={"candidate_environment_names": ("OPENAI_API_KEY",)}
    )
    path = tmp_path / "keys.env"
    adapter.console.config = adapter.console.config.model_copy(
        update={"tasks": (task,), "credential_file": str(path)}
    )
    missing = adapter.review("fresh", selection).credential_readiness
    assert (missing.file_status, missing.ready) == ("missing", False)
    assert missing.missing_names == ("OPENAI_API_KEY",)
    path.write_text("OPENAI_API_KEY=SECRET-MARKER\n")
    path.chmod(0o644)
    assert adapter.review("fresh", selection).credential_readiness.file_status == "unavailable"
    path.chmod(0o600)
    ready = adapter.review("fresh", selection)
    assert ready.credential_readiness.ready
    assert "SECRET-MARKER" not in ready.model_dump_json()
