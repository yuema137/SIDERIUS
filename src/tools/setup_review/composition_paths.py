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


def validate_check_locations(
    request: TaskCheckRequest, declaration: SetupDeclarationReport
) -> None:
    """Validate new output locations before claiming them; never inspect data contents."""
    # Existing source-path acceptance remains owned by the sandbox schema.
    sources = SandboxProfile.read_only_paths(request.read_only)
    runtime = runtime_roots()
    protected = (*runtime, *SYSTEM_DIRECTORIES, *(path.parent for path in SYSTEM_FILES))
    for label, path in (("scratch", request.scratch), ("output", request.output)):
        if not path.is_absolute() or path != path.resolve():
            raise ValueError(f"{label} must be a canonical absolute path without symlink aliases")
        if os.path.lexists(path):
            raise ValueError(f"{label} already exists; choose a new directory: {path}")
        if not path.parent.is_dir():
            raise ValueError(f"Create the {label} parent directory first: {path.parent}")
        if any(
            _overlap(path, root) for root in (*protected, *sources, Path(declaration.workspace))
        ):
            raise ValueError(
                f"{label} must be separate from runtime, source roots and the actual run workspace"
            )
    if _overlap(request.scratch, request.output):
        raise ValueError("scratch and output must be separate non-nested directories")
    manifest = Path(declaration.task_manifest)
    if not any(manifest.is_relative_to(root) for root in (*runtime, *sources)):
        raise ValueError(
            "Expose the selected task manifest using --read-only on its task source directory"
        )
    if request.resolve_task_settings:
        health_path = next(
            row.declared_value
            for row in declaration.parameters
            if row.name == "health_checks_config"
        )
        if isinstance(health_path, str) and health_path:
            selected = (Path(request.setup.working_directory) / health_path).resolve()
            if not any(selected.is_relative_to(root) for root in (*runtime, *sources)):
                raise ValueError(
                    "Expose the selected Health configuration using --read-only on its source directory"
                )
    data = next(row.declared_value for row in declaration.parameters if row.name == "data_dir")
    if isinstance(data, str):
        data_path = (Path(request.setup.working_directory) / data).resolve()
        if any(_overlap(data_path, root) for root in (*runtime, *sources)):
            raise ValueError(
                "Declared data_dir overlaps an exposed source/runtime root. Keep source and data "
                "separate; expose only task code/configuration with --read-only for this check."
            )
