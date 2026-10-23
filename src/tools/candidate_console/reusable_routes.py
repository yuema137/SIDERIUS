"""Thin authenticated HTTP transport for the shared reusable capture service."""

from uuid import UUID

from fastapi import APIRouter, Query, Request
from starlette.concurrency import run_in_threadpool

from .reusable_candidate import ReusableCandidate
from .reusable_models import ReusableCaptureChoice, ReusableCaptureLaunch, ReusableCaptureSelection
from .service import CandidateConsole


def reusable_router(console: CandidateConsole) -> APIRouter:
    router = APIRouter(prefix="/api/editor/{project_id}/reusable-captures")
    service = ReusableCandidate(console)

    @router.get("")
    def captures(
        project_id: str,
        task_id: str,
        cursor: UUID | None = None,
        limit: int = Query(25, ge=1, le=100),
    ):
        return service.list_captures(project_id, task_id, cursor, limit)

    @router.post("/select")
    async def select(project_id: str, request: Request):
        selection = ReusableCaptureChoice.model_validate_json(await request.body())
        return await run_in_threadpool(service.select, project_id, selection)

    @router.post("/review")
    async def review(project_id: str, request: Request):
        selection = ReusableCaptureSelection.model_validate_json(await request.body())
        return await run_in_threadpool(service.review, project_id, selection)

    @router.post("/launch", status_code=202)
    async def launch(project_id: str, request: Request):
        selection = ReusableCaptureLaunch.model_validate_json(await request.body())
        return await run_in_threadpool(service.launch, project_id, selection)

    return router
