"""Template gallery and per-agent advice targets for the declaration editor.

Thin routes over ``tools.workflow_authoring.templates`` (the one template owner)
and ``advice_targets``. Importing a template never writes: it returns unsaved
source that the browser reviews through the ordinary ``/review`` source path.
"""

from collections.abc import Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from tools.workflow_authoring.advice_targets import AdviceTargets, advice_targets
from tools.workflow_authoring.service import AuthoringError, WorkflowAuthoring
from tools.workflow_authoring.templates import (
    TemplateCatalog,
    TemplateImportRequest,
    TemplateImportView,
    TemplateRefusal,
    instantiate,
    template_catalog,
)


def import_template(
    service: WorkflowAuthoring, request: TemplateImportRequest
) -> TemplateImportView:
    current = service.read()
    if current.sha256 != request.expected_sha256:
        raise AuthoringError(
            "conflict", "source changed; inspect current source and import again", current
        )
    try:
        source = instantiate(request.template_id, current.document)
    except TemplateRefusal as error:
        raise AuthoringError("unsupported", str(error), current) from error
    return TemplateImportView(template_id=request.template_id, source=source)


def add_template_routes(
    router: APIRouter,
    selected: Callable[[str], WorkflowAuthoring],
    perform: Callable[[Callable[[], BaseModel]], BaseModel | JSONResponse],
) -> None:
    """Register before ``/{project_id}`` so fixed paths are not read as project IDs."""

    @router.get("/templates", response_model=TemplateCatalog)
    def templates() -> TemplateCatalog:
        return template_catalog()

    @router.get("/advice-targets", response_model=AdviceTargets)
    def advice() -> AdviceTargets:
        return advice_targets()

    @router.post("/{project_id}/template")
    async def template(project_id: str, request: Request):
        service = selected(project_id)
        proposal = TemplateImportRequest.model_validate_json(await request.body())
        return await run_in_threadpool(perform, lambda: import_template(service, proposal))
