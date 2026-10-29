"""Fixed ``siderius_workspace`` layout: derivation parity, missing sources and ``init`` safety."""

import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

import pytest

from tests.unit.tools.candidate_console.test_editor import editor_config
from tests.unit.tools.candidate_console.test_native_chain import chain, native_config
from tools.candidate_console import ConsoleConfig, RecordedExampleChoice
from tools.candidate_console.config import load_config, load_console
from tools.candidate_console.workspace import (
    WorkspaceRefused,
    init_workspace,
    resolve_console,
    workspace_readiness,
)
from workflows.definition import TaskBinding

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


def _variant(name: str, request, console_config, tmp_path) -> ConsoleConfig:
    task = console_config.tasks[0]
    if name == "editor":
        return request.getfixturevalue("editor_config")
    if name == "pinned_task":
        pin = TaskBinding(
            package_id="synthetic",
            revision="snapshot-one",
            task_data_path_id="synthetic-path",
            semantic_fingerprint="a" * 64,
        )
        update = {"task_revision": pin, "reusable_runs_root": task.preparation_root}
        return console_config.model_copy(update={"tasks": (task.model_copy(update=update),)})
    if name == "credential_and_recorded":
        example = RecordedExampleChoice(
            example_id="x", label="X", workspace=str(tmp_path / "w"), expected_run_id="a" * 32
        )
        return console_config.model_copy(
            update={"credential_file": str(tmp_path / "cred"), "recorded_examples": (example,)}
        )
    record, _ = request.getfixturevalue("chain")
    return native_config(console_config, record)


@pytest.mark.parametrize("name", ["editor", "pinned_task", "credential_and_recorded", "native"])
def test_other_console_shapes_resolve_unchanged(name, request, console_config, tmp_path):
    """Defect: the generated file schema drops or rewrites a nested model or optional field (P1)."""
    config = _variant(name, request, console_config, tmp_path)
    payload = config.model_dump_json().encode()
    expected = ConsoleConfig.model_validate_json(payload)
    assert resolve_console(payload).config.model_dump_json() == expected.model_dump_json()


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
    for name in (
        "",
        "operations",
        "preparations",
        "candidates",
        "runs",
        "tasks",
        "library/llm",
        "data",
    ):
        assert _mode(workspace / name) == 0o700
    assert not (workspace / "exported_configs").exists()  # created lazily by its writer
    assert _mode(workspace / "settings" / "console-token") == 0o600
    (profile,) = (workspace / "library" / "llm").iterdir()
    default = (REPO / "configs/llm/default.json").read_bytes()
    assert profile.read_bytes() == default
    assert profile.name == f"default-{hashlib.sha256(default).hexdigest()[:12]}.json"
    assert _mode(profile) == 0o600
    assert _main(monkeypatch, capsys, "check", "--config", str(config))[0] == 0
    resolved = load_console(str(config))
    readiness = workspace_readiness(resolved)
    assert readiness is not None and readiness.ready and readiness.init_command is None


@pytest.mark.parametrize("command", ["init", "check", "serve"])
def test_cli_explains_token_and_access_with_browser_port(command, tmp_path, monkeypatch, capsys):
    """Defect: access guidance omits the token, or the tunnel does not map the browser port to the server port."""
    config = init_workspace(str(tmp_path), port=8741)
    data = json.loads(config.read_text())
    data["browser_origin"] = "http://127.0.0.1:9842"
    config.write_text(json.dumps(data))
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)
    argv = ("--workspace", str(tmp_path)) if command == "init" else ("--config", str(config))
    code, out, err = _main(monkeypatch, capsys, command, *argv)
    token_file = config.parent / "console-token"
    expected = (
        "Console address: http://127.0.0.1:9842\n"
        f"Access token file: {token_file}\n"
        "  The console asks for this token when you connect, on this machine or remotely.\n"
        f"  Show it with: cat {token_file}\n"
        "  On this machine: open the console address in your browser.\n"
        "  On a remote server: first run on your own computer\n"
        "    ssh -N -L 127.0.0.1:9842:127.0.0.1:8741 YOUR_HOST\n"
        "  then open the console address there.\n"
    )
    if command == "init":
        expected = f"Workspace configuration: {config}\n" + expected
    assert code == 0, err
    assert out == expected
    assert token_file.read_text().strip() not in out


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
    (profile,) = (workspace / "library" / "llm").iterdir()
    library = profile.stat()
    init_workspace(str(tmp_path))
    assert json.loads(config.read_text())["port"] == 8741
    assert token.read_bytes() == before
    after = profile.stat()
    assert (after.st_ino, after.st_mtime_ns) == (library.st_ino, library.st_mtime_ns)

    profile.write_text("{}")  # a library file is write-once: different bytes are refused
    with pytest.raises(WorkspaceRefused, match="library default LLM profile exists"):
        init_workspace(str(tmp_path))
    assert profile.read_text() == "{}"


