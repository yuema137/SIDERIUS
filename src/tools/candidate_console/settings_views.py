"""Browser payloads for the Settings page: names, labels, refs and resolved server paths.

Origins are presentation only; they never enter native requests, records or digests.
"""

from typing import Literal

from pydantic import Field

from tools.workflow_preview.models import PreviewModel

from .readiness_models import WorkspaceReadiness
from .settings_models import FileRef, GlobalSettings, Id, Origin

SettingName = Literal[
    "llm_profile", "advice", "data_root", "preparation_root", "candidate_root", "reusable_runs_root"
]


class SettingRow(PreviewModel):
    name: SettingName
    task_id: Id | None
    origin: Origin | Literal["not_set"]
    label: str  # allowlist label or library name; never file contents
    effective: str | None  # the resolved server path


class ChoiceCard(PreviewModel):
    label: str
    ref: FileRef


class DataRootCard(PreviewModel):
    id: Id
    label: str


class TaskCard(PreviewModel):
    task_id: Id
    label: str
    data_root_origin: Origin  # a console.json data_root is not editable here


class SettingsView(PreviewModel):
    enabled: bool  # console.json declares global_settings
    writable: bool
    settings_sha256: str | None  # revision of the file now on disk (pending)
    pending: GlobalSettings | None
    active: GlobalSettings | None  # loaded at startup; in effect until restart
    active_sha256: str | None
    restart_required: bool
    problem: str | None  # the settings file on disk cannot be used, and how to recover
    rows: tuple[SettingRow, ...]
    llm_profiles: tuple[ChoiceCard, ...]
    advice_files: tuple[ChoiceCard, ...]
    data_roots: tuple[DataRootCard, ...]
    tasks: tuple[TaskCard, ...]
    workspace_root: str | None
    workspace: WorkspaceReadiness | None
    host: str


class SettingsWrite(PreviewModel):
    expected_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")  # None only when absent
    settings: GlobalSettings


class FolderEntry(PreviewModel):
    name: str
    kind: Literal["directory", "link"]  # links are shown, never followed or selectable


class FolderListing(PreviewModel):
    """Mirrors ``OperationListing``: bounded, sorted, path-free."""

    entries: tuple[FolderEntry, ...]
    incomplete: bool
