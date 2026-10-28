"""Operator allowlists and the global settings file: precedence, refs, folders and exclusions."""

import hashlib
import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from tools.candidate_console import PrepareSelection
from tools.candidate_console.config import load_console
from tools.candidate_console.service import preparation_request
from tools.candidate_console.settings_file import SettingsInvalid
from tools.candidate_console.workspace import init_workspace, resolve_console

REPO = Path(__file__).resolve().parents[4]
SCHEMA = "siderius.console-global-settings/v1"


def _main(monkeypatch, capsys, *argv):
    from tools.candidate_console.__main__ import main

    monkeypatch.setattr(sys, "argv", ["candidate_console", *argv])
    code = main()
    return code, capsys.readouterr().err


@pytest.fixture
def workspace(console_config, tmp_path):
    """An init workspace whose console.json lists the synthetic task with locations omitted."""
    parent = tmp_path / "parent"
    parent.mkdir(mode=0o700)
    config = init_workspace(str(parent))
    root = config.parent.parent
    document = json.loads(config.read_text())
    task = console_config.tasks[0].model_dump(mode="json")
    for field in ("llm_config_file", "data_root", "preparation_root", "candidate_root"):
        task.pop(field)
    document["tasks"] = [task]
    config.write_text(json.dumps(document))
    init_workspace(str(parent))  # per-task output roots
    (root / "data" / "synthetic").mkdir()
    return root


def _console(root: Path) -> Path:
    return root / "settings" / "console.json"


def _edit_console(root: Path, **changes) -> None:
    path = _console(root)
    path.write_text(json.dumps(json.loads(path.read_text()) | changes))


def _write_settings(root: Path, **fields) -> None:
    path = root / "settings" / "global_settings.json"
    path.write_text(json.dumps({"schema_version": SCHEMA, **fields}))
    path.chmod(0o600)


def _library_default(root: Path) -> dict:
    (profile,) = (root / "library" / "llm").iterdir()
    digest = hashlib.sha256(profile.read_bytes()).hexdigest()
    return {"source": "library", "name": profile.name, "sha256": digest}


# Precedence and parity


def test_init_selects_the_library_default_for_tasks_that_omit_a_profile(workspace):
    """Defect: init's settings file is inert, or the default is not the shipped profile."""
    resolved = load_console(str(_console(workspace)))
    task = resolved.config.tasks[0]
    assert (
        Path(task.llm_config_file).read_bytes() == (REPO / "configs/llm/default.json").read_bytes()
    )
    assert resolved.settings.origin("synthetic", "llm_config_file") == "global_settings"
    assert resolved.settings.origin("synthetic", "data_root") == "workspace_layout"
    assert resolved.settings.origin("synthetic", "task_manifest") == "server_config"


def test_explicit_console_json_ignores_a_present_settings_file(console_config, workspace, tmp_path):
    """Defect: a settings value overrides a field console.json sets (P1, OQ-1)."""
    other = tmp_path / "other-data"
    other.mkdir()
    _edit_console(
        workspace,
        tasks=[console_config.tasks[0].model_dump(mode="json")],
        data_roots=[{"id": "lab", "label": "Lab", "path": str(other.parent)}],
    )
    _write_settings(
        workspace,
        llm_profile=_library_default(workspace),
        data_folders={"synthetic": {"root_id": "lab", "subpath": "other-data"}},
    )
    resolved = resolve_console(_console(workspace).read_bytes())
    assert resolved.config.tasks == console_config.tasks
    assert not resolved.settings.from_settings