@pytest.mark.parametrize("target", ["console", "library"])
def test_init_names_a_symlinked_file_it_refuses(target, tmp_path, monkeypatch, capsys):
    """Defect: a refused file is reported as a bad --workspace, or is followed."""
    config = init_workspace(str(tmp_path))
    workspace = config.parent.parent
    (profile,) = (workspace / "library" / "llm").iterdir()
    victim = config if target == "console" else profile
    real = tmp_path / "real"
    victim.rename(real)
    victim.symlink_to(real)
    code, _, err = _main(monkeypatch, capsys, "init", "--workspace", str(tmp_path))
    named = "settings/console.json" if target == "console" else "library default LLM profile"
    assert code == 2 and named in err and "not a symlink" in err
    assert "--workspace must be" not in err
    assert victim.is_symlink()


def test_init_rerun_names_a_task_field_without_source(
    console_config, tmp_path, monkeypatch, capsys
):
    """Defect: an incomplete console.json on re-run is misreported as a bad --workspace."""
    config = init_workspace(str(tmp_path))
    skeleton = json.loads(config.read_text())
    skeleton["tasks"] = [_task_without_locations(console_config, "llm_config_file")]
    skeleton["global_settings"] = None  # no settings layer supplies the default profile
    config.write_text(json.dumps(skeleton))
    code, _, err = _main(monkeypatch, capsys, "init", "--workspace", str(tmp_path))
    assert code == 2 and "task synthetic needs llm_config_file" in err
    assert "--workspace must be" not in err


@pytest.mark.parametrize("content", ["not json", '{"port": "x"}', '{"workspace_root": "rel"}'])
def test_init_rerun_names_an_invalid_console_json(content, tmp_path, monkeypatch, capsys):
    """Defect: a malformed, schema-invalid or non-canonical console.json is a generic refusal."""
    config = init_workspace(str(tmp_path))
    config.write_text(content)
    code, _, err = _main(monkeypatch, capsys, "init", "--workspace", str(tmp_path))
    assert code == 2
    assert "console.json is invalid at " in err
    assert config.read_text() == content


def test_umask_does_not_weaken_or_disable_init(tmp_path):
    """Defect: a 0777 umask leaves mode-000 folders that init itself cannot open."""
    previous = os.umask(0o777)
    try:
        config = init_workspace(str(tmp_path))
    finally:
        os.umask(previous)
    workspace = config.parent.parent
    for name in ("", "settings", "library/llm", "data"):
        assert _mode(workspace / name) == 0o700
    assert _mode(workspace / "settings" / "console-token") == 0o600
    assert load_console(str(config)).config.port == 8740


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
    with pytest.raises(WorkspaceRefused, match="owned by uid") as refusal:
        init_workspace(str(tmp_path))
    assert "chmod" not in str(refusal.value)
    assert not (tmp_path / "siderius_workspace").exists()


def test_init_refuses_a_group_writable_parent_with_the_chmod_fix(tmp_path):
    """Defect: a group/other-writable parent is refused without naming the path or the fix."""
    from tools.candidate_console.workspace import WorkspaceRefused

    parent = tmp_path / "parent"
    parent.mkdir()
    os.chmod(parent, 0o775)
    with pytest.raises(WorkspaceRefused, match="chmod 700") as refusal:
        init_workspace(str(parent))
    assert f"workspace parent {parent.resolve()} must not be writable" in str(refusal.value)
    assert f"chmod 700 {parent.resolve()}" in str(refusal.value)
    assert not (parent / "siderius_workspace").exists()


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

    # Re-running init creates output roots for configured tasks, then reports the
    # task data it never creates (README step 2: expected status 2).
    code, _, err = _main(monkeypatch, capsys, "init", "--workspace", str(parent))
    assert code == 2 and "Workspace data/synthetic: missing" in err
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

    (workspace / "library").chmod(0o000)  # refused, not absent
    try:
        refused = workspace_readiness(resolved)
    finally:
        (workspace / "library").chmod(0o700)
    assert refused is not None
    assert {e.name: e.status for e in refused.entries}["library/llm"] == "unreadable"
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


def _credential_file(tmp_path: Path, mode: int, secret: str) -> Path:
    path = tmp_path / "private" / "credentials.env"
    path.parent.mkdir(mode=0o700)
    path.write_text(f"OPENAI_API_KEY={secret}\n")
    path.chmod(mode)
    return path


