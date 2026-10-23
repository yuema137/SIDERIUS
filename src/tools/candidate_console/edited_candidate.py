"""Saved declaration review and launch through existing native operation owners."""

import hashlib
import json
from pathlib import Path
from uuid import UUID

from pydantic import Field

from tools.candidate_operations import (
    CandidateOperation,
    OperationHandle,
    lookup_operation_request,
    submit_operation,
)
from tools.candidate_operations.models import OperationFailure
from tools.candidate_worker.admission import admit_input_paths
from tools.candidate_worker.models import (
    CandidateRunRequest,
    ReviewedContext,
    WorkflowSourceSnapshot,
)
from tools.workflow_authoring.service import WorkflowAuthoring
from tools.workflow_preview import preview_workflow
from tools.workflow_preview.files import resolve_location
from tools.workflow_preview.models import FileObservation, PreviewModel, WorkflowPreviewRequest
from workflows.definition import TaskReferences

from .files import credentials
from .models import CredentialReadiness, PreparedSelection, RouteView
from .readiness import credential_readiness
from .service import CandidateConsole


class EditedRunSelection(PreparedSelection):
    expected_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EditedRunLaunch(EditedRunSelection):
    expected_review_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_operation_id: UUID


class ReviewedEnvelope(PreviewModel):
    context: ReviewedContext
    request: CandidateRunRequest

    def digest(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


class EditedRunEffects(PreviewModel):
    nodes: tuple[tuple[str, str], ...]
    routes: tuple[RouteView, ...]
    files: tuple[FileObservation, ...]
    task: TaskReferences
    llm_config_file: str
    run_name: str
    implementation_advice: str | None
    validation_advice: str | None
    timeout_seconds: float
    network: bool
    devices: tuple[str, ...]
    environment_names: tuple[str, ...]
    read_only: tuple[str, ...]


class EditedRunReview(PreviewModel):
    credential_readiness: CredentialReadiness | None = None
    selection: EditedRunSelection
    source_origin: str
    reviewed_context: ReviewedContext
    review_digest: str
    envelope: ReviewedEnvelope = Field(exclude=True)
    effects: EditedRunEffects
    boundary: str = "Bindings reviewed; native validation at launch. No training or iteration."


class EditedCandidate:
    """Code-callable adapter. Prepared policy and configured authoring remain authorities."""

    def __init__(self, console: CandidateConsole):
        self.console = console

    def project(self, project_id: str):
        config = self.console.config
        if project_id not in config.runnable_editor_projects:
            raise OperationFailure("editor_policy", "project is not enabled for candidate runs")
        return next(
            project for project in config.editor_projects if project.project_id == project_id
        )

    def review(self, project_id: str, selection: EditedRunSelection) -> EditedRunReview:
        review = self._checked_review(project_id, selection)
        return review.model_copy(
            update={
                "credential_readiness": credential_readiness(
                    review.envelope.request, self.console.config.credential_file
                )
            }
        )

    def _checked_review(self, project_id: str, selection: EditedRunSelection) -> EditedRunReview:
        """Verify bindings without reading credentials, including during launch identity checks."""
        try:
            return self._review(project_id, selection)
        except OperationFailure:
            raise
        except (ValueError, OSError) as error:
            raise OperationFailure(
                "unsupported", "saved declaration bindings cannot be reviewed"
            ) from error

    def _review(self, project_id: str, selection: EditedRunSelection) -> EditedRunReview:
        selection = EditedRunSelection.model_validate_json(selection.model_dump_json())
        project = self.project(project_id)
        prepared, _ = self.console.resolve_prepared_context(
            PreparedSelection(prepare_operation_id=selection.prepare_operation_id)
        )
        source = WorkflowAuthoring(project).read()
        if source.sha256 != selection.expected_source_sha256:
            raise OperationFailure("stale_review", "saved source changed; review again")
        if source.document is None:
            raise OperationFailure("unsupported", "source is not a supported declaration")
        template = prepared.request
        original_root = Path(template.preview.project_root)
        if template.preview.llm_config_file is None:
            raise OperationFailure("context", "prepared context needs an explicit LLM config")
        config_path = resolve_location(
            original_root, template.preview.llm_config_file, "llm_config"
        )
        preview = WorkflowPreviewRequest(
            document=source.document,
            project_root=str(project.project_root),
            llm_config_file=str(config_path),
        )
        definition = source.document.definition
        root = project.project_root
        # Check mounts before reading any user-selected external bytes.
        admit_input_paths(
            (
                resolve_location(root, definition.task.data_root, "data_root"),
                resolve_location(root, definition.task.manifest, "manifest"),
                config_path,
                *(resolve_location(root, item.location, item.id) for item in definition.externals),
            ),
            template.read_only,
        )
        original_task = template.preview.document.definition.task
        for name in ("manifest", "data_root", "workspace"):
            if resolve_location(root, getattr(definition.task, name), name) != resolve_location(
                original_root, getattr(original_task, name), name
            ):
                raise OperationFailure("context", f"edited {name} differs from prepared context")
        observed = preview_workflow(preview)
        old_config = next(item for item in template.files if item.reference == "llm_config")
        new_config = next(item for item in observed.files if item.reference == "llm_config")
        if old_config != new_config:
            raise OperationFailure("context", "prepared LLM config observation changed")
        context = ReviewedContext(
            project_id=project_id,
            prepare_operation_id=prepared.prepare_operation_id,
            prepared_request_sha256=prepared.request_sha256,
        )
        fields = template.model_dump(mode="json")
        fields.update(
            preview=preview.model_dump(mode="json"),
            declaration_digest=definition.declaration_digest(),
            files=[item.model_dump(mode="json") for item in observed.files],
            selected_constructor_routes=[
                item.model_dump(mode="json") for item in observed.selected_constructor_routes
            ],
            workflow_source=WorkflowSourceSnapshot(
                origin_path=source.source_path,
                sha256=source.sha256,
                source=source.source,
                reviewed_context=context,
            ).model_dump(mode="json"),
        )
        request = CandidateRunRequest.model_validate_json(json.dumps(fields))
        envelope = ReviewedEnvelope(context=context, request=request)
        return EditedRunReview(
            selection=selection,
            source_origin=source.source_path,
            reviewed_context=context,
            review_digest=envelope.digest(),
            envelope=envelope,
            effects=EditedRunEffects(
                nodes=tuple((node.id, node.capability) for node in definition.nodes),
                routes=tuple(
                    RouteView(
                        node_id=route.name,
                        provider=route.transport.provider if route.transport else None,
                        model=route.transport.model_id if route.transport else None,
                    )
                    for route in request.selected_constructor_routes
                ),
                files=request.files,
                task=TaskReferences(
                    manifest=str(resolve_location(root, definition.task.manifest, "manifest")),
                    data_root=observed.data_root,
                    workspace=observed.workspace,
                ),
                llm_config_file=str(config_path),
                **request.model_dump(
                    include={
                        "run_name",
                        "implementation_advice",
                        "validation_advice",
                        "timeout_seconds",
                        "network",
                        "devices",
                        "environment_names",
                        "read_only",
                    }
                ),
            ),
        )

    def launch(self, project_id: str, selection: EditedRunLaunch) -> OperationHandle:
        selection = EditedRunLaunch.model_validate_json(selection.model_dump_json())
        self.project(project_id)
        store = self.console.config.operation_store
        prior = lookup_operation_request(store, selection.candidate_operation_id)
        if prior is not None:
            if prior.kind != "candidate":
                raise OperationFailure("conflict", "operation ID identifies another operation kind")
            capture = prior.request.workflow_source
            context = capture.reviewed_context if capture is not None else None
            if (
                capture is None
                or context is None
                or context.project_id != project_id
                or context.prepare_operation_id != selection.prepare_operation_id
                or capture.sha256 != selection.expected_source_sha256
                or ReviewedEnvelope(context=context, request=prior.request).digest()
                != selection.expected_review_digest
            ):
                raise OperationFailure(
                    "conflict", "operation ID identifies another reviewed capture"
                )
            return submit_operation(store, prior, launch_environment={})
        review = self._checked_review(
            project_id,
            EditedRunSelection(
                prepare_operation_id=selection.prepare_operation_id,
                expected_source_sha256=selection.expected_source_sha256,
            ),
        )
        if review.review_digest != selection.expected_review_digest:
            raise OperationFailure("stale_review", "reviewed bindings changed; review again")
        request = review.envelope.request
        environment = credentials(self.console.config.credential_file, request.environment_names)
        return submit_operation(
            store,
            CandidateOperation(request_id=selection.candidate_operation_id, request=request),
            launch_environment=environment,
        )
