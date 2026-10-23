"""Read-only admission and source observations, before the exclusive output claim."""

import os
from collections.abc import Callable
from pathlib import Path

from tools.workflow_preview.config import parse_config
from tools.workflow_preview.files import inspect_workspace, observe_file, resolve_location
from tools.workflow_preview.models import FileObservation
from tools.workspace_sandbox.profile import (
    SYSTEM_DIRECTORIES,
    SandboxProfile,
    runtime_roots,
    validate_mount_boundaries,
)

from .models import CandidatePreparationRequest, PreparationControl


def canonical(value: str) -> Path:
    path = resolve_location(Path("/"), value, "selected path")
    if str(path) != value:
        raise ValueError(f"use a canonical absolute path: {value}")
    return path


def overlap(left: Path, right: Path) -> bool:
    return left.is_relative_to(right) or right.is_relative_to(left)


def absent_destination(path: Path) -> None:
    if os.path.lexists(path) or not path.parent.is_dir():
        raise ValueError(f"destination must be absent with an existing directory parent: {path}")


def validate_destination_overlap(destination: Path, inputs: tuple[Path, ...]) -> None:
    """Shared static protection; no reads or existence requirements."""
    protected = (
        *inputs,
        *runtime_roots(),
        *SYSTEM_DIRECTORIES,
        Path("/etc"),
        Path("/proc"),
        Path("/dev"),
        Path("/sys"),
        Path("/sandbox-home"),
    )
    if any(overlap(destination, root) for root in protected):
        raise ValueError(f"destination overlaps selected input or protected root: {destination}")


def admit(
    request: CandidatePreparationRequest, *, future_parent: Path | None = None
) -> tuple[tuple[FileObservation, bytes], ...]:
    """Validate selected paths and both policies without creating either destination."""
    manifest, config, data, output, workspace = map(
        canonical,
        (
            request.task_manifest,
            request.llm_config_file,
            request.data_root,
            request.output_dir,
            request.candidate_workspace,
        ),
    )
    sources = tuple(canonical(value) for value in request.task_read_only)
    SandboxProfile.read_only_paths((manifest, config, data, *sources))
    SandboxProfile.device_paths(tuple(canonical(value) for value in request.candidate_devices))
    SandboxProfile.environment_keys(request.candidate_environment_names)
    if not data.is_dir():
        raise ValueError("data_root must be an existing directory")
    destinations = (
        (output, workspace) if future_parent is None else (output, workspace, future_parent)
    )
    for destination in destinations:
        if future_parent is None or destination == future_parent:
            absent_destination(destination)
        elif destination.parent != future_parent or os.path.lexists(destination):
            raise ValueError("future destinations must be absent children of the envelope")
        inspect_workspace(destination, data, (manifest, config))
        validate_destination_overlap(destination, (manifest, config, data, *sources))
    if overlap(output, workspace):
        raise ValueError("output_dir and candidate_workspace must not overlap")
    validate_mount_boundaries(output, (manifest, config, data, *sources))
    validate_mount_boundaries(workspace, (output, manifest, data, *sources))
    captures = (observe_file(manifest, "task.manifest"), observe_file(config, "llm_config"))
    parse_config(captures[1][1])
    return captures


def verify_sources(
    control: PreparationControl,
    *,
    read_file: Callable[[Path, str], tuple[FileObservation, bytes]] = observe_file,
) -> None:
    expected_paths = (control.request.task_manifest, control.request.llm_config_file)
    if tuple(item.path for item in control.sources) != expected_paths:
        raise ValueError("control source paths disagree with selections")
    if tuple(item.reference for item in control.sources) != ("task.manifest", "llm_config"):
        raise ValueError("control source references disagree with selections")
    for expected in control.sources:
        actual, _ = read_file(canonical(expected.path), expected.reference)
        if actual != expected:
            raise ValueError(f"selected input changed: {expected.reference}")
