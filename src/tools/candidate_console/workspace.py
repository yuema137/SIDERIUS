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
import shlex
import stat
from collections.abc import Iterator
from pathlib import Path

from pydantic import ValidationError

from .files import canonical, config_bytes, open_directory, require_owner_only_file, write_all
from .readiness_models import WorkspaceEntry, WorkspaceReadiness, WorkspaceStatus
from .settings_file import (
    SETTINGS_FILE,
    MissingSetting,
    SettingsInvalid,
    allowlists,
    llm_profile_path,
    read_settings,
    resolve_folder,
    settings_path,
)
from .settings_models import (
    SETTINGS_SCHEMA,
    AdviceFileChoice,
    ConsoleFile,
    DataRootChoice,
    ExperimentSetupsPolicy,
    GlobalSettings,
    GlobalSettingsPolicy,
    LibraryRef,
    LLMProfileChoice,
    ResolvedConsole,
    SettingsContext,
)

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
    "tasks",
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


class WorkspaceRefused(ValueError):
    """``init`` found a directory or file it must not use; nothing was deleted."""


class CredentialFileNotAdded(WorkspaceRefused):
    """``init --credential-file`` met an existing console.json it never rewrites.

    ``member`` is the exact top-level JSON member (no trailing comma) the operator
    adds or substitutes; ``replaces`` says whether a different value exists.
    """

    def __init__(self, member: str, *, config_path: Path, replaces: bool) -> None:
        super().__init__("settings/console.json was left unchanged")
        self.member = member
        self.config_path = config_path
        self.replaces = replaces


def init_command(workspace_root: Path) -> str:
    return ".venv/bin/python -m tools.candidate_console init --workspace " + str(
        workspace_root.parent
    )


# Resolution ------------------------------------------------------------------------


def resolve_console(payload: bytes, *, settings: GlobalSettings | None = None) -> ResolvedConsole:
    """Fill omitted fields: console.json, then the global settings file, then the layout.

    ``settings`` replaces the settings file's content (a candidate write is resolved
    before it is published). The result is typed but not yet filesystem-validated.
    """
    from .models import ConsoleConfig

    document = ConsoleFile.model_validate_json(payload).model_dump(mode="json", exclude_unset=True)
    value = document.pop("workspace_root", None)
    workspace = None if value is None else canonical(value)
    lists = allowlists(
        tuple(LLMProfileChoice.model_validate(item) for item in document.pop("llm_profiles", [])),
        tuple(AdviceFileChoice.model_validate(item) for item in document.pop("advice_files", [])),
        tuple(DataRootChoice.model_validate(item) for item in document.pop("data_roots", [])),
        workspace,
    )
    policy_value = document.pop("global_settings", None)
    policy = None if policy_value is None else GlobalSettingsPolicy.model_validate(policy_value)
    setups_value = document.pop("experiment_setups", None)
    setups_policy = (
        None if setups_value is None else ExperimentSetupsPolicy.model_validate(setups_value)
    )
    if setups_policy is not None and workspace is None:
        raise SettingsInvalid("experiment_setups requires workspace_root")
    path = digest = None
    if policy is not None:
        if workspace is None:
            raise SettingsInvalid("global_settings requires workspace_root")
        path = settings_path(workspace)
        if settings is None:
            settings, digest = read_settings(path)
    elif settings is not None:
        raise SettingsInvalid("global settings are not enabled in console.json")
    derived: set[tuple[str | None, str]] = set()
    from_settings: set[tuple[str, str]] = set()
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
    tasks = document.get("tasks", [])
    if settings is not None:
        unknown = sorted(set(settings.data_folders) - {task["task_id"] for task in tasks})
        if unknown:
            raise SettingsInvalid(f"global settings data folder names unknown task {unknown[0]!r}")
    for task in tasks:
        task_id = task["task_id"]
        if settings is not None:
            if task.get("llm_config_file") is None and settings.llm_profile is not None:
                profile = llm_profile_path(settings.llm_profile, lists, workspace)
                task["llm_config_file"] = str(profile)
                from_settings.add((task_id, "llm_config_file"))
            folder = settings.data_folders.get(task_id)
            if task.get("data_root") is None and folder is not None:
                label = f"data folder for task {task_id}"
                task["data_root"] = str(resolve_folder(folder, lists, label=label))
                from_settings.add((task_id, "data_root"))
        for field, parent in TASK_PARENTS.items():
            # An explicit null reusable_runs_root keeps reusable runs disabled.
            explicit = field in task and (field == "reusable_runs_root" or task[field] is not None)
            if workspace is not None and not explicit:
                task[field] = str(workspace / parent / task_id)
                derived.add((task_id, field))
        for field in ("data_root", "preparation_root", "candidate_root"):
            if task.get(field) is None:
                raise MissingSetting(
                    f"task {task_id} needs {field} (set it in console.json, global settings "
                    "or workspace_root)"
                )
        if task.get("llm_config_file") is None:
            raise MissingSetting(
                f"task {task_id} needs llm_config_file (set it in console.json or global settings)"
            )
    config = ConsoleConfig.model_validate_json(json.dumps(document))
    context = SettingsContext(
        workspace_root=workspace,
        derived=frozenset(derived),
        allowlists=lists,
        policy=policy,
        settings_path=path,
        settings=settings,
        settings_sha256=digest,
        from_settings=frozenset(from_settings),
        setups_policy=setups_policy,
    )
    return ResolvedConsole(config, context)


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
    directory = open_directory(path)
    try:
        yield directory
    finally:
        os.close(directory)


