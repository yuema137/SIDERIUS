"""Fixed ``siderius_workspace`` layout: derivation parity, missing sources and ``init`` safety."""

import json
import os
import re
import stat
import sys
from pathlib import Path

import pytest

from tools.candidate_console import ConsoleConfig
from tools.candidate_console.config import load_config, load_console
from tools.candidate_console.workspace import (
    init_workspace,
    resolve_console,
    workspace_readiness,
)

REPO = Path(__file__).resolve().parents[4]
CONTRACT = REPO / "src/tools/candidate_console/console-contract.md"


def _main(monkeypatch, capsys, *argv):
    from tools.candidate_console.__main__ import main

    monkeypatch.setattr(sys, "argv", ["candidate_console", *argv])
    code = main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _contract_example() -> bytes:
    block = re.search(r"## Configuration.*?```json\n(.*?)```", CONTRACT.read_text(), re.S)
    assert block is not None
    return block.group(1).encode()


def _task_without_locations(console_config: ConsoleConfig, *omit: str) -> dict:
    task = console_config.tasks[0].model_dump(mode="json")
    for field in (*omit, "preparation_root", "candidate_root", "reusable_runs_root"):
        task.pop(field, None)
    return task


# P1: an explicit console.json resolves to exactly its strict ConsoleConfig.


@pytest.mark.parametrize("source", ["fixture", "contract"])
def test_explicit_console_files_resolve_unchanged(source, console_config, tmp_path):
    """Defect: the resolver rewrites, drops or reorders an explicit field (P1)."""
    payload = (
        console_config.model_dump_json().encode() if source == "fixture" else _contract_example()
    )
    expected = ConsoleConfig.model_validate_json(payload)
    resolved = resolve_console(payload)
    assert resolved.config.model_dump_json() == expected.model_dump_json()
    assert resolved.settings.workspace_root is None and not resolved.settings.derived
    if source == "fixture":
        path = tmp_path / "console.json"
        path.write_bytes(payload)
        assert load_console(str(path)).config == load_config(str(path)) == console_config


def test_explicit_fields_win_over_the_workspace_layout(console_config, tmp_path):
    """Defect: a layout location replaces a value that console.json sets explicitly (OQ-1)."""
    init_workspace(str(tmp_path))
    document = json.loads(console_config.model_dump_json())
    document["workspace_root"] = str(tmp_path / "siderius_workspace")
    resolved = resolve_console(json.dumps(document).encode())
    assert resolved.config.model_dump_json() == console_config.model_dump_json()
    # An explicit null keeps reusable runs disabled; only an absent key is derived.
    assert resolved.settings.derived == frozenset()
    document["tasks"][0].pop("reusable_runs_root")
    omitted = resolve_console(json.dumps(document).encode())
    assert omitted.settings.derived == {("synthetic", "reusable_runs_root")}
    assert omitted.config.tasks[0].reusable_runs_root == str(
        tmp_path / "siderius_workspace" / "runs" / "synthetic"
    )


# P5: a field with no source fails check by name, without printing paths.


@pytest.mark.parametrize(
    ("omit", "workspace", "named"),
    [
        ("llm_config_file", True, "task synthetic needs llm_config_file"),
        ("data_root", False, "task synthetic needs data_root"),
        ("auth_token_file", False, "console needs auth_token_file"),
    ],
)
def test_check_names_a_field_without_source(
    omit, workspace, named, console_config, tmp_path, monkeypatch, capsys
):
    """Defect: an unfillable field passes, or the refusal hides its name or prints paths."""
    document = json.loads(console_config.model_dump_json())
    if workspace:
        document["workspace_root"] = str(tmp_path)
    if omit == "auth_token_file":
        document.pop(omit)
    else:
        document["tasks"][0].pop(omit)
    path = tmp_path / "console.json"
    path.write_text(json.dumps(document))
    code, out, err = _main(monkeypatch, capsys, "check", "--config", str(path))
    assert code == 2 and not out
    assert named in err
    assert str(tmp_path) not in err


# init


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def test_init_output_passes_check_with_owner_only_folders(tmp_path, monkeypatch, capsys):
    """Defect: init leaves a layout that check refuses, or creates readable/writable folders."""
    code, out, err = _main(monkeypatch, capsys, "init", "--workspace", str(tmp_path))
    assert code == 0, err
    workspace = tmp_path / "siderius_workspace"
    config = workspace / "settings" / "console.json"
    assert f"Workspace configuration: {config}" in out
    for name in ("", "operations", "preparations", "candidates", "runs", "library/llm", "data"):
        assert _mode(workspace / name) == 0o700
    assert not (workspace / "exported_configs").exists()  # created lazily by its writer
    assert _mode(workspace / "settings" / "console-token") == 0o600
    (profile,) = (workspace / "library" / "llm").iterdir()
    assert profile.read_bytes() == (REPO / "configs/llm/default.json").read_bytes()
    assert _main(monkeypatch, capsys, "check", "--config", str(config))[0] == 0
    resolved = load_console(str(config))
    readiness = workspace_readiness(resolved)
    assert readiness is not None and readiness.ready and readiness.init_command is None


def test_init_rerun_never_overwrites_console_json_token_or_library(tmp_path):
    """Defect: a second init replaces operator files or rewrites the token."""
    config = init_workspace(str(tmp_path))
    workspace = config.parent.parent
    edited = json.loads(config.read_text()) | {
        "port": 8741,
        "browser_origin": "http://127.0.0.1:8741",
    }
    config.write_text(json.dumps(edited))
    token = workspace / "settings" / "console-token"
    before = token.read_bytes()
    init_workspace(str(tmp_path))
    assert json.loads(config.read_text())["port"] == 8741
    assert token.read_bytes() == before


