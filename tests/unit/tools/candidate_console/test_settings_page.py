"""Settings routes: CAS write, read-only policy, bounded folder listing and stale safety (P4)."""

import hashlib
import json
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tools.candidate_console import CandidateConsole, PreparedSelection
from tools.candidate_console.app import create_app
from tools.candidate_console.config import load_console
from tools.candidate_console.workspace import init_workspace

SCHEMA = "siderius.console-global-settings/v1"


def _client(resolved) -> TestClient:
    config = resolved.config
    result = TestClient(
        create_app(config, resolved.settings),
        base_url=config.browser_origin,
        raise_server_exceptions=False,
    )
    result.headers.update(
        {
            "Authorization": "Bearer " + Path(config.auth_token_file).read_text(),
            "Origin": config.browser_origin,
        }
    )
    return result


@pytest.fixture
def workspace(console_config, tmp_path):
    """init workspace + synthetic task with locations and model omitted, plus a lab data root."""
    parent = tmp_path / "parent"
    parent.mkdir(mode=0o700)
    config = init_workspace(str(parent))
    root = config.parent.parent
    lab = tmp_path / "lab"
    (lab / "run-a").mkdir(parents=True)
    document = json.loads(config.read_text())
    task = console_config.tasks[0].model_dump(mode="json")
    for field in ("llm_config_file", "data_root", "preparation_root", "candidate_root"):
        task.pop(field)
    document |= {
        "tasks": [task],
        "data_roots": [{"id": "lab", "label": "Lab disk", "path": str(lab)}],
    }
    config.write_text(json.dumps(document))
    init_workspace(str(parent))
    (root / "data" / "synthetic").mkdir()
    return root


def _settings_file(root: Path) -> Path:
    return root / "settings" / "global_settings.json"


def _load(root: Path):
    return load_console(str(root / "settings" / "console.json"))


def _put(api: TestClient, expected: str | None, **settings):
    return api.put(
        "/api/settings",
        json={"expected_sha256": expected, "settings": {"schema_version": SCHEMA, **settings}},
    )


def test_view_reports_origins_paths_and_restart_state(workspace):
    view = _client(_load(workspace)).get("/api/settings").json()
    assert view["enabled"] and view["writable"] and not view["restart_required"]
    rows = {(row["task_id"], row["name"]): row for row in view["rows"]}
    assert rows[("synthetic", "llm_profile")]["origin"] == "global_settings"
    assert rows[("synthetic", "data_root")]["origin"] == "workspace_layout"
    assert {card["label"] for card in view["llm_profiles"]} == {
        card["ref"]["name"] for card in view["llm_profiles"]
    }
    assert [root["id"] for root in view["data_roots"]] == ["lab", "workspace"]