def test_settings_values_build_the_same_requests_as_explicit_values(workspace, tmp_path):
    """Defect: a settings-filled field takes a different path than the explicit equivalent (P2)."""
    lab = tmp_path / "lab"
    (lab / "run-a").mkdir(parents=True)
    _edit_console(workspace, data_roots=[{"id": "lab", "label": "Lab", "path": str(lab)}])
    _write_settings(
        workspace,
        llm_profile=_library_default(workspace),
        data_folders={"synthetic": {"root_id": "lab", "subpath": "run-a"}},
    )
    filled = load_console(str(_console(workspace)))
    task = filled.config.tasks[0]
    assert task.data_root == str(lab / "run-a")
    explicit_task = json.loads(_console(workspace).read_text())["tasks"][0] | {
        "llm_config_file": task.llm_config_file,
        "data_root": task.data_root,
    }
    _edit_console(workspace, tasks=[explicit_task], global_settings=None)
    explicit = load_console(str(_console(workspace)))
    assert explicit.config.model_dump_json() == filled.config.model_dump_json()
    selection = PrepareSelection(operation_id=uuid4(), task_id="synthetic", run_name="same")
    assert preparation_request(explicit.config.tasks[0], selection) == preparation_request(
        task, selection
    )


# Refusals at check (OQ-4: fail closed, name the ref, print no values)


@pytest.mark.parametrize(
    ("subpath", "named"),
    [
        ("../escape", "relative path"),
        ("/abs", "relative path"),
        ("a//b", "relative path"),
        ("a/./b", "relative path"),
        ("link", "without symlinks"),
        ("missing", "not a directory"),
    ],
)
def test_folder_refs_stay_beneath_their_root(
    subpath, named, workspace, tmp_path, monkeypatch, capsys
):
    """Defect: a subpath escapes its allowlisted root, follows a link or names no folder."""
    lab = tmp_path / "lab"
    lab.mkdir()
    (lab / "link").symlink_to(tmp_path)
    _edit_console(workspace, data_roots=[{"id": "lab", "label": "Lab", "path": str(lab)}])
    _write_settings(workspace, data_folders={"synthetic": {"root_id": "lab", "subpath": subpath}})
    code, err = _main(monkeypatch, capsys, "check", "--config", str(_console(workspace)))
    assert code == 2 and named in err
    assert str(tmp_path) not in err


@pytest.mark.parametrize(
    ("settings", "named"),
    [
        ({"llm_profile": {"source": "allowlist", "id": "nope"}}, "unknown llm_profiles ID 'nope'"),
        (
            {"data_folders": {"ghost": {"root_id": "workspace", "subpath": "x"}}},
            "unknown task 'ghost'",
        ),
        ({"data_folders": {"synthetic": {"root_id": "nope", "subpath": "x"}}}, "unknown data root"),
        (
            {
                "llm_profile": {
                    "source": "library",
                    "name": "default-000000000000.json",
                    "sha256": "0" * 64,
                }
            },
            "library file does not match",
        ),
    ],
)
def test_unknown_refs_and_digest_mismatch_fail_startup(
    settings, named, workspace, monkeypatch, capsys
):
    """Defect: an unknown ID or a changed library file is ignored instead of failing closed."""
    if "library" in json.dumps(settings):
        name = _library_default(workspace)["name"]
        target = workspace / "library" / "llm" / "default-000000000000.json"
        target.write_bytes((workspace / "library" / "llm" / name).read_bytes())
    _write_settings(workspace, **settings)
    code, err = _main(monkeypatch, capsys, "check", "--config", str(_console(workspace)))
    assert code == 2 and named in err


def test_allowlisted_files_are_certified_by_their_owners(workspace, tmp_path, monkeypatch, capsys):
    """Defect: a misspelled LLM key or unconsumable advice file is accepted into the allowlist."""
    profile = tmp_path / "typo.json"
    profile.write_text('{"interpet": {}}')
    _edit_console(workspace, llm_profiles=[{"id": "typo", "label": "Typo", "file": str(profile)}])
    code, err = _main(monkeypatch, capsys, "check", "--config", str(_console(workspace)))
    assert code == 2 and "llm_profiles typo is not a readable, valid LLM profile" in err

    advice = tmp_path / "advice.json"
    advice.write_text('{"propse": "x"}')
    _edit_console(
        workspace,
        llm_profiles=[],
        advice_files=[{"id": "notes", "label": "Notes", "file": str(advice)}],
    )
    code, err = _main(monkeypatch, capsys, "check", "--config", str(_console(workspace)))
    assert code == 2 and "advice_files notes" in err and "'propse'" in err
    assert str(tmp_path) not in err


