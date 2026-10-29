"""Build ``siderius-example-quickstart-<version>.zip``, the stage-1 example bundle.

Usage (from the checkout root)::

    .venv/bin/python -m tools.release.build_example_bundle --output-dir /absolute/dir

Single source of truth: the bundle is assembled from the checkout, never from a
second hand-maintained copy.

- ``task/task.yaml``: ``configs/task_composition/quickstart.yaml`` with every
  ``../../examples/quickstart/`` reference rewritten package-relative; any other
  ``..`` or absolute reference is refused.
- ``task/declared/``, ``task/plugins/``: the non-Markdown files of
  ``examples/quickstart/declared`` and ``examples/quickstart/plugins``.
- ``setup/setup.json``, ``fetch_data.py``, ``README.md``: ``examples/console_bundle/``.
- ``console-task.json``: :data:`TASK_ID`, :data:`TASK_LABEL` and
  ``add_task.STARTER_VALUES``.
- ``SHA256SUMS``: every other file (``example_bundle.format_sums``).

Determinism: entries sorted under one top folder
``siderius-example-quickstart-<version>/``, stored (no compression, so the bytes do
not depend on the zlib build), mtime 1980-01-01 00:00:00, mode 0644, Unix
creator. An existing output file is refused, never replaced.
"""

from __future__ import annotations

import argparse
import json
import stat
import sys
import tomllib
import zipfile
from pathlib import Path
from typing import Any

import yaml

from tools.candidate_console.add_task import STARTER_VALUES
from tools.candidate_console.example_bundle import (
    SETUP,
    SUMS,
    TASK,
    TASK_FRAGMENT,
    TASK_SCHEMA,
    BundleSetup,
    BundleTask,
    format_sums,
)

REPO = Path(__file__).resolve().parents[3]
SOURCES = REPO / "examples" / "console_bundle"
PACK = REPO / "examples" / "quickstart"
SHIPPED_MANIFEST = REPO / "configs" / "task_composition" / "quickstart.yaml"
PACK_PREFIX = "../../examples/quickstart/"
PACKAGE_FOLDERS = ("declared", "plugins")
PACKAGE_SUFFIXES = (".py", ".json", ".yaml")
TASK_ID = "quickstart"  # also the data folder: <workspace>/data/quickstart
TASK_LABEL = "Quickstart (synthetic classification)"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
FILE_MODE = 0o644
HEADER = (
    "# Quickstart task package manifest, generated from SIDERIUS\n"
    "# configs/task_composition/quickstart.yaml by tools.release.build_example_bundle.\n"
    "# Every reference is relative to this file's folder (the task package).\n"
)


class BundleBuildError(ValueError):
    """The checkout cannot produce a self-contained bundle."""


def _rewrite(value: Any, location: str) -> Any:
    if isinstance(value, dict):
        return {key: _rewrite(item, f"{location}.{key}") for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite(item, f"{location}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, str):
        if value.startswith(PACK_PREFIX):
            return value[len(PACK_PREFIX) :]
        if value.startswith("/") or ".." in Path(value).parts:
            raise BundleBuildError(f"{location} = {value!r} is not inside examples/quickstart")
    return value


def task_manifest() -> bytes:
    """The shipped quickstart manifest with package-relative references."""
    document = yaml.safe_load(SHIPPED_MANIFEST.read_text(encoding="utf-8"))
    rewritten = _rewrite(document, "manifest")
    body = yaml.safe_dump(rewritten, sort_keys=False, default_flow_style=None, width=88)
    return (HEADER + body).encode()


def console_task() -> bytes:
    fragment = BundleTask(
        schema_version=TASK_SCHEMA,
        task_id=TASK_ID,
        label=TASK_LABEL,
        preparation_timeout_seconds=STARTER_VALUES.preparation_timeout_seconds,
        candidate_timeout_seconds=STARTER_VALUES.candidate_timeout_seconds,
        candidate_network=STARTER_VALUES.candidate_network,
    )
    return (json.dumps(fragment.model_dump(mode="json"), indent=2) + "\n").encode()


def bundle_files() -> dict[str, bytes]:
    """``{path inside the bundle: bytes}``, including ``SHA256SUMS``."""
    files = {f"{TASK}/task.yaml": task_manifest()}
    for folder in PACKAGE_FOLDERS:
        for path in sorted((PACK / folder).iterdir()):
            if path.is_file() and not path.is_symlink() and path.suffix in PACKAGE_SUFFIXES:
                files[f"{TASK}/{folder}/{path.name}"] = path.read_bytes()
    setup = (SOURCES / SETUP).read_bytes()
    BundleSetup.model_validate_json(setup)  # never ship a descriptor import would refuse
    files[SETUP] = setup
    files["fetch_data.py"] = (SOURCES / "fetch_data.py").read_bytes()
    files["README.md"] = (SOURCES / "README.md").read_bytes()
    files[TASK_FRAGMENT] = console_task()
    files[SUMS] = format_sums(files)
    return files


def default_version() -> str:
    return tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]


def build(output_dir: Path, version: str) -> Path:
    """Write the zip into ``output_dir`` (must exist); returns its path."""
    stem = f"siderius-example-quickstart-{version}"
    target = output_dir / f"{stem}.zip"
    files = bundle_files()
    with target.open("xb") as handle, zipfile.ZipFile(handle, "w", zipfile.ZIP_STORED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(f"{stem}/{name}", date_time=FIXED_TIME)
            info.create_system = 3  # Unix, so external_attr carries the mode
            info.external_attr = (stat.S_IFREG | FILE_MODE) << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, files[name])
    return target


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description="Build the quickstart example bundle zip.")
    cli.add_argument("--output-dir", required=True, help="existing absolute folder")
    cli.add_argument("--version", default=None, help="default: pyproject.toml version")
    args = cli.parse_args(argv)
    output = Path(args.output_dir)
    if not output.is_absolute() or not output.is_dir():
        print("build refused: --output-dir must be an existing absolute folder.", file=sys.stderr)
        return 2
    try:
        target = build(output, args.version or default_version())
    except FileExistsError as error:
        print(f"build refused: {error.filename} exists; nothing was replaced.", file=sys.stderr)
        return 2
    except BundleBuildError as error:
        print(f"build refused: {error}.", file=sys.stderr)
        return 2
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
