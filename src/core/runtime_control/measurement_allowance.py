"""Charge preparation and cleanup once, excluding intervening scientific execution."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field


class MeasurementSegmentReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: str
    started_at: float
    ended_at: float
    allowed_seconds: float = Field(gt=0)
    spent_seconds: float = Field(ge=0)
    outcome: str


@dataclass
class MeasurementAllowance:
    total_seconds: float
    clock: Callable[[], float] = time.monotonic
    receipts: list[MeasurementSegmentReceipt] = field(default_factory=list)
    _active: tuple[str, float, float] | None = None

    @property
    def remaining(self) -> float:
        return max(0.0, self.total_seconds - sum(item.spent_seconds for item in self.receipts))

    @property
    def deadline(self) -> float:
        if self._active is None:
            raise RuntimeError("no measurement segment is active")
        _, started, allowed = self._active
        return started + allowed

    def begin(self, kind: str) -> float:
        if self._active is not None:
            raise RuntimeError("a measurement segment is already active")
        remaining = self.remaining
        if remaining <= 0:
            raise TimeoutError("attempt measurement allowance is exhausted")
        started = self.clock()
        self._active = kind, started, remaining
        return started + remaining

    def finish(self, outcome: str, *, ended_at: float | None = None) -> None:
        if self._active is None:
            raise RuntimeError("no measurement segment is active")
        kind, started, allowed = self._active
        ended = self.clock() if ended_at is None else ended_at
        if ended < started:
            raise RuntimeError("measurement completion precedes its start")
        self.receipts.append(
            MeasurementSegmentReceipt(
                kind=kind,
                started_at=started,
                ended_at=ended,
                allowed_seconds=allowed,
                spent_seconds=ended - started,
                outcome=outcome,
            )
        )
        self._active = None

    def finish_if_active(self, outcome: str) -> None:
        if self._active is not None:
            self.finish(outcome)
