"""Inert request/result contracts for explicit sandboxed task checks."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from tools.setup_review.models import SetupDeclarationReport, SetupReviewRequest
from tools.workspace_sandbox.profile import SandboxProfile
from tools.workspace_sandbox.runner import ExecutionResult

PositiveBytes = Annotated[int, Field(strict=True, gt=0)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
CHILD_REQUEST_NAME = "check-request.json"
CHILD_RESULT_NAME = "check-result.json"
FAILURE_MESSAGE_MAX_CHARS = 4096
FailureStage = Literal["composition", "planner_strategy", "transport", "sandbox", "stale_manifest"]


class CheckModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class TaskCheckSettings(CheckModel):
    timeout_seconds: float = Field(gt=0)
    result_max_bytes: PositiveBytes = 1048576


class TaskCheckRequest(CheckModel):
    setup: SetupReviewRequest
    scratch: Path
    output: Path
    read_only: tuple[Path, ...]
    settings: TaskCheckSettings


class CompositionJob(CheckModel):
    """Only explicit task/provider selection enters the isolated child."""

    manifest: str
    manifest_sha256: Digest
    planner_strategy: str | None
    scratch: str
    settings: TaskCheckSettings

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class PluginObservation(CheckModel):
    identity: dict[str, JsonValue]
    path: str


class TaskCompositionSummary(CheckModel):
    """Owner-projected JSON, never runtime implementations or source contents."""

    semantic_fingerprint: Digest
    task_data_path_id: str
    task_config: dict[str, JsonValue]
    dataset_profile: dict[str, JsonValue]
    primary_metric: dict[str, JsonValue]
    secondary_metrics: list[dict[str, JsonValue]]
    parameter_rules: dict[str, JsonValue]
    inference_preflight: dict[str, JsonValue]
    source_paths: dict[str, str]
    plugins: list[PluginObservation]
    code_package_identity: dict[str, JsonValue] | None
    prompt_renderer_identity: dict[str, JsonValue] | None
    preflight_estimator_identity: dict[str, JsonValue]
    data_analysis_identity: dict[str, JsonValue] | None
    task_health_declaration: str


class CheckFailure(CheckModel):
    stage: FailureStage
    exception_type: str
    message: str = Field(max_length=FAILURE_MESSAGE_MAX_CHARS)


class CompositionResult(CheckModel):
    request_sha256: Digest
    manifest_sha256: Digest
    outcome: Literal["passed", "failed"]
    task: TaskCompositionSummary | None = None
    planner_strategy_identity: dict[str, JsonValue] | None = None
    failure: CheckFailure | None = None

    @classmethod
    def failed(
        cls,
        job: CompositionJob,
        stage: FailureStage,
        error: Exception,
        *,
        task: TaskCompositionSummary | None = None,
    ) -> CompositionResult:
        return cls(
            request_sha256=job.digest,
            manifest_sha256=job.manifest_sha256,
            outcome="failed",
            task=task,
            failure=CheckFailure(
                stage=stage,
                exception_type=type(error).__name__,
                message=str(error)[:FAILURE_MESSAGE_MAX_CHARS],
            ),
        )

    @model_validator(mode="after")
    def complete_outcome(self) -> CompositionResult:
        if self.outcome == "passed":
            if (
                self.task is None
                or self.planner_strategy_identity is None
                or self.failure is not None
            ):
                raise ValueError(
                    "passed composition check requires task and planner facts without a failure"
                )
        elif self.failure is None:
            raise ValueError("failed composition check requires a failure reason")
        return self


class TaskCheckReport(CheckModel):
    schema_version: Literal["siderius.task-composition-check/v1"] = (
        "siderius.task-composition-check/v1"
    )
    declaration: SetupDeclarationReport
    request: TaskCheckRequest
    job: CompositionJob
    sandbox: SandboxProfile
    runtime_read_only_roots: tuple[str, ...]
    execution: ExecutionResult | None
    result: CompositionResult
    limitations: tuple[str, ...]
