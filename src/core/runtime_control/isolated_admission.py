"""Conservative headroom evidence for an explicitly limited GPU process view.

Only actual phase admission uses this condition. Bounded measurement bootstrap
retains its existing resource/deadline controls and never borrows a requirement
from another phase. Ordinary admission remains owned by admission.py.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import ValidationError

from core.runtime_control.admission import AdmissionDecision
from core.runtime_control.gpu_accounting import GpuAccountingSnapshot
from core.runtime_control.gpu_accounting import OccupancyBound as OccupancyBound
from core.runtime_control.gpu_requirement_evidence import GpuRequirementOwnership
from core.runtime_control.pair_admission import gib_from_mib, resolve_gpu_ceiling
from core.runtime_control.process_visibility import (
    GpuExecutionConditions,
    IsolatedHeadroomPolicy,
    declared_visibility,
)


def environment_refusal(
    detail: str, evidence: dict[str, Any], *, requirement_source: str = "unavailable"
) -> AdmissionDecision:
    """An unconditional isolated-mode stop, with no candidate-capacity claim."""
    return AdmissionDecision(
        admitted=False,
        reason_code="environment_headroom_unproven",
        requirement_source=requirement_source,
        reason=(
            f"GPU phase not started: environment headroom was not demonstrated. {detail} "
            "This is an execution-evidence limitation, not evidence that the model is too large; "
            "do not reduce model or batch settings from this refusal."
        ),
        evidence=evidence,
    )


def evaluate_isolated_admission(
    *,
    snapshot: Any,
    requirement_mib: float | None,
    requirement_provenance: str | None,
    mode: str,
    ceiling_gib: float | None,
    sampling_error: str | None,
    requirement_ownership: GpuRequirementOwnership | None = None,
    requirement_error: str | None = None,
) -> AdmissionDecision:
    """Require new-worker demand plus all retained pre-spawn occupancy to fit.

    Both production callers sample after the measurement worker exits and
    before the phase worker starts. The requirement describes that new worker;
    the persistent parent's CUDA memory is additional, not replaceable demand.
    """
    from core.runtime_control.admission import ACCEPTED_MODES, AUTHORITATIVE_PROVENANCE

    evidence: dict[str, Any] = {
        "mode": mode,
        "effective_execution_conditions": IsolatedHeadroomPolicy().model_dump(mode="json"),
    }
    try:
        visibility = declared_visibility() or getattr(snapshot, "process_visibility", None)
        conditions = GpuExecutionConditions.model_validate({"process_visibility": visibility})
    except ValidationError:
        return environment_refusal(
            "The explicit GPU process-visibility declaration is invalid.", evidence
        )
    evidence["effective_execution_conditions"] = conditions.model_dump(mode="json")
    if sampling_error is not None:
        evidence["sampling_error"] = sampling_error
        return environment_refusal(
            "Obtain a current device occupancy sample before retrying.", evidence
        )
    if not isinstance(snapshot, GpuAccountingSnapshot) or not snapshot.telemetry_available:
        return environment_refusal("A current typed GPU occupancy sample is unavailable.", evidence)
    evidence["observed_accounting"] = snapshot.model_dump(mode="json")
    try:
        bound = OccupancyBound.model_validate(
            snapshot.model_dump(include=set(OccupancyBound.model_fields))
        )
    except ValidationError:
        return environment_refusal(
            "GPU accounting is incomplete or inconsistent; refresh the device evidence.", evidence
        )
    evidence["outside_upper_bound_mib"] = bound.outside_upper_bound_mib
    if mode not in ACCEPTED_MODES:
        return environment_refusal("The phase admission mode is invalid.", evidence)
    if (
        requirement_provenance not in AUTHORITATIVE_PROVENANCE
        or not isinstance(requirement_mib, (int, float))
        or isinstance(requirement_mib, bool)
        or not math.isfinite(requirement_mib)
        or requirement_mib <= 0
    ):
        return environment_refusal(
            "An authoritative GPU requirement for this exact phase is missing. "
            "Provide phase-specific measurement evidence; training evidence cannot substitute "
            "for inference. The current default trial/inference paths do not supply this evidence.",
            evidence,
        )
    evidence.update(requirement_mib=requirement_mib, requirement_provenance=requirement_provenance)
    evidence["requirement_ownership"] = (
        requirement_ownership.model_dump(mode="json")
        if isinstance(requirement_ownership, GpuRequirementOwnership)
        else None
    )
    ownership_issue = requirement_error
    if not isinstance(requirement_ownership, GpuRequirementOwnership):
        ownership_issue = ownership_issue or "Requirement ownership is missing or invalid."
    elif requirement_ownership.device_uuid != snapshot.device.uuid:
        ownership_issue = "Requirement and current occupancy describe different GPU UUIDs."
    else:
        ownership_issue = ownership_issue or requirement_ownership.applicability_refusal(snapshot)
    if ownership_issue is not None:
        evidence["requirement_error"] = ownership_issue
        return environment_refusal(ownership_issue, evidence)

    try:
        limits = resolve_gpu_ceiling(
            ceiling_gib=ceiling_gib, measured_capacity_gib=gib_from_mib(bound.device_total_mib)
        )
    except (TypeError, ValueError) as error:
        return environment_refusal(
            f"The aggregate GPU ceiling could not be resolved: {error}",
            evidence,
            requirement_source=str(requirement_provenance),
        )
    effective = limits.effective_gib
    aggregate = gib_from_mib(requirement_mib + bound.device_used_mib)
    if not math.isfinite(aggregate):
        return environment_refusal("Aggregate GPU demand must be finite.", evidence)
    evidence.update(
        configured_ceiling_gib=limits.operator_ceiling_gib,
        ceiling_resolution=limits.model_dump(mode="json"),
        effective_ceiling_gib=effective,
        retained_own_tree_mib=bound.own_tree_mib,
        current_device_used_mib=bound.device_used_mib,
        aggregate_gib=aggregate,
        headroom_gib=effective - aggregate,
    )
    if aggregate > effective:
        return environment_refusal(
            f"Measured demand plus current occupancy is {aggregate:.2f} GiB against "
            f"a {effective:.2f} GiB ceiling. Retry when environment evidence establishes sufficient headroom.",
            evidence,
            requirement_source=str(requirement_provenance),
        )
    return AdmissionDecision(
        admitted=True,
        requirement_source=str(requirement_provenance),
        reason=(
            f"Measured demand plus current occupancy {aggregate:.2f} GiB fits the "
            f"{effective:.2f} GiB ceiling under namespace-limited visibility."
        ),
        evidence=evidence,
    )


def isolated_policy_error_result(
    snapshot: object, *, phase: str, mode: str, error: Exception
) -> dict[str, Any] | None:
    """Keep a failed isolated-mode policy from taking the legacy trial fallback."""
    from core.runtime_control.process_visibility import requires_isolated_admission

    if not requires_isolated_admission(snapshot):
        return None
    failure = environment_refusal(
        "The admission check failed; repair the execution evidence before retrying.",
        {
            "phase": phase,
            "mode": mode,
            "policy_error": str(error),
            "effective_execution_conditions": IsolatedHeadroomPolicy().model_dump(mode="json"),
        },
    )
    return {
        "status": "skipped_resource_admission",
        "message": failure.reason,
        "admission": failure.model_dump(mode="json"),
    }


def missing_device_identity_result(
    device_available: object, *, phase: str
) -> dict[str, Any] | None:
    """Only proven CPU execution may skip an isolated phase's GPU identity check."""
    from core.runtime_control.process_visibility import (
        DeviceAvailability,
        requires_isolated_admission,
    )

    if not requires_isolated_admission():
        return None
    evidence: dict[str, Any] = {
        "phase": phase,
        "effective_execution_conditions": IsolatedHeadroomPolicy().model_dump(mode="json"),
    }
    try:
        conditions = GpuExecutionConditions.model_validate(
            {"process_visibility": declared_visibility()}
        )
        availability = DeviceAvailability.model_validate({"device_available": device_available})
    except ValidationError:
        detail = "The transported device availability or process-visibility declaration is invalid."
    else:
        evidence["effective_execution_conditions"] = conditions.model_dump(mode="json")
        evidence["device_available"] = availability.device_available
        if availability.device_available is False:
            return None
        detail = (
            "No verified GPU device identity was supplied. Transport the existing hardware "
            "discovery result; only explicit device_available=False establishes the CPU path."
        )
    refusal = environment_refusal(detail, evidence)
    return {
        "status": "skipped_resource_admission",
        "message": refusal.reason,
        "admission": refusal.model_dump(mode="json"),
    }
