"""Configured capture consumption through preparation and operation owners."""

import hashlib
import heapq
import os
from pathlib import Path
from uuid import UUID, uuid4

from tools.candidate_operations import (
    CandidateOperation,
    OperationHandle,
    build_reusable_operation,
    lookup_operation_request,
    operation_request_digest,
)
from tools.candidate_operations.models import OperationFailure
from tools.candidate_prepare import verify_reusable_preparation
from tools.candidate_prepare.reusable_models import ReusableBindingInspection
from tools.candidate_prepare.reusable_selection import (
    CapturedBytes,
    captured_plan,
    inspect_current_reusable_binding,
    inspect_reusable_binding,
)
from tools.candidate_worker.models import CandidateRunRequest
from tools.workflow_authoring.versions import recorded_name
from workflows.definition import AuthoredLoop

from .files import credentials
from .models import RouteView, TaskChoice
from .package_mounts import device_warnings
from .readiness import credential_readiness
from .reusable_models import (
    ReusableAdmissionNotAttempted,
    ReusableCaptureChoice,
    ReusableCaptureDescriptor,
    ReusableCaptureLaunch,
    ReusableCapturePage,
    ReusableCaptureReview,
    ReusableCaptureSelection,
)
from .reusable_policy import capture_path, check_capture_policy, configured_capture
from .seed_labels import review_label
from .service import CandidateConsole, with_run_resources


