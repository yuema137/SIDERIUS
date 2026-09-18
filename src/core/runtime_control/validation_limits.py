"""Shared consistency checks for diagnostic execution limits."""

from __future__ import annotations


def validate_phase_deadline(max_phase_seconds: float | None, *, watchdog_enabled: bool) -> None:
    """Refuse a recorded phase limit that no enabled mechanism can enforce."""
    if max_phase_seconds is not None and not watchdog_enabled:
        raise ValueError(
            "validation_max_phase_seconds requires runtime_watchdog_enabled=True: "
            "the watchdog is what enforces the deadline, so without it the "
            "ceiling would be recorded and never applied. Enable --runtime_watchdog "
            "for this diagnostic limit, or omit --validation_max_phase_seconds "
            "to keep the phase watchdog disabled."
        )
