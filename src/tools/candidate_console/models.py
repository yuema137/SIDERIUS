"""Inert console selections and curated views; native requests own execution."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from agent.schemas.output_types import OutputTypeName
from execute_tools.run_report import MetricView, RunHeadline
from tools.candidate_operations import OperationStoreConfig
from tools.candidate_operations.models import OperationKind, ProcessObservation
from tools.candidate_operations.native_chain_models import NativeChainObservation
from tools.candidate_prepare.models import CandidatePreparationRequest
from tools.candidate_worker import CandidateTokenSnapshot
from tools.candidate_worker.graph_models import GraphReason, GraphState, GraphTrace
from tools.candidate_worker.loop_stop import StopReason
from tools.workflow_authoring.models import Project
from tools.workflow_preview.models import PreviewModel
from tools.workspace_sandbox.profile import SandboxProfile
from workflows.definition import TaskBinding, WorkflowDefinition

from .native_chain_models import NativeChainChoice
from .readiness_models import CredentialReadiness as CredentialReadiness

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
    task_revision: TaskBinding | None = Field(default=None, exclude_if=lambda value: value is None)

    @field_validator("candidate_environment_names")
    @classmethod
    def environment(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return SandboxProfile.environment_keys(value)


class ConsoleConfig(PreviewModel):
    operation_store: OperationStoreConfig
    tasks: tuple[TaskChoice, ...] = ()
    native_chain_choices: tuple[NativeChainChoice, ...] = ()
    recorded_examples: tuple[RecordedExampleChoice, ...] = ()
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
        if len({c.choice_id for c in self.native_chain_choices}) != len(self.native_chain_choices):
            raise ValueError("native chain choice IDs must be unique")
        if len({c.example_id for c in self.recorded_examples}) != len(self.recorded_examples):
            raise ValueError("recorded example IDs must be unique")
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


class RecordedExampleChoice(PreviewModel):
    """Explicit read-only selection of one candidate workspace."""

    example_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    label: str = Field(min_length=1, max_length=160)
    workspace: str
    expected_run_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class RecordedExampleOption(PreviewModel):
    """Browser-safe label without configured filesystem or record identities."""

    example_id: str
    label: str


class RecordedStage(PreviewModel):
    capability: str
    model_type: str
    passed: bool | None = None


class RecordedExampleView(PreviewModel):
    example_id: str
    label: str
    run_id: str
    candidate_id: str
    run_name: str
    declaration_digest: str
    declaration: WorkflowDefinition
    source_snapshot_available: bool
    candidate_status: Literal["accepted", "rejected"]
    validation_passed: bool
    stages: tuple[RecordedStage, ...]
    tokens: CandidateTokenSnapshot


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


class LoopStatusView(PreviewModel):
    """Declared finite-loop bound plus the receipt's verified attempted bodies.

    ``attempted_iterations`` is ``None`` while no native receipt exists; the
    console never infers per-body progress from an active process.
    """

    final_iteration: int = Field(gt=0)
    attempted_iterations: int | None = Field(default=None, ge=0)
    # The receipt's verified reason when a declared stop condition completed the loop
    # before its limit; absent otherwise (and absent while no receipt exists).
    stop_reason: StopReason | None = Field(default=None, exclude_if=lambda value: value is None)


class LoopStopSelection(PreviewModel):
    """Empty JSON body: the path UUID is the only Stop input."""


class LoopStopAcknowledgement(PreviewModel):
    """Stop was recorded for the loop; the active body still completes."""

    operation_id: UUID
    outcome: Literal["requested"] = "requested"


class LoopPauseSelection(PreviewModel):
    """Empty JSON body: the path UUID selects the segment to Pause."""


class LoopPauseAcknowledgement(PreviewModel):
    """Pause was recorded for this segment; the active body still completes."""

    operation_id: UUID
    outcome: Literal["requested"] = "requested"


class LoopResumeReview(PreviewModel):
    """Verified paused segment the operator may continue; names-only credential facts."""

    predecessor_operation_id: UUID
    expected_receipt_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    completed_iterations: int = Field(gt=0)
    final_iteration: int = Field(gt=0)
    credential_readiness: CredentialReadiness


class LoopResumeSelection(PreviewModel):
    """Client-retained request UUID plus the reviewed paused receipt digest."""

    request_id: UUID
    predecessor_operation_id: UUID
    expected_receipt_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class StatusView(PreviewModel):
    operation_id: UUID
    kind: OperationKind
    request_digest: str
    observed_at: str
    state: Literal["active", "completed", "operation_failed", "unknown"]
    process: ProcessObservation
    successor_operation_id: UUID | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    finishing: bool
    receipt_available: bool
    native_status: str | None
    native_id: str | None
    validation_passed: bool | None
    graph_trace: GraphTrace | None = Field(default=None, exclude_if=lambda value: value is None)
    native_chain: NativeChainObservation | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    loop: LoopStatusView | None = Field(default=None, exclude_if=lambda value: value is None)
    reason: str


class GraphRunSummary(PreviewModel):
    """Path-free subset of the existing one-run report projection."""

    run_name: str
    model_type: str
    status: Literal["completed", "partial", "failed"]
    termination_reason: str
    started_at: str
    finished_at: str
    completed_rounds: int
    total_attempts: int
    metric: MetricView | None
    metric_source: Literal["run_output_metric_spec", "records_reconciled", "unavailable"]
    ranking_refusal: str | None
    secondary_metrics: tuple[MetricView, ...]
    headline: RunHeadline
    status_counts: dict[str, int]


class GraphSkippedNode(PreviewModel):
    """A declared node a verified route decision left unrun; never a failure."""

    node_id: str
    reason: GraphReason


class GraphBodyResult(PreviewModel):
    iteration: int
    tuning_state: GraphState
    result: GraphRunSummary | None
    # Route-skipped nodes in declaration order; omitted when none (unrouted bytes).
    skipped: tuple[GraphSkippedNode, ...] = Field(default=(), exclude_if=lambda value: not value)


class GraphResultsView(PreviewModel):
    operation_id: UUID
    available: bool
    bodies: tuple[GraphBodyResult, ...] = ()
