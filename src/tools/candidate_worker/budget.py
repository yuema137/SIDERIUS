"""Remaining part of the worker's declared wall budget (issue #984).

``CandidateRunRequest.timeout_seconds`` is the caller's declared limit for one
sandboxed worker process; the sandbox runner enforces it from launch. A worker
process entry (fresh child or loop continuation) anchors a ``WorkerBudget`` once
and passes it down explicitly, so phases can bound their own children by what
remains. The anchor is taken after the sandbox started, so ``remaining_seconds``
is an upper bound and the outer sandbox limit still governs. No host cap is
inferred here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

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
