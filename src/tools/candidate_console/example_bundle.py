"""Example bundle format and ``add-task --from-bundle`` import.

An example bundle is an unpacked folder (the release zip has one top folder):

- ``task/``: a self-contained task package; ``task/task.yaml`` is the manifest and
  every reference in it is package-relative;
- ``setup/setup.json``: :class:`BundleSetup`, the first experiment setup to create
  (a template ID and a label, never workflow source);
- ``console-task.json``: :class:`BundleTask`, the suggested ``task_id``/``label``
  and, for reference, the starter resource values ``add-task`` writes;
- ``fetch_data.py``, ``README.md``;
- ``SHA256SUMS``: ``<sha256>  <relative path>`` for every other file, sorted.

Import (:func:`import_bundle`) verifies ``SHA256SUMS`` and reads each listed file
once, no-follow, into memory; only those verified bytes are used. It then copies
the listed ``task/`` files to ``<workspace>/tasks/<task_id>/`` (folders 0700,
files 0600, write-once: an existing folder is refused), registers the task
through :mod:`add_task`, and creates the setup through ``SetupStore.create``,
the owner behind ``POST /api/tasks/{task_id}/setups``. Nothing is ever deleted:
a failure after the copy names what was left in place.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import ValidationError

from tools.candidate_operations.models import OperationFailure
from tools.workflow_authoring.templates import TemplateId
from tools.workflow_preview.models import PreviewModel

from .files import canonical, config_bytes, open_directory
from .settings_models import Id, Label

SUMS = "SHA256SUMS"
TASK = "task"
MANIFEST = "task.yaml"
SETUP = "setup/setup.json"
TASK_FRAGMENT = "console-task.json"
SETUP_SCHEMA = "siderius.example-bundle-setup/v1"
TASK_SCHEMA = "siderius.example-bundle-task/v1"
MAX_FILE_BYTES = 16 * 1024 * 1024
_SUM_LINE = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9._/-]+)$")


class BundleSetup(PreviewModel):
    """The first experiment setup: created by the setup owner from this template."""

    schema_version: Literal["siderius.example-bundle-setup/v1"]
    template_id: TemplateId
    label: Label


class BundleTask(PreviewModel):
    """Suggested task identity plus the starter values add-task writes (reference only)."""

    schema_version: Literal["siderius.example-bundle-task/v1"]
    task_id: Id
    label: Label
    preparation_timeout_seconds: float
    candidate_timeout_seconds: float
    candidate_network: bool


class BundleRefused(ValueError):
    """The bundle is not usable; the message names the file and the reason."""


@dataclass(frozen=True)
class VerifiedBundle:
    root: Path
    files: dict[str, bytes]  # every SHA256SUMS entry, verified
    setup: BundleSetup
    task: BundleTask

    def task_files(self) -> dict[str, bytes]:
        """Listed files under ``task/``, keyed by their path inside the package."""
        prefix = TASK + "/"
        return {
            name[len(prefix) :]: payload
            for name, payload in self.files.items()
            if name.startswith(prefix)
        }


# Format -------------------------------------------------------------------------------


def format_sums(files: dict[str, bytes]) -> bytes:
    """``SHA256SUMS`` bytes for ``files`` (sorted, two spaces, ``sha256sum -c`` compatible)."""
    lines = [f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n" for name in sorted(files)]
    return "".join(lines).encode()


def _relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or any(part in ("", ".", "..") for part in path.parts)
        or str(path) != name
        or name == SUMS
    ):
        raise BundleRefused(f"{SUMS} lists an unsafe path {name!r}")
    return path


def parse_sums(payload: bytes) -> dict[str, str]:
    """``{relative path: sha256}``; any malformed, duplicate or unsorted line is refused."""
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError:
        raise BundleRefused(f"{SUMS} is not ASCII") from None
    entries: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        match = _SUM_LINE.fullmatch(line)
        if match is None:
            raise BundleRefused(f"{SUMS} line {number} is not '<sha256>  <path>'")
        digest, name = match.groups()
        _relative(name)
        if name in entries:
            raise BundleRefused(f"{SUMS} lists {name} twice")
        entries[name] = digest
    if list(entries) != sorted(entries):
        raise BundleRefused(f"{SUMS} entries are not sorted")
    for required in (f"{TASK}/{MANIFEST}", SETUP, TASK_FRAGMENT):
        if required not in entries:
            raise BundleRefused(f"{SUMS} does not list {required}")
    return entries


def _read_file(root: int, name: str) -> bytes:
    """Read one regular file below ``root`` without following any symlink."""
    parts = PurePosixPath(name).parts
    directory = os.dup(root)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
    except OSError:
        raise BundleRefused(f"{name} is missing, a symlink or unreadable") from None
    finally:
        os.close(directory)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_FILE_BYTES:
            raise BundleRefused(f"{name} must be a regular file of at most {MAX_FILE_BYTES} bytes")
        chunks, total = [], 0
        while chunk := os.read(descriptor, 1 << 20):
            total += len(chunk)
            if total > MAX_FILE_BYTES:
                raise BundleRefused(f"{name} grew past {MAX_FILE_BYTES} bytes while reading")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def read_bundle(directory: str) -> VerifiedBundle:
    """Verify every ``SHA256SUMS`` entry and validate the two descriptors."""
    if not os.path.isabs(directory) or os.path.normpath(directory) != directory:
        raise BundleRefused(
            f"--from-bundle must be an absolute path without '..' or a trailing slash, "
            f"for example {os.path.abspath(directory)}"
        )
    try:
        root_path = canonical(directory)
        root = open_directory(root_path)
    except (OSError, OperationFailure):
        raise BundleRefused(
            f"{directory} must be an existing folder whose path has no symlinks"
        ) from None
    try:
        expected = parse_sums(_read_file(root, SUMS))
        files: dict[str, bytes] = {}
        for name, digest in expected.items():
            payload = _read_file(root, name)
            if hashlib.sha256(payload).hexdigest() != digest:
                raise BundleRefused(
                    f"{name} does not match {SUMS}; download and unpack the bundle again"
                )
            files[name] = payload
    finally:
        os.close(root)
    try:
        setup = BundleSetup.model_validate_json(files[SETUP])
    except ValidationError:
        raise BundleRefused(f"{SETUP} is not a valid {SETUP_SCHEMA} descriptor") from None
    try:
        task = BundleTask.model_validate_json(files[TASK_FRAGMENT])
    except ValidationError:
        raise BundleRefused(f"{TASK_FRAGMENT} is not a valid {TASK_SCHEMA} fragment") from None
    return VerifiedBundle(root_path, files, setup, task)


# Import -------------------------------------------------------------------------------


@dataclass(frozen=True)
class ImportTarget:
    workspace: Path
    package: Path  # <workspace>/tasks/<task_id>
    task_id: str


def plan_import(bundle: VerifiedBundle, config: str, task_id: str | None) -> ImportTarget:
    """Check everything that can fail before the copy; writes nothing."""
    from .add_task import TASK_ID, TASKS_DIRECTORY, AddTaskRefused
    from .settings_file import SettingsInvalid
    from .settings_models import ConsoleFile
    from .workspace import resolve_console

    try:
        payload = config_bytes(str(canonical(config)))
        ConsoleFile.model_validate_json(payload)
        resolved = resolve_console(payload)
    except (OSError, OperationFailure, SettingsInvalid, ValueError):
        raise AddTaskRefused(
            "console.json is not a valid console configuration; run check on it first"
        ) from None
    workspace = resolved.settings.workspace_root
    if workspace is None:
        raise AddTaskRefused("console.json has no workspace_root; create it with init first")
    policy = resolved.settings.setups_policy
    if policy is None or not policy.browser_creatable:
        raise AddTaskRefused(
            "console.json does not allow creating experiment setups; set "
            "experiment_setups.browser_creatable to true (init writes it) and try again"
        )
    chosen = task_id or bundle.task.task_id
    if not TASK_ID.fullmatch(chosen):
        raise AddTaskRefused(f"{chosen!r} is not a valid task ID (letters, digits, - and _)")
    if any(task.task_id == chosen for task in resolved.config.tasks):
        raise AddTaskRefused(f"console.json already has a task {chosen!r}; pass --task-id")
    package = workspace / TASKS_DIRECTORY / chosen
    if os.path.lexists(package):
        raise AddTaskRefused(
            f"{package} already exists; nothing was copied (pass --task-id for another name)"
        )
    return ImportTarget(workspace, package, chosen)


def copy_package(bundle: VerifiedBundle, target: ImportTarget) -> Path:
    """Write the verified ``task/`` bytes write-once below ``tasks/``; returns the manifest."""
    from .add_task import TASKS_DIRECTORY, AddTaskRefused
    from .settings_export import _write_once
    from .workspace import WorkspaceRefused, ensure_owned_directory

    opened: dict[str, int] = {}
    try:
        root = open_directory(target.workspace)
        try:
            tasks = ensure_owned_directory(root, TASKS_DIRECTORY, TASKS_DIRECTORY)
        finally:
            os.close(root)
        try:
            try:
                os.mkdir(target.task_id, 0o700, dir_fd=tasks)
            except FileExistsError:
                raise AddTaskRefused(
                    f"{target.package} already exists; nothing was copied"
                ) from None
            opened[""] = ensure_owned_directory(
                tasks, target.task_id, f"{TASKS_DIRECTORY}/{target.task_id}"
            )
        finally:
            os.close(tasks)
        for name, payload in sorted(bundle.task_files().items()):
            parent = ""
            for part in PurePosixPath(name).parts[:-1]:
                path = f"{parent}/{part}" if parent else part
                if path not in opened:
                    opened[path] = ensure_owned_directory(opened[parent], part, path)
                parent = path
            _write_once(opened[parent], PurePosixPath(name).name, payload)
    except (OSError, WorkspaceRefused) as error:
        left = f"; {target.package} was left in place" if opened else ""
        raise AddTaskRefused(f"copying the task package failed ({error}){left}") from None
    finally:
        for descriptor in opened.values():
            os.close(descriptor)
    return target.package / MANIFEST


def create_first_setup(config_path: str, task_id: str, setup: BundleSetup) -> str:
    """Create the bundle's setup through ``SetupStore.create``; returns its setup ID."""
    from .setups import SetupCreate, SetupStore
    from .workspace import resolve_console

    resolved = resolve_console(config_bytes(config_path))
    workspace = resolved.settings.workspace_root
    store = SetupStore.load(resolved.config, workspace, resolved.settings.setups_policy)
    entry = store.create(
        resolved.config,
        task_id,
        SetupCreate(label=setup.label, template_id=setup.template_id),
    )
    return entry.setup_id


def describe(bundle: VerifiedBundle, target: ImportTarget) -> str:
    return json.dumps(
        {
            "bundle": str(bundle.root),
            "task_package": str(target.package),
            "task_id": target.task_id,
            "files": sorted(bundle.task_files()),
            "first_setup": bundle.setup.model_dump(exclude={"schema_version"}),
        },
        indent=2,
    )


__all__ = [
    "BundleRefused",
    "BundleSetup",
    "BundleTask",
    "VerifiedBundle",
    "copy_package",
    "create_first_setup",
    "format_sums",
    "parse_sums",
    "plan_import",
    "read_bundle",
]