class ReusableCandidate:
    """Code-callable service; HTTP delegates here without assembling native requests."""

    def __init__(self, console: CandidateConsole):
        self.console = console

    def _inspect(
        self,
        project_id: str,
        choice: ReusableCaptureChoice,
        retained: ReusableCaptureSelection | None = None,
    ) -> tuple[TaskChoice, ReusableBindingInspection]:
        project, task, root = configured_capture(self.console.setups, project_id, choice.task_id)
        path = capture_path(root, choice.run_id)
        if retained is not None and retained.preparation.envelope != str(path):
            raise OperationFailure("task_policy", "retained capture is outside selected task")
        try:
            inspected = (
                inspect_reusable_binding(retained.preparation)
                if retained is not None
                else inspect_current_reusable_binding(str(path))
            )
            check_capture_policy(project, task, inspected)
            return task, inspected
        except OperationFailure:
            raise
        except (ValueError, OSError) as error:
            raise OperationFailure(
                "reusable_preparation", "capture metadata is unavailable"
            ) from error

    def list_captures(
        self, project_id: str, task_id: str, cursor: UUID | None = None, limit: int = 25
    ) -> ReusableCapturePage:
        if not 1 <= limit <= 100:
            raise ValueError("capture page limit must be between 1 and 100")
        _, _, root = configured_capture(self.console.setups, project_id, task_id)

        # Bounded memory and metadata reads, direct children only, lexical UUID pagination.
        def names():
            with os.scandir(root) as entries:
                for entry in entries:
                    try:
                        run_id = UUID(entry.name)
                    except ValueError:
                        continue
                    if str(run_id) == entry.name and (cursor is None or entry.name > str(cursor)):
                        yield entry.name

        page = heapq.nsmallest(limit + 1, names())
        descriptors = []
        for name in page[:limit]:
            choice = ReusableCaptureChoice(task_id=task_id, run_id=UUID(name))
            try:
                _, inspected = self._inspect(project_id, choice)
                descriptors.append(
                    ReusableCaptureDescriptor(
                        run_id=choice.run_id,
                        available=True,
                        run_name=inspected.binding.request.run_name,
                        source_sha256=inspected.binding.original_source.sha256,
                    )
                )
            except (OperationFailure, ValueError, OSError):
                descriptors.append(
                    ReusableCaptureDescriptor(
                        run_id=choice.run_id,
                        available=False,
                        reason="Capture unavailable or outside policy",
                    )
                )
        return ReusableCapturePage(
            captures=tuple(descriptors),
            next_cursor=UUID(page[limit - 1]) if len(page) > limit else None,
        )

    def select(self, project_id: str, choice: ReusableCaptureChoice) -> ReusableCaptureSelection:
        choice = ReusableCaptureChoice.model_validate_json(choice.model_dump_json())
        _, inspected = self._inspect(project_id, choice)
        build_reusable_operation(self.console.config.operation_store, inspected.selection, uuid4())
        return ReusableCaptureSelection(**choice.model_dump(), preparation=inspected.selection)

    def _operation(
        self, project_id: str, selection: ReusableCaptureSelection, operation_id: UUID
    ) -> tuple[TaskChoice, ReusableBindingInspection, CandidateOperation]:
        task, inspected = self._inspect(project_id, selection, selection)
        operation = build_reusable_operation(
            self.console.config.operation_store,
            selection.preparation,
            operation_id,
            selection.run_seed,
        )
        # Attribute the run to the setup ``_inspect`` admitted (exists, runnable, task).
        operation = CandidateOperation.model_validate_json(
            operation.model_copy(update={"setup_id": project_id}).model_dump_json()
        )
        return task, inspected, operation

    def review(self, project_id: str, selection: ReusableCaptureSelection) -> ReusableCaptureReview:
        selection = ReusableCaptureSelection.model_validate_json(selection.model_dump_json())
        self.console.require_reviewable_resources(selection)
        task, inspected, operation = self._operation(project_id, selection, uuid4())
        operation = with_run_resources(operation, selection)
        binding, request = inspected.binding, operation.request
        saved = binding.request
        plan, _ = captured_plan(Path(binding.envelope), binding, CapturedBytes())
        profile = plan.document.execution_profile
        if request.preview.execution_profile != profile:
            raise OperationFailure(
                "reusable_preparation",
                "candidate profile differs from captured reusable declaration",
            )
        loop = request.preview.document.definition.loop
        if loop != plan.document.definition.loop:
            raise OperationFailure(
                "reusable_preparation",
                "candidate research loop differs from captured reusable declaration",
            )
        if loop is not None:
            admit_captured_judge_route(loop, request)
        literature_settings = {}
        if profile == "native-literature-candidate/v1":
            from tools.candidate_prepare.reusable_literature import review_settings
            from workflows.definition import ManagedCandidateBinding

            selected = review_settings(plan.document)
            assert selected is not None
            authored = next(
                item.literature_settings
                for item in plan.document.definition.externals
                if isinstance(item, ManagedCandidateBinding)
                and item.literature_settings is not None
            )
            literature_settings = {selected[0]: authored}
        return ReusableCaptureReview(
            loop=loop,
            literature_settings=literature_settings,
            execution_profile=profile,
            selection=selection,
            request_digest=operation_request_digest(operation),
            source_path=binding.original_source.path,
            source_sha256=binding.original_source.sha256,
            task_label=task.label,
            task_manifest=saved.task_manifest,
            data_root=saved.data_root,
            llm_config_file=saved.llm_config_file,
            allowed_output_types=saved.allowed_output_types,
            run_name=saved.run_name,
            envelope=binding.envelope,
            inputs=saved.output_dir,
            workspace=saved.candidate_workspace,
            nodes=tuple(
                (node.id, node.capability) for node in request.preview.document.definition.nodes
            ),
            routes=tuple(
                RouteView(
                    node_id=r.name,
                    provider=r.transport.provider if r.transport else None,
                    model=r.transport.model_id if r.transport else None,
                )
                for r in request.selected_constructor_routes
            ),
            composition_fingerprint=verify_reusable_preparation(
                selection.preparation
            ).composition_fingerprint,
            proposal_advice=saved.proposal_advice,
            implementation_advice=saved.implementation_advice,
            validation_advice=saved.validation_advice,
            preparation_timeout_seconds=saved.preparation_timeout_seconds,
            candidate_timeout_seconds=saved.candidate_timeout_seconds,
            network=request.network,
            devices=request.devices,
            environment_names=request.environment_names,
            read_only=request.read_only,
            device_warnings=device_warnings(request.devices, request.read_only),
            credential_readiness=credential_readiness(request, self.console.config.credential_file),
            source_version_name=recorded_name(
                Path(binding.original_source.path), binding.original_source.sha256
            ),
            seed=review_label(selection.run_seed),
        )

    def launch(self, project_id: str, launch: ReusableCaptureLaunch) -> OperationHandle:
        launch = ReusableCaptureLaunch.model_validate_json(launch.model_dump_json())
        store = self.console.config.operation_store
        prior = lookup_operation_request(store, launch.candidate_operation_id)
        if prior is not None:
            if (
                prior.kind != "candidate"
                or prior.reusable_preparation != launch.selection.preparation
                or operation_request_digest(prior) != launch.expected_request_digest
            ):
                raise OperationFailure("conflict", "operation ID identifies another capture")
            return self.console.submit(prior, launch_environment={})
        try:
            _, _, operation = self._operation(
                project_id, launch.selection, launch.candidate_operation_id
            )
            # Bound before the digest check: the review digested the same operation.
            operation = with_run_resources(operation, launch.selection)
            if operation_request_digest(operation) != launch.expected_request_digest:
                raise OperationFailure("stale_review", "captured request changed; review again")
            environment = credentials(
                self.console.config.credential_file, operation.request.environment_names
            )
        except OperationFailure as error:
            raise ReusableAdmissionNotAttempted(error.detail.code, error.detail.message) from error
        return self.console.submit(operation, launch_environment=environment)


def admit_captured_judge_route(loop: AuthoredLoop, request: CandidateRunRequest) -> None:
    """Refuse at review what the worker would refuse at loop start (B2-5, Q-B2-10).

    Calls the worker's own ``admit_judge_route`` with the reviewed loop and the model
    settings the worker will load: the request's captured ``llm_config`` file, else the
    default settings, exactly as ``candidate_worker.native`` does. A missing judge route
    or a static call bound above ``max_judge_calls`` is a typed ``judge_route`` refusal
    before any launch; the owner's message names the route or the bound and the cap.
    """
    from tools.candidate_worker.loop_judge import admit_judge_route
    from tools.candidate_worker.loop_stop import StopConditionError
    from tools.workflow_preview.config import parse_config
    from workflows.llm_config import WorkflowLLMConfig

    config = WorkflowLLMConfig.default()
    for observation in request.files:
        if observation.reference == "llm_config":
            data = Path(observation.path).read_bytes()
            if hashlib.sha256(data).hexdigest() != observation.sha256:
                raise OperationFailure(
                    "reusable_preparation", "captured model settings changed since preparation"
                )
            config = parse_config(data)
    try:
        admit_judge_route(loop, config)
    except StopConditionError as error:
        raise OperationFailure("judge_route", str(error)) from error
