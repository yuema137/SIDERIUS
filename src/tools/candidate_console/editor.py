"""Optional declaration editor routes, independent of native console execution."""

from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from tools.setup_review.composition_models import TaskCheckSettings
from tools.workflow_authoring.models import (
    DraftRequest,
    NodeCatalog,
    NodeDraftRequest,
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
    projects: tuple[Project, ...],
    runnable_projects: tuple[str, ...] = (),
    task_targets: tuple[TaskReferenceTarget, ...] = (),
) -> APIRouter:
    router = APIRouter(prefix="/api/editor")
    services = {
        project.project_id: WorkflowAuthoring(project, task_targets) for project in projects
    }

    def selected(project_id: str) -> WorkflowAuthoring:
        if project_id not in services:
            raise HTTPException(404)
        return services[project_id]

    def perform(action: Callable[[], BaseModel]) -> BaseModel | JSONResponse:
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
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "code": "filesystem",
                        "message": "configured source/recovery is unavailable; proposal remains unsaved",
                    }
                },
            )

    @router.get("/projects")
    def choices():
        return [
            {
                "project_id": project.project_id,
                "candidate_run_enabled": project.project_id in runnable_projects,
            }
            for project in projects
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

    @router.get("/{project_id}")
    def read(project_id: str):
        service = selected(project_id)
        return perform(service.read)

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

    @router.post("/{project_id}/save")
    async def save(project_id: str, request: Request):
        service = selected(project_id)
        proposal = SaveRequest.model_validate_json(await request.body())
        return await run_in_threadpool(perform, lambda: service.save(proposal))

    return router
