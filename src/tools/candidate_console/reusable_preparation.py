"""Saved-source review and recovery-first preparation through native owners."""

from pathlib import Path
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
from tools.workflow_authoring.versions import recorded_name
from tools.workflow_preview.models import PreviewModel
from workflows.definition import ReusableWorkflowDocument

from .readiness import named_credential_readiness
from .readiness_models import CredentialReadiness
from .reusable_models import ReusableAdmissionNotAttempted
from .reusable_policy import check_request_policy, configured_capture
from .service import CandidateConsole
from .settings_file import protected_paths


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
    # Name-only precheck of the task's configured candidate environment names, read in
    # this server process before Prepare. Provider-derived requirements are known only
    # after preparation and are rechecked at capture review and again at launch.
    credential_readiness: CredentialReadiness
    # Display-only Save name of expected_source_sha256; the SHA-256 stays the bound identity.
    source_version_name: str | None = Field(default=None, exclude_if=lambda value: value is None)
    effects: str = "Prepare captures saved source and creates inputs; candidate launch is separate."


def check_declared_launch_policy(document: ReusableWorkflowDocument) -> None:
    """Refuse at review what training admission would refuse after launch (L-1).

    Reads the declared ``healthgate_mode``/``result_authority`` from the same sparse
    training payload preparation captures (``settings_payload``) and calls the launch
    policy owner's declaration check. A workflow without authored training settings
    has nothing to check here. Config-dependent refusals (4-6) stay at launch.
    """
    from execute_tools.health_checks.launch_policy import (
        FormalLaunchPolicyError,
        validate_declared_policy,
    )
    from tools.candidate_prepare.reusable_training import settings_payload
    from workflows.candidate_training_settings import parse_training_settings

    payload = settings_payload(document)
    if payload is None:
        return
    launch = parse_training_settings(payload).launch
    try:
        validate_declared_policy(
            healthgate_mode=launch.healthgate_mode, result_authority=launch.result_authority
        )
    except FormalLaunchPolicyError as error:
        raise OperationFailure("launch_policy", str(error)) from error


class ReusablePreparation:
    def __init__(self, console: CandidateConsole, *, protected: tuple[Path, ...] | None = None):
        """``protected``: paths no read-only input may overlap at admission; by default
        derived from the config alone (``create_app`` adds the workspace settings/library)."""
        self.console = console
        self.protected = protected_paths(console.config) if protected is None else protected

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
            plan = preflight_reusable_candidate(request, protected=self.protected)
            check_request_policy(task, plan.binding.request)
            check_declared_launch_policy(plan.document)
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
            credential_readiness=named_credential_readiness(
                (), native.candidate_environment_names, self.console.config.credential_file
            ),
            source_version_name=recorded_name(
                project.source_file, selection.expected_source_sha256
            ),
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
