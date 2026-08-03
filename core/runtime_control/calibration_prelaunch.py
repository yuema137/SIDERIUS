"""Pre-launch lookup of applicable measured duration calibration.

V20 PR C1 / C-C5b.

WHERE THIS RUNS AND WHY IT MATTERS. At the tuner's "[Pre-flight 2/2] Time
check", before the training subprocess is launched. That timing is the whole
point: a time-budget decision made after launch cannot gate the phase it is
meant to gate. `train_engine_sandbox` holds a more complete identity, but it
is already inside the subprocess, so it is the wrong place to ask.

WHAT IT MAY AND MAY NOT DECIDE (O-6, asymmetric on purpose). Historical
evidence may SUPPORT allowing a candidate through; it may never by itself
REJECT one. A stored measurement says what a similar run cost, not what this
run will cost, and rejecting a candidate on that basis is how a subsystem
starts refusing work it was never measured against. Rejection requires a live
measurement of the concrete candidate.

DURATION EVIDENCE IS TIME-ONLY. Nothing here reaches GPU admission. The two
gates are structurally disjoint -- `admission.evaluate_gpu_admission` is
called only from `sandbox_executor`, and this module returns a
`RuntimeEstimate` describing seconds. A millisecond throughput figure must
never influence a VRAM decision, because it says nothing about memory.

FAIL CLOSED, SILENTLY IS NOT ENOUGH. Every refusal carries a reason. A
lookup that returns "no evidence" without saying why is indistinguishable
from a subsystem that is not wired at all -- which is the exact defect this
PR exists to remove.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class PrelaunchCalibrationResult(BaseModel):
    """What the pre-launch lookup found, and why it found nothing.

    `estimate` is present only when an applicable, validated, local record
    was found. `reasons` is populated in every outcome, so an operator can
    always distinguish "no calibration recorded" from "recorded but not
    applicable to this candidate".
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: A `RuntimeEstimate` when applicable evidence was found, else None.
    #: Typed as Any to keep this module free of a circular import.
    estimate: Any = None
    reasons: tuple[str, ...] = ()

    @property
    def found(self) -> bool:
        return self.estimate is not None


def _resolved_identity(
    *,
    context_inputs: Any,
    task_identity: str | None,
    data_shape_class: str | None,
    hardware_uuid: str | None,
    phase: str,
) -> tuple[Any, tuple[str, ...]]:
    """Build the exact-match identity, or say which field is missing.

    No field is defaulted. A guessed device UUID or task would produce an
    identity that matches a record describing something else, which is worse
    than finding nothing.
    """
    from core.runtime_control.calibration_context import (
        build_calibration_context,
        candidate_config_hash,
    )
    from core.runtime_control.registry_schemas import MeasurementIdentity

    missing = [
        name
        for name, value in (
            ("task_identity", task_identity),
            ("data_shape_class", data_shape_class),
            ("hardware_uuid", hardware_uuid),
        )
        if not value
    ]
    if missing:
        return None, (
            "pre-launch identity incomplete, calibration cannot be matched: " + ", ".join(missing),
        )

    from core.runtime_control.calibration_policy import stack_identity
    from core.runtime_control.provenance import capture_software_stack

    context = build_calibration_context(context_inputs)
    identity = MeasurementIdentity(
        measurement_kind="duration",
        task_identity=str(task_identity),
        data_shape_class=str(data_shape_class),
        model_family=context_inputs.model_family,
        candidate_config_hash=candidate_config_hash(context),
        phase=phase,  # type: ignore[arg-type]
        hardware_uuid=str(hardware_uuid),
        runtime_stack_identity=stack_identity(capture_software_stack()),
    )
    return identity, ()


