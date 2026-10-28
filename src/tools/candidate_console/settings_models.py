"""Console file schema: the strict console configuration with layout-derivable fields optional.

``ConsoleConfig``/``TaskChoice`` (``models.py``) stay the single execution schema. The
file schema is generated from them, so every field keeps its owner's type and
constraints; only the location fields a ``siderius_workspace`` layout can derive
become optional. The resolver fills omitted fields and validates the result as an
ordinary ``ConsoleConfig``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import create_model
from pydantic.fields import FieldInfo

from tools.workflow_preview.models import PreviewModel

from .models import ConsoleConfig, TaskChoice

# Location facts a workspace layout can derive (§3.6). Content choices never are.
DERIVABLE_TASK_FIELDS = ("data_root", "preparation_root", "candidate_root", "reusable_runs_root")
# Required content choice; omission is refused by name until a settings layer exists.
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


TaskEntry = _relaxed(TaskChoice, "TaskEntry", OPTIONAL_TASK_FIELDS)
_TASKS: Any = tuple[TaskEntry, ...]
ConsoleFile = _relaxed(
    ConsoleConfig,
    "ConsoleFile",
    DERIVABLE_CONSOLE_FIELDS,
    tasks=(_TASKS, ()),
    workspace_root=(str | None, None),
)


@dataclass(frozen=True)
class SettingsContext:
    """Presentation and readiness facts beside the strict config; never native input."""

    workspace_root: Path | None
    derived: frozenset[tuple[str | None, str]]  # (task_id or None, field) filled by the layout

    def derived_task_fields(self) -> list[tuple[str, str]]:
        return sorted((task, field) for task, field in self.derived if task is not None)


@dataclass(frozen=True)
class ResolvedConsole:
    config: ConsoleConfig
    settings: SettingsContext
