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
    """The caller's continuing allocation cannot admit another operation.

    ``expires_at`` is the monotonic expiry of the allocation that refused: the one
    passed explicitly, otherwise the deadline active where the error is created
    (subclasses inherit this), or ``None`` without one. ``stopped_by`` uses it to
    tell which allocation stopped an operation.
    """

    def __init__(self, *args: object, expires_at: float | None = None) -> None:
        super().__init__(*args)
        if expires_at is None:
            active = _active.get()
            expires_at = None if active is None else active.expires_at
        self.expires_at = expires_at


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
            raise ExecutionDeadlineExceeded(
                f"Execution deadline exhausted at {boundary}", expires_at=self.expires_at
            )
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


def _cause_chain(error: BaseException) -> Iterator[BaseException]:
    """``error`` and its explicit ``__cause__`` chain, each exception once."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__


def deadline_failure(error: BaseException) -> ExecutionDeadlineExceeded | None:
    """The deadline refusal in ``error`` or its explicit ``__cause__`` chain, if any."""
    return next(
        (item for item in _cause_chain(error) if isinstance(item, ExecutionDeadlineExceeded)),
        None,
    )


def raise_if_deadline_exceeded(error: BaseException) -> None:
    """Re-raise a deadline refusal hidden in ``error``; else return.

    For broad retry handlers: an allocation that refused one operation refuses
    the next as well, so the refusal must end the caller instead of counting as
    one failed attempt.
    """
    failure = deadline_failure(error)
    if failure is not None:
        raise failure


def stopped_by(error: BaseException, deadline: ExecutionDeadline) -> bool:
    """Whether ``error`` or its explicit ``__cause__`` chain is a refusal by ``deadline``.

    A nested allocation clamped to ``deadline`` has the same expiry, so its refusal
    counts (``deadline`` was the binding limit); a refusal by a shorter nested
    allocation, or by an unrelated deadline, does not.
    """
    return any(
        isinstance(item, ExecutionDeadlineExceeded) and item.expires_at == deadline.expires_at
        for item in _cause_chain(error)
    )


def active_deadline() -> ExecutionDeadline | None:
    """The deadline bound in this context, or None."""
    return _active.get()


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
