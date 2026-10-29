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


def test_view_reports_origins_paths_and_restart_state(workspace, tmp_path):
    """Defect: a row claims the wrong source, or names a nested folder by the layout.

    The advice row must say "not set" rather than console.json, and a data folder
    chosen two levels under a root is labelled by that root (F2/F3 of #1065 review).
    """
    view = _client(_load(workspace)).get("/api/settings").json()
    assert view["enabled"] and view["writable"] and not view["restart_required"]
    assert view["problem"] is None
    rows = {(row["task_id"], row["name"]): row for row in view["rows"]}
    assert rows[("synthetic", "llm_profile")]["origin"] == "global_settings"
    assert rows[("synthetic", "data_root")]["origin"] == "workspace_layout"
    assert (rows[(None, "advice")]["origin"], rows[(None, "advice")]["label"]) == (
        "not_set",
        "None",
    )
    (tmp_path / "lab" / "x" / "y").mkdir(parents=True)
    api = _client(_load(workspace))
    current = api.get("/api/settings").json()
    nested = {"synthetic": {"root_id": "lab", "subpath": "x/y"}}
    assert (
        _put(
            api,
            current["settings_sha256"],
            llm_profile=current["pending"]["llm_profile"],
            data_folders=nested,
        ).status_code
        == 200
    )
    restarted = _client(_load(workspace)).get("/api/settings").json()
    row = next(
        r for r in restarted["rows"] if (r["task_id"], r["name"]) == ("synthetic", "data_root")
    )
    assert (row["origin"], row["label"]) == ("global_settings", "Lab disk / x/y")
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
    assert "secret.txt" not in json.dumps(listing)  # files are never listed


@pytest.mark.parametrize("damage", ["schema", "mode", "repeated_key"])
def test_an_unusable_settings_file_is_named_with_its_recovery(damage, workspace):
    """Defect: a file broken after startup makes GET 500 and PUT loop on 409 (#1065 F1)."""
    path = _settings_file(workspace)
    api = _client(_load(workspace))
    if damage == "schema":
        path.write_text('{"schema_version": "wrong"}')
    elif damage == "repeated_key":
        path.write_text(
            path.read_text().replace('"advice": null', '"advice": null, "advice": null')
        )
    else:
        path.chmod(0o640)
    response = api.get("/api/settings")
    assert response.status_code == 200
    view = response.json()
    assert view["pending"] is None and "settings/global_settings.json" in view["problem"]
    choice = {"llm_profile": view["active"]["llm_profile"]}
    if damage == "mode":
        assert "chmod 600" in view["problem"] and view["settings_sha256"] is None
        refused = _put(api, None, **choice)
        assert refused.status_code == 422
        assert refused.json()["error"]["code"] == "settings_unreadable"
        assert stat.S_IMODE(path.stat().st_mode) == 0o640
        return
    assert "Save to replace it" in view["problem"]
    assert ("at schema_version" if damage == "schema" else "repeats a key") in view["problem"]
    replaced = _put(api, view["settings_sha256"], **choice)  # recovery: explicit Save under CAS
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["problem"] is None
    assert json.loads(path.read_text())["llm_profile"] == choice["llm_profile"]


def test_publish_refuses_a_settings_folder_linked_after_its_canonical_check(
    workspace, tmp_path, monkeypatch
):
    """Defect: the publish step opens its parent with a path that follows links.

    The folder is swapped for a link inside the publish step, after ``canonical()``
    has accepted the path, so only the no-follow descriptor walk of
    ``files.open_directory`` can refuse it.
    """
    from tools.candidate_console import settings_service

    api = _client(_load(workspace))
    view = api.get("/api/settings").json()
    settings = workspace / "settings"
    aside = tmp_path / "settings-aside"
    real = settings_service.canonical

    def canonical_then_swap(value):
        checked = real(value)
        if checked == settings and not settings.is_symlink():
            settings.rename(aside)
            settings.symlink_to(aside)
        return checked

    monkeypatch.setattr(settings_service, "canonical", canonical_then_swap)
    before = (settings / "global_settings.json").read_bytes()
    response = _put(api, view["settings_sha256"], llm_profile=view["pending"]["llm_profile"])
    assert settings.is_symlink(), "the swap must happen inside the publish step"
    assert response.status_code == 422 and response.json()["error"]["code"] == "settings_invalid"
    assert (aside / "global_settings.json").read_bytes() == before
    assert sorted(path.name for path in aside.iterdir()) == [
        "console-token",
        "console.json",
        "global_settings.json",
    ]


