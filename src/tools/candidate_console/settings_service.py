"""Settings page service: read view, compare-and-swap write and bounded folder listing.

The active configuration is the snapshot loaded at startup; a saved settings file
takes effect after a restart (OQ-2). The settings file is the only file the
browser changes, and only when console.json sets ``global_settings.browser_writable``.
"""

from __future__ import annotations

import hashlib
import os
import socket
import stat
import threading
from pathlib import Path

from tools.candidate_operations.models import OperationFailure

from .files import canonical, config_bytes, open_directory
from .models import ConsoleConfig
from .settings_file import (
    SettingsInvalid,
    advice_path,
    check_subpath,
    library_directory,
    read_settings,
)
from .settings_models import (
    AllowlistRef,
    FileRef,
    GlobalSettings,
    LibraryRef,
    ResolvedConsole,
    SettingsContext,
)
from .settings_views import (
    ChoiceCard,
    DataRootCard,
    FolderEntry,
    FolderListing,
    SettingRow,
    SettingsView,
    SettingsWrite,
    TaskCard,
)

MAX_LISTED = 200
SCAN_LIMIT = 4096  # directory entries examined per listing, as in operations listing


class SettingsRefusal(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _library_cards(workspace: Path | None, kind: str) -> tuple[ChoiceCard, ...]:
    """Regular files named ``<slug>-<sha12>.json`` whose bytes match their name."""
    if workspace is None:
        return ()
    directory = library_directory(workspace, kind)
    cards: list[ChoiceCard] = []
    try:
        descriptor = open_directory(directory)
    except OSError:
        return ()
    try:
        with os.scandir(descriptor) as entries:
            names = sorted(entry.name for entry in entries if entry.is_file(follow_symlinks=False))[
                :MAX_LISTED
            ]
    finally:
        os.close(descriptor)
    for name in names:
        try:
            digest = hashlib.sha256(config_bytes(str(directory / name))).hexdigest()
            ref = LibraryRef(name=name, sha256=digest)
        except (OSError, ValueError):
            continue  # not a library entry (wrong name, symlink swap or changed bytes)
        cards.append(ChoiceCard(label=name, ref=ref))
    return tuple(cards)


class ConsoleSettings:
    def __init__(self, config: ConsoleConfig, context: SettingsContext):
        self.config, self.context = config, context
        self._lock = threading.Lock()

    @property
    def writable(self) -> bool:
        policy = self.context.policy
        return policy is not None and policy.browser_writable

    def _pending(self) -> tuple[GlobalSettings | None, str | None]:
        path = self.context.settings_path
        if path is None:
            return None, None
        return read_settings(path)

    def _label(self, ref: FileRef | None, kind: str) -> str:
        if ref is None:
            return "None"
        if isinstance(ref, LibraryRef):
            return ref.name
        lists = self.context.allowlists
        choices = lists.llm_profiles if kind == "llm" else lists.advice_files
        return next((c.label for c in choices if c.id == ref.id), ref.id)

    def _rows(self) -> tuple[SettingRow, ...]:
        context, active = self.context, self.context.settings
        rows: list[SettingRow] = []
        advice = active.advice if active is not None else None
        rows.append(
            SettingRow(
                name="advice",
                task_id=None,
                origin="global_settings" if advice is not None else "server_config",
                label=self._label(advice, "advice"),
                effective=None
                if advice is None
                else str(advice_path(advice, context.allowlists, context.workspace_root)),
            )
        )
        roots = {root.path: root.label for root in context.allowlists.data_roots}
        for task in self.config.tasks:
            origin = context.origin(task.task_id, "llm_config_file")
            profile = active.llm_profile if active is not None else None
            label = (
                self._label(profile, "llm")
                if origin == "global_settings"
                else next(
                    (
                        p.label
                        for p in context.allowlists.llm_profiles
                        if p.file == task.llm_config_file
                    ),
                    "Set in console.json",
                )
            )
            rows.append(
                SettingRow(
                    name="llm_profile",
                    task_id=task.task_id,
                    origin=origin,
                    label=label,
                    effective=task.llm_config_file,
                )
            )
            for name in ("data_root", "preparation_root", "candidate_root", "reusable_runs_root"):
                value = getattr(task, name)
                folder_origin = context.origin(task.task_id, name)
                parent = str(Path(value).parent) if value is not None else None
                rows.append(
                    SettingRow(
                        name=name,
                        task_id=task.task_id,
                        origin=folder_origin,
                        label=roots.get(parent or "", "Workspace layout")
                        if folder_origin != "server_config"
                        else "Set in console.json",
                        effective=value,
                    )
                )
        return tuple(rows)

    def view(self) -> SettingsView:
        from .workspace import workspace_readiness

        pending, digest = self._pending()
        context = self.context
        lists = context.allowlists
        resolved = ResolvedConsole(self.config, context)
        return SettingsView(
            enabled=context.policy is not None,
            writable=self.writable,
            settings_sha256=digest,
            pending=pending,
            active=context.settings,
            active_sha256=context.settings_sha256,
            restart_required=digest != context.settings_sha256,
            rows=self._rows(),
            llm_profiles=(
                *(ChoiceCard(label=p.label, ref=AllowlistRef(id=p.id)) for p in lists.llm_profiles),
                *_library_cards(context.workspace_root, "llm"),
            ),
            advice_files=(
                *(ChoiceCard(label=a.label, ref=AllowlistRef(id=a.id)) for a in lists.advice_files),
                *_library_cards(context.workspace_root, "advice"),
            ),
            data_roots=tuple(DataRootCard(id=r.id, label=r.label) for r in lists.data_roots),
            tasks=tuple(
                TaskCard(
                    task_id=task.task_id,
                    label=task.label,
                    data_root_origin=context.origin(task.task_id, "data_root"),
                )
                for task in self.config.tasks
            ),
            workspace_root=None if context.workspace_root is None else str(context.workspace_root),
            workspace=workspace_readiness(resolved),
            host=socket.gethostname(),
        )

    def write(self, request: SettingsWrite) -> SettingsView:
        """CAS on the file's sha256, full validation, then one atomic 0600 publish."""
        from core.durable_io import publish_bytes_atomically

        from .config import validate_resolved
        from .workspace import resolve_console

        request = SettingsWrite.model_validate_json(request.model_dump_json())
        path, console = self.context.settings_path, self.context.console_path
        if not self.writable or path is None or console is None:
            raise SettingsRefusal(403, "read_only", "global settings are read-only on this console")
        payload = (request.settings.model_dump_json(indent=2) + "\n").encode()
        with self._lock:
            try:
                _, current = read_settings(path)
            except SettingsInvalid:
                current = "unreadable"
            if current != request.expected_sha256:
                raise SettingsRefusal(
                    409, "stale", "settings changed since they were loaded; reload"
                )
            try:
                candidate = resolve_console(config_bytes(str(console)), settings=request.settings)
                validate_resolved(candidate)
            except SettingsInvalid as error:
                raise SettingsRefusal(422, "settings_invalid", str(error)) from None
            except (OSError, ValueError):
                raise SettingsRefusal(
                    422, "settings_invalid", "settings fail console validation; run check"
                ) from None
            canonical(str(path.parent))
            publish_bytes_atomically(str(path), payload)
        return self.view()

    def folders(self, root_id: str, subpath: str, limit: int) -> FolderListing:
        """Direct child directory names under an allowlisted root; links shown, never followed."""
        if not 0 < limit <= MAX_LISTED:
            raise SettingsRefusal(422, "validation", f"limit must be between 1 and {MAX_LISTED}")
        roots = {root.id: root for root in self.context.allowlists.data_roots}
        if root_id not in roots:
            raise SettingsRefusal(404, "not_found", "data root is not configured")
        try:
            parts = check_subpath(subpath) if subpath else ()
            root = canonical(roots[root_id].path)
        except (SettingsInvalid, OperationFailure):
            raise SettingsRefusal(422, "validation", "folder subpath is not allowed") from None
        try:
            descriptor = open_directory(root)
        except OSError:
            raise SettingsRefusal(404, "not_found", "data root is unavailable") from None
        try:
            for part in parts:
                child = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                )
                os.close(descriptor)
                descriptor = child
            entries: list[FolderEntry] = []
            examined = 0
            with os.scandir(descriptor) as items:
                for item in items:
                    examined += 1
                    if examined > SCAN_LIMIT:
                        break
                    if item.is_symlink():
                        entries.append(FolderEntry(name=item.name, kind="link"))
                    elif stat.S_ISDIR(item.stat(follow_symlinks=False).st_mode):
                        entries.append(FolderEntry(name=item.name, kind="directory"))
        except OSError:
            raise SettingsRefusal(404, "not_found", "folder is unavailable") from None
        finally:
            os.close(descriptor)
        entries.sort(key=lambda entry: entry.name)
        return FolderListing(
            entries=tuple(entries[:limit]),
            incomplete=examined > SCAN_LIMIT or len(entries) > limit,
        )
