"""Code-callable console policy; native operations remain the execution owner."""

from pathlib import Path
from uuid import UUID

from tools.candidate_operations import (
    CandidateLoopResumeOperation,
    CandidateLoopResumeRequest,
    CandidateOperation,
    LogChunk,
    LogReadRequest,
    OperationHandle,
    OperationSnapshot,
    OperationStoreConfig,
    PreparedCandidate,
    PrepareOperation,
    list_operations,
    loop_root_operation,
    read_operation,
    read_operation_log,
    read_operation_tokens,
    read_prepared_candidate,
    request_cancel,
    request_loop_pause,
    request_loop_stop,
    review_loop_resume,
    submit_operation,
)
from tools.candidate_operations.models import OperationFailure
from tools.candidate_operations.read import lookup_operation_request
from tools.candidate_prepare.models import CandidatePreparationReceipt, CandidatePreparationRequest
from tools.candidate_prepare.reusable_models import ReusablePreparationReceipt
from tools.candidate_worker import CandidateTokenSnapshot
from tools.candidate_worker.models import CandidateRunReceipt

from .config import validate_config
from .files import credentials
from .graph_results import read_graph_results
from .models import (
    ChoiceView,
    ConsoleConfig,
    GraphResultsView,
    LaunchSelection,
    LoopPauseAcknowledgement,
    LoopResumeReview,
    LoopResumeSelection,
    LoopStatusView,
    LoopStopAcknowledgement,
    OperationCancelAcknowledgement,
    OperationListItemView,
    OperationListView,
    PreparedReview,
    PreparedSelection,
    PrepareSelection,
    RecordedExampleOption,
    RecordedExampleView,
    RouteView,
    StatusView,
    TaskChoice,
)
from .readiness import credential_readiness
from .recorded_examples import read_recorded_example


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


