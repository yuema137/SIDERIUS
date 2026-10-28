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
from tools.candidate_operations.models import OperationFailure, UnknownOperation

from .boundary import RequestBoundary
from .edited_routes import edited_router
from .editor import editor_router, task_reference_targets
from .files import token
from .models import (
    ConsoleConfig,
    LaunchSelection,
    LoopPauseSelection,
    LoopResumeSelection,
    LoopStopSelection,
    PreparedSelection,
    PrepareSelection,
)
from .native_chain_routes import native_chain_router
from .reusable_models import ReusableAdmissionNotAttempted
from .reusable_preparation_routes import reusable_preparation_router
from .reusable_routes import reusable_router
from .service import CandidateConsole


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


# Route-local: ``kind`` is also raised by unrelated operation readers.
LOOP_STOP_REFUSALS = {
    "kind": "Stop is available only for an authored candidate research loop",
    "not_ready": "candidate loop has not claimed its workspace yet; read status and retry",
    "not_running": "candidate loop is terminal or not confirmed running; Stop was not recorded",
}


LOOP_PAUSE_REFUSALS = {
    "kind": "Pause is available only for an authored candidate research loop",
    "not_ready": "candidate loop has not claimed its workspace yet; read status and retry",
    "not_running": "loop segment is terminal or not confirmed running; Pause was not recorded",
}
LOOP_RESUME_REFUSALS = {
    "kind": "Resume is available only for an authored candidate research loop",
    "not_ready": "candidate loop has not claimed its workspace yet; read status and retry",
    "loop_resume": (
        "operation is not an exited, cleanly paused loop segment that can continue, "
        "or it changed since review; read status and review again"
    ),
    "runtime": "the console runtime differs from the one that started this loop",
}


def refusal(table: dict[str, str], error: OperationFailure) -> JSONResponse:
    """Route-local fixed message; unknown codes keep the global (path-free) mapping."""
    if error.detail.code not in table:
        raise error
    return error_response(409, error.detail.code, table[error.detail.code])


