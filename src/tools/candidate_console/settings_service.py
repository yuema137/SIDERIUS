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

from pydantic import ValidationError

from tools.candidate_operations.models import OperationFailure

from .files import canonical, config_bytes, open_directory, private_bytes, write_all
from .models import ConsoleConfig
from .settings_export import (
    ExportFile,
    ExportRefused,
    ExportRequest,
    ExportResult,
    download,
    export,
)
from .settings_file import (
    SettingsInvalid,
    advice_path,
    check_subpath,
    invalid_fields,
    library_directory,
)
from .settings_library import (
    LibraryRefused,
    LibraryUpload,
    advice_card,
    profile_card,
    store,
)
from .settings_models import (
    SETTINGS_SCHEMA,
    AllowlistRef,
    FileRef,
    GlobalSettings,
    LibraryRef,
    ResolvedConsole,
    SettingsContext,
)
from .settings_views import (
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


def _library_entries(workspace: Path | None, kind: str) -> tuple[tuple[LibraryRef, Path], ...]:
    """Regular files named ``<slug>-<sha12>.json`` whose bytes match their name."""
    if workspace is None:
        return ()
    directory = library_directory(workspace, kind)
    cards: list[tuple[LibraryRef, Path]] = []
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
        cards.append((ref, directory / name))
    return tuple(cards)


def _publish_private(path: Path, payload: bytes) -> bool:
    """Atomic 0600 replace inside a parent opened with no-follow descriptors.

    Temp file (complete write) + fsync + ``os.replace`` relative to that descriptor,
    so a swapped parent link cannot redirect the write (design §5.1). On any failure
    before the replace, the temp file this call created is removed and the previous
    file is untouched; a failed removal is recorded as a note on the original
    exception, which is re-raised. Returns ``False`` when the file was replaced but
    the directory fsync failed, so the new file is in place but its durability is
    not confirmed.
    """
    import secrets

    directory = open_directory(canonical(str(path.parent)))
    temporary = f".{path.name}.{secrets.token_hex(8)}.tmp"
    try:
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory
        )
        try:
            try:
                os.fchmod(descriptor, 0o600)
                write_all(descriptor, payload)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
        except BaseException as error:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
            except OSError as cleanup:
                error.add_note(
                    f"temporary file {temporary} could not be removed: {cleanup.strerror}"
                )
            raise
        try:
            os.fsync(directory)
        except OSError:
            return False
        return True
    finally:
        os.close(directory)


