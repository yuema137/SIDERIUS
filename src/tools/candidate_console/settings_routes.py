"""Settings routes behind ``RequestBoundary``; refusals never echo input or paths."""

import re

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .settings_export import ExportFile, ExportRequest
from .settings_library import LibraryUpload
from .settings_service import ConsoleSettings, SettingsRefusal
from .settings_views import SettingsWrite


def _refused(error: SettingsRefusal) -> JSONResponse:
    return JSONResponse(
        status_code=error.status, content={"error": {"code": error.code, "message": error.message}}
    )


def settings_router(settings: ConsoleSettings) -> APIRouter:
    router = APIRouter()

    @router.get("/api/settings")
    def view():
        return settings.view()

    @router.put("/api/settings")
    async def write(request: Request):
        selection = SettingsWrite.model_validate_json(await request.body())
        try:
            return await run_in_threadpool(settings.write, selection)
        except SettingsRefusal as error:
            return _refused(error)

    @router.post("/api/settings/library")
    async def upload(request: Request):
        selection = LibraryUpload.model_validate_json(await request.body())
        try:
            return await run_in_threadpool(settings.upload, selection)
        except SettingsRefusal as error:
            return _refused(error)

    @router.post("/api/settings/exports")
    async def export(request: Request):
        selection = ExportRequest.model_validate_json(await request.body())
        try:
            return await run_in_threadpool(settings.export, selection)
        except SettingsRefusal as error:
            return _refused(error)

    @router.get("/api/settings/exports/{name}/{file}")
    def download(name: str, file: ExportFile):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", name):
            return _refused(SettingsRefusal(404, "not_found", "export is unavailable"))
        try:
            payload = settings.download(name, file)
        except SettingsRefusal as error:
            return _refused(error)
        return Response(
            payload,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{file}"'},
        )

    @router.get("/api/settings/folders")
    def folders(
        root_id: str = Query(pattern=r"^[a-zA-Z0-9_-]{1,80}$"),
        subpath: str = Query("", max_length=512),
        limit: int = Query(200),
    ):
        try:
            return settings.folders(root_id, subpath, limit)
        except SettingsRefusal as error:
            return _refused(error)

    return router
