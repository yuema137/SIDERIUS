"""Read-only task routes behind ``RequestBoundary``; observation runs in the background."""

from fastapi import APIRouter, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from .task_summary import TaskListView, TaskSummaries, TaskSummaryView


def task_summary_router(summaries: TaskSummaries) -> APIRouter:
    router = APIRouter(prefix="/api/tasks")

    @router.get("")
    def tasks() -> TaskListView:
        return summaries.list_view()

    @router.get("/{task_id}/summary")
    async def summary(
        task_id: str,
        refresh: bool = Query(False),
        count_samples: bool = Query(False),
    ) -> TaskSummaryView:
        # Reading the manifest digest and model profile is file I/O; keep it off the loop.
        view = await run_in_threadpool(
            summaries.summary, task_id, refresh=refresh, count_samples=count_samples
        )
        if view is None:
            raise HTTPException(404)
        return view

    return router
