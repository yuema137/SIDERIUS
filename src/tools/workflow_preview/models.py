"""Inputs and observation-only output for a single candidate chain."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tools.setup_review.route_models import LLMRoute
from workflows.definition import WorkflowDocument


class PreviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class WorkflowPreviewRequest(PreviewModel):
    document: WorkflowDocument
    execution_profile: Literal["native-proposal-fanout/v1"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    project_root: str
    llm_config_file: str | None = None

    @field_validator("project_root")
    @classmethod
    def absolute_project(cls, value: str) -> str:
        if "\0" in value or not Path(value).is_absolute():
            raise ValueError("project_root must be an explicit absolute directory")
        return value

    @field_validator("llm_config_file")
    @classmethod
    def local_config(cls, value: str | None) -> str | None:
        if value is not None and (not value or "\0" in value):
            raise ValueError("llm_config_file must be a nonempty local path")
        return value


class FileObservation(PreviewModel):
    """Digest of captured bytes, not a task fingerprint or execution lock."""

    reference: str
    path: str
    sha256: str
    size_bytes: int


class WorkflowBindings(PreviewModel):
    """Inert input observations; does not admit or inspect workspace lifecycle."""

    project_root: str
    data_root: str
    workspace: str
    files: tuple[FileObservation, ...]
    config_source: Literal["workflow_default", "explicit_file"]
    selected_constructor_routes: tuple[LLMRoute, ...]
    inactive_roles: tuple[str, ...]


class WorkflowPreview(WorkflowBindings):
    status: Literal["bindings_observed"] = "bindings_observed"
    execution_ready: Literal[False] = False
    workspace_state: Literal["absent", "empty"]
    pending_checks: tuple[str, ...] = (
        "Native external payload validation and reconciliation with selected routes, task and storage",
        "Task composition, plugin imports, dependency closure and scientific identity",
        "Data contents, resource admission and provider availability",
        "Execution lifecycle, workspace creation, persistence and resume identity",
        "SDK/environment endpoint selection when a constructor transport has base_url=None",
    )
