"""Per-instance loopback HTTP adapter; handlers only call the shared service."""

from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from tools.candidate_operations import LogReadRequest
from tools.candidate_operations.models import OperationFailure

from .boundary import RequestBoundary
from .edited_routes import edited_router
from .editor import editor_router
from .files import token
from .models import ConsoleConfig, LaunchSelection, PreparedSelection, PrepareSelection
from .reusable_models import ReusableAdmissionNotAttempted
from .reusable_preparation_routes import reusable_preparation_router
from .reusable_routes import reusable_router
from .service import CandidateConsole


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def create_app(config: ConsoleConfig) -> FastAPI:
    service = CandidateConsole(config)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.console = service
    app.include_router(
        editor_router(service.config.editor_projects, service.config.runnable_editor_projects)
    )
    app.include_router(edited_router(service))
    app.include_router(reusable_router(service))
    app.include_router(reusable_preparation_router(service))
    app.add_middleware(RequestBoundary, config=service.config, token=token(config.auth_token_file))

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def invalid(request: Request, error: Exception):
        return error_response(422, "validation", "invalid request fields")

    @app.exception_handler(FileNotFoundError)
    async def missing(request: Request, error: Exception):
        return error_response(404, "not_found", "operation or required resource is unavailable")

    @app.exception_handler(OperationFailure)
    async def operation_error(request: Request, error: OperationFailure):
        # Only credential name diagnostics are safe to forward; native errors may carry paths.
        message = (
            error.detail.message
            if error.detail.code == "credentials"
            else {
                "busy": "another operation is active or unresolved",
                "conflict": "operation ID already identifies different content",
                "stale_review": "reviewed source or bindings changed; review again",
                "unsupported": "saved declaration bindings cannot be reviewed; inspect source and prepared context",
                "context": "saved declaration differs from selected prepared context",
                "editor_policy": "project is not enabled for candidate runs",
                "task_policy": "preparation does not match the configured task policy",
                "not_prepared": "preparation has no verified candidate to review",
            }.get(error.detail.code, "native operation could not be verified")
        )
        response = error_response(409, error.detail.code, message)
        if isinstance(error, ReusableAdmissionNotAttempted):
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "code": error.detail.code,
                        "message": message,
                        "admission_not_attempted": True,
                    }
                },
            )
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        return error_response(error.status_code, "http", "request is not available")

    @app.get("/api/choices")
    def choices():
        return service.choices()

    @app.post("/api/preparations", status_code=202)
    async def prepare(request: Request):
        selection = PrepareSelection.model_validate_json(await request.body())
        return await run_in_threadpool(service.prepare, selection)

    @app.get("/api/preparations/{operation_id}/review")
    def review(operation_id: UUID):
        return service.review(PreparedSelection(prepare_operation_id=operation_id))

    @app.post("/api/candidates", status_code=202)
    async def launch(request: Request):
        selection = LaunchSelection.model_validate_json(await request.body())
        return await run_in_threadpool(service.launch, selection)

    @app.get("/api/operations/{operation_id}")
    def status(operation_id: UUID):
        return service.status(operation_id)

    @app.get("/api/operations/{operation_id}/tokens")
    def tokens(operation_id: UUID):
        return service.tokens(operation_id)

    @app.get("/api/operations/{operation_id}/log")
    def log(
        operation_id: UUID,
        kind: Literal["native", "operation"] = "native",
        offset: int = Query(0, ge=0),
        max_bytes: int = Query(65536, gt=0, le=65536),
    ):
        return service.log(
            LogReadRequest(operation_id=operation_id, kind=kind, offset=offset, max_bytes=max_bytes)
        )

    assets = Path(__file__).parent / "static"

    @app.get("/")
    def index():
        return FileResponse(assets / "index.html", media_type="text/html")

    @app.get("/{asset}")
    def static(asset: str):
        types = {
            "app.js": "text/javascript",
            "session.js": "text/javascript",
            "navigation.js": "text/javascript",
            "editor-entry.js": "text/javascript",
            "styles.css": "text/css",
            "theme.css": "text/css",
            "theme.js": "text/javascript",
            "editor.html": "text/html",
            "editor.js": "text/javascript",
            "reusable-run.js": "text/javascript",
            "reusable-intents.js": "text/javascript",
            "new-run.js": "text/javascript",
            "editor.css": "text/css",
        }
        if asset not in types:
            raise HTTPException(404)
        return FileResponse(assets / asset, media_type=types[asset])

    return app
