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

The framework-owned Quickstart manifest is the base. The helper relocates the
complete pack and preserves its relative references, so the copied manifest
exercises the same portable package shape as an external consumer without
creating a second identity for the original plugin path.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_MANIFEST = REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml"


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
    for key, value in sections.items():
        if value is None:
            raw.pop(key, None)
        else:
            raw[key] = value
    pack_target = tmp_path / "examples" / "quickstart"
    shutil.copytree(REPO_ROOT / "examples" / "quickstart", pack_target)
    target = tmp_path / "configs" / "task_composition" / "manifest.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(raw, sort_keys=True), encoding="utf-8")
    return target
