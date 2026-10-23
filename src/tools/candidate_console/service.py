"""Code-callable console policy; native operations remain the execution owner."""

from pathlib import Path
from uuid import UUID

from tools.candidate_operations import (
    CandidateOperation,
    LogChunk,
    LogReadRequest,
    OperationHandle,
    PreparedCandidate,
    PrepareOperation,
    read_operation,
    read_operation_log,
    read_operation_tokens,
    read_prepared_candidate,
    submit_operation,
)
from tools.candidate_operations.models import OperationFailure
from tools.candidate_prepare.models import CandidatePreparationReceipt, CandidatePreparationRequest
from tools.candidate_worker import CandidateTokenSnapshot
from tools.candidate_worker.models import CandidateRunReceipt

from .config import validate_config
from .files import credentials
from .models import (
    ChoiceView,
    ConsoleConfig,
    LaunchSelection,
    PreparedReview,
    PreparedSelection,
    PrepareSelection,
    RouteView,
    StatusView,
    TaskChoice,
)
from .readiness import credential_readiness


def preparation_request(
    task: TaskChoice, selection: PrepareSelection
) -> CandidatePreparationRequest:
    fields = task.model_dump(
        exclude={"task_id", "label", "preparation_root", "candidate_root", "reusable_runs_root"}
    )
    return CandidatePreparationRequest(
        **fields,
        output_dir=str(Path(task.preparation_root) / str(selection.operation_id)),
        candidate_workspace=str(Path(task.candidate_root) / str(selection.operation_id)),
        run_name=selection.run_name,
        proposal_advice=selection.proposal_advice,
        implementation_advice=selection.implementation_advice,
        validation_advice=selection.validation_advice,
    )


class CandidateConsole:
    def __init__(self, config: ConsoleConfig):
        self.config = validate_config(config)

    def choices(self) -> tuple[ChoiceView, ...]:
        return tuple(
            ChoiceView(
                task_id=t.task_id,
                label=t.label,
                task_manifest=t.task_manifest,
                data_root=t.data_root,
                llm_config_file=t.llm_config_file,
                preparation_root=t.preparation_root,
                candidate_root=t.candidate_root,
                reusable_runs_root=t.reusable_runs_root,
                preparation_timeout_seconds=t.preparation_timeout_seconds,
                candidate_timeout_seconds=t.candidate_timeout_seconds,
            )
            for t in self.config.tasks
        )

    def prepare(self, selection: PrepareSelection) -> OperationHandle:
        selection = PrepareSelection.model_validate_json(selection.model_dump_json())
        task = next((t for t in self.config.tasks if t.task_id == selection.task_id), None)
        if task is None:
            raise OperationFailure("task_policy", "unknown configured task")
        return submit_operation(
            self.config.operation_store,
            PrepareOperation(
                request_id=selection.operation_id, request=preparation_request(task, selection)
            ),
            launch_environment={},
        )

    def resolve_prepared_context(
        self, selection: PreparedSelection
    ) -> tuple[PreparedCandidate, TaskChoice]:
        selection = PreparedSelection.model_validate_json(selection.model_dump_json())
        prepared = read_prepared_candidate(
            self.config.operation_store, selection.prepare_operation_id
        )
        saved = prepared.preparation_request
        matches = []
        for task in self.config.tasks:
            editable = PrepareSelection(
                operation_id=selection.prepare_operation_id,
                task_id=task.task_id,
                run_name=saved.run_name,
                proposal_advice=saved.proposal_advice,
                implementation_advice=saved.implementation_advice,
                validation_advice=saved.validation_advice,
            )
            if preparation_request(task, editable) == saved:
                matches.append(task)
        if len(matches) != 1:
            raise OperationFailure(
                "task_policy", "preparation does not match exactly one configured task"
            )
        return prepared, matches[0]

    def review(self, selection: PreparedSelection) -> PreparedReview:
        prepared, task = self.resolve_prepared_context(selection)
        saved, request = prepared.preparation_request, prepared.request
        return PreparedReview(
            credential_readiness=credential_readiness(request, self.config.credential_file),
            prepare_operation_id=prepared.prepare_operation_id,
            prepared_digest=prepared.request_sha256,
            task_id=task.task_id,
            task_label=task.label,
            run_name=saved.run_name,
            composition_fingerprint=prepared.composition_fingerprint,
            routes=tuple(
                RouteView(
                    node_id=r.name,
                    provider=r.transport.provider if r.transport else None,
                    model=r.transport.model_id if r.transport else None,
                )
                for r in request.selected_constructor_routes
            ),
            proposal_advice=saved.proposal_advice,
            implementation_advice=saved.implementation_advice,
            validation_advice=saved.validation_advice,
            task_manifest=saved.task_manifest,
            data_root=saved.data_root,
            candidate_workspace=saved.candidate_workspace,
            preparation_timeout_seconds=saved.preparation_timeout_seconds,
            candidate_timeout_seconds=saved.candidate_timeout_seconds,
            network=request.network,
            devices=request.devices,
            environment_names=request.environment_names,
            read_only=request.read_only,
        )

    def launch(self, selection: LaunchSelection) -> OperationHandle:
        selection = LaunchSelection.model_validate_json(selection.model_dump_json())
        prepared, _ = self.resolve_prepared_context(
            PreparedSelection(prepare_operation_id=selection.prepare_operation_id)
        )
        if selection.expected_prepared_digest != prepared.request_sha256:
            raise OperationFailure(
                "stale_review", "prepared request changed; prepare and review again"
            )
        environment = credentials(self.config.credential_file, prepared.request.environment_names)
        return submit_operation(
            self.config.operation_store,
            CandidateOperation(
                request_id=selection.candidate_operation_id, request=prepared.request
            ),
            launch_environment=environment,
        )

    def status(self, operation_id: UUID) -> StatusView:
        snapshot = read_operation(self.config.operation_store, operation_id)
        receipt = snapshot.receipt
        native_id = (
            str(receipt.preparation_id)
            if isinstance(receipt, CandidatePreparationReceipt)
            else receipt.run_id
            if isinstance(receipt, CandidateRunReceipt)
            else None
        )
        return StatusView(
            **snapshot.model_dump(exclude={"receipt", "receipt_digest"}),
            native_status=receipt.status if receipt else None,
            native_id=native_id,
            validation_passed=receipt.validation_passed
            if isinstance(receipt, CandidateRunReceipt)
            else None,
        )

    def tokens(self, operation_id: UUID) -> CandidateTokenSnapshot:
        return read_operation_tokens(self.config.operation_store, operation_id)

    def log(self, request: LogReadRequest) -> LogChunk:
        return read_operation_log(self.config.operation_store, request)
