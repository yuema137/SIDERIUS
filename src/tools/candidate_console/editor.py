"""Optional declaration editor routes, independent of native console execution."""

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from tools.workflow_authoring.models import Project, ReviewRequest, SaveRequest
from tools.workflow_authoring.service import AuthoringError, WorkflowAuthoring
from workflows.definition.source import WorkflowSourceError


def editor_router(
    projects: tuple[Project, ...], runnable_projects: tuple[str, ...] = ()
) -> APIRouter:
    router = APIRouter(prefix="/api/editor")
    services = {project.project_id: WorkflowAuthoring(project) for project in projects}

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

    @router.get("/{project_id}")
    def read(project_id: str):
        service = selected(project_id)
        return perform(service.read)

    @router.post("/{project_id}/review")
    async def review(project_id: str, request: Request):
        service = selected(project_id)
        proposal = ReviewRequest.model_validate_json(await request.body())
        return await run_in_threadpool(perform, lambda: service.review(proposal))

    @router.post("/{project_id}/save")
    async def save(project_id: str, request: Request):
        service = selected(project_id)
        proposal = SaveRequest.model_validate_json(await request.body())
        return await run_in_threadpool(perform, lambda: service.save(proposal))

    return router
