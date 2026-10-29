"""Authenticated transport for the code-callable saved-source preparation adapter."""

from pathlib import Path

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from .reusable_preparation import NewRunIntent, NewRunSelection, ReusablePreparation
from .service import CandidateConsole


def reusable_preparation_router(
    console: CandidateConsole, *, protected: tuple[Path, ...] | None = None
) -> APIRouter:
    router = APIRouter(prefix="/api/editor/{project_id}/reusable-preparations")
    service = ReusablePreparation(console, protected=protected)

    @router.post("/review")
    async def review(project_id: str, request: Request):
        selection = NewRunSelection.model_validate_json(await request.body())
        return await run_in_threadpool(service.review, project_id, selection)

    @router.post("/prepare", status_code=202)
    async def prepare(project_id: str, request: Request):
        intent = NewRunIntent.model_validate_json(await request.body())
        return await run_in_threadpool(service.prepare, project_id, intent)

    return router
