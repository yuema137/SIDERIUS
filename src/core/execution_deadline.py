"""Cooperative monotonic deadlines shared by callers, requests and retry waits.

This is not a process watchdog. Blocking implementations must consume the
remaining timeout; late results are rejected at the next checked boundary.
"""

from __future__ import annotations

import math
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExecutionDeadlineExceeded(TimeoutError):
    """The caller's continuing allocation cannot admit another operation."""


class ExecutionBudgetReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    budget_seconds: float = Field(gt=0)
    elapsed_seconds: float = Field(ge=0)
    status: Literal["completed", "failed", "deadline_exceeded"]
    last_boundary: str
    enforcement: Literal["cooperative_remaining_time"] = "cooperative_remaining_time"


@dataclass
class ExecutionDeadline:
    started_at: float
    expires_at: float
    last_boundary: str = "start"

    def remaining(self, boundary: str) -> float:
        self.last_boundary = boundary
        remaining = self.expires_at - time.monotonic()
        if remaining <= 0:
            raise ExecutionDeadlineExceeded(f"Execution deadline exhausted at {boundary}")
        return remaining

    def receipt(self, status: Literal["completed", "failed", "deadline_exceeded"]):
        return ExecutionBudgetReceipt(
            budget_seconds=self.expires_at - self.started_at,
            elapsed_seconds=max(0.0, time.monotonic() - self.started_at),
            status=status,
            last_boundary=self.last_boundary,
        )


_active: ContextVar[ExecutionDeadline | None] = ContextVar("execution_deadline", default=None)


@contextmanager
def execution_deadline(seconds: float) -> Iterator[ExecutionDeadline]:
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("Execution deadline requires a finite positive allocation")
    started = time.monotonic()
    parent = _active.get()
    expires = started + seconds
    if parent is not None:
        parent.remaining("nested allocation")
        expires = min(expires, parent.expires_at)
    deadline = ExecutionDeadline(started, expires)
    token = _active.set(deadline)
    try:
        yield deadline
    finally:
        _active.reset(token)


def remaining_seconds(boundary: str) -> float | None:
    deadline = _active.get()
    return None if deadline is None else deadline.remaining(boundary)


def bounded_timeout(seconds: float, boundary: str) -> float:
    remaining = remaining_seconds(boundary)
    return seconds if remaining is None else min(seconds, remaining)


def deadline_sleep(seconds: float, boundary: str) -> None:
    remaining = remaining_seconds(boundary)
    if remaining is not None and seconds >= remaining:
        raise ExecutionDeadlineExceeded(
            f"Execution deadline cannot fit {seconds:g}s retry wait at {boundary}; "
            f"{remaining:.3g}s remain"
        )
    time.sleep(seconds)
    remaining_seconds(boundary)