def _failing(name, *, after=0):
    """Replace one ``os`` call: the first ``after`` calls pass through, the next raises."""
    import os

    real, calls = getattr(os, name), []

    def call(*args, **kwargs):
        calls.append(args)
        if len(calls) > after:
            raise OSError(f"{name} refused")
        return real(*args, **kwargs)

    return call


@pytest.mark.parametrize("failure", ["fchmod", "fsync", "replace"])
def test_failed_publish_leaves_no_trace(failure, tmp_path, monkeypatch):
    """Defect: a publish that fails before the replace leaves its temp file behind or
    damages the previous file (cleanup must cover fchmod, write and fsync too)."""
    from tools.candidate_console import settings_service

    directory = tmp_path / "settings"
    directory.mkdir(mode=0o700)
    target = directory / "global_settings.json"
    target.write_text("previous")
    monkeypatch.setattr(settings_service.os, failure, _failing(failure))
    with pytest.raises(OSError, match=f"{failure} refused"):
        settings_service._publish_private(target, b"x" * 10000)
    assert target.read_text() == "previous"
    assert sorted(path.name for path in directory.iterdir()) == ["global_settings.json"]


def test_short_writes_still_publish_every_byte(tmp_path, monkeypatch):
    """Defect: one ``os.write`` call publishes a truncated settings file."""
    from tools.candidate_console import settings_service

    directory = tmp_path / "settings"
    directory.mkdir(mode=0o700)
    target = directory / "global_settings.json"
    payload = b"x" * 10000
    real = settings_service.os.write
    monkeypatch.setattr(
        "tools.candidate_console.files.os.write", lambda fd, data: real(fd, bytes(data[:7]))
    )
    assert settings_service._publish_private(target, payload) is True
    assert target.read_bytes() == payload
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_failed_cleanup_keeps_the_original_error_and_says_so(tmp_path, monkeypatch):
    """Defect: a temp-file removal error replaces the real failure and hides the leftover."""
    from tools.candidate_console import settings_service

    directory = tmp_path / "settings"
    directory.mkdir(mode=0o700)
    target = directory / "global_settings.json"
    monkeypatch.setattr(settings_service.os, "fsync", _failing("fsync"))
    monkeypatch.setattr(settings_service.os, "unlink", _failing("unlink"))
    with pytest.raises(OSError, match="fsync refused") as error:
        settings_service._publish_private(target, b"x")
    assert any("could not be removed" in note for note in error.value.__notes__)


def test_unconfirmed_directory_sync_reports_a_completed_save(workspace, monkeypatch):
    """Defect: a save that replaced the file is reported as "nothing was saved"."""
    from tools.candidate_console import settings_service

    path = _settings_file(workspace)
    api = _client(_load(workspace))
    view = api.get("/api/settings").json()
    folder = {"synthetic": {"root_id": "lab", "subpath": "run-a"}}
    # The file fsync passes; the directory fsync after os.replace fails.
    monkeypatch.setattr(settings_service.os, "fsync", _failing("fsync", after=1))
    response = _put(
        api,
        view["settings_sha256"],
        llm_profile=view["pending"]["llm_profile"],
        data_folders=folder,
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["notice"] and "could not confirm" in saved["notice"]
    assert saved["settings_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert json.loads(path.read_text())["data_folders"] == folder


def test_listing_names_a_root_that_is_no_longer_canonical(workspace, tmp_path):
    """Defect: a moved or linked root is reported as a bad subpath (#1065 F7)."""
    api = _client(_load(workspace))
    lab = tmp_path / "lab"
    lab.rename(tmp_path / "lab-real")
    lab.symlink_to(tmp_path / "lab-real")
    response = api.get("/api/settings/folders", params={"root_id": "lab"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "root_changed"
    assert "data_roots" in response.json()["error"]["message"]


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