def loop_status(
    operation_store: OperationStoreConfig, snapshot: OperationSnapshot
) -> LoopStatusView | None:
    """Declared loop bound from the root submission; bodies only from this segment's receipt.

    A resume segment's own submission carries no definition, so the bound comes from
    the root candidate the operations owner resolves through immutable predecessors.
    """
    if snapshot.kind not in ("candidate", "candidate_loop_resume"):
        return None
    root = loop_root_operation(operation_store, snapshot.operation_id)
    if root is None:
        return None
    loop = root.request.preview.document.definition.loop
    if loop is None:
        raise OperationFailure("kind", "operation loop definition is missing")
    receipt = snapshot.receipt
    trace = receipt.loop_trace if isinstance(receipt, CandidateRunReceipt) else None
    return LoopStatusView(
        final_iteration=loop.final_iteration,
        attempted_iterations=None if trace is None else trace.attempted_iterations,
        stop_reason=None if trace is None else trace.stop_reason,
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
            if isinstance(receipt, (CandidatePreparationReceipt, ReusablePreparationReceipt))
            else receipt.run_id
            if isinstance(receipt, CandidateRunReceipt)
            else None
        )
        return StatusView(
            **snapshot.model_dump(exclude={"receipt", "receipt_digest"}),
            native_status=receipt.status if receipt else None,
            graph_trace=receipt.graph_trace if isinstance(receipt, CandidateRunReceipt) else None,
            native_id=native_id,
            validation_passed=receipt.validation_passed
            if isinstance(receipt, CandidateRunReceipt)
            else None,
            loop=loop_status(self.config.operation_store, snapshot),
        )

    def cancel_operation(self, operation_id: UUID) -> OperationCancelAcknowledgement:
        """Record cancel for a live candidate; acknowledgement is not termination."""
        request_cancel(self.config.operation_store, operation_id)
        return OperationCancelAcknowledgement(operation_id=operation_id)

    def operations(self, limit: int = 50) -> OperationListView:
        """Read-only list of this store's verified records; receipts and paths stay out."""
        store = self.config.operation_store
        listing = list_operations(store, limit)
        items = []
        for entry in listing.entries:
            snapshot = entry.snapshot
            try:
                loop = loop_status(store, snapshot)
            except (OSError, ValueError):
                loop = None
            items.append(
                OperationListItemView(
                    operation_id=snapshot.operation_id,
                    kind=snapshot.kind,
                    run_name=entry.run_name,
                    project_id=entry.project_id,
                    admitted_at=entry.admitted_at,
                    state=snapshot.state,
                    native_status=snapshot.receipt.status if snapshot.receipt else None,
                    loop=loop,
                )
            )
        return OperationListView(
            operations=tuple(items),
            unreadable=listing.unreadable,
            examined=listing.examined,
            incomplete=listing.incomplete,
        )

    def request_loop_stop(self, operation_id: UUID) -> LoopStopAcknowledgement:
        """Record graceful Stop; acknowledgement is not termination (read status for that)."""
        request_loop_stop(self.config.operation_store, operation_id)
        return LoopStopAcknowledgement(operation_id=operation_id)

    def request_loop_pause(self, operation_id: UUID) -> LoopPauseAcknowledgement:
        """Record a completed-boundary Pause; acknowledgement is not paused (read status)."""
        request_loop_pause(self.config.operation_store, operation_id)
        return LoopPauseAcknowledgement(operation_id=operation_id)

    def review_loop_resume(self, operation_id: UUID) -> LoopResumeReview:
        """Owner review of one exited paused segment, plus names-only credential facts."""
        snapshot = review_loop_resume(self.config.operation_store, operation_id)
        root = loop_root_operation(self.config.operation_store, operation_id)
        receipt = snapshot.receipt
        if root is None or root.request.preview.document.definition.loop is None:
            raise OperationFailure("kind", "resume segment root is not an authored loop")
        if not isinstance(receipt, CandidateRunReceipt) or receipt.loop_trace is None:
            raise OperationFailure("integrity", "loop resume receipt missing trace")
        if snapshot.receipt_digest is None:
            raise OperationFailure("integrity", "loop resume receipt has no digest")
        return LoopResumeReview(
            predecessor_operation_id=operation_id,
            expected_receipt_digest=snapshot.receipt_digest,
            completed_iterations=receipt.loop_trace.attempted_iterations,
            final_iteration=root.request.preview.document.definition.loop.final_iteration,
            credential_readiness=credential_readiness(root.request, self.config.credential_file),
        )

    def resume_loop(self, selection: LoopResumeSelection) -> OperationHandle:
        """Submit one reviewed Resume; a known request UUID replays before credential reads."""
        selection = LoopResumeSelection.model_validate_json(selection.model_dump_json())
        store = self.config.operation_store
        submission = CandidateLoopResumeOperation(
            request_id=selection.request_id,
            request=CandidateLoopResumeRequest(
                predecessor_operation_id=selection.predecessor_operation_id,
                expected_receipt_digest=selection.expected_receipt_digest,
            ),
        )
        environment: dict[str, str] = {}
        if lookup_operation_request(store, selection.request_id) is None:
            root = loop_root_operation(store, selection.predecessor_operation_id)
            if root is None:
                raise OperationFailure("kind", "operation is not an authored loop")
            environment = credentials(self.config.credential_file, root.request.environment_names)
        return submit_operation(store, submission, launch_environment=environment)

    def graph_results(self, operation_id: UUID) -> GraphResultsView:
        return read_graph_results(self.config, operation_id)

    def tokens(self, operation_id: UUID) -> CandidateTokenSnapshot:
        return read_operation_tokens(self.config.operation_store, operation_id)

    def recorded_example_choices(self) -> tuple[RecordedExampleOption, ...]:
        return tuple(
            RecordedExampleOption(example_id=item.example_id, label=item.label)
            for item in self.config.recorded_examples
        )

    def recorded_example(self, example_id: str) -> RecordedExampleView:
        choice = next(
            (item for item in self.config.recorded_examples if item.example_id == example_id),
            None,
        )
        if choice is None:
            raise OperationFailure("example", "recorded example is not configured")
        return read_recorded_example(self.config.operation_store, choice)

    def log(self, request: LogReadRequest) -> LogChunk:
        return read_operation_log(self.config.operation_store, request)