def create_app(config: ConsoleConfig) -> FastAPI:
    service = CandidateConsole(config)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.console = service
    app.include_router(
        editor_router(
            service.config.editor_projects,
            service.config.runnable_editor_projects,
            task_reference_targets(service.config.tasks),
        )
    )
    app.include_router(edited_router(service))
    app.include_router(reusable_router(service))
    app.include_router(native_chain_router(service))
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
                "native_chain_policy": "native chain choice is unavailable or overlaps editor writes",
                "not_supported": "native-chain token aggregation is not supported",
                "example": "recorded example is not configured",
                "example_path": "recorded example is unavailable",
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
        if isinstance(error, UnknownOperation):
            # Typed absence after a successful store read; the only code that may
            # justify forgetting a retained intent. Plain 404 ``not_found`` never does.
            return error_response(404, "unknown_operation", error.detail.message)
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
        return service.choices_view()

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

    @app.get("/api/operations")
    def operations(limit: int = Query(50, gt=0, le=200)):
        return service.operations(limit)

    @app.get("/api/operations/{operation_id}")
    def status(operation_id: UUID):
        return service.status(operation_id)

    @app.post("/api/operations/{operation_id}/loop-stop")
    async def loop_stop(operation_id: UUID, request: Request):
        LoopStopSelection.model_validate_json(await request.body())
        try:
            return await run_in_threadpool(service.request_loop_stop, operation_id)
        except OperationFailure as error:
            return refusal(LOOP_STOP_REFUSALS, error)

    @app.post("/api/operations/{operation_id}/loop-pause")
    async def loop_pause(operation_id: UUID, request: Request):
        LoopPauseSelection.model_validate_json(await request.body())
        try:
            return await run_in_threadpool(service.request_loop_pause, operation_id)
        except OperationFailure as error:
            return refusal(LOOP_PAUSE_REFUSALS, error)

    @app.get("/api/operations/{operation_id}/loop-resume-review")
    def loop_resume_review(operation_id: UUID):
        try:
            return service.review_loop_resume(operation_id)
        except OperationFailure as error:
            return refusal(LOOP_RESUME_REFUSALS, error)

    @app.post("/api/loop-resumes", status_code=202)
    async def loop_resume(request: Request):
        selection = LoopResumeSelection.model_validate_json(await request.body())
        try:
            return await run_in_threadpool(service.resume_loop, selection)
        except OperationFailure as error:
            return refusal(LOOP_RESUME_REFUSALS, error)

    @app.get("/api/operations/{operation_id}/graph-results")
    def graph_results(operation_id: UUID):
        return service.graph_results(operation_id)

    @app.get("/api/operations/{operation_id}/tokens")
    def tokens(operation_id: UUID):
        return service.tokens(operation_id)

    @app.get("/api/recorded-examples")
    def recorded_example_choices():
        return service.recorded_example_choices()

    @app.get("/api/recorded-examples/{example_id}")
    def recorded_example(example_id: str):
        return service.recorded_example(example_id)

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
            "native-chain.js": "text/javascript",
            "native-chain-monitor.js": "text/javascript",
            "graph-results-monitor.js": "text/javascript",
            "loop-control.js": "text/javascript",
            "token-presenter.js": "text/javascript",
            "recorded-example.js": "text/javascript",
            "session.js": "text/javascript",
            "number-format.js": "text/javascript",
            "operations-list.js": "text/javascript",
            "navigation.js": "text/javascript",
            "editor-entry.js": "text/javascript",
            "styles.css": "text/css",
            "theme.css": "text/css",
            "theme.js": "text/javascript",
            "editor.html": "text/html",
            "editor.js": "text/javascript",
            "editor-capability-presentation.js": "text/javascript",
            "editor-contract-presentation.js": "text/javascript",
            "editor-contract-presentation.css": "text/css",
            "editor-circuit.js": "text/javascript",
            "editor-palette.js": "text/javascript",
            "editor-palette-guidance.js": "text/javascript",
            "editor-circuit-geometry.js": "text/javascript",
            "editor-task-controls.js": "text/javascript",
            "editor-loop-controls.js": "text/javascript",
            "editor-problems.js": "text/javascript",
            "editor-node-parameters.js": "text/javascript",
            "editor-versions.js": "text/javascript",
            "editor-draft.js": "text/javascript",
            "editor-draft.css": "text/css",
            "editor-node-drafts.js": "text/javascript",
            "editor-external-inputs.js": "text/javascript",
            "editor-external-inputs.css": "text/css",
            "reusable-run.js": "text/javascript",
            "reusable-intents.js": "text/javascript",
            "new-run.js": "text/javascript",
            "page-guidance.js": "text/javascript",
            "page-guidance.css": "text/css",
            "onboarding.js": "text/javascript",
            "onboarding.css": "text/css",
            "ui-settings.js": "text/javascript",
            # Operator logo: shapes plus an embedded PNG only, served as <img> (no script context).
            "siderius-logo-light.svg": "image/svg+xml",
            "siderius-logo-dark.svg": "image/svg+xml",
            "editor.css": "text/css",
            "editor-parameters.css": "text/css",
            "editor-palette.css": "text/css",
            "editor-templates.js": "text/javascript",
            "editor-templates.css": "text/css",
            "editor-advice.js": "text/javascript",
            "editor-page-bar.js": "text/javascript",
            "editor-canvas-add.js": "text/javascript",
            "editor-canvas-ui.css": "text/css",
            "editor-circuit-tooltip.js": "text/javascript",
            "editor-inspector-rows.js": "text/javascript",
            "editor-managed-inputs.js": "text/javascript",
            "editor-page-bar.css": "text/css",
            "icons.js": "text/javascript",
            # Vendored Lucide sprite (shapes only; licence in icons-LICENSE.txt), fetched by icons.js.
            "icons.svg": "image/svg+xml",
        }
        if asset not in types:
            raise HTTPException(404)
        return FileResponse(assets / asset, media_type=types[asset])

    return app