def test_init_credential_file_records_it_in_a_new_console_json_without_printing_it(
    tmp_path, monkeypatch, capsys
):
    """Defect: init --credential-file omits the key, or a credential value reaches the output."""
    secret = "sk-init-never-printed-" + "y" * 24
    credentials = _credential_file(tmp_path, 0o600, secret)
    parent = tmp_path / "project"
    parent.mkdir(mode=0o700)
    code, out, err = _main(
        monkeypatch,
        capsys,
        "init",
        "--workspace",
        str(parent),
        "--credential-file",
        str(credentials),
    )
    assert code == 0, err
    config = parent / "siderius_workspace" / "settings" / "console.json"
    assert json.loads(config.read_text())["credential_file"] == str(credentials)
    assert load_console(str(config)).config.credential_file == str(credentials)
    assert secret not in out + err


@pytest.mark.parametrize("mode", [0o640, 0o644, 0o400])
def test_init_credential_file_refuses_a_file_that_is_not_owner_only_600(
    mode, tmp_path, monkeypatch, capsys
):
    """Defect: init records a credential file others can read, or creates a workspace anyway."""
    secret = "sk-mode-never-printed-" + "z" * 24
    credentials = _credential_file(tmp_path, mode, secret)
    code, out, err = _main(
        monkeypatch,
        capsys,
        "init",
        "--workspace",
        str(tmp_path),
        "--credential-file",
        str(credentials),
    )
    assert code == 2
    assert "--credential-file is refused unless it is a regular file you own with mode 600" in err
    assert secret not in out + err
    assert not (tmp_path / "siderius_workspace").exists()


def test_init_credential_file_never_rewrites_an_existing_console_json(
    tmp_path, monkeypatch, capsys
):
    """Defect: a re-run of init silently rewrites console.json, or gives no line to add."""
    config = init_workspace(str(tmp_path))
    before = config.read_bytes()
    credentials = _credential_file(tmp_path, 0o600, "sk-existing-" + "w" * 24)
    argv = ("init", "--workspace", str(tmp_path), "--credential-file", str(credentials))
    code, _, err = _main(monkeypatch, capsys, *argv)
    assert code == 2
    line = f'"credential_file": {json.dumps(str(credentials))},'
    assert f"  {line}\n" in err and "Add this line right after its opening {" in err
    assert f"check --config {config}\n" in err
    assert config.read_bytes() == before
    # Adding exactly that line makes the same re-run succeed without touching the file.
    text = before.decode()
    edited = text.replace("{\n", "{\n  " + line + "\n", 1)
    config.write_text(edited)
    code, _, err = _main(monkeypatch, capsys, *argv)
    assert code == 0, err
    assert config.read_text() == edited


def test_init_credential_file_printed_replace_line_keeps_console_json_valid(
    tmp_path, monkeypatch, capsys
):
    """Defect: following the printed replace instruction yields invalid JSON.

    init writes ``credential_file`` as the last member, so a replace line with a
    trailing comma would break the file; ``check`` must pass after applying it.
    """
    first = _credential_file(tmp_path, 0o600, "sk-first-" + "a" * 24)
    second = tmp_path / "private" / "second.env"
    second.write_text("OPENAI_API_KEY=sk-second\n")
    second.chmod(0o600)
    config = init_workspace(str(tmp_path), credential_file=str(first))
    text = config.read_text()
    old = f'"credential_file": {json.dumps(str(first))}'
    assert old in text
    argv = ("init", "--workspace", str(tmp_path), "--credential-file", str(second))
    code, _, err = _main(monkeypatch, capsys, *argv)
    assert code == 2
    member = f'"credential_file": {json.dumps(str(second))}'
    assert f"  {member}\n" in err and "keeping the line's trailing comma" in err
    config.write_text(text.replace(old, member))
    assert _main(monkeypatch, capsys, "check", "--config", str(config))[0] == 0
    assert _main(monkeypatch, capsys, *argv)[0] == 0


def test_init_credential_file_refuses_a_symlinked_file(tmp_path, monkeypatch, capsys):
    """Defect: a symlink to a mode-600 key file is accepted and recorded."""
    target = _credential_file(tmp_path, 0o600, "sk-link-" + "b" * 24)
    link = tmp_path / "private" / "link.env"
    link.symlink_to(target)
    parent = tmp_path / "project"
    parent.mkdir(mode=0o700)
    argv = ("init", "--workspace", str(parent), "--credential-file", str(link))
    code, _, err = _main(monkeypatch, capsys, *argv)
    assert code == 2 and "--credential-file is refused" in err
    assert not (parent / "siderius_workspace").exists()


@pytest.mark.parametrize("command", ["check", "serve"])
def test_check_and_serve_reject_credential_file(command, tmp_path, monkeypatch, capsys):
    """Defect: --credential-file is silently ignored outside init."""
    config = init_workspace(str(tmp_path))
    credentials = _credential_file(tmp_path, 0o600, "sk-ignored-" + "c" * 24)
    with pytest.raises(SystemExit) as raised:
        _main(
            monkeypatch,
            capsys,
            command,
            "--config",
            str(config),
            "--credential-file",
            str(credentials),
        )
    assert raised.value.code == 2
    assert "--credential-file is for init only" in capsys.readouterr().err