def test_save_is_compare_and_swap_and_applies_after_restart(workspace):
    """Defect: a stale page overwrites a newer file, or a save changes the running console."""
    path = _settings_file(workspace)
    api = _client(_load(workspace))
    view = api.get("/api/settings").json()
    before = path.read_bytes()
    stale = _put(api, "0" * 64, llm_profile=view["pending"]["llm_profile"])
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale"
    assert path.read_bytes() == before

    folder = {"synthetic": {"root_id": "lab", "subpath": "run-a"}}
    saved = _put(
        api,
        view["settings_sha256"],
        llm_profile=view["pending"]["llm_profile"],
        data_folders=folder,
    )
    assert saved.status_code == 200, saved.text
    after = saved.json()
    assert (
        after["restart_required"]
        and after["settings_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    )
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    rows = {(row["task_id"], row["name"]): row for row in after["rows"]}
    assert rows[("synthetic", "data_root")]["effective"].endswith("data/synthetic")  # still active
    restarted = _load(workspace).config.tasks[0]
    assert restarted.data_root.endswith("lab/run-a")


@pytest.mark.parametrize(("policy", "status"), [(None, 403), ({"browser_writable": False}, 403)])
def test_write_is_refused_unless_console_json_opts_in(policy, status, workspace):
    """Defect: the browser can write settings the operator did not make writable."""
    config = workspace / "settings" / "console.json"
    document = json.loads(config.read_text()) | {"global_settings": policy}
    (profile,) = (workspace / "library" / "llm").iterdir()
    document["tasks"][0]["llm_config_file"] = str(profile)  # no settings layer to fill it
    config.write_text(json.dumps(document))
    path = _settings_file(workspace)
    before = path.read_bytes()
    api = _client(_load(workspace))
    digest = hashlib.sha256(before).hexdigest()
    response = _put(api, digest)
    assert response.status_code == status and response.json()["error"]["code"] == "read_only"
    assert path.read_bytes() == before


def test_invalid_settings_are_refused_by_name_without_writing(workspace):
    """Defect: a write that fails console validation is published, or echoes input."""
    path = _settings_file(workspace)
    before = path.read_bytes()
    api = _client(_load(workspace))
    response = _put(
        api,
        hashlib.sha256(before).hexdigest(),
        data_folders={"synthetic": {"root_id": "lab", "subpath": "missing-DO-NOT-ECHO"}},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "settings_invalid"
    assert "data folder for task synthetic" in error["message"]
    assert "DO-NOT-ECHO" not in response.text
    assert path.read_bytes() == before


def test_folder_listing_returns_only_directory_names_and_never_follows_links(workspace, tmp_path):
    """Defect: listing exposes files, follows a link outside the root or is unbounded."""
    lab = tmp_path / "lab"
    (lab / "secret.txt").write_text("DO-NOT-ECHO")
    (lab / "outside").symlink_to(tmp_path)
    for index in range(205):
        (lab / "many" / f"d{index:03}").mkdir(parents=True)
    api = _client(_load(workspace))
    listing = api.get("/api/settings/folders", params={"root_id": "lab"}).json()
    assert listing["entries"] == [
        {"name": "many", "kind": "directory"},
        {"name": "outside", "kind": "link"},
        {"name": "run-a", "kind": "directory"},
    ]
    assert not listing["incomplete"]
    many = api.get("/api/settings/folders", params={"root_id": "lab", "subpath": "many"}).json()
    assert len(many["entries"]) == 200 and many["incomplete"]
    assert many["entries"][0]["name"] == "d000"
    followed = api.get("/api/settings/folders", params={"root_id": "lab", "subpath": "outside"})
    assert followed.status_code == 404
    for params, status in (
        ({"root_id": "lab", "subpath": "../lab"}, 422),
        ({"root_id": "lab", "subpath": "/etc"}, 422),
        ({"root_id": "nope"}, 404),
        ({"root_id": "lab", "limit": 0}, 422),
        ({"root_id": "lab", "limit": 201}, 422),
    ):
        response = api.get("/api/settings/folders", params=params)
        assert response.status_code == status, params
    assert "DO-NOT-ECHO" not in listing.__repr__()


# P4: a changed model profile makes an already-prepared run fail closed after restart.


@pytest.fixture
def console_config(console_config, selection, tmp_path):
    """The conftest config, but with its model profile selected through global settings."""
    from tools.candidate_console.workspace import resolve_console

    parent = tmp_path / "ws-parent"
    parent.mkdir(mode=0o700)
    config = init_workspace(str(parent))
    root = config.parent.parent
    other = tmp_path / "llm-b.json"
    other.write_text("{}")
    document = json.loads(console_config.model_dump_json())
    document["tasks"][0].pop("llm_config_file")
    document |= {
        "workspace_root": str(root),
        "global_settings": {"browser_writable": True},
        "llm_profiles": [
            {"id": "a", "label": "A", "file": selection.llm_config_file},
            {"id": "b", "label": "B", "file": str(other)},
        ],
    }
    config.write_text(json.dumps(document))
    _settings_file(root).write_text(
        json.dumps({"schema_version": SCHEMA, "llm_profile": {"source": "allowlist", "id": "a"}})
    )
    resolved = resolve_console(config.read_bytes())
    assert resolved.config == console_config  # P2: the settings path builds the same config
    return resolved.config


def test_changed_profile_makes_prepared_review_fail_closed(prepared, tmp_path):
    """Defect: after a profile switch and restart, a run prepared with the old one launches."""
    _, selection, _ = prepared
    config = next((tmp_path / "ws-parent").glob("siderius_workspace/settings/console.json"))
    root = config.parent.parent
    for profile, refused in (("b", True), ("a", False)):
        _settings_file(root).write_text(
            json.dumps(
                {"schema_version": SCHEMA, "llm_profile": {"source": "allowlist", "id": profile}}
            )
        )
        restarted = CandidateConsole(load_console(str(config)).config)
        operation = PreparedSelection(prepare_operation_id=selection.operation_id)
        if refused:
            from tools.candidate_operations.models import OperationFailure

            with pytest.raises(OperationFailure) as error:
                restarted.review(operation)
            assert error.value.detail.code == "task_policy"
        else:
            assert restarted.review(operation).prepare_operation_id == selection.operation_id


def test_changed_profile_fails_reusable_request_policy(prepared, tmp_path):
    """Defect: a reusable capture made with the old profile passes the policy comparison."""
    from tools.candidate_console.reusable_policy import check_request_policy
    from tools.candidate_console.service import preparation_request
    from tools.candidate_operations.models import OperationFailure

    service, selection, _ = prepared
    config = next((tmp_path / "ws-parent").glob("siderius_workspace/settings/console.json"))
    old_task = service.config.tasks[0]
    request = preparation_request(old_task, selection)
    _settings_file(config.parent.parent).write_text(
        json.dumps({"schema_version": SCHEMA, "llm_profile": {"source": "allowlist", "id": "b"}})
    )
    new_task = load_console(str(config)).config.tasks[0]
    with pytest.raises(OperationFailure, match="differ from policy"):
        check_request_policy(new_task, request)
    check_request_policy(old_task, request)
