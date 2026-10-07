"""Input and process contracts for explicitly selected workspace isolation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from tools.workspace_sandbox.command import SandboxUnavailable, build_command, child_environment
from tools.workspace_sandbox.profile import SandboxProfile


def profile(tmp_path: Path, **extra) -> SandboxProfile:
    return SandboxProfile(workspace=tmp_path, network=False, timeout_seconds=10, **extra)


def test_requires_network_decision_and_finite_positive_deadline(tmp_path):
    for bad in (0, -1, float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            SandboxProfile(workspace=tmp_path, network=False, timeout_seconds=bad)
    with pytest.raises(ValidationError, match="network"):
        SandboxProfile(workspace=tmp_path, timeout_seconds=10)


def test_rejects_workspace_alias_and_runtime_overlap(tmp_path):
    alias = tmp_path / "alias"
    real = tmp_path / "real"
    real.mkdir()
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValidationError, match="canonical absolute"):
        profile(alias)
    with pytest.raises(ValidationError, match="protected runtime"):
        profile(Path(sys.prefix).resolve())
    with pytest.raises(ValidationError, match="specific project"):
        profile(Path("/tmp"))
    with pytest.raises(ValidationError, match="inside or equal"):
        profile(real, read_only=(tmp_path,))


def test_read_only_task_can_be_nested_inside_workspace(tmp_path):
    task = tmp_path / "task"
    task.mkdir()
    value = profile(tmp_path, read_only=(task,))
    assert value.read_only == (task,)


def test_environment_is_explicit_and_never_embedded_in_command(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_ACCESS_KEY", "secret-for-test")
    monkeypatch.setenv("UNDECLARED_SECRET", "not-forwarded")
    value = profile(tmp_path, environment_names=("DEMO_ACCESS_KEY",))
    command, env = build_command(value, ["/bin/true"])
    assert env["DEMO_ACCESS_KEY"] == "secret-for-test"
    assert "UNDECLARED_SECRET" not in env
    assert "secret-for-test" not in repr(command)
    assert "secret-for-test" not in value.model_dump_json()
    assert env["HOME"] == "/sandbox-home"
    with pytest.raises(SandboxUnavailable, match="DEMO_ACCESS_KEY"):
        child_environment(value, {})


@pytest.mark.parametrize("name", ["LD_PRELOAD", "PYTHONPATH", "HOME", "BASH_ENV", "BAD=VALUE"])
def test_reserved_environment_cannot_replace_runtime(tmp_path, name):
    with pytest.raises(ValidationError):
        profile(tmp_path, environment_names=(name,))


def test_no_bubblewrap_means_no_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.workspace_sandbox.command.shutil.which", lambda name: None)
    with pytest.raises(SandboxUnavailable, match="install bubblewrap"):
        build_command(profile(tmp_path), ["/bin/true"])


def test_paths_revalidated_when_used(tmp_path):
    task = tmp_path / "input"
    task.write_text("original")
    value = profile(tmp_path, read_only=(task,))
    task.unlink()
    task.symlink_to("/etc/hosts")
    with pytest.raises(ValidationError, match="canonical absolute"):
        build_command(value, ["/bin/true"])