def test_settings_require_workspace_and_a_private_file(console_config, workspace, tmp_path):
    """Defect: a settings file is read without a workspace, or a group-readable one is trusted."""
    document = json.loads(console_config.model_dump_json()) | {
        "global_settings": {"browser_writable": True}
    }
    with pytest.raises(SettingsInvalid, match="requires workspace_root"):
        resolve_console(json.dumps(document).encode())
    _write_settings(workspace)
    (workspace / "settings" / "global_settings.json").chmod(0o640)
    with pytest.raises(SettingsInvalid, match="mode 600"):
        resolve_console(_console(workspace).read_bytes())


# Read-only exclusion (lead verdict 2): no data folder may expose protected paths.


@pytest.mark.parametrize("protected", ["settings", "library", "state", "output", "credential"])
def test_data_roots_and_folders_never_contain_protected_paths(
    protected, workspace, tmp_path, monkeypatch, capsys
):
    """Defect: a secret or output root becomes a read-only sandbox mount (fails on master)."""
    credential = workspace / "data" / "synthetic" / "credentials.json"
    credential.write_text("{}")
    credential.chmod(0o600)
    targets = {
        "settings": workspace / "settings",
        "library": workspace / "library",
        "state": workspace / "operations",
        "output": workspace / "preparations" / "synthetic",
        "credential": workspace / "data" / "synthetic",
    }
    if protected == "credential":
        _edit_console(workspace, credential_file=str(credential))
        code, err = _main(monkeypatch, capsys, "check", "--config", str(_console(workspace)))
        assert code == 2 and "data folder for task synthetic overlaps" in err
        return
    _edit_console(
        workspace, data_roots=[{"id": "bad", "label": "Bad", "path": str(targets[protected])}]
    )
    code, err = _main(monkeypatch, capsys, "check", "--config", str(_console(workspace)))
    assert code == 2 and "data_roots bad overlaps a protected console path" in err


def test_a_data_root_holding_only_the_token_is_refused(console_config, tmp_path):
    """Defect: the token file is missing from the protected set (no workspace to cover it)."""
    from tools.candidate_console.config import validate_resolved

    secret = tmp_path / "secret"
    secret.mkdir()
    token = secret / "token"
    token.write_bytes(Path(console_config.auth_token_file).read_bytes())
    token.chmod(0o600)
    document = json.loads(console_config.model_dump_json()) | {
        "auth_token_file": str(token),
        "data_roots": [{"id": "secret", "label": "Secret", "path": str(secret)}],
    }
    with pytest.raises(SettingsInvalid, match="data_roots secret overlaps"):
        validate_resolved(resolve_console(json.dumps(document).encode()))


def test_task_data_root_containing_the_workspace_is_refused(workspace, monkeypatch, capsys):
    """Defect: an explicit data_root that contains settings passes because only destinations are protected."""
    task = json.loads(_console(workspace).read_text())["tasks"][0] | {"data_root": str(workspace)}
    _edit_console(workspace, tasks=[task])
    code, err = _main(monkeypatch, capsys, "check", "--config", str(_console(workspace)))
    assert code == 2 and "data folder for task synthetic overlaps" in err


def test_native_admission_refuses_protected_read_only_inputs(selection, tmp_path):
    """Defect: admit(protected=...) is ignored on the in-process reusable path."""
    from tools.candidate_prepare.admission import admit

    secret = Path(selection.data_root) / "token"
    with pytest.raises(ValueError, match="overlaps a protected path"):
        admit(selection, protected=(secret,))
