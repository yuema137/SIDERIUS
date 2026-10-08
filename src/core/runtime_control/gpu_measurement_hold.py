"""Acknowledge synchronized allocator reservations with driver samples.

Reservation high-water and held reservation describe the same backing-memory
allocation domain. Neither is substituted for a sampled driver peak.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from core.runtime_control.gpu_measurement_phases import PhaseJournal
    from core.runtime_control.gpu_measurement_sampler import TreeMemorySample


class ObservedReservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    hold_id: str = Field(min_length=1)
    started_at: float
    ended_at: float
    reserved_before_bytes: int = Field(ge=0)
    reserved_after_bytes: int = Field(ge=0)
    acknowledged: bool
    # Populated by the parent from samples inside this exact hold window.
    driver_samples: int = Field(default=0, ge=0)
    required_samples: int = Field(default=0, ge=0)


def reservation_peak_bytes(device: str) -> int:
    import torch

    torch.cuda.synchronize(device)
    return int(torch.cuda.max_memory_reserved(device))


def reservation_observer(
    *,
    device: str,
    journal: PhaseJournal,
    phase: Literal["setup", "training", "inference"],
    request_id: str,
    ack_path: str,
    timeout_seconds: float,
    deadline_at: float | None = None,
) -> Callable[[], ObservedReservation]:
    """Hold each synchronized state until its own nonce has been observed.

    The end event closes a failed/expired hold too: late samples must never
    acknowledge a state the worker has already released. The parent owns the
    hard deadline; ``deadline_at`` additionally bounds all worker holds together.
    """
    sequence = 0

    def hold() -> ObservedReservation:
        import torch

        nonlocal sequence
        identity = f"{request_id}:{phase}:{sequence}"
        sequence += 1
        torch.cuda.synchronize(device)
        before = int(torch.cuda.memory_reserved(device))
        started = time.time()
        journal.record("reservation_hold_start", phase, hold_id=identity)
        deadline = time.monotonic() + timeout_seconds
        if deadline_at is not None:
            deadline = min(deadline, deadline_at)
        acknowledged = False
        path = Path(ack_path)
        try:
            while time.monotonic() < deadline:
                with suppress(FileNotFoundError):
                    acknowledged = path.read_text(encoding="utf-8") == identity
                if acknowledged:
                    break
                time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
            torch.cuda.synchronize(device)
            after = int(torch.cuda.memory_reserved(device))
            return ObservedReservation(
                hold_id=identity,
                started_at=started,
                ended_at=time.time(),
                reserved_before_bytes=before,
                reserved_after_bytes=after,
                acknowledged=acknowledged,
            )
        finally:
            journal.record("reservation_hold_end", phase, hold_id=identity)

    return hold


def acknowledge_reservation(
    *,
    journal_path: Path,
    ack_path: Path,
    samples: Sequence[TreeMemorySample],
    minimum_samples: int,
    request_id: str | None = None,
) -> None:
    """Only samples within the currently open hold acknowledge its nonce."""
    if minimum_samples < 1:
        raise ValueError("A reservation hold requires positive driver sample coverage")
    try:
        lines = journal_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    event = None
    for line in reversed(lines):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(candidate, dict):
            continue
        kind = candidate.get("event")
        if kind == "reservation_hold_end":
            return
        if kind == "reservation_hold_start":
            event = candidate
            break
    if event is None:
        return
    identity, started = event.get("hold_id"), event.get("at")
    if not isinstance(identity, str) or not isinstance(started, (int, float)):
        return
    if request_id is not None and not identity.startswith(f"{request_id}:"):
        return
    try:
        if ack_path.read_text(encoding="utf-8") == identity:
            return
    except FileNotFoundError:
        pass
    observed = sum(
        sample.at >= started and sample.telemetry_available and sample.own_tree_mib is not None
        for sample in samples
    )
    if observed >= minimum_samples:
        temporary = ack_path.with_suffix(".tmp")
        temporary.write_text(identity, encoding="utf-8")
        temporary.replace(ack_path)


def bind_reservation_samples(
    hold: ObservedReservation,
    samples: Sequence[TreeMemorySample],
    *,
    minimum_samples: int,
) -> ObservedReservation:
    """Replace worker claims with the parent's independently observed hold coverage."""
    observed = sum(
        hold.started_at <= sample.at <= hold.ended_at
        and sample.telemetry_available
        and sample.own_tree_mib is not None
        for sample in samples
    )
    return hold.model_copy(update={"driver_samples": observed, "required_samples": minimum_samples})
