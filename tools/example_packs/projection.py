"""TIDMAD read-only RESOLVED-SNAPSHOT projection (Step-07 PR0, commit C1).

Projects what production ALREADY resolves for the TIDMAD task into
``examples/tidmad/resolved/`` — five JSON snapshots plus a DO-NOT-EDIT banner —
so that "TIDMAD is projected too" (roadmap §22.23.2) is true without a second
authority (§22.23.1). Every value is read from the owning production
accessor; nothing is restated here:

==================  ==========================================================
snapshot            production authority (read at generation time)
==================  ==========================================================
dataset_profile     ``execute_tools.dataset_config.resolve_dataset_profile()``
model_io_contract   ``workflows.task_config.run_bound_model_io_contract()``
                    (from ``configs/task_config.yaml``)
deliverable_spec    ``execute_tools.deliverable_spec.derive_tidmad_deliverable_spec``
metric_spec         ``execute_tools.evaluation_metric.derive_tidmad_metric_spec``
identity            file indices + file-name families rendered from the
                    profile's ``DatasetConfig`` (nothing beyond what it derives)
==================  ==========================================================

The snapshots are READ-ONLY. **The runtime does not read them.** Editing one
changes nothing at run time; the CI test
``tests/unit/examples/test_tidmad_projection.py`` regenerates every snapshot
from the authorities and deep-compares, so drift is a red test, resolved by
regenerating in the SAME commit as the intentional authority change.

This module is TOOLING (package docstring; OD-PR0-1) — no production package
imports it, and D14 / Step 12 are not obliged to reuse it.

Regenerate::

    .venv/bin/python -m tools.example_packs.projection            # writes examples/tidmad/resolved/
    .venv/bin/python -m tools.example_packs.projection --root DIR # write under DIR/resolved/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from execute_tools.dataset_config import (
    DatasetProfile,
    resolve_dataset_profile,
    tidmad_topology,
)
from execute_tools.deliverable_spec import derive_tidmad_deliverable_spec
from execute_tools.evaluation_metric import derive_tidmad_metric_spec
from tools.example_packs._common import repo_root, write_json, write_text
from workflows.task_config import run_bound_model_io_contract

#: Snapshot keys, in the order they are written. ``model_io_contract`` is
#: absent from a projection when the bound task declares no ``model_io``
#: (legacy prose-only task) — the STATUS then says so; the current
#: ``configs/task_config.yaml`` declares one, and the test asserts presence.
SNAPSHOT_KEYS: tuple[str, ...] = (
    "dataset_profile",
    "model_io_contract",
    "deliverable_spec",
    "metric_spec",
    "identity",
)

RESOLVED_DIRNAME = "resolved"
REGENERATE_COMMAND = ".venv/bin/python -m tools.example_packs.projection"

#: The owning paths the banner cites (documentation references, never copies).
AUTHORITY_PATHS: dict[str, str] = {
    "dataset_profile": "execute_tools/dataset_config.py (`resolve_dataset_profile`, `TIDMAD_PROFILE`)",
    "model_io_contract": (
        "configs/task_config.yaml `forward_contract.model_io` via "
        "workflows/task_config.py (`run_bound_model_io_contract`)"
    ),
    "deliverable_spec": "execute_tools/deliverable_spec.py (`derive_tidmad_deliverable_spec`)",
    "metric_spec": "execute_tools/evaluation_metric.py (`derive_tidmad_metric_spec`)",
    "identity": "execute_tools/dataset_config.py (`DatasetConfig` file patterns / `num_files`)",
}


def _task_config_path(root: Path) -> str:
    """The shipped task YAML, addressed from the checkout root.

    ``load_task_config`` now defaults to the SIDERIUS_ROOT-anchored
    canonical file (F-SCANA-2; it used to be CWD-relative). The projection
    keeps its own explicit path anyway: this tooling addresses whichever
    checkout ``root`` names, which need not be the checkout the module was
    imported from (CLAUDE.md portability).
    """
    return str(root / "configs" / "task_config.yaml")


def project_identity(profile: DatasetProfile) -> dict[str, Any]:
    """File indices and the two file-name families, rendered from the profile.

    Deliberately nothing beyond what ``DatasetConfig`` derives: TIDMAD's input
    identity IS the file index (``0..num_files-1``); the names are the
    patterns the production data path formats. Anchor / peek file sets are
    already in the ``dataset_profile`` snapshot and are not repeated.
    """
    dataset = tidmad_topology(profile).dataset
    indices = list(range(dataset.num_files))
    return {
        "input_identity": "file_index",
        "num_files": dataset.num_files,
        "file_indices": indices,
        "training_file_pattern": dataset.training_file_pattern,
        "validation_file_pattern": dataset.validation_file_pattern,
        "training_files": [dataset.training_file_pattern.format(file_index=i) for i in indices],
        "validation_files": [dataset.validation_file_pattern.format(file_index=i) for i in indices],
    }


def project_tidmad(root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return JSON-ready dicts for every TIDMAD snapshot, read from production.

    Args:
        root: Checkout root used to address ``configs/task_config.yaml``.
            Defaults to the root this file lives in.

    Returns:
        ``{snapshot_key: json_ready_dict}``. ``model_io_contract`` is omitted
        when the bound task declares no ``model_io``.
    """
    root = root or repo_root()
    profile = resolve_dataset_profile()
    deliverable = derive_tidmad_deliverable_spec(profile)
    metric = derive_tidmad_metric_spec(profile, deliverable)
    contract = run_bound_model_io_contract(_task_config_path(root))

    projection: dict[str, dict[str, Any]] = {
        "dataset_profile": profile.to_wire(),
        "deliverable_spec": deliverable.model_dump(mode="json"),
        "metric_spec": metric.model_dump(mode="json"),
        "identity": project_identity(profile),
    }
    if contract is not None:
        projection["model_io_contract"] = contract.model_dump(mode="json")
    return {key: projection[key] for key in SNAPSHOT_KEYS if key in projection}


