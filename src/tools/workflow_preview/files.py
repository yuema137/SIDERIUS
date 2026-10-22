"""Read local observations and check location separation without creating paths."""

import hashlib
import os
import stat
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from core.layout import checkout_root, package_root

from .models import FileObservation


def resolve_location(project: Path, location: str, reference: str) -> Path:
    if urlsplit(location).scheme or location.startswith("//"):
        raise ValueError(f"{reference}: expected a local path, not a URI: {location!r}")
    try:
        return (project / location).resolve()
    except (OSError, ValueError, RuntimeError) as error:
        raise ValueError(f"{reference}: cannot resolve local path {location!r}: {error}") from error


def observe_file(path: Path, reference: str) -> tuple[FileObservation, bytes]:
    """Reject special files before reading; hash exactly the captured bytes."""
    try:
        # O_NONBLOCK also prevents a swapped-in FIFO from hanging this inspection.
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError(f"{reference}: expected a regular readable file: {path}")
            content = stream.read()
    except OSError as error:
        raise ValueError(f"{reference}: cannot read local file {path}: {error}") from error
    return FileObservation(
        reference=reference,
        path=str(path),
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
    ), content


def _overlap(first: Path, second: Path) -> bool:
    return first.is_relative_to(second) or second.is_relative_to(first)


def _source_roots() -> tuple[Path, ...]:
    checkout = checkout_root()
    if checkout is not None:
        return (checkout.resolve(),)
    # Protect the distribution's packages, not all unrelated site-packages.
    root = package_root()
    return tuple(
        (root / name).resolve()
        for name in (
            "agent",
            "nodes",
            "core",
            "execute_tools",
            "ml_models",
            "tools",
            "workflows",
            "dashboard",
        )
    )


def inspect_workspace(
    workspace: Path, data: Path, selected_files: tuple[Path, ...]
) -> Literal["absent", "empty"]:
    if any(_overlap(workspace, root) for root in _source_roots()):
        raise ValueError(f"task.workspace overlaps framework source: {workspace}")
    if _overlap(workspace, data):
        raise ValueError(f"task.workspace overlaps task.data_root: {workspace}")
    if any(path.is_relative_to(workspace) for path in selected_files):
        raise ValueError(f"task.workspace contains a selected input file: {workspace}")
    try:
        if not workspace.exists():
            # An absent descendant of a regular file cannot be a future directory.
            for parent in workspace.parents:
                if parent.exists():
                    if not parent.is_dir():
                        raise ValueError(f"task.workspace ancestor is not a directory: {parent}")
                    break
            return "absent"
        if not workspace.is_dir() or next(workspace.iterdir(), None) is not None:
            raise ValueError(f"task.workspace must be absent or an empty directory: {workspace}")
    except OSError as error:
        raise ValueError(f"task.workspace cannot be inspected: {workspace}: {error}") from error
    return "empty"