def _refused_status(error: OSError) -> WorkspaceStatus:
    """Map an open/stat failure: not found is ``missing``; anything else is not usable."""
    if isinstance(error, FileNotFoundError):
        return "missing"
    if error.errno == errno.ELOOP:
        return "symlink"
    if error.errno == errno.ENOTDIR:
        return "not_directory"
    return "unreadable"


def _status(directory: int, name: str, *, owned: bool = True) -> WorkspaceStatus:
    try:
        metadata = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except OSError as error:
        return _refused_status(error)
    if stat.S_ISLNK(metadata.st_mode):
        return "symlink"
    if not stat.S_ISDIR(metadata.st_mode):
        return "not_directory"
    if owned and (metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o022):
        return "not_owner"
    return "present"


def ensure_owned_directory(
    directory: int, name: str, label: str, *, remedy: Path | None = None
) -> int:
    """Open/create a private directory; suggest chmod only for an absolute remedy path."""
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
    metadata = os.fstat(child)
    if metadata.st_uid != os.getuid():
        os.close(child)
        raise WorkspaceRefused(
            f"{label} is owned by uid {metadata.st_uid}, not you; choose a folder you own"
        )
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        os.close(child)
        message = f"{label} must not have group/other write permissions"
        if remedy is not None and remedy.is_absolute():
            message += f"; fix it with: chmod 700 {shlex.quote(str(remedy))}"
        raise WorkspaceRefused(message)
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
    except OSError as error:
        root_status = _refused_status(error)
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
    try:
        child = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
    except OSError as error:
        return _refused_status(error)
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
        if _existing_file(path, label=label) != payload:
            raise WorkspaceRefused(
                f"{label} exists with different content; left unchanged"
            ) from None


