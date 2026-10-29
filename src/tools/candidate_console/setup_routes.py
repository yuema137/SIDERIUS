"""Per-task experiment setup routes over ``setups.SetupStore`` and ``SetupRegistry``.

``GET /api/tasks/{task_id}/setups`` lists the setups whose task is ``task_id``;
``POST`` creates one (console.json ``experiment_setups.browser_creatable``).
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .service import CandidateConsole
from .settings_file import SettingsInvalid
from .setups import SetupCreate, SetupRefused, SetupView


def _refusal(error: SetupRefused) -> JSONResponse:
    content: dict[str, object] = {"error": {"code": error.code, "message": error.message}}
    if error.finding is not None:
        content["finding"] = error.finding.model_dump(mode="json")
    return JSONResponse(status_code=error.status, content=content)


def setups_router(console: CandidateConsole) -> APIRouter:
    router = APIRouter(prefix="/api/tasks/{task_id}/setups")

    @router.get("")
    def listing(task_id: str):
        try:
            return {
                "setups": [
                    view.model_dump(mode="json") for view in console.setups.for_task(task_id)
                ]
            }
        except SetupRefused as error:
            return _refusal(error)

    @router.post("", status_code=201)
    async def create(task_id: str, request: Request):
        selection = SetupCreate.model_validate_json(await request.body())

        def created() -> SetupView | JSONResponse:
            try:
                entry = console.setup_store.create(console.config, task_id, selection)
                return next(
                    view
                    for view in console.setups.for_task(task_id)
                    if view.setup_id == entry.setup_id
                )
            except SetupRefused as error:
                return _refusal(error)
            except SettingsInvalid as error:
                return JSONResponse(
                    status_code=409, content={"error": {"code": "invalid", "message": str(error)}}
                )

        return await run_in_threadpool(created)

    return router
