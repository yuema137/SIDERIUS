"""Inert console selections and curated views; native requests own execution."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from agent.schemas.output_types import OutputTypeName
from tools.candidate_operations import OperationStoreConfig
from tools.candidate_operations.models import ProcessObservation
from tools.candidate_prepare.models import CandidatePreparationRequest
from tools.workflow_authoring.models import Project
from tools.workflow_preview.models import PreviewModel
from tools.workspace_sandbox.profile import SandboxProfile

Advice = Annotated[str, Field(max_length=32768)]


class TaskChoice(PreviewModel):
    task_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    label: str = Field(min_length=1, max_length=160)
    task_manifest: str
    data_root: str
    llm_config_file: str
    task_read_only: tuple[str, ...] = ()
    preparation_root: str
    candidate_root: str
    reusable_runs_root: str | None = None
    preparation_timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    candidate_timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    candidate_network: bool
    candidate_devices: tuple[str, ...]
    candidate_environment_names: tuple[str, ...]
    allowed_output_types: tuple[OutputTypeName, ...] | None = Field(default=None, min_length=1)

    @field_validator("candidate_environment_names")
    @classmethod
    def environment(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return SandboxProfile.environment_keys(value)


class ConsoleConfig(PreviewModel):
    operation_store: OperationStoreConfig
    tasks: tuple[TaskChoice, ...] = Field(min_length=1)
    bind_host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(ge=1024, le=65535)
    browser_origin: str
    auth_token_file: str
    credential_file: str | None = None
    editor_projects: tuple[Project, ...] = ()
    runnable_editor_projects: tuple[str, ...] = ()

    @model_validator(mode="after")
    def origins_and_ids(self):
        from urllib.parse import urlsplit

        origin = urlsplit(self.browser_origin)
        if (
            origin.scheme != "http"
            or origin.hostname != "127.0.0.1"
            or origin.port is None
            or not 1024 <= origin.port <= 65535
            or self.browser_origin != f"http://127.0.0.1:{origin.port}"
        ):
            raise ValueError("browser_origin must be an exact loopback HTTP origin with port")
        if len({task.task_id for task in self.tasks}) != len(self.tasks):
            raise ValueError("task IDs must be unique")
        if len({project.project_id for project in self.editor_projects}) != len(
            self.editor_projects
        ):
            raise ValueError("editor project IDs must be unique")
        if len(set(self.runnable_editor_projects)) != len(self.runnable_editor_projects) or not set(
            self.runnable_editor_projects
        ).issubset({project.project_id for project in self.editor_projects}):
            raise ValueError("runnable editor project IDs must be unique configured projects")
        return self


class PrepareSelection(PreviewModel):
    operation_id: UUID
    task_id: str
    run_name: str
    proposal_advice: Advice | None = None
    implementation_advice: Advice | None = None
    validation_advice: Advice | None = None

    @field_validator("run_name")
    @classmethod
    def name(cls, value: str) -> str:
        return CandidatePreparationRequest.safe_name(value)


class PreparedSelection(PreviewModel):
    prepare_operation_id: UUID


class LaunchSelection(PreparedSelection):
    candidate_operation_id: UUID
    expected_prepared_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ChoiceView(PreviewModel):
    task_id: str
    label: str
    preparation_timeout_seconds: float
    candidate_timeout_seconds: float
    task_manifest: str
    data_root: str
    llm_config_file: str
    preparation_root: str
    candidate_root: str
    reusable_runs_root: str | None = None


class RouteView(PreviewModel):
    node_id: str
    provider: str | None
    model: str | None


class CredentialReadiness(PreviewModel):
    """Ephemeral name-only facts; never admission or provider authentication."""

    required_names: tuple[str, ...]
    omitted_names: tuple[str, ...]
    unresolved_routes: tuple[str, ...]
    present_names: tuple[str, ...]
    missing_names: tuple[str, ...]
    file_status: Literal["not_needed", "not_selected", "readable", "unavailable"]
    ready: bool
    instructions: tuple[str, ...]


class PreparedReview(PreviewModel):
    credential_readiness: CredentialReadiness
    prepare_operation_id: UUID
    prepared_digest: str
    task_id: str
    task_label: str
    run_name: str
    composition_fingerprint: str
    stages: tuple[str, ...] = ("propose", "implement", "validate")
    routes: tuple[RouteView, ...]
    proposal_advice: str | None
    implementation_advice: str | None
    validation_advice: str | None
    task_manifest: str
    data_root: str
    candidate_workspace: str
    preparation_timeout_seconds: float
    candidate_timeout_seconds: float
    network: bool
    devices: tuple[str, ...]
    environment_names: tuple[str, ...]
    read_only: tuple[str, ...]


class StatusView(PreviewModel):
    operation_id: UUID
    kind: Literal["prepare", "prepare_reusable", "candidate"]
    request_digest: str
    observed_at: str
    state: Literal["active", "completed", "operation_failed", "unknown"]
    process: ProcessObservation
    finishing: bool
    receipt_available: bool
    native_status: str | None
    native_id: str | None
    validation_passed: bool | None
    reason: str