def render_resolved_banner(keys: tuple[str, ...] = SNAPSHOT_KEYS) -> str:
    """The ``resolved/README.md`` text — generated with the snapshots so it cannot drift."""
    rows = "\n".join(f"| `{key}.json` | {AUTHORITY_PATHS[key]} |" for key in keys)
    return f"""# `resolved/` — READ-ONLY resolved snapshots (GENERATED — DO NOT EDIT)

**GENERATED · DO NOT EDIT · the runtime does not read this file.**

Every file in this directory is a resolved SNAPSHOT of what SIDERIUS
production already derives for the TIDMAD task, written by
`tools/example_packs/projection.py`. It is a projection for humans, never a
second authority (roadmap §22.23.1):

- **The runtime does not read these files.** Editing them changes nothing at
  run time. To change the task, edit the OWNING path listed below.
- **CI regenerates and deep-compares them**
  (`tests/unit/examples/test_tidmad_projection.py`). If an authority changes
  intentionally, regenerate in the SAME commit:

  ```bash
  {REGENERATE_COMMAND}
  ```

| snapshot | generated from (owning authority) |
|---|---|
{rows}

Migration rule (design §3.6): when a later Step introduces a real,
user-editable task binding for this pack, these snapshots must not coexist
with it as a second authoritative-looking config.
"""


def write_pack(pack_root: Path, projection: dict[str, dict[str, Any]] | None = None) -> list[Path]:
    """Write ``pack_root/resolved/{key}.json`` + ``resolved/README.md``; return the paths.

    Only the writer performs I/O; :func:`project_tidmad` is pure.
    """
    projection = project_tidmad() if projection is None else projection
    resolved = pack_root / RESOLVED_DIRNAME
    written = [write_json(resolved / f"{key}.json", value) for key, value in projection.items()]
    written.append(
        write_text(resolved / "README.md", render_resolved_banner(tuple(projection.keys())))
    )
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="pack root to write under (default: <checkout>/examples/tidmad)",
    )
    args = parser.parse_args(argv)
    pack_root = args.root or (repo_root() / "examples" / "tidmad")
    for path in write_pack(pack_root):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
