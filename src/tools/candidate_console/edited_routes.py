"""Optional HTTP adapter for saved candidate execution; policy lives in Python service."""

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from .edited_candidate import EditedCandidate, EditedRunLaunch, EditedRunSelection
from .service import CandidateConsole


def edited_router(console: CandidateConsole) -> APIRouter:
    router = APIRouter(prefix="/api/editor")
    service = EditedCandidate(console)

    @router.post("/{project_id}/candidate-review")
    async def review(project_id: str, request: Request):
        selection = EditedRunSelection.model_validate_json(await request.body())
        return await run_in_threadpool(service.review, project_id, selection)

    @router.post("/{project_id}/candidate-launch", status_code=202)
    async def launch(project_id: str, request: Request):
        selection = EditedRunLaunch.model_validate_json(await request.body())
        return await run_in_threadpool(service.launch, project_id, selection)

    return router
