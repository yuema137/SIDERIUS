"""Conservative headroom evidence for an explicitly limited GPU process view.

Only actual phase admission uses this condition. Bounded measurement bootstrap
retains its existing resource/deadline controls and never borrows a requirement
from another phase. Ordinary admission remains owned by admission.py.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from core.runtime_control.admission import AdmissionDecision
from core.runtime_control.gpu_accounting import GpuAccountingSnapshot
from core.runtime_control.pair_admission import gib_from_mib, pair_ceiling_gib
from core.runtime_control.process_visibility import (
    GpuExecutionConditions,
    IsolatedHeadroomPolicy,
    declared_visibility,
)


class OccupancyBound(BaseModel):
    """A coherent accounting split, not a guessed attribution of residual bytes."""

    model_config = ConfigDict(frozen=True, strict=True)

    device_total_mib: int = Field(gt=0)
    device_used_mib: int = Field(ge=0)
    own_tree_mib: int = Field(ge=0)
    other_mib: int = Field(ge=0)
    unattributed_mib: int = Field(ge=0)
    per_pid_total_mib: int = Field(ge=0)
    accounting_skew_mib: int

    @model_validator(mode="after")
    def coherent_accounting(self) -> OccupancyBound:
        if (
            self.device_used_mib > self.device_total_mib
            or self.own_tree_mib + self.other_mib != self.per_pid_total_mib
            or self.per_pid_total_mib + self.unattributed_mib != self.device_used_mib
            or self.accounting_skew_mib != self.unattributed_mib
        ):
            raise ValueError("GPU ownership and device readings do not form a coherent bound")
        return self

    @property
    def outside_upper_bound_mib(self) -> int:
        return self.other_mib + self.unattributed_mib


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
    try:
        configured = pair_ceiling_gib() if ceiling_gib is None else ceiling_gib
        if isinstance(configured, bool) or not math.isfinite(configured) or configured <= 0:
            raise ValueError("invalid ceiling")
    except (TypeError, ValueError):
        return environment_refusal(
            "The configured aggregate GPU ceiling is invalid.",
            evidence,
            requirement_source=str(requirement_provenance),
        )
    effective = min(configured, gib_from_mib(bound.device_total_mib))
    aggregate = gib_from_mib(requirement_mib + bound.device_used_mib)
    evidence.update(
        configured_ceiling_gib=configured,
        effective_ceiling_gib=effective,
        retained_own_tree_mib=bound.own_tree_mib,
        current_occupancy_upper_bound_mib=bound.device_used_mib,
        aggregate_upper_bound_gib=aggregate,
        headroom_lower_bound_gib=effective - aggregate,
    )
    if aggregate > effective:
        return environment_refusal(
            f"The conservative aggregate upper bound is {aggregate:.2f} GiB against "
            f"a {effective:.2f} GiB ceiling. Retry when environment evidence establishes sufficient headroom.",
            evidence,
            requirement_source=str(requirement_provenance),
        )
    return AdmissionDecision(
        admitted=True,
        requirement_source=str(requirement_provenance),
        reason=(
            f"Conservative aggregate upper bound {aggregate:.2f} GiB fits the "
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
