"""Files a task composition manifest names, found without importing task code.

Owner: the task composition (``workflows.task_composition``), which resolves
every authored path reference with :func:`resolve_manifest_ref`. This module
lists the references a manifest writes so a caller that mounts a task package
(the console's ``check`` and ``add-task``) can prove each referenced file is
inside a mounted path before a sandboxed child fails to find it.

Scope and limits:

- Only references the composition itself resolves against the manifest
  directory are listed, by the composition's own rules:

  * a string ``file`` (``_load_symbol``), ``declaration`` (metric and secondary
    declarations) or ``dir`` (model/loss plugin directories) at any depth
    outside a constructor ``config`` mapping;
  * a string ``config`` (dataset profile, task config, Health, blocks, rubrics,
    data analysis);
  * inside a ``config`` *mapping* (task-owned constructor arguments, passed
    unchanged by ``_validated_task_config_mapping``) only the values of exact
    ``{ref: <str>}`` envelopes; every other key and value there belongs to the
    task and is never read as a path, at any depth;
  * the ``code_package`` ``root`` plus each of its ``files``.
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

#: Keys whose string value the composition resolves as a manifest-relative path.
PATH_KEYS = frozenset({"file", "declaration", "dir", "config"})


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


def _reference(
    where: str, ref: str, manifest_dir: str, kind: Literal["file", "directory"]
) -> ManifestReference:
    return ManifestReference(where, Path(resolve_manifest_ref(ref, manifest_dir)), kind)


def _constructor_refs(
    config: dict[Any, Any], location: str, manifest_dir: str, found: list[ManifestReference]
) -> None:
    """Only exact ``{ref: <str>}`` envelopes, as ``_validated_task_config_mapping`` resolves."""
    for key, value in config.items():
        if isinstance(value, dict) and set(value) == {"ref"} and isinstance(value["ref"], str):
            found.append(_reference(f"{location}.{key}.ref", value["ref"], manifest_dir, "file"))


def _walk(value: Any, location: str, manifest_dir: str, found: list[ManifestReference]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            where = f"{location}.{key}"
            if key == "config" and isinstance(item, dict):
                _constructor_refs(item, where, manifest_dir, found)
            elif key in PATH_KEYS and isinstance(item, str) and item.strip():
                found.append(
                    _reference(where, item, manifest_dir, "directory" if key == "dir" else "file")
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
