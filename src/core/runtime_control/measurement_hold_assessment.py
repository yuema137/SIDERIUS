"""Shared consistency checks for a driver-observed allocator reservation hold."""

from core.runtime_control.gpu_measurement_runner import PhaseMeasurement


def reservation_hold_refusal(
    observed: PhaseMeasurement, *, request_id: str, expected_count: int
) -> str | None:
    name = observed.phase
    peak = observed.allocator_reserved_peak_bytes
    holds = observed.observed_reservations
    if peak is None or not holds or len(holds) != expected_count:
        return f"Missing {name} reservation hold evidence"
    for sequence, hold in enumerate(holds):
        if (
            not hold.acknowledged
            or hold.required_samples < 1
            or hold.driver_samples < hold.required_samples
            or hold.hold_id != f"{request_id}:{name}:{sequence}"
            or hold.reserved_before_bytes != hold.reserved_after_bytes
            or hold.started_at < observed.started_at
            or hold.ended_at > observed.ended_at
        ):
            return f"Incomplete or inconsistent {name} reservation hold"
    if peak > max(hold.reserved_before_bytes for hold in holds):
        return f"{name} reserved high-water was not resident during a driver-observed hold"
    return None
