"""Fixed ``siderius_workspace`` layout: derivation of omitted locations, readiness and ``init``.

Derivation fills only location facts that console.json omits (output roots, the
operation store, the token path and ``data_root``); content choices stay explicit.
``init`` is the only creator. It walks with no-follow directory descriptors,
creates missing fixed folders with mode 0700, requires every existing or created
directory to be owned by the caller without group/other write, and never deletes,
overwrites or follows a symlink. Residual race: ``core.durable_io`` publishes by
path, so after the no-follow parent check only a process running as the same
user, who already owns the workspace, could swap a parent.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import secrets
import stat
from collections.abc import Iterator
from pathlib import Path

from .files import canonical, config_bytes
from .readiness_models import WorkspaceEntry, WorkspaceReadiness, WorkspaceStatus
from .settings_models import ConsoleFile, ResolvedConsole, SettingsContext

WORKSPACE_DIRECTORY = "siderius_workspace"
SETTINGS = "settings"
CONSOLE_FILE = "console.json"
TOKEN_FILE = "console-token"
DEFAULT_PORT = 8740
# Created by init in this order; ``exported_configs`` is created lazily by its writer.
INIT_CHILDREN = (
    "operations",
    "preparations",
    "candidates",
    "runs",
    "projects",
    "library",
    "library/llm",
    "library/advice",
    SETTINGS,
    "data",
)
LAZY_CHILDREN = ("exported_configs",)
# Per-task derived roots init may create; ``data/<task_id>`` is task data and never created.
TASK_OUTPUT_PARENTS = {
    "preparation_root": "preparations",
    "candidate_root": "candidates",
    "reusable_runs_root": "runs",
}
TASK_PARENTS = {**TASK_OUTPUT_PARENTS, "data_root": "data"}


class MissingSetting(ValueError):
    """A required console field has no source; the message names fields, never values."""


class WorkspaceRefused(ValueError):
    """``init`` found a directory or file it must not use; nothing was deleted."""


def init_command(workspace_root: Path) -> str:
    return ".venv/bin/python -m tools.candidate_console init --workspace " + str(
        workspace_root.parent
    )


# Resolution ------------------------------------------------------------------------


def resolve_console(payload: bytes) -> ResolvedConsole:
    """Fill omitted layout locations; the result is typed but not yet filesystem-validated."""
    from .models import ConsoleConfig

    document = ConsoleFile.model_validate_json(payload).model_dump(mode="json", exclude_unset=True)
    value = document.pop("workspace_root", None)
    workspace = None if value is None else canonical(value)
    derived: set[tuple[str | None, str]] = set()
    if workspace is not None:
        if "operation_store" not in document or document["operation_store"] is None:
            document["operation_store"] = {
                "state_root": str(workspace / "operations"),
                "preparation_roots": [str(workspace / "preparations"), str(workspace / "runs")],
                "candidate_roots": [str(workspace / "candidates"), str(workspace / "runs")],
            }
            derived.add((None, "operation_store"))
        if document.get("auth_token_file") is None:
            document["auth_token_file"] = str(workspace / SETTINGS / TOKEN_FILE)
            derived.add((None, "auth_token_file"))
    for field in ("operation_store", "auth_token_file"):
        if document.get(field) is None:
            raise MissingSetting(
                f"console needs {field} (set it in console.json or set workspace_root)"
            )
    for task in document.get("tasks", []):
        task_id = task["task_id"]
        for field, parent in TASK_PARENTS.items():
            # An explicit null reusable_runs_root keeps reusable runs disabled.
            explicit = field in task and (field == "reusable_runs_root" or task[field] is not None)
            if workspace is not None and not explicit:
                task[field] = str(workspace / parent / task_id)
                derived.add((task_id, field))
        for field in ("data_root", "preparation_root", "candidate_root"):
            if task.get(field) is None:
                raise MissingSetting(
                    f"task {task_id} needs {field} (set it in console.json or set workspace_root)"
                )
        if task.get("llm_config_file") is None:
            raise MissingSetting(f"task {task_id} needs llm_config_file (set it in console.json)")
    config = ConsoleConfig.model_validate_json(json.dumps(document))
    return ResolvedConsole(config, SettingsContext(workspace, frozenset(derived)))


# No-follow directory walking ----------------------------------------------------------


def _owned(descriptor: int) -> bool:
    metadata = os.fstat(descriptor)
    return (
        stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid == os.getuid()
        and not stat.S_IMODE(metadata.st_mode) & 0o022
    )


@contextlib.contextmanager
def _open_directory(path: Path) -> Iterator[int]:
    """Open a canonical directory by walking no-follow descriptors from ``/``."""
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        yield directory
    finally:
        os.close(directory)


def _status(directory: int, name: str, *, owned: bool = True) -> WorkspaceStatus:
    try:
        metadata = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return "missing"
    if stat.S_ISLNK(metadata.st_mode):
        return "symlink"
    if not stat.S_ISDIR(metadata.st_mode):
        return "not_directory"
    if owned and (metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o022):
        return "not_owner"
    return "present"


def _ensure_directory(directory: int, name: str, label: str) -> int:
    """Create ``name`` (0700) when missing, open it no-follow and enforce ownership."""
    try:
        os.mkdir(name, 0o700, dir_fd=directory)
        created = True
    except FileExistsError:
        created = False
    try:
        child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            raise WorkspaceRefused(f"{label} must be a directory, not a symlink or file") from None
        raise
    if created:
        os.fchmod(child, 0o700)
    if not _owned(child):
        os.close(child)
        raise WorkspaceRefused(f"{label} must be owned by you without group/other write")
    return child


# Readiness ----------------------------------------------------------------------------


def workspace_readiness(resolved: ResolvedConsole) -> WorkspaceReadiness | None:
    """Name-only presence of the fixed children and derived task folders; no probes, no creation."""
    workspace = resolved.settings.workspace_root
    if workspace is None:
        return None
    names = [*INIT_CHILDREN, *LAZY_CHILDREN]
    data: list[str] = []
    for task_id, field in resolved.settings.derived_task_fields():
        name = f"{TASK_PARENTS[field]}/{task_id}"
        (data if field == "data_root" else names).append(name)
    entries: list[WorkspaceEntry] = []
    try:
        with _open_directory(workspace) as root:
            root_status: WorkspaceStatus = "present" if _owned(root) else "not_owner"
            for name in (*names, *data):
                parent, _, leaf = name.rpartition("/")
                status = _status_under(root, parent, leaf, owned=name not in data)
                entries.append(
                    WorkspaceEntry(
                        name=name,
                        status=status,
                        created_by=(
                            "writer"
                            if name in LAZY_CHILDREN
                            else "operator"
                            if name in data
                            else "init"
                        ),
                    )
                )
    except OSError:
        root_status = "missing"
    ready = root_status == "present" and all(
        entry.status == "present" for entry in entries if entry.created_by != "writer"
    )
    fixable = root_status != "present" or any(
        entry.status == "missing" for entry in entries if entry.created_by == "init"
    )
    return WorkspaceReadiness(
        workspace_status=root_status,
        entries=tuple(entries),
        ready=ready,
        init_command=init_command(workspace) if fixable else None,
    )


def _status_under(root: int, parent: str, leaf: str, *, owned: bool) -> WorkspaceStatus:
    if not parent:
        return _status(root, leaf, owned=owned)
    status = _status(root, parent)
    if status != "present":
        return "missing" if status == "missing" else status
    child = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
    try:
        return _status(child, leaf, owned=owned)
    finally:
        os.close(child)


# init ---------------------------------------------------------------------------------


def _default_llm_profile() -> bytes:
    """The documented export expression (docs/reference/llm-defaults.md); no checkout read."""
    from workflows.llm_config import WorkflowLLMConfig

    profile = WorkflowLLMConfig.default().model_dump(mode="json", by_alias=True, exclude_none=True)
    return (json.dumps(profile, indent=2) + "\n").encode()


def _write_once(path: Path, payload: bytes, *, label: str) -> None:
    from core.durable_io import publish_bytes_write_once

    try:
        publish_bytes_write_once(str(path), payload)
    except FileExistsError:
        if config_bytes(str(path)) != payload:
            raise WorkspaceRefused(
                f"{label} exists with different content; left unchanged"
            ) from None


def _create_token(settings: int) -> None:
    try:
        descriptor = os.open(
            TOKEN_FILE,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=settings,
        )
    except FileExistsError:
        return  # left untouched; load_console validates it with files.token
    try:
        os.write(descriptor, secrets.token_urlsafe(32).encode())
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def init_workspace(parent: str, *, port: int = DEFAULT_PORT) -> Path:
    """Create missing fixed folders, token, default LLM profile and console.json skeleton.

    Returns the console.json path. Re-running is safe: existing items are checked,
    never replaced. With an existing console.json, the derived per-task output roots
    of its tasks are created too (never ``data/<task_id>``).
    """
    import hashlib

    if not 1024 <= port <= 65535:
        raise WorkspaceRefused("port must be between 1024 and 65535")
    base = canonical(parent)
    workspace = base / WORKSPACE_DIRECTORY
    with _open_directory(base) as directory:
        if not _owned(directory):
            raise WorkspaceRefused(
                "workspace parent must be owned by you without group/other write"
            )
        root = _ensure_directory(directory, WORKSPACE_DIRECTORY, WORKSPACE_DIRECTORY)
    opened = {"": root}
    try:
        for name in INIT_CHILDREN:
            above, _, leaf = name.rpartition("/")
            opened[name] = _ensure_directory(opened[above], leaf, f"{WORKSPACE_DIRECTORY}/{name}")
        _create_token(opened[SETTINGS])
        profile = _default_llm_profile()
        digest = hashlib.sha256(profile).hexdigest()[:12]
        _write_once(
            workspace / "library" / "llm" / f"default-{digest}.json",
            profile,
            label="library default LLM profile",
        )
        console = workspace / SETTINGS / CONSOLE_FILE
        if _status(opened[SETTINGS], CONSOLE_FILE) == "missing":
            skeleton = {
                "workspace_root": str(workspace),
                "port": port,
                "browser_origin": f"http://127.0.0.1:{port}",
                "tasks": [],
            }
            _write_once(
                console, (json.dumps(skeleton, indent=2) + "\n").encode(), label="console.json"
            )
        else:
            resolved = resolve_console(config_bytes(str(console)))
            if resolved.settings.workspace_root == workspace:
                for task_id, field in resolved.settings.derived_task_fields():
                    if field in TASK_OUTPUT_PARENTS:
                        parent_name = TASK_OUTPUT_PARENTS[field]
                        os.close(
                            _ensure_directory(
                                opened[parent_name],
                                task_id,
                                f"{WORKSPACE_DIRECTORY}/{parent_name}/{task_id}",
                            )
                        )
    finally:
        for descriptor in opened.values():
            os.close(descriptor)
    return console
