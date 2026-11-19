"""Remaining part of the worker's declared wall budget (issue #984).

``CandidateRunRequest.timeout_seconds`` is the caller's declared limit for one
sandboxed worker process; the sandbox runner enforces it from launch. A worker
process entry (fresh child or loop continuation) anchors a ``WorkerBudget`` once
and passes it down explicitly, so phases can bound their own children by what
remains. The anchor is taken after the sandbox started, so ``remaining_seconds``
is an upper bound and the outer sandbox limit still governs. No host cap is
inferred here.

``deadline_scope`` publishes the same remainder through the cooperative deadline
owner ``core.execution_deadline`` (issue #1548). Worker process entries bind it
around node execution, so ``LLMBridge`` clips request timeouts and refuses a
retry wait or an OpenAI background completion window that cannot fit the
worker's remaining budget, instead of leaving that work to the sandbox kill.
"""

from __future__ import annotations

import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Imported lazily: worker entries bind the workspace before heavier imports.
    from agent.skills.generated_pytest import PytestLimit
    from core.execution_deadline import ExecutionDeadline

#: Smallest limit handed to a child once the budget is spent: a positive value
#: keeps the child's declared-limit contract valid and makes it stop at its
#: first deadline check instead of running unbounded.
_EXHAUSTED_SECONDS = 0.001


@dataclass(frozen=True)
class WorkerBudget:
    """A monotonic deadline anchored at one worker process entry."""

    deadline: float

    @classmethod
    def start(cls, timeout_seconds: float) -> WorkerBudget:
        return cls(deadline=time.monotonic() + timeout_seconds)

    def remaining_seconds(self) -> float:
        return max(self.deadline - time.monotonic(), _EXHAUSTED_SECONDS)

    def deadline_scope(self) -> AbstractContextManager[ExecutionDeadline]:
        """Bind the remaining budget as this context's cooperative execution deadline.

        An exhausted budget binds the smallest positive allocation, so the first
        checked boundary (an LLM request, a retry wait) raises
        ``ExecutionDeadlineExceeded`` rather than running unbounded.
        """
        from core.execution_deadline import execution_deadline

        return execution_deadline(self.remaining_seconds())

    def pytest_limit(self) -> PytestLimit:
        """The remaining budget as a validator pytest limit naming its source."""
        from agent.skills.generated_pytest import PytestLimit

        return PytestLimit(seconds=self.remaining_seconds(), source="worker_budget")
