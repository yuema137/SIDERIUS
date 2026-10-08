"""Project validated runtime admissions into existing executor status vocabulary."""

from typing import Any

from core.runtime_control.records import RuntimeObservation


def runtime_refusal_status(
    observation: dict[str, Any] | None, *, completed_policy_only: bool = False
) -> dict[str, Any] | None:
    """Return a refusal only when the validated sidecar explicitly records one."""
    if observation is None:
        return None
    parsed = RuntimeObservation.model_validate(observation)
    if (
        completed_policy_only
        and parsed.runtime_policy.get("runtime_completion_policy") != "completed-workload-v1"
    ):
        return None
    admission = parsed.admission
    if admission is None or admission.decision != "rejected":
        return None
    reason = admission.reason or ""
    infrastructure = admission.failure_class == "infrastructure"
    return {
        "status": "aborted_infrastructure" if infrastructure else "rejected_time_risk",
        "message": (
            f"runtime evidence channel failed: {reason}"
            if infrastructure
            else f"runtime verification rejected the attempt: {reason}"
        ),
        "runtime_verification": observation,
    }
