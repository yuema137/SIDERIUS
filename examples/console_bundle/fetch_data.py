"""Write the quickstart example's synthetic data into a console workspace.

Run it with the SIDERIUS checkout's interpreter, after ``init``::

    /path/to/SIDERIUS/.venv/bin/python fetch_data.py \
        --workspace /absolute/project/siderius_workspace

The enclosing bundle's SHA256SUMS is verified before executing task code; only
the verified generator and data manifest bytes are used.
The data is generated, not downloaded: the task package's seeded generator
(``task/plugins/_quickstart_task.py``) renders four CSV shards, and every shard is
checked against ``task/declared/data_manifest.json`` before anything is written.
The shards go to ``<workspace>/data/<task_id>/`` (``task_id`` from
``console-task.json``, ``quickstart`` in the shipped bundle): folders 0700, files
0600, opened without following symlinks. A workspace, ``data/`` or task folder that
is a symlink, belongs to another user or is writable by group or others is
refused. Re-running is safe: an identical shard is kept, a different one is
refused and never overwritten. Exit status 0 on success, 2 on refusal.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
from pathlib import Path
from types import ModuleType

sys.dont_write_bytecode = True  # never leave __pycache__ inside the verified bundle

HERE = Path(__file__).resolve().parent


class FetchRefused(ValueError):
    """Nothing unsafe was written; the message names the folder or file."""


def _load_generator(package: Path, source: bytes) -> ModuleType:
    path = package / "plugins" / "_quickstart_task.py"
    spec = importlib.util.spec_from_file_location("siderius_example_quickstart_data", path)
    if spec is None or spec.loader is None:
        raise FetchRefused(f"{path} is missing; run this from the unpacked bundle")
    module = importlib.util.module_from_spec(spec)
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def render_shards(package: Path) -> dict[str, bytes]:
    """``{shard file name: bytes}``, each verified against the package's data manifest."""
    from tools.candidate_console.example_bundle import BundleRefused, read_bundle

    package = package.absolute()
    if package.name != "task":
        raise FetchRefused("--package must name the task/ folder in an unpacked bundle")
    try:
        bundle = read_bundle(str(package.parent))
    except BundleRefused as error:
        raise FetchRefused(str(error)) from None
    generator_name = "task/plugins/_quickstart_task.py"
    manifest_name = "task/declared/data_manifest.json"
    for name in (generator_name, manifest_name):
        if name not in bundle.files:
            raise FetchRefused(f"SHA256SUMS does not list {name}")
    generator = _load_generator(package, bundle.files[generator_name])
    manifest = json.loads(bundle.files[manifest_name])
    expected = manifest["sha256"]
    shards = {}
    for shard in range(generator.SHARD_COUNT):
        name = generator.shard_filename(shard)
        payload = generator.render_shard_csv(shard).encode("utf-8")
        if hashlib.sha256(payload).hexdigest() != expected.get(name):
            raise FetchRefused(
                f"generated {name} does not match declared/data_manifest.json; nothing was written"
            )
        shards[name] = payload
    if set(shards) != set(expected):
        raise FetchRefused("declared/data_manifest.json lists other shards; nothing was written")
    return shards


def _refuse_unsafe(descriptor: int, label: str) -> None:
    metadata = os.fstat(descriptor)
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o022:
        raise FetchRefused(f"{label} must be owned by you and not writable by group or others")


def _existing(directory: int, name: str) -> bytes | None:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
    except FileNotFoundError:
        return None
    except OSError:
        raise FetchRefused(
            f"{name} exists but is a symlink or unreadable; left unchanged"
        ) from None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise FetchRefused(f"{name} exists but is not a regular file; left unchanged")
        chunks = []
        while chunk := os.read(descriptor, 1 << 20):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def write_shards(workspace: Path, task_id: str, shards: dict[str, bytes]) -> Path:
    """Create ``data/<task_id>/`` privately and write each shard write-once."""
    from tools.candidate_console.files import open_directory
    from tools.candidate_console.settings_export import _write_once
    from tools.candidate_console.workspace import WorkspaceRefused, ensure_owned_directory

    if not workspace.is_absolute() or os.path.normpath(workspace) != str(workspace):
        raise FetchRefused("--workspace must be an absolute path without '..'")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", task_id):
        raise FetchRefused(f"{task_id!r} is not a valid task ID (letters, digits, - and _)")
    opened: list[int] = []
    try:
        try:
            opened.append(open_directory(workspace))
        except OSError:
            raise FetchRefused(
                f"{workspace} must be an existing folder whose path has no symlinks; run init first"
            ) from None
        _refuse_unsafe(opened[0], str(workspace))
        opened.append(ensure_owned_directory(opened[0], "data", f"{workspace}/data"))
        target = workspace / "data" / task_id
        opened.append(ensure_owned_directory(opened[1], task_id, str(target)))
        for name, payload in sorted(shards.items()):
            current = _existing(opened[2], name)
            if current is None:
                _write_once(opened[2], name, payload)
                print(f"wrote {target / name}")
            elif current == payload:
                print(f"kept {target / name} (already identical)")
            else:
                raise FetchRefused(f"{target / name} exists with different content; left unchanged")
    except WorkspaceRefused as error:
        raise FetchRefused(str(error)) from None
    finally:
        for descriptor in opened:
            os.close(descriptor)
    return target


def _default_task_id() -> str | None:
    fragment = HERE / "console-task.json"
    if not fragment.is_file():
        return None
    return json.loads(fragment.read_text("utf-8"))["task_id"]


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description="Write the quickstart example data.")
    cli.add_argument("--workspace", required=True, help="absolute path of siderius_workspace/")
    cli.add_argument("--task-id", default=None, help="default: task_id in console-task.json")
    cli.add_argument(
        "--package", default=str(HERE / "task"), help="the task package (default: ./task)"
    )
    args = cli.parse_args(argv)
    task_id = args.task_id or _default_task_id()
    if task_id is None:
        print("fetch_data refused: pass --task-id (no console-task.json here).", file=sys.stderr)
        return 2
    try:
        target = write_shards(Path(args.workspace), task_id, render_shards(Path(args.package)))
    except FetchRefused as error:
        print(f"fetch_data refused: {error}.", file=sys.stderr)
        return 2
    print(f"Data ready in {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