def lookup_applicable_duration(
    *,
    context_inputs: Any,
    task_identity: str | None,
    data_shape_class: str | None,
    hardware_uuid: str | None,
    phase: str = "training",
    registry: Any = None,
    current_environment_id: str | None = None,
) -> PrelaunchCalibrationResult:
    """Applicable validated duration evidence for this candidate, or nothing.

    Every record in the matching bucket is offered to the C-C5a authority
    seam, which enforces identity, bucket state and applicability. Only an
    estimate that survives all three is returned.

    Never raises. A registry that is absent, locked or malformed costs this
    decision its calibration and nothing else -- the caller keeps its existing
    non-authoritative fallback.
    """
    try:
        identity, problems = _resolved_identity(
            context_inputs=context_inputs,
            task_identity=task_identity,
            data_shape_class=data_shape_class,
            hardware_uuid=hardware_uuid,
            phase=phase,
        )
        if identity is None:
            return PrelaunchCalibrationResult(reasons=problems)

        from core.runtime_control.calibration_context import build_calibration_context
        from core.runtime_control.calibration_read import CandidateRequest
        from core.runtime_control.calibration_registry import CalibrationRegistry

        reg = registry if registry is not None else CalibrationRegistry()
        context = build_calibration_context(context_inputs)
        request = CandidateRequest(
            identity=identity,
            # The derived writer's vocabulary: these are the keys a derived
            # record stores, so these are the spans that can exist.
            dimensions={
                "batch_size": float(context["batch_size"]),
                "seg_size": float(context["seg_size"]),
                "param_count": float(context["param_count"]),
            },
        )

        env_id = current_environment_id
        if env_id is None:
            from core.runtime_control.probe_production import (
                collect_execution_environment_profile,
                collect_hardware_compatibility_profile,
            )

            hardware_id = reg.put_hardware_profile(collect_hardware_compatibility_profile())
            env_id = reg.put_environment_profile(
                collect_execution_environment_profile(
                    installation_id=reg.installation_id(),
                    hardware_compatibility_id=hardware_id,
                    concurrency_regime="single_candidate_idle",
                )
            )

        key = identity.identity_key
        considered = 0
        for obs in reg.iter_observations():
            obs_identity = getattr(obs, "identity", None)
            if obs_identity is None or obs_identity.identity_key != key:
                continue
            considered += 1
            estimate = reg.as_estimate(obs, current_environment_id=env_id, request=request)
            # Measured provenance survives ONLY when identity, bucket state
            # and applicability all held. Anything downgraded to a prior is
            # not applicable evidence and is not returned as such.
            if getattr(estimate, "blocking_eligible", False):
                return PrelaunchCalibrationResult(estimate=estimate)

        if considered == 0:
            return PrelaunchCalibrationResult(
                reasons=("no calibration record matches this candidate's identity",)
            )
        return PrelaunchCalibrationResult(
            reasons=(
                f"{considered} record(s) matched the identity but none was "
                "applicable and validated for this candidate",
            )
        )
    except Exception as exc:  # never costs the run its decision
        return PrelaunchCalibrationResult(
            reasons=(f"calibration lookup unavailable ({type(exc).__name__}: {exc})",)
        )


def historical_support_only(
    estimate: Any,
    *,
    predicted_seconds: float,
    budget_seconds: float,
) -> tuple[bool, tuple[str, ...]]:
    """O-6: historical evidence may support ALLOW, never force REJECT.

    Returns ``(may_support_allow, reasons)``. An over-budget historical
    result deliberately returns False rather than a rejection signal: the
    caller keeps whatever verdict it would otherwise have reached, so this
    function has no path by which history alone denies a candidate.

    Asymmetric on purpose. Supporting a candidate on prior evidence risks
    running something that turns out slow, which the budget and the watchdog
    already bound. Rejecting on prior evidence risks refusing work that was
    never measured, which nothing bounds.
    """
    if estimate is None:
        return False, ("no applicable historical evidence",)
    if predicted_seconds <= budget_seconds:
        return True, (
            f"applicable measured history predicts {predicted_seconds:.1f}s "
            f"within the {budget_seconds:.1f}s budget",
        )
    return False, (
        f"applicable measured history predicts {predicted_seconds:.1f}s over "
        f"the {budget_seconds:.1f}s budget; historical evidence may not reject "
        "a candidate on its own -- a live measurement is required",
    )
