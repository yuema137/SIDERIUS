"""Stage generated model source; retain current declared package members."""

from __future__ import annotations

import os
import shutil

from ml_models.plugin_binding import (
    active_run_model_plugins,
    declared_package_model,
    require_declared_model_source,
)


def _save_forensic_source(source: str, model_name: str) -> None:
    """Keep source before construction can OOM (2026-06-24 v15 incident).

    The workspace-root sentinel survives iteration cleanup; failures remain
    best-effort diagnostics and never block ordinary generated registration.
    """
    try:
        root = os.environ.get("SIDERIUS_CHAIN_WORKSPACE", os.path.dirname(os.path.dirname(source)))
        directory = os.path.join(root, "plugin_source_sentinel")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"{model_name}.py")
        shutil.copy2(source, path)
        print(f"    [DEBUG] Plugin source saved to sentinel: {path}", flush=True)
    except Exception as exc:
        print(f"    [DEBUG] Plugin source sentinel write skipped ({type(exc).__name__}: {exc})")


def _copy_generated_model(source: str, model_name: str, destinations: list[str]) -> str | None:
    _save_forensic_source(source, model_name)
    primary = None
    for directory in destinations:
        os.makedirs(directory, exist_ok=True)
        target = os.path.join(directory, f"{model_name}.py")
        shutil.copy2(source, target)
        if primary is None:
            primary = target
        print(f"    Plugin registered → {target}")
    return primary


def _copy_description(source: str, model_name: str, destinations: list[str]) -> None:
    if not os.path.isfile(source):
        print(f"    Warning: description not found at {source}, skipping registration")
        return
    for directory in destinations:
        target_dir = os.path.join(directory, model_name)
        os.makedirs(target_dir, exist_ok=True)
        target = os.path.join(target_dir, "description.md")
        shutil.copy2(source, target)
        print(f"    Description registered → {target}")


def stage_model_source(
    source: str, description: str, model_name: str, destinations: list[str], *, model_type: str
) -> tuple[bool, str | None]:
    """Return source presence/path; an empty destination list is not missing source."""
    declared = declared_package_model(model_type, active_run_model_plugins())
    if declared is not None:
        require_declared_model_source(declared, source)
        primary = declared.absolute_path
    elif not os.path.isfile(source):
        print(f"    Warning: plugin file not found at {source}, skipping registration")
        return False, None
    else:
        primary = _copy_generated_model(source, model_name, destinations)
    _copy_description(description, model_name, destinations)
    return True, primary
