"""Materialize a COMPLETE task-composition manifest for a test.

Step 11 C5/C6. The child-side composers
(``compose_metric_from_manifest``, ``compose_deliverable_naming_from_manifest``)
read the manifest through ``_read_manifest``, which enforces the required
section set. That is deliberate and stronger than reading one section in
isolation — a partial manifest is refused before any section is composed —
but it means a test fixture must be a real manifest, not a fragment.

A fragment would still raise, so a negative test written against one passes
**for the wrong reason**: it proves the required-section check fires, not
the branch it claims to exercise.

The framework-owned Quickstart manifest is the base, with its relative refs
rewritten to absolute so the copy resolves from ``tmp_path``. Derived from the
current checkout — never a hardcoded path or an external experiment package.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_MANIFEST = REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml"

#: Keys whose values are refs the composer resolves relative to the manifest.
_REF_KEYS = ("config", "declaration", "dir")


def _absolutize(node: Any, base_dir: Path) -> Any:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in _REF_KEYS and isinstance(value, str):
                out[key] = os.path.abspath(os.path.join(base_dir, value))
            elif key == "file" and isinstance(value, str):
                out[key] = os.path.abspath(os.path.join(base_dir, value))
            else:
                out[key] = _absolutize(value, base_dir)
        return out
    if isinstance(node, list):
        return [_absolutize(item, base_dir) for item in node]
    return node


def write_complete_manifest(tmp_path: Path, **sections: Any) -> Path:
    """A complete, resolvable manifest at ``tmp_path``, plus ``sections``.

    Args:
        tmp_path: pytest's per-test directory.
        **sections: sections to ADD or REPLACE, e.g.
            ``deliverable={"prefix": "pets_pred"}``. A value of ``None``
            REMOVES the section, which is how a "missing required section"
            case is written honestly.

    Returns:
        The path to the written manifest.
    """
    raw = yaml.safe_load(BASE_MANIFEST.read_text(encoding="utf-8"))
    raw = _absolutize(raw, BASE_MANIFEST.parent)
    for key, value in sections.items():
        if value is None:
            raw.pop(key, None)
        else:
            raw[key] = value
    tmp_path.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "manifest.yaml"
    target.write_text(yaml.safe_dump(raw, sort_keys=True), encoding="utf-8")
    return target
