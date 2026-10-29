"""Experiment setups: registry, per-task creation and the readers that must see created setups."""

import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.unit.tools.candidate_console.test_http import client
from tests.unit.tools.candidate_console.test_settings_page import _client, _load
from tests.unit.tools.candidate_console.test_settings_page import workspace as settings_workspace
from tools.candidate_console.native_chain import check_editor_separation
from tools.candidate_console.reusable_policy import configured_capture
from tools.candidate_console.settings_file import SettingsInvalid
from tools.candidate_operations.models import OperationFailure
from tools.workflow_authoring.templates import render_shape
from workflows.definition import ReusableTaskReferences, TaskBinding

PIN = TaskBinding(
    package_id="synthetic",
    revision="r1",
    task_data_path_id="path-1",
    semantic_fingerprint="a" * 64,
)


def _console_json(root: Path) -> Path:
    return root / "settings" / "console.json"


def _edit(root: Path, **fields) -> None:
    path = _console_json(root)
    path.write_text(json.dumps(json.loads(path.read_text()) | fields))


@pytest.fixture
def workspace(settings_workspace):
    """The init workspace (browser_creatable) with a second task beside ``synthetic``."""
    document = json.loads(_console_json(settings_workspace).read_text())
    first = document["tasks"][0]
    first.pop("reusable_runs_root", None)  # derived: runs/<task_id> enables reusable runs
    other = dict(first, task_id="other", label="Other task")
    _edit(settings_workspace, tasks=[first, other])
    (settings_workspace / "data" / "other").mkdir()
    (settings_workspace / "runs" / "synthetic").mkdir(mode=0o700, exist_ok=True)
    for parent in ("preparations", "candidates", "runs"):
        (settings_workspace / parent / "other").mkdir(mode=0o700)
    return settings_workspace


def _create(api, task_id="synthetic", label="My setup", template_id="single-step"):
    return api.post(
        f"/api/tasks/{task_id}/setups", json={"label": label, "template_id": template_id}
    )


def _registry(root: Path) -> Path:
    return root / "settings" / "experiment_setups.json"


def test_created_setup_is_admitted_only_for_its_own_task(workspace):
    """Defect: a run of a created setup borrows another task's policy (task_policy)."""
    api = _client(_load(workspace))
    response = _create(api)
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["setup_id"] == "my-setup" and created["runnable"]
    assert created["refs_match_task"] and created["saved_version"] is not None
    root = workspace / "projects" / "my-setup"
    assert stat.S_IMODE((root / ".recovery").stat().st_mode) == 0o700
    assert stat.S_IMODE(_registry(workspace).stat().st_mode) == 0o600
    console = api.app.state.console
    project, task, _ = configured_capture(console.setups, "my-setup", "synthetic")
    assert (project.source_file, task.task_id) == (root / "workflow.py", "synthetic")
    with pytest.raises(OperationFailure, match="another task") as refused:
        configured_capture(console.setups, "my-setup", "other")
    assert refused.value.detail.code == "task_policy"
    # Listed for its task only, and usable in the editor without a restart.
    assert [s["setup_id"] for s in api.get("/api/tasks/synthetic/setups").json()["setups"]] == [
        "my-setup"
    ]
    assert api.get("/api/tasks/other/setups").json() == {"setups": []}
    assert api.get("/api/editor/my-setup").status_code == 200


def test_setup_created_at_runtime_is_covered_by_native_chain_separation(workspace):
    """Defect: native chains check only startup editor_projects, so a new setup escapes."""
    api = _client(_load(workspace))
    assert _create(api).status_code == 201
    console = api.app.state.console
    source = workspace / "projects" / "my-setup" / "workflow.py"
    choice = SimpleNamespace(
        request=SimpleNamespace(
            capture_path=str(source), envelope=str(workspace / "candidates" / "chain")
        )
    )
    admission = SimpleNamespace(input_files=(), workspace=str(workspace / "candidates" / "w"))
    with pytest.raises(OperationFailure, match="overlaps"):
        check_editor_separation(console, choice, admission)


def test_registry_id_colliding_with_editor_project_fails_startup(workspace):
    """Defect: two setups share an ID and every route silently serves only one of them."""
    assert _create(_client(_load(workspace))).status_code == 201
    root = workspace / "projects" / "my-setup"
    _edit(
        workspace,
        editor_projects=[
            {
                "project_id": "my-setup",
                "project_root": str(root),
                "source_file": str(root / "workflow.py"),
                "recovery_directory": str(root / ".recovery"),
            }
        ],
    )
    with pytest.raises(SettingsInvalid, match=r"also a console\.json editor project"):
        _load(workspace)