class ConsoleSettings:
    def __init__(self, config: ConsoleConfig, context: SettingsContext):
        self.config, self.context = config, context
        self._lock = threading.Lock()

    @property
    def writable(self) -> bool:
        policy = self.context.policy
        return policy is not None and policy.browser_writable

    def _pending(self) -> tuple[GlobalSettings | None, str | None, str | None]:
        """(settings, sha256 of the bytes on disk, problem sentence) for the file now on disk.

        A readable but invalid file keeps its digest, so an explicit Save can replace
        it under the same compare-and-swap; an unreadable file has no digest.
        """
        path = self.context.settings_path
        if path is None:
            return None, None, None
        try:
            payload = private_bytes(str(path))
        except FileNotFoundError:
            return None, None, None
        except (OSError, OperationFailure):
            return (
                None,
                None,
                (
                    "settings/global_settings.json cannot be read: it must be a regular file "
                    "owned by you with mode 600. Run chmod 600 on it (or restore it), then Reload."
                ),
            )
        digest = hashlib.sha256(payload).hexdigest()
        try:
            return GlobalSettings.model_validate_json(payload), digest, None
        except ValidationError as error:
            return (
                None,
                digest,
                (
                    f"settings/global_settings.json is not valid {SETTINGS_SCHEMA} JSON at "
                    f"{invalid_fields(error, payload)}. Fix or "
                    "restore the file and Reload, or choose values here and Save to replace it."
                ),
            )

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
                origin="global_settings" if advice is not None else "not_set",
                label=self._label(advice, "advice"),
                effective=None
                if advice is None
                else str(advice_path(advice, context.allowlists, context.workspace_root)),
            )
        )
        roots = {root.id: root.label for root in context.allowlists.data_roots}
        folders = active.data_folders if active is not None else {}
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
                folder = folders.get(task.task_id) if name == "data_root" else None
                label = {
                    "server_config": "Set in console.json",
                    "workspace_layout": "Workspace layout",
                }.get(folder_origin, "")
                if folder_origin == "global_settings" and folder is not None:
                    label = f"{roots.get(folder.root_id, folder.root_id)} / {folder.subpath}"
                rows.append(
                    SettingRow(
                        name=name,
                        task_id=task.task_id,
                        origin=folder_origin,
                        label=label,
                        effective=value,
                    )
                )
        return tuple(rows)

    def view(self) -> SettingsView:
        from .workspace import workspace_readiness

        pending, digest, problem = self._pending()
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
            restart_required=problem is None and digest != context.settings_sha256,
            problem=problem,
            rows=self._rows(),
            llm_profiles=(
                *(
                    profile_card(p.label, AllowlistRef(id=p.id), Path(p.file))
                    for p in lists.llm_profiles
                ),
                *(
                    profile_card(ref.name, ref, path)
                    for ref, path in _library_entries(context.workspace_root, "llm")
                ),
            ),
            advice_files=(
                *(
                    advice_card(a.label, AllowlistRef(id=a.id), Path(a.file))
                    for a in lists.advice_files
                ),
                *(
                    advice_card(ref.name, ref, path)
                    for ref, path in _library_entries(context.workspace_root, "advice")
                ),
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
        from .config import validate_resolved
        from .workspace import resolve_console

        request = SettingsWrite.model_validate_json(request.model_dump_json())
        path, console = self.context.settings_path, self.context.console_path
        if not self.writable or path is None or console is None:
            raise SettingsRefusal(403, "read_only", "global settings are read-only on this console")
        payload = (request.settings.model_dump_json(indent=2) + "\n").encode()
        with self._lock:
            _, current, problem = self._pending()
            if problem is not None and current is None:
                raise SettingsRefusal(422, "settings_unreadable", problem)
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
            try:
                durable = _publish_private(path, payload)
            except (OSError, OperationFailure) as error:
                leftover = any(
                    "could not be removed" in note for note in getattr(error, "__notes__", ())
                )
                raise SettingsRefusal(
                    422,
                    "settings_invalid",
                    "the settings folder is unavailable or contains a link; nothing was saved"
                    + ("; a temporary file may remain in settings/" if leftover else ""),
                ) from None
        view = self.view()
        if durable:
            return view
        return view.model_copy(
            update={
                "notice": "Saved, but the server could not confirm the save is on disk; "
                "save again or check the disk before restarting."
            }
        )

    def upload(self, upload: LibraryUpload) -> LibraryRef:
        """Validate, then publish once into the workspace library; never replaces a file."""
        workspace = self.context.workspace_root
        if not self.writable or workspace is None:
            raise SettingsRefusal(403, "read_only", "global settings are read-only on this console")
        with self._lock:
            try:
                return store(workspace, upload)
            except LibraryRefused as error:
                raise SettingsRefusal(error.status, error.code, error.message) from None

    def export(self, request: ExportRequest) -> ExportResult:
        """Write-once native-format export under the workspace; never overwrites."""
        workspace = self.context.workspace_root
        if not self.writable or workspace is None:
            raise SettingsRefusal(403, "read_only", "global settings are read-only on this console")
        try:
            return export(self.config, workspace, request)
        except ExportRefused as error:
            raise SettingsRefusal(error.status, error.code, error.message) from None

    def download(self, name: str, file: ExportFile) -> bytes:
        workspace = self.context.workspace_root
        if workspace is None:
            raise SettingsRefusal(404, "not_found", "export is unavailable")
        try:
            return download(workspace, name, file)
        except ExportRefused as error:
            raise SettingsRefusal(error.status, error.code, error.message) from None

    def folders(self, root_id: str, subpath: str, limit: int) -> FolderListing:
        """Direct child directory names under an allowlisted root; links shown, never followed."""
        if not 0 < limit <= MAX_LISTED:
            raise SettingsRefusal(422, "validation", f"limit must be between 1 and {MAX_LISTED}")
        roots = {root.id: root for root in self.context.allowlists.data_roots}
        if root_id not in roots:
            raise SettingsRefusal(404, "not_found", "data root is not configured")
        try:
            parts = check_subpath(subpath) if subpath else ()
        except SettingsInvalid:
            raise SettingsRefusal(422, "validation", "folder subpath is not allowed") from None
        try:
            root = canonical(roots[root_id].path)
        except OperationFailure:
            raise SettingsRefusal(
                409,
                "root_changed",
                "this data root now contains a link or moved; point console.json data_roots "
                "at the real folder and restart",
            ) from None
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
