"""Optional declaration editor routes, independent of native console execution."""

import threading
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from tools.setup_review.composition_models import TaskCheckSettings
from tools.workflow_authoring.external_inputs import external_input_catalog
from tools.workflow_authoring.models import (
    DraftRequest,
    ExternalInputCatalog,
    NodeCatalog,
    NodeDraftRequest,
    NodeDraftsRequest,
    Project,
    ReviewRequest,
    SaveRequest,
)
from tools.workflow_authoring.options import node_catalog
from tools.workflow_authoring.service import AuthoringError, WorkflowAuthoring
from tools.workflow_authoring.task_models import TaskReferenceTarget
from workflows.definition import TaskBinding
from workflows.definition.source import WorkflowSourceError

from .models import TaskChoice
from .setups import SetupRegistry
from .template_routes import add_template_routes


class EditorTaskChoice(BaseModel):
    """Safe configured intent; internal inspection paths are never browser metadata."""

    choice_id: str
    binding: TaskBinding


class EditorTaskChoices(BaseModel):
    choices: tuple[EditorTaskChoice, ...]


def task_reference_targets(tasks: tuple[TaskChoice, ...]) -> tuple[TaskReferenceTarget, ...]:
    """Project the existing curated choices; no independent task registry or resolver."""
    return tuple(
        TaskReferenceTarget(
            choice_id=task.task_id,
            binding=task.task_revision,
            manifest=Path(task.task_manifest),
            data_root=Path(task.data_root),
            llm_config_file=Path(task.llm_config_file),
            inspection_root=Path(task.preparation_root),
            read_only=tuple(Path(path) for path in task.task_read_only),
            settings=TaskCheckSettings(timeout_seconds=task.preparation_timeout_seconds),
        )
        for task in tasks
        if task.task_revision is not None
    )


def editor_router(
    setups: SetupRegistry | tuple[Project, ...],
    runnable_projects: tuple[str, ...] = (),
    task_targets: tuple[TaskReferenceTarget, ...] = (),
) -> APIRouter:
    """``setups``: the console registry, or bare projects (legacy code callers)."""
    registry = (
        setups
        if isinstance(setups, SetupRegistry)
        else SetupRegistry.legacy(setups, runnable_projects)
    )
    router = APIRouter(prefix="/api/editor")
    # Startup setups are opened eagerly (as before); a setup created later is opened on
    # first use, so it is editable without a restart.
    services = {
        project.project_id: WorkflowAuthoring(project, task_targets)
        for project in registry.projects()
    }
    lock = threading.Lock()

    def selected(project_id: str) -> WorkflowAuthoring:
        with lock:
            if project_id not in services:
                setup = registry.get(project_id)
                if setup is None:
                    raise HTTPException(404)
                try:
                    services[project_id] = WorkflowAuthoring(setup.project, task_targets)
                except (OSError, ValueError):
                    raise HTTPException(404) from None
            return services[project_id]

    def perform(
        action: Callable[[], BaseModel], *, writing: bool = False
    ) -> BaseModel | JSONResponse:
        try:
            return action()
        except AuthoringError as error:
            return JSONResponse(
                status_code=409,
                content={
                    "error": {"code": error.code, "message": str(error)},
                    "current": error.current.model_dump(mode="json") if error.current else None,
                    "proposal": error.proposal.model_dump(mode="json") if error.proposal else None,
                },
            )
        except WorkflowSourceError as error:
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "source",
                        "message": "proposal is not a supported declaration",
                    },
                    "diagnostics": [item.model_dump(mode="json") for item in error.diagnostics],
                },
            )
        except OSError:
            # A read never claims anything about a proposal; a failed write says nothing was saved.
            message = (
                "Not saved: the project folder or its recovery copies could not be written"
                if writing
                else "The workflow file or its project folder is unavailable on disk"
            )
            return JSONResponse(
                status_code=409,
                content={"error": {"code": "filesystem", "message": message}},
            )

    @router.get("/projects")
    def choices():
        return [
            {
                "project_id": setup.project.project_id,
                "candidate_run_enabled": setup.runnable,
            }
            for setup in registry.setups()
        ]

    @router.get("/task-choices", response_model=EditorTaskChoices)
    def task_choices() -> EditorTaskChoices:
        return EditorTaskChoices(
            choices=tuple(
                EditorTaskChoice(choice_id=target.choice_id, binding=target.binding)
                for target in task_targets
            )
        )

    @router.get("/node-catalog", response_model=NodeCatalog)
    def catalog() -> NodeCatalog:
        """Read-only projection of the native catalog for the node palette."""
        return node_catalog()

    @router.get("/external-inputs", response_model=ExternalInputCatalog)
    def external_inputs() -> ExternalInputCatalog:
        """Read-only explanation of how each catalog contract becomes an external input."""
        return external_input_catalog()

    # Template gallery and advice targets (template_routes.py); fixed paths first.
    add_template_routes(router, selected, perform)

    @router.get("/{project_id}")
    def read(project_id: str):
        service = selected(project_id)
        return perform(service.read)

    @router.get("/{project_id}/versions")
    def versions(project_id: str):
        service = selected(project_id)
        return perform(service.versions)

    @router.get("/{project_id}/versions/{index}")
    def version(project_id: str, index: int, sha256: str):
        service = selected(project_id)
        return perform(lambda: service.version(index, sha256))

    @router.post("/{project_id}/review")
    async def review(project_id: str, request: Request):
        service = selected(project_id)
        proposal = ReviewRequest.model_validate_json(await request.body())
        return await run_in_threadpool(perform, lambda: service.review(proposal))

    @router.post("/{project_id}/draft")
    async def draft(project_id: str, request: Request):
        service = selected(project_id)
        proposal = DraftRequest.model_validate_json(await request.body())
        return await run_in_threadpool(perform, lambda: service.inspect_draft(proposal))

    @router.post("/{project_id}/node-draft")
    async def node_draft(project_id: str, request: Request):
        service = selected(project_id)
        proposal = NodeDraftRequest.model_validate_json(await request.body())
        return await run_in_threadpool(perform, lambda: service.inspect_node_draft(proposal))

    @router.post("/{project_id}/nodes-draft")
    async def nodes_draft(project_id: str, request: Request):
        service = selected(project_id)
        proposal = NodeDraftsRequest.model_validate_json(await request.body())
        return await run_in_threadpool(perform, lambda: service.inspect_node_drafts(proposal))

    @router.post("/{project_id}/save")
    async def save(project_id: str, request: Request):
        service = selected(project_id)
        proposal = SaveRequest.model_validate_json(await request.body())
        return await run_in_threadpool(
            lambda: perform(lambda: service.save(proposal), writing=True)
        )

    return router
