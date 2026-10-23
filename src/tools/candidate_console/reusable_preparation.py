"""Saved-source review and recovery-first preparation through native owners."""

from uuid import UUID

from pydantic import Field, field_validator

from tools.candidate_operations import (
    OperationHandle,
    ReusablePreparationExpectation,
    ReusablePrepareOperation,
    operation_request_digest,
    recover_reusable_preparation,
    submit_operation,
)
from tools.candidate_operations.models import OperationFailure
from tools.candidate_prepare import (
    ReusableCandidatePreparationRequest,
    ReusablePreparationObservations,
    inspect_reusable_source,
    preflight_reusable_candidate,
)
from tools.workflow_preview.models import PreviewModel

from .reusable_models import ReusableAdmissionNotAttempted
from .reusable_policy import check_request_policy, configured_capture
from .service import CandidateConsole


class NewRunSelection(PreviewModel):
    task_id: str
    run_name: str
    run_id: UUID
    preparation_operation_id: UUID
    expected_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("run_name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        return ReusableCandidatePreparationRequest.safe_name(value)


class NewRunIntent(PreviewModel):
    selection: NewRunSelection
    expectation: ReusablePreparationExpectation


class NewRunReview(NewRunIntent):
    source_path: str
    task_label: str
    task_manifest: str
    data_root: str
    llm_config_file: str
    inputs: str
    workspace: str
    preparation_timeout_seconds: float
    candidate_timeout_seconds: float
    network: bool
    devices: tuple[str, ...]
    environment_names: tuple[str, ...]
    read_only: tuple[str, ...]
    effects: str = "Prepare captures saved source and creates inputs; candidate launch is separate."


class ReusablePreparation:
    def __init__(self, console: CandidateConsole):
        self.console = console

    def _review(
        self, project_id: str, selection: NewRunSelection
    ) -> tuple[NewRunReview, ReusablePrepareOperation]:
        project, task, root = configured_capture(self.console.config, project_id, selection.task_id)
        request = ReusableCandidatePreparationRequest(
            source_path=str(project.source_file),
            project_root=str(project.project_root),
            runs_root=str(root),
            **selection.model_dump(exclude={"task_id", "preparation_operation_id"}),
            **task.model_dump(
                include={
                    "llm_config_file",
                    "preparation_timeout_seconds",
                    "candidate_timeout_seconds",
                    "task_read_only",
                    "candidate_network",
                    "candidate_devices",
                    "candidate_environment_names",
                }
            ),
        )
        try:
            inspected = inspect_reusable_source(request)
            check_request_policy(task, inspected.request)
            plan = preflight_reusable_candidate(request)
            check_request_policy(task, plan.binding.request)
        except OperationFailure:
            raise
        except (ValueError, OSError) as error:
            raise OperationFailure(
                "stale_review", "saved source or selected inputs unavailable"
            ) from error
        operation = ReusablePrepareOperation(
            request_id=selection.preparation_operation_id, request=request
        )
        native = plan.binding.request
        return NewRunReview(
            selection=selection,
            expectation=ReusablePreparationExpectation(
                request_digest=operation_request_digest(operation),
                observations=ReusablePreparationObservations.from_binding(plan.binding),
            ),
            source_path=request.source_path,
            task_label=task.label,
            task_manifest=native.task_manifest,
            data_root=native.data_root,
            llm_config_file=native.llm_config_file,
            inputs=native.output_dir,
            workspace=native.candidate_workspace,
            preparation_timeout_seconds=native.preparation_timeout_seconds,
            candidate_timeout_seconds=native.candidate_timeout_seconds,
            network=native.candidate_network,
            devices=native.candidate_devices,
            environment_names=native.candidate_environment_names,
            read_only=native.task_read_only,
        ), operation

    def review(self, project_id: str, selection: NewRunSelection) -> NewRunReview:
        selection = NewRunSelection.model_validate_json(selection.model_dump_json())
        return self._review(project_id, selection)[0]

    def prepare(self, project_id: str, intent: NewRunIntent) -> OperationHandle:
        intent = NewRunIntent.model_validate_json(intent.model_dump_json())
        store = self.console.config.operation_store
        operation = recover_reusable_preparation(
            store, intent.selection.preparation_operation_id, intent.expectation
        )
        if operation is not None and (
            operation.kind != "prepare_reusable"
            or operation.request.run_id != intent.selection.run_id
            or operation.request.run_name != intent.selection.run_name
            or operation.request.expected_source_sha256 != intent.selection.expected_source_sha256
        ):
            raise OperationFailure("conflict", "retained selection differs from admitted run")
        if operation is None:
            try:
                review, operation = self._review(project_id, intent.selection)
                if review.expectation != intent.expectation:
                    raise OperationFailure("stale_review", "reviewed inputs changed")
            except OperationFailure as error:
                raise ReusableAdmissionNotAttempted(
                    error.detail.code, error.detail.message
                ) from error
        return submit_operation(
            store, operation, launch_environment={}, expected_reusable_inputs=intent.expectation
        )
