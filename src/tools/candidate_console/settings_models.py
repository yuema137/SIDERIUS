"""Console file and global settings schemas around the strict console configuration.

``ConsoleConfig``/``TaskChoice`` (``models.py``) stay the single execution schema. The
file schema is generated from them, so every field keeps its owner's type and
constraints; only fields a ``siderius_workspace`` layout or the global settings file
can fill become optional, and the operator allowlists are added. The resolver fills
omitted fields and validates the result as an ordinary ``ConsoleConfig``.

The global settings file holds allowlist IDs and library refs only, never paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, create_model, model_validator
from pydantic.fields import FieldInfo

from tools.workflow_preview.models import PreviewModel

from .models import ConsoleConfig, TaskChoice

# Location facts a workspace layout can derive (§3.6). Content choices never are.
DERIVABLE_TASK_FIELDS = ("data_root", "preparation_root", "candidate_root", "reusable_runs_root")
# A content choice: filled only from console.json or the global settings file.
OPTIONAL_TASK_FIELDS = (*DERIVABLE_TASK_FIELDS, "llm_config_file")
DERIVABLE_CONSOLE_FIELDS = ("operation_store", "auth_token_file")


def _relaxed(
    model: type[PreviewModel], name: str, optional: tuple[str, ...], **overrides: Any
) -> type[PreviewModel]:
    model.model_rebuild()  # resolve the owner's forward references before copying fields
    fields: dict[str, Any] = {}
    for field, info in model.model_fields.items():
        if field in overrides:
            fields[field] = overrides.pop(field)
        elif field in optional:
            annotation: Any = info.annotation
            fields[field] = (annotation | None, None)
        else:
            fields[field] = (info.annotation, FieldInfo.merge_field_infos(info))
    fields.update(overrides)
    return create_model(name, __base__=PreviewModel, **fields)


Id = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")]
Label = Annotated[str, Field(min_length=1, max_length=160)]
WORKSPACE_DATA_ROOT = "workspace"  # reserved data root ID: <workspace_root>/data
SETTINGS_SCHEMA = "siderius.console-global-settings/v1"


class LLMProfileChoice(PreviewModel):
    """Operator-allowlisted LLM profile, referenced in place."""

    id: Id
    label: Label
    file: str


class AdviceFileChoice(PreviewModel):
    """Operator-allowlisted advice file in the CLI format, referenced in place."""

    id: Id
    label: Label
    file: str


class DataRootChoice(PreviewModel):
    """Operator-allowlisted data root; folders are chosen beneath it by relative subpath."""

    id: Id
    label: Label
    path: str


class GlobalSettingsPolicy(PreviewModel):
    browser_writable: bool = False


class AllowlistRef(PreviewModel):
    source: Literal["allowlist"] = "allowlist"
    id: Id


class LibraryRef(PreviewModel):
    source: Literal["library"] = "library"
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}-[0-9a-f]{12}\.json$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def name_carries_digest(self) -> LibraryRef:
        if not self.name.removesuffix(".json").endswith("-" + self.sha256[:12]):
            raise ValueError("library name must end with the first 12 digits of its sha256")
        return self


FileRef = Annotated[AllowlistRef | LibraryRef, Field(discriminator="source")]


class FolderRef(PreviewModel):
    """A folder beneath an allowlisted data root; never an absolute path."""

    root_id: Id
    subpath: str = Field(min_length=1, max_length=512)


class GlobalSettings(PreviewModel):
    schema_version: Literal["siderius.console-global-settings/v1"]
    llm_profile: FileRef | None = None
    advice: FileRef | None = None  # never applied to a run directly
    data_folders: dict[Id, FolderRef] = Field(default_factory=dict)  # keyed by task_id


TaskEntry = _relaxed(TaskChoice, "TaskEntry", OPTIONAL_TASK_FIELDS)
_TASKS: Any = tuple[TaskEntry, ...]
ConsoleFile = _relaxed(
    ConsoleConfig,
    "ConsoleFile",
    DERIVABLE_CONSOLE_FIELDS,
    tasks=(_TASKS, ()),
    workspace_root=(str | None, None),
    llm_profiles=(tuple[LLMProfileChoice, ...], ()),
    advice_files=(tuple[AdviceFileChoice, ...], ()),
    data_roots=(tuple[DataRootChoice, ...], ()),
    global_settings=(GlobalSettingsPolicy | None, None),
)
ALLOWLIST_FIELDS = ("llm_profiles", "advice_files", "data_roots", "global_settings")


@dataclass(frozen=True)
class Allowlists:
    llm_profiles: tuple[LLMProfileChoice, ...] = ()
    advice_files: tuple[AdviceFileChoice, ...] = ()
    data_roots: tuple[DataRootChoice, ...] = ()  # includes the derived "workspace" root


Origin = Literal["server_config", "global_settings", "workspace_layout"]


@dataclass(frozen=True)
class SettingsContext:
    """Presentation and readiness facts beside the strict config; never native input."""

    workspace_root: Path | None
    derived: frozenset[tuple[str | None, str]]  # (task_id or None, field) filled by the layout
    allowlists: Allowlists = Allowlists()
    policy: GlobalSettingsPolicy | None = None
    settings_path: Path | None = None  # None when no settings file is read
    settings: GlobalSettings | None = None  # active: loaded at startup
    settings_sha256: str | None = None
    from_settings: frozenset[tuple[str, str]] = frozenset()  # (task_id, field)
    console_path: Path | None = None  # the console.json this snapshot was loaded from

    def origin(self, task_id: str | None, field: str) -> Origin:
        if task_id is not None and (task_id, field) in self.from_settings:
            return "global_settings"
        return "workspace_layout" if (task_id, field) in self.derived else "server_config"

    def derived_task_fields(self) -> list[tuple[str, str]]:
        return sorted((task, field) for task, field in self.derived if task is not None)


@dataclass(frozen=True)
class ResolvedConsole:
    config: ConsoleConfig
    settings: SettingsContext
