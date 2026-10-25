"""Admission of explicit source roots and fresh inspection directories."""

from __future__ import annotations

import os
from pathlib import Path

from tools.setup_review.composition_models import TaskCheckRequest
from tools.setup_review.models import SetupDeclarationReport
from tools.workspace_sandbox.profile import (
    SYSTEM_DIRECTORIES,
    SYSTEM_FILES,
    SandboxProfile,
    runtime_roots,
)


def _overlap(first: Path, second: Path) -> bool:
    return first.is_relative_to(second) or second.is_relative_to(first)


def _fresh_directory(label: str, path: Path, sources: tuple[Path, ...]) -> None:
    if not path.is_absolute() or path != path.resolve():
        raise ValueError(f"{label} must be a canonical absolute path without symlink aliases")
    if os.path.lexists(path):
        raise ValueError(f"{label} already exists; choose a new directory: {path}")
    if not path.parent.is_dir():
        raise ValueError(f"Create the {label} parent directory first: {path.parent}")
    protected = (*runtime_roots(), *SYSTEM_DIRECTORIES, *(p.parent for p in SYSTEM_FILES))
    if any(_overlap(path, root) for root in (*protected, *sources)):
        raise ValueError(f"{label} must be separate from runtime and source roots")


def validate_observation_locations(
    scratch: Path, read_only: tuple[Path, ...], manifest: Path, data_root: Path | None = None
) -> None:
    """Shared inspection-only mount admission; never inspect dataset contents."""
    sources = SandboxProfile.read_only_paths(read_only)
    _fresh_directory("scratch", scratch, sources)
    runtime = runtime_roots()
    if not manifest.is_absolute() or manifest != manifest.resolve():
        raise ValueError("manifest must be a canonical absolute path without symlink aliases")
    if not any(manifest.is_relative_to(root) for root in (*runtime, *sources)):
        raise ValueError(
            "Expose the selected task manifest using --read-only on its task source directory"
        )
    if data_root is not None and any(_overlap(data_root, root) for root in (*runtime, *sources)):
        raise ValueError(
            "Declared data_dir overlaps an exposed source/runtime root. Keep source and data "
            "separate; expose only task code/configuration with --read-only for this check."
        )


def validate_check_locations(
    request: TaskCheckRequest, declaration: SetupDeclarationReport
) -> None:
    """Validate new output locations before claiming them; never inspect data contents."""
    data = next(row.declared_value for row in declaration.parameters if row.name == "data_dir")
    data_root = (
        (Path(request.setup.working_directory) / data).resolve() if isinstance(data, str) else None
    )
    validate_observation_locations(
        request.scratch, request.read_only, Path(declaration.task_manifest), data_root
    )
    sources = SandboxProfile.read_only_paths(request.read_only)
    _fresh_directory("output", request.output, sources)
    if any(
        _overlap(path, Path(declaration.workspace)) for path in (request.scratch, request.output)
    ):
        raise ValueError("scratch and output must be separate from the actual run workspace")
    if _overlap(request.scratch, request.output):
        raise ValueError("scratch and output must be separate non-nested directories")
    if request.resolve_task_settings:
        health_path = next(
            row.declared_value
            for row in declaration.parameters
            if row.name == "health_checks_config"
        )
        if isinstance(health_path, str) and health_path:
            selected = (Path(request.setup.working_directory) / health_path).resolve()
            if not any(selected.is_relative_to(root) for root in (*runtime_roots(), *sources)):
                raise ValueError(
                    "Expose the selected Health configuration using --read-only on its source directory"
                )
