"""Global settings layer: allowlist refs, folder refs and the browser-writable settings file.

The settings file holds IDs and refs only. Every ref resolves to a path that the
operator allowlisted in console.json or to a write-once file in the workspace
library; a folder is ``(root_id, relative subpath)`` beneath an allowlisted root.
Certification reuses owners: ``files.config_bytes``/``private_bytes`` (bounded,
no-follow), ``parse_llm_config_bytes`` for LLM profiles, and the preparation
reader ``safe_bytes`` with ``parse_advice_bytes`` for advice. Errors name the
field or ref, never a path or file content.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import ValidationError

from tools.candidate_operations.models import OperationFailure

from .files import canonical, config_bytes, private_bytes
from .models import ConsoleConfig
from .settings_models import (
    SETTINGS_SCHEMA,
    WORKSPACE_DATA_ROOT,
    AdviceFileChoice,
    AllowlistRef,
    Allowlists,
    DataRootChoice,
    FileRef,
    FolderRef,
    GlobalSettings,
    LibraryRef,
    LLMProfileChoice,
    ResolvedConsole,
)

SETTINGS_FILE = "global_settings.json"


class SettingsInvalid(ValueError):
    """Console settings fail a named predicate; the message names fields or IDs only."""


class MissingSetting(SettingsInvalid):
    """A required console field has no source; the message names fields, never values."""


def settings_path(workspace: Path) -> Path:
    return workspace / "settings" / SETTINGS_FILE


def library_directory(workspace: Path, kind: str) -> Path:
    return workspace / "library" / kind


def read_settings(path: Path) -> tuple[GlobalSettings | None, str | None]:
    """Return the settings and their sha256 revision; an absent file is ``(None, None)``."""
    try:
        payload = private_bytes(str(path))
    except FileNotFoundError:
        return None, None
    except (OSError, OperationFailure) as error:
        raise SettingsInvalid(
            "global settings file must be a private regular file (mode 600)"
        ) from error
    try:
        settings = GlobalSettings.model_validate_json(payload)
    except ValidationError as error:
        raise SettingsInvalid(
            f"global settings file is not valid {SETTINGS_SCHEMA} JSON at {invalid_fields(error, payload)}"
        ) from None
    return settings, hashlib.sha256(payload).hexdigest()


def _schema_names() -> frozenset[str]:
    names: set[str] = {"allowlist", "library"}  # FileRef discriminator tags
    for model in (GlobalSettings, AllowlistRef, LibraryRef, FolderRef):
        names.update(model.model_fields)
    return frozenset(names)


MAPPING_FIELDS = frozenset({"data_folders"})  # values keyed by file-supplied task IDs


def _entry_index(payload: bytes | None, field: str, key: object) -> str:
    """Position of a mapping entry in the file, so several entries are told apart."""
    import json

    if payload is None:
        return ".<key>"
    try:
        return f"[{list(json.loads(payload)[field]).index(key)}]"
    except (ValueError, TypeError, KeyError):
        return ".<key>"


def invalid_fields(error: ValidationError, payload: bytes | None = None) -> str:
    """Field locations only (Pydantic ``loc``), never offending values or file text.

    A segment in the schema vocabulary (field names, ``FileRef`` tags, list
    indexes and Pydantic's constant ``[key]`` token for a bad mapping key) is
    shown verbatim. A mapping key under ``data_folders`` is shown by its position
    in the file (``data_folders[2].subpath``); any other segment is ``<key>``.
    """
    known = _schema_names()
    locations: set[str] = set()
    for item in error.errors():
        text, previous = "", None
        for part in item["loc"]:
            if previous in MAPPING_FIELDS:
                text += _entry_index(payload, previous, part)
            elif isinstance(part, int):
                text += f"[{part}]"
            else:
                segment = part if part in known or part == "[key]" else "<key>"
                text += ("." if text else "") + segment
            previous = part
        locations.add(text or "(document)")
    return ", ".join(sorted(locations)[:5])


def allowlists(
    llm_profiles: tuple[LLMProfileChoice, ...],
    advice_files: tuple[AdviceFileChoice, ...],
    data_roots: tuple[DataRootChoice, ...],
    workspace: Path | None,
) -> Allowlists:
    for name, items in (
        ("llm_profiles", llm_profiles),
        ("advice_files", advice_files),
        ("data_roots", data_roots),
    ):
        if len({item.id for item in items}) != len(items):
            raise SettingsInvalid(f"{name} IDs must be unique")
    if any(root.id == WORKSPACE_DATA_ROOT for root in data_roots):
        raise SettingsInvalid(f"data_roots ID {WORKSPACE_DATA_ROOT!r} is reserved")
    if workspace is not None:
        data_roots = (
            *data_roots,
            DataRootChoice(
                id=WORKSPACE_DATA_ROOT, label="Workspace data", path=str(workspace / "data")
            ),
        )
    return Allowlists(llm_profiles, advice_files, data_roots)


def _ref_path(ref: FileRef, kind: str, lists: Allowlists, workspace: Path | None) -> Path:
    field = "llm_profile" if kind == "llm" else "advice"
    if isinstance(ref, LibraryRef):
        if workspace is None:
            raise SettingsInvalid(f"global settings {field} library ref requires workspace_root")
        return library_directory(workspace, kind) / ref.name
    choices = lists.llm_profiles if kind == "llm" else lists.advice_files
    for choice in choices:
        if choice.id == ref.id:
            return Path(choice.file)
    allowlist = "llm_profiles" if kind == "llm" else "advice_files"
    raise SettingsInvalid(f"global settings {field} names unknown {allowlist} ID {ref.id!r}")


def llm_profile_path(ref: FileRef, lists: Allowlists, workspace: Path | None) -> Path:
    return _ref_path(ref, "llm", lists, workspace)


def advice_path(ref: FileRef, lists: Allowlists, workspace: Path | None) -> Path:
    return _ref_path(ref, "advice", lists, workspace)


def check_subpath(subpath: str) -> tuple[str, ...]:
    """Syntax only: relative, no empty, ``.``/``..`` or NUL segment, at most 512 bytes."""
    parts = tuple(subpath.split("/"))
    if (
        len(subpath.encode()) > 512
        or "\0" in subpath
        or subpath.startswith("/")
        or any(part in ("", ".", "..") for part in parts)
    ):
        raise SettingsInvalid(
            "folder subpath must be a relative path without '.', '..' or empty parts"
        )
    return parts


def resolve_folder(ref: FolderRef, lists: Allowlists, *, label: str) -> Path:
    """Join a checked subpath to its allowlisted root; the result is a canonical directory."""
    roots = {root.id: root for root in lists.data_roots}
    if ref.root_id not in roots:
        raise SettingsInvalid(f"{label} names unknown data root ID {ref.root_id!r}")
    parts = check_subpath(ref.subpath)
    try:
        root = canonical(roots[ref.root_id].path)
        folder = canonical(str(root.joinpath(*parts)))
    except (OSError, OperationFailure):
        raise SettingsInvalid(f"{label} must be canonical, without symlinks") from None
    if not folder.is_relative_to(root) or not folder.is_dir():
        raise SettingsInvalid(f"{label} is not a directory under its data root")
    return folder


# Certification --------------------------------------------------------------------------


def _llm_bytes(path: Path, *, label: str) -> bytes:
    from workflows.llm_config import parse_llm_config_bytes

    try:
        payload = config_bytes(str(path))
        parse_llm_config_bytes(payload)
    except (OSError, ValueError) as error:
        raise SettingsInvalid(f"{label} is not a readable, valid LLM profile") from error
    return payload


def advice_bytes(path: Path, *, label: str) -> bytes:
    """The preparation reader (canonical, no-follow, regular, bounded) plus the advice owner."""
    from tools.candidate_prepare.reusable_admission import safe_bytes
    from workflows.advice import AdviceArtifactError, parse_advice_bytes

    try:
        payload = safe_bytes(path)
    except (OSError, ValueError) as error:
        raise SettingsInvalid(f"{label} is not a readable regular file") from error
    try:
        parse_advice_bytes(payload, label=label)
    except AdviceArtifactError as error:
        raise SettingsInvalid(str(error)) from None
    return payload


def _check_digest(ref: FileRef, payload: bytes, *, label: str) -> None:
    if isinstance(ref, LibraryRef) and hashlib.sha256(payload).hexdigest() != ref.sha256:
        raise SettingsInvalid(f"{label} library file does not match its recorded sha256")


def protected_paths(config: ConsoleConfig, workspace: Path | None = None) -> tuple[Path, ...]:
    """Paths no read-only data folder may contain or lie inside."""
    store = config.operation_store
    paths = [
        Path(config.auth_token_file),
        Path(store.state_root),
        *map(Path, (*store.preparation_roots, *store.candidate_roots)),
    ]
    if config.credential_file is not None:
        paths.append(Path(config.credential_file))
    for task in config.tasks:
        paths += [Path(task.preparation_root), Path(task.candidate_root)]
        if task.reusable_runs_root is not None:
            paths.append(Path(task.reusable_runs_root))
    if workspace is not None:
        paths += [workspace / "settings", workspace / "library"]
    return tuple(dict.fromkeys(paths))


def validate_settings(resolved: ResolvedConsole) -> None:
    """Certify every allowlist entry and the active settings refs; no writes."""
    from tools.candidate_prepare.admission import validate_read_only_exclusion

    context = resolved.settings
    lists = context.allowlists
    for profile in lists.llm_profiles:
        _llm_bytes(Path(profile.file), label=f"llm_profiles {profile.id}")
    for advice in lists.advice_files:
        advice_bytes(Path(advice.file), label=f"advice_files {advice.id}")
    protected = protected_paths(resolved.config, context.workspace_root)
    for root in lists.data_roots:
        try:
            path = canonical(root.path)
        except (OSError, OperationFailure):
            raise SettingsInvalid(f"data_roots {root.id} must be canonical") from None
        if not path.is_dir():
            raise SettingsInvalid(f"data_roots {root.id} is not a directory")
        try:
            validate_read_only_exclusion((path,), protected)
        except ValueError:
            raise SettingsInvalid(
                f"data_roots {root.id} overlaps a protected console path"
            ) from None
    settings = context.settings
    if settings is None:
        return
    # Every folder ref fails closed, including ones console.json overrides (OQ-4).
    for task_id, folder in settings.data_folders.items():
        label = f"data folder for task {task_id}"
        path = resolve_folder(folder, lists, label=label)
        try:
            validate_read_only_exclusion((path,), protected)
        except ValueError:
            raise SettingsInvalid(f"{label} overlaps a protected console path") from None
    if settings.llm_profile is not None:
        path = llm_profile_path(settings.llm_profile, lists, context.workspace_root)
        payload = _llm_bytes(path, label="global settings llm_profile")
        _check_digest(settings.llm_profile, payload, label="global settings llm_profile")
    if settings.advice is not None:
        path = advice_path(settings.advice, lists, context.workspace_root)
        payload = advice_bytes(path, label="global settings advice")
        _check_digest(settings.advice, payload, label="global settings advice")
