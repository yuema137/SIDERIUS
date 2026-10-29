"""Files a task composition manifest names, found without importing task code.

Owner: the task composition (``workflows.task_composition``), which resolves
every authored path reference with :func:`resolve_manifest_ref`. This module
lists the references a manifest writes so a caller that mounts a task package
(the console's ``check`` and ``add-task``) can prove each referenced file is
inside a mounted path before a sandboxed child fails to find it.

Scope and limits:

- Only references written in the manifest itself are listed: a string value of
  a ``file``, ``declaration``, ``dir``, ``config`` or ``ref`` key at any depth,
  and the ``code_package`` ``root`` plus each of its ``files``. A ``config``
  mapping (constructor arguments) is walked, not treated as a path.
- References inside the referenced files (for example a Health config naming
  another file) are not followed.
- Nothing is imported, composed, validated or digested; composition remains
  the authority for whether the manifest is valid.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

PATH_KEYS = frozenset({"file", "declaration", "dir", "config", "ref"})


def resolve_manifest_ref(ref: str, manifest_dir: str) -> str:
    """Refs are relative to the MANIFEST's directory, never to the cwd.

    A task package must be movable and must compose identically regardless of
    where the process happens to be launched from.
    """
    return ref if os.path.isabs(ref) else os.path.normpath(os.path.join(manifest_dir, ref))


@dataclass(frozen=True)
class ManifestReference:
    """One authored path reference: where it is written and the path it resolves to."""

    location: str  # dotted manifest location, e.g. ``metric.implementation.file``
    path: Path  # lexically resolved against the manifest directory
    kind: Literal["file", "directory"]


def _walk(value: Any, location: str, manifest_dir: str, found: list[ManifestReference]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            where = f"{location}.{key}"
            if key in PATH_KEYS and isinstance(item, str) and item.strip():
                kind: Literal["file", "directory"] = "directory" if key == "dir" else "file"
                found.append(
                    ManifestReference(where, Path(resolve_manifest_ref(item, manifest_dir)), kind)
                )
            else:
                _walk(item, where, manifest_dir, found)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk(item, f"{location}[{index}]", manifest_dir, found)


def _code_package(value: Any, manifest_dir: str, found: list[ManifestReference]) -> None:
    if not isinstance(value, dict) or not isinstance(value.get("root"), str):
        return
    root = resolve_manifest_ref(value["root"], manifest_dir)
    found.append(ManifestReference("code_package.root", Path(root), "directory"))
    files = value.get("files")
    for index, member in enumerate(files if isinstance(files, list) else ()):
        if isinstance(member, str) and member.strip():
            found.append(
                ManifestReference(
                    f"code_package.files[{index}]",
                    Path(resolve_manifest_ref(member, root)),
                    "file",
                )
            )


def manifest_references(manifest_path: str | Path) -> tuple[ManifestReference, ...]:
    """Every path reference the manifest writes, in document order.

    Raises ``ValueError`` when the file is not a YAML mapping (``OSError`` when
    it cannot be read).
    """
    path = Path(manifest_path)
    with path.open(encoding="utf-8") as handle:
        try:
            raw = yaml.safe_load(handle)
        except yaml.YAMLError:
            raise ValueError(f"task manifest {path} is not valid YAML") from None
    if not isinstance(raw, dict):
        raise ValueError(f"task manifest {path} must be a YAML mapping")
    found: list[ManifestReference] = []
    manifest_dir = str(path.parent)
    for key, value in raw.items():
        if key == "code_package":
            _code_package(value, manifest_dir, found)
        else:
            _walk(value, str(key), manifest_dir, found)
    return tuple(found)
