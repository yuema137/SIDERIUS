"""Thin native-chain routes behind the console's shared request boundary."""

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from .native_chain import NativeChainConsole
from .native_chain_models import NativeChainChoiceSelection, NativeChainLaunchSelection
from .service import CandidateConsole


def native_chain_router(console: CandidateConsole) -> APIRouter:
    router = APIRouter(prefix="/api/native-chain")
    service = NativeChainConsole(console)

    @router.get("/choices")
    def choices():
        return service.choices()

    @router.post("/review")
    async def review(request: Request):
        selection = NativeChainChoiceSelection.model_validate_json(await request.body())
        return await run_in_threadpool(service.review, selection)

    @router.post("/launch", status_code=202)
    async def launch(request: Request):
        selection = NativeChainLaunchSelection.model_validate_json(await request.body())
        return await run_in_threadpool(service.launch, selection)

    return router