@pytest.mark.parametrize("target", ["parent", "child"])
def test_init_refuses_group_or_other_writable_directories(target, tmp_path, monkeypatch, capsys):
    """Defect: init adopts a pre-created directory in a shared parent such as /tmp."""
    parent = tmp_path / "shared"
    parent.mkdir()
    if target == "parent":
        parent.chmod(0o777)
    else:
        (parent / "siderius_workspace").mkdir(mode=0o700)
        (parent / "siderius_workspace" / "runs").mkdir()
        (parent / "siderius_workspace" / "runs").chmod(0o770)
    code, _, err = _main(monkeypatch, capsys, "init", "--workspace", str(parent))
    assert code == 2 and "Nothing was deleted" in err
    assert not (parent / "siderius_workspace" / "settings").exists()


def test_init_refuses_a_directory_owned_by_another_user(tmp_path, monkeypatch):
    """Defect: ownership is not checked, only the mode bits."""
    from tools.candidate_console import workspace
    from tools.candidate_console.workspace import WorkspaceRefused

    real = os.getuid()
    monkeypatch.setattr(workspace.os, "getuid", lambda: real + 1)
    with pytest.raises(WorkspaceRefused, match="owned by you"):
        init_workspace(str(tmp_path))
    assert not (tmp_path / "siderius_workspace").exists()


def test_init_never_follows_a_symlinked_child(tmp_path):
    """Defect: init creates or writes through a symlink planted inside the workspace."""
    from tools.candidate_console.workspace import WorkspaceRefused

    workspace = tmp_path / "siderius_workspace"
    workspace.mkdir(mode=0o700)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (workspace / "settings").symlink_to(elsewhere)
    with pytest.raises(WorkspaceRefused, match="not a symlink"):
        init_workspace(str(tmp_path))
    assert list(elsewhere.iterdir()) == []
    assert (workspace / "settings").is_symlink()  # never deleted or replaced


def test_init_requires_an_explicit_existing_parent(tmp_path, monkeypatch, capsys):
    """Defect: init falls back to a home default or creates a missing parent."""
    with pytest.raises(SystemExit):
        _main(monkeypatch, capsys, "init")
    code, _, err = _main(monkeypatch, capsys, "init", "--workspace", str(tmp_path / "absent"))
    assert code == 2 and "existing canonical directory" in err
    assert not (tmp_path / "absent").exists()


# Derived per-task locations (lead decision Q-A).


def test_derived_task_roots_come_from_init_and_satisfy_store_scopes(
    console_config, tmp_path, monkeypatch, capsys
):
    """Defect: derived roots are never created, or runs/ lies outside an output scope."""
    parent = tmp_path / "parent"
    parent.mkdir(mode=0o700)
    config = init_workspace(str(parent))
    workspace = config.parent.parent
    skeleton = json.loads(config.read_text())
    skeleton["tasks"] = [_task_without_locations(console_config, "data_root")]
    config.write_text(json.dumps(skeleton))

    code, _, err = _main(monkeypatch, capsys, "check", "--config", str(config))
    assert code == 2
    assert "preparations/synthetic: missing" in err and "init --workspace" in err

    init_workspace(str(parent))  # creates output roots for configured tasks
    for name in ("preparations", "candidates", "runs"):
        assert _mode(workspace / name / "synthetic") == 0o700
    assert not (workspace / "data" / "synthetic").exists()  # task data is never created
    code, _, err = _main(monkeypatch, capsys, "check", "--config", str(config))
    assert code == 2 and "data/synthetic: missing" in err

    (workspace / "data" / "synthetic").mkdir()
    resolved = load_console(str(config))
    task = resolved.config.tasks[0]
    assert task.reusable_runs_root == str(workspace / "runs" / "synthetic")
    assert task.data_root == str(workspace / "data" / "synthetic")
    readiness = workspace_readiness(resolved)
    assert readiness is not None and readiness.ready


def test_readiness_reports_symlink_and_file_children_by_name(tmp_path):
    """Defect: readiness follows a symlink or reports an unusable child as present."""
    config = init_workspace(str(tmp_path))
    workspace = config.parent.parent
    resolved = load_console(str(config))
    (workspace / "projects").rename(tmp_path / "projects-aside")
    (workspace / "projects").symlink_to(tmp_path)
    (workspace / "exported_configs").write_text("")
    readiness = workspace_readiness(resolved)
    assert readiness is not None and not readiness.ready
    status = {entry.name: entry.status for entry in readiness.entries}
    assert status["projects"] == "symlink"
    assert status["exported_configs"] == "not_directory"
    assert all(str(tmp_path) not in entry.name for entry in readiness.entries)


def test_settings_modules_do_not_import_prompt_lock_or_node_code():
    """Defect: settings code reaches the rendering assembly or the run lock (P3)."""
    import ast

    package = REPO / "src/tools/candidate_console"
    modules = sorted({package / "workspace.py", *package.glob("settings*.py")})
    assert len(modules) >= 2
    forbidden = ("agent.prompt", "core.run_invariants", "nodes")
    for module in modules:
        for node in ast.walk(ast.parse(module.read_text())):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            assert not [name for name in names if name.startswith(forbidden)], module.name