def test_legacy_editor_project_is_listed_for_its_task_and_keeps_its_routes(workspace):
    """Defect: legacy editor_projects vanish from the editor or match the wrong task."""
    task = _load(workspace).config.tasks[0]
    root = workspace.parent / "legacy"
    (root / "recovery").mkdir(parents=True)
    (root / "recovery").chmod(0o700)
    references = ReusableTaskReferences(manifest=task.task_manifest, data_root=task.data_root)
    (root / "workflow.py").write_text(render_shape(None, references))
    project = {
        "project_id": "legacy",
        "project_root": str(root),
        "source_file": str(root / "workflow.py"),
        "recovery_directory": str(root / "recovery"),
    }
    _edit(workspace, editor_projects=[project], runnable_editor_projects=["legacy"])
    api = _client(_load(workspace))
    assert api.get("/api/editor/projects").json() == [
        {"project_id": "legacy", "candidate_run_enabled": True}
    ]
    assert api.get("/api/editor/legacy").status_code == 200
    listed = api.get("/api/tasks/synthetic/setups").json()["setups"]
    assert [(s["setup_id"], s["runnable"], s["refs_match_task"]) for s in listed] == [
        ("legacy", True, True)
    ]
    assert api.get("/api/tasks/other/setups").json() == {"setups": []}
    # Legacy setups keep their unbound run admission: any configured task's policy applies.
    console = api.app.state.console
    assert configured_capture(console.setups, "legacy", "other")[1].task_id == "other"


@pytest.mark.parametrize("matches", [False, True])
def test_binding_is_written_only_after_identity_is_observed(workspace, monkeypatch, matches):
    """Defect: a setup carries an accepted revision the task package no longer proves."""
    document = json.loads(_console_json(workspace).read_text())
    document["tasks"][0]["task_revision"] = PIN.model_dump(mode="json")
    _edit(workspace, tasks=document["tasks"])
    observed = SimpleNamespace(result=SimpleNamespace(outcome="passed"))
    monkeypatch.setattr(
        "tools.workflow_authoring.task_observation.observe_target", lambda target: observed
    )
    monkeypatch.setattr(
        "tools.workflow_authoring.task_observation.identity_matches", lambda *a: matches
    )
    api = _client(_load(workspace))
    response = _create(api)
    if not matches:
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "identity_mismatch"
        assert response.json()["finding"]["state"] == "blocked"
        assert not _registry(workspace).exists()
        assert list((workspace / "projects").iterdir()) == []
        return
    assert response.status_code == 201, response.text
    source = (workspace / "projects" / "my-setup" / "workflow.py").read_text()
    assert PIN.semantic_fingerprint in source and "task_binding" in source


def test_concurrent_registry_write_is_refused(workspace):
    """Defect: a stale console overwrites setups another writer registered."""
    api = _client(_load(workspace))
    assert _create(api).status_code == 201
    path = _registry(workspace)
    changed = json.loads(path.read_text())
    changed["setups"][0]["label"] = "Renamed elsewhere"
    path.write_text(json.dumps(changed))
    os.chmod(path, 0o600)
    before = path.read_bytes()
    response = _create(api, label="Second")
    assert response.status_code == 409 and response.json()["error"]["code"] == "stale"
    assert path.read_bytes() == before
    assert not (workspace / "projects" / "second").exists()


@pytest.mark.parametrize("policy", [{"browser_creatable": False}, None])
def test_creation_is_refused_unless_console_json_allows_it(workspace, policy):
    """Defect: a console that never opted in lets the browser create folders and files."""
    _edit(workspace, experiment_setups=policy)
    api = _client(_load(workspace))
    response = _create(api)
    assert response.status_code == 403 and response.json()["error"]["code"] == "read_only"
    assert list((workspace / "projects").iterdir()) == []
    assert not _registry(workspace).exists()


def test_operations_filter_returns_only_the_setups_runs(prepared, monkeypatch):
    """Defect: the Run tab of one setup shows another setup's (or a task-only) run."""
    service, _, _ = prepared
    from tools.candidate_operations import listing as owner

    real = owner.list_operations(service.config.operation_store, 1)
    entry = real.entries[0]
    rows = tuple(entry.model_copy(update={"project_id": p}) for p in ("a", "b", None, "a"))
    seen = []

    def listed(store, limit):
        seen.append(limit)
        return real.model_copy(update={"entries": rows})

    monkeypatch.setattr("tools.candidate_console.service.list_operations", listed)
    api = client(service.config)
    body = api.get("/api/operations?project_id=a&limit=1").json()
    assert [item["project_id"] for item in body["operations"]] == ["a"]
    assert seen == [owner.MAX_LISTED]  # filtered from the bounded window, then limited
    assert len(api.get("/api/operations").json()["operations"]) == 4
    assert api.get("/api/operations?project_id=../x").status_code == 422