def _existing_file(path: Path, *, label: str) -> bytes:
    try:
        return config_bytes(str(path))
    except (OSError, ValueError):
        raise WorkspaceRefused(
            f"{label} must be a regular file you can read, not a symlink; left unchanged"
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
        write_all(descriptor, secrets.token_urlsafe(32).encode())
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def init_workspace(
    parent: str, *, port: int = DEFAULT_PORT, credential_file: str | None = None
) -> Path:
    """Create missing fixed folders, token, default LLM profile and console.json skeleton.

    Returns the console.json path. Re-running is safe: existing items are checked,
    never replaced. With an existing console.json, the derived per-task output roots
    of its tasks are created too (never ``data/<task_id>``).

    ``credential_file`` must be a canonical owner-only (mode 600) regular file; only
    its metadata is checked. A new console.json records it as the top-level
    ``credential_file``. An existing console.json naming another (or no) credential
    file is never rewritten: after creating the folders (including per-task output
    roots), ``CredentialFileNotAdded`` carries the exact member to add or substitute.
    """
    if not 1024 <= port <= 65535:
        raise WorkspaceRefused("port must be between 1024 and 65535")
    if credential_file is not None:
        try:
            require_owner_only_file(credential_file)
        except (OSError, ValueError):  # OperationFailure is a ValueError
            raise WorkspaceRefused(
                "--credential-file is refused unless it is a regular file you own with mode 600 "
                "(chmod 600 FILE), given as an absolute path without symlinks; "
                "its contents were not read"
            ) from None
    try:
        base = canonical(parent)
        if not base.is_dir():
            raise NotADirectoryError(parent)
    except (OSError, ValueError):
        raise WorkspaceRefused(
            "--workspace must be an existing canonical directory without symlinks"
        ) from None
    workspace = base / WORKSPACE_DIRECTORY
    # A restrictive umask must not leave unusable (mode 000) folders: mkdir modes
    # are 0700 under a 077 umask, and created folders are fchmod-ed to 0700 too.
    previous = os.umask(0o077)
    try:
        return _init(base, workspace, port, credential_file)
    finally:
        os.umask(previous)


def _init(base: Path, workspace: Path, port: int, credential_file: str | None) -> Path:
    import hashlib

    with _open_directory(base) as directory:
        metadata = os.fstat(directory)
        if not stat.S_ISDIR(metadata.st_mode):
            raise WorkspaceRefused(f"workspace parent {base} is not a directory")
        if metadata.st_uid != os.getuid():
            raise WorkspaceRefused(
                f"workspace parent {base} is owned by uid {metadata.st_uid}, not you; "
                "choose a folder you own"
            )
        if stat.S_IMODE(metadata.st_mode) & 0o022:
            raise WorkspaceRefused(
                f"workspace parent {base} must not be writable by group or others; "
                f"fix it with: chmod 700 {shlex.quote(str(base))}"
            )
        root = ensure_owned_directory(
            directory, WORKSPACE_DIRECTORY, str(workspace), remedy=workspace
        )
    opened = {"": root}
    try:
        for name in INIT_CHILDREN:
            above, _, leaf = name.rpartition("/")
            opened[name] = ensure_owned_directory(
                opened[above], leaf, str(workspace / name), remedy=workspace / name
            )
        _create_token(opened[SETTINGS])
        profile = _default_llm_profile()
        digest = hashlib.sha256(profile).hexdigest()[:12]
        _write_once(
            workspace / "library" / "llm" / f"default-{digest}.json",
            profile,
            label="library default LLM profile",
        )
        if _status(opened[SETTINGS], SETTINGS_FILE) == "missing":
            default = LibraryRef(
                name=f"default-{digest}.json", sha256=hashlib.sha256(profile).hexdigest()
            )
            selection = GlobalSettings(schema_version=SETTINGS_SCHEMA, llm_profile=default)
            _write_once(
                settings_path(workspace),
                (selection.model_dump_json(indent=2) + "\n").encode(),
                label="global settings",
            )
        console = workspace / SETTINGS / CONSOLE_FILE
        if _status(opened[SETTINGS], CONSOLE_FILE) == "missing":
            skeleton = {
                "workspace_root": str(workspace),
                "port": port,
                "browser_origin": f"http://127.0.0.1:{port}",
                "tasks": [],
                "global_settings": {"browser_writable": True},
                "experiment_setups": {"browser_creatable": True},
            }
            if credential_file is not None:
                skeleton["credential_file"] = credential_file
            _write_once(
                console, (json.dumps(skeleton, indent=2) + "\n").encode(), label="console.json"
            )
        else:
            payload = _existing_file(console, label="settings/console.json")
            try:
                resolved = resolve_console(payload)
            except (SettingsInvalid, ValidationError):
                raise  # names its own field or predicate (MissingSetting included)
            except ValueError:
                raise WorkspaceRefused(
                    "settings/console.json is not a valid console configuration; left unchanged"
                ) from None
            if resolved.settings.workspace_root == workspace:
                for task_id, field in resolved.settings.derived_task_fields():
                    if field in TASK_OUTPUT_PARENTS:
                        parent_name = TASK_OUTPUT_PARENTS[field]
                        os.close(
                            ensure_owned_directory(
                                opened[parent_name],
                                task_id,
                                str(workspace / parent_name / task_id),
                                remedy=workspace / parent_name / task_id,
                            )
                        )
            existing = resolved.config.credential_file
            if credential_file is not None and existing != credential_file:
                raise CredentialFileNotAdded(
                    f'"credential_file": {json.dumps(credential_file)}',
                    config_path=console,
                    replaces=existing is not None,
                )
    finally:
        for descriptor in opened.values():
            os.close(descriptor)
    return console
