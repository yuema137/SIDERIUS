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
