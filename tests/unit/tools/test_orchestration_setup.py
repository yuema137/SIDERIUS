"""External assembly: hidden discovery, non-overwrite and incomplete publication."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.orchestration_setup.assembly import MANIFEST_NAME, assemble

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def inputs(tmp_path):
    project = tmp_path / "user project"
    project.mkdir()
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps({"workspace": str(project), "network": False, "timeout_seconds": 30})
    )
    declaration = tmp_path / "operator.md"
    declaration.write_bytes(b"# Run\r\nPhase: preparation; task and budget UNCONFIGURED.\r\n")
    return project, profile, declaration


def test_real_cli_installs_discoverable_payload_without_mutating_sources(inputs):
    """A cwd-dependent or hidden-file-skipping copier loses the startup skill."""
    project, profile, declaration = inputs
    before = {p: p.read_bytes() for p in (profile, declaration)}
    unrelated_task = project / "user-task.yaml"
    unrelated_task.write_text("keep: original\n")
    source = ROOT / "docs/agent-reference/orchestrator-toolkit/payload"
    payload = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.orchestration_setup",
            "--profile",
            str(profile),
            "--run-declaration",
            str(declaration),
        ],
        cwd="/",
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["status"] == "assembled"
    assert receipt["python"] == sys.executable
    assert receipt["source_checkout"] == str(ROOT)
    assert json.loads((project / MANIFEST_NAME).read_text()) == receipt
    assert (project / ".agents/skills/siderius-toolkit/SKILL.md").is_file()
    assert (project / ".agents/skills/siderius-toolkit/references/invocation.md").is_file()
    for relative, original in payload.items():
        assert (project / relative).read_bytes() == original
        assert (source / relative).read_bytes() == original
    for path, original in before.items():
        assert path.read_bytes() == original
    assert (project / "SIDERIUS-RUN.md").read_bytes() == before[declaration]
    assert unrelated_task.read_text() == "keep: original\n"
    assert not (project / "scripts/caller.py").exists()
    for relative, digest in receipt["files"].items():
        assert hashlib.sha256((project / relative).read_bytes()).hexdigest() == digest
    guide = (project / "RUN-ORCHESTRATION.md").read_text()
    assert sys.executable in guide
    assert str(project / "sandbox.json") in guide
    assert str(project / "scripts/caller.py") in guide


@pytest.mark.parametrize("collision", ["AGENTS.md", "sandbox.json", MANIFEST_NAME])
def test_preflights_all_collisions_before_any_write(inputs, collision):
    """A late collision must not leave an earlier partial instruction install."""
    project, profile, declaration = inputs
    existing = project / collision
    existing.write_text("user-owned")
    with pytest.raises(FileExistsError, match="will not replace"):
        assemble(profile, declaration)
    assert list(project.iterdir()) == [existing]
    assert existing.read_text() == "user-owned"


def test_refuses_symlinked_hidden_destination_without_writing_outside(inputs, tmp_path):
    project, profile, declaration = inputs
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / ".agents").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        assemble(profile, declaration)
    assert list(outside.iterdir()) == []
    assert not (project / "AGENTS.md").exists()


def test_failed_publication_preserves_partial_files_without_success_marker(inputs, monkeypatch):
    from tools.orchestration_setup import assembly

    project, profile, declaration = inputs
    real_publish = assembly.publish_bytes_write_once
    published: list[Path] = []

    def fail_after_first(path, content):
        if published:
            raise OSError("simulated disk failure")
        real_publish(path, content)
        published.append(Path(path))

    monkeypatch.setattr(assembly, "publish_bytes_write_once", fail_after_first)
    with pytest.raises(RuntimeError, match=r"assembly incomplete.*simulated disk failure"):
        assemble(profile, declaration)
    assert len(published) == 1 and published[0].is_file()
    assert not (project / MANIFEST_NAME).exists()


def test_invalid_profile_or_empty_declaration_has_no_effect(inputs):
    project, profile, declaration = inputs
    declaration.write_text(" \n")
    with pytest.raises(ValueError, match="run declaration is empty"):
        assemble(profile, declaration)
    assert list(project.iterdir()) == []


def test_installed_guide_command_quotes_shell_metacharacters(tmp_path):
    """Saving a command must not turn a caller-owned path into shell expansion."""
    import shlex

    from tools.orchestration_setup.guide import render_guide

    project = tmp_path / "project $HOME `id` ' space"
    python = str(tmp_path / "environment space/bin/python")
    guide = render_guide(project, python)
    commands = [block.split("\n```", 1)[0] for block in guide.split("```bash\n")[1:]]
    assert shlex.split(commands[0]) == [
        python,
        "-m",
        "tools.workspace_sandbox",
        "check",
        str(project / "sandbox.json"),
    ]
    assert shlex.split(commands[1]) == [
        python,
        "-m",
        "tools.workspace_sandbox",
        "run",
        str(project / "sandbox.json"),
        "--",
        python,
        str(project / "scripts/caller.py"),
    ]
