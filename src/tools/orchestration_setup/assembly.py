"""Publish a documentation overlay without replacing caller-owned files."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from core.durable_io import publish_bytes_write_once
from core.layout import checkout_root, require_checkout
from tools.orchestration_setup.guide import render_guide
from tools.workspace_sandbox.profile import SandboxProfile

MANIFEST_NAME = ".siderius-orchestration-assembly.json"


class AssemblyReceipt(BaseModel):
    """Installation provenance, not task readiness or a launch authorization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    status: Literal["assembled"] = "assembled"
    project: str
    python: str
    source_checkout: str
    source_revision: str
    source_tree_dirty: bool
    files: dict[str, str]


def _payload(checkout: Path) -> dict[str, bytes]:
    root = checkout / "docs/agent-reference/orchestrator-toolkit/payload"
    if not root.is_dir():
        raise FileNotFoundError(f"toolkit payload missing from this checkout: {root}")
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"toolkit payload must not contain symlinks: {path}")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path.read_bytes()
    for required in ("AGENTS.md", ".agents/skills/siderius-toolkit/SKILL.md"):
        if required not in files:
            raise FileNotFoundError(f"toolkit payload is incomplete: missing {required}")
    return files


def _check_destination(project: Path, relative: str) -> Path:
    target = project / relative
    # Check again just before publication. This is not an adversarial concurrent
    # filesystem boundary; the destination must remain caller-controlled.
    for parent in (project, *target.parents):
        if parent.is_symlink():
            raise ValueError(f"output ancestor must not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"output ancestor must be a directory: {parent}")
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"will not replace existing project file: {target}")
    return target


def assemble(profile_path: Path, declaration_path: Path) -> AssemblyReceipt:
    """Read all inputs, preflight all destinations, then publish files once.

    On publication failure, retain existing files and omit the completion
    manifest. The caller chooses a fresh directory or inspects the partial
    installation; this function never recursively removes user material.
    """
    checkout = require_checkout(checkout_root())
    profile = SandboxProfile.model_validate_json(profile_path.read_bytes())
    declaration = declaration_path.read_bytes()
    if not declaration.decode("utf-8").strip():
        raise ValueError("run declaration is empty; supply preparation or execution instructions")
    files = _payload(checkout)
    files.update(
        {
            "SIDERIUS-RUN.md": declaration,
            "sandbox.json": (profile.model_dump_json(indent=2) + "\n").encode("utf-8"),
            "RUN-ORCHESTRATION.md": render_guide(profile.workspace, sys.executable).encode("utf-8"),
        }
    )
    revision = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(checkout), "status", "--porcelain", "--untracked-files=normal"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout
    receipt = AssemblyReceipt(
        project=str(profile.workspace),
        python=sys.executable,
        source_checkout=str(checkout),
        source_revision=revision,
        source_tree_dirty=bool(dirty.strip()),
        files={name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
    )
    for relative in (*files, MANIFEST_NAME):
        _check_destination(profile.workspace, relative)
    try:
        for relative, payload in files.items():
            destination = _check_destination(profile.workspace, relative)
            publish_bytes_write_once(str(destination), payload)
        manifest = _check_destination(profile.workspace, MANIFEST_NAME)
        publish_bytes_write_once(str(manifest), (receipt.model_dump_json(indent=2) + "\n").encode())
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"assembly incomplete in {profile.workspace}; no completion manifest was published. "
            "Previously written files are retained. Inspect them or choose a fresh project. "
            f"Cause: {exc}"
        ) from exc
    return receipt
