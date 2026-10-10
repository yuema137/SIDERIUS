"""Build and describe static decisions without granting GPU measurement authority."""

from typing import Any, Literal

from agent.schemas.preflight import StaticPhaseDecision, StaticPreflightEvidence
from agent.skills.evaluate_vram_skill import compute_intensity


def phase_decision(
    *,
    phase: Literal["training", "inference"],
    batch_size: int,
    cap_bytes: int,
    estimate_bytes: int | None,
    segmentation_size: int | None,
    estimator: str | None = None,
) -> StaticPhaseDecision:
    limit = compute_intensity.configured_limit() if segmentation_size is not None else None
    return StaticPhaseDecision(
        phase=phase,
        batch_size=batch_size,
        vram_cap_bytes=cap_bytes,
        vram_estimate_bytes=estimate_bytes,
        estimator=(
            estimator
            or ("training_saved_tensors_v1" if phase == "training" else "inference_leaf_sum_v1")
        )
        if estimate_bytes is not None
        else None,
        intensity_product=(
            compute_intensity.compute_intensity(batch_size, segmentation_size)
            if segmentation_size is not None and limit is not None
            else None
        ),
        intensity_limit=limit,
    )


def render_static_refusal(evidence: StaticPreflightEvidence) -> str:
    lines = []
    for phase in evidence.phases:
        if not phase.binding_caps:
            continue
        if "vram" in phase.binding_caps:
            lines.append(
                f"{phase.phase} B={phase.batch_size}: structural estimate "
                f"{phase.vram_estimate_bytes:,} bytes exceeds the configured cap "
                f"{phase.vram_cap_bytes:,} bytes ({phase.estimator})."
            )
        if "compute_intensity" in phase.binding_caps:
            lines.append(
                f"{phase.phase} B={phase.batch_size}: compute-intensity product "
                f"{phase.intensity_product:,} exceeds the rule limit {phase.intensity_limit:,}."
            )
    if not lines:
        raise ValueError("Cannot render a static refusal from passing evidence")
    return (
        " ".join(lines)
        + " This is a static preflight refusal, not a measured GPU peak or CUDA OOM."
    )


def static_refusal_suggestion(evidence: StaticPreflightEvidence) -> str:
    parts = []
    if "vram" in evidence.binding_caps:
        parts.append(
            "Inspect the structural estimate and its assumptions; actual GPU capacity "
            "was not established. Do not infer that a particular layer must shrink."
        )
    if "compute_intensity" in evidence.binding_caps:
        parts.append(
            "Check task-supported batch and segmentation settings against the recorded intensity rule."
        )
    return " ".join(parts)


def preflight_memory_fields(resource_check: dict[str, Any]) -> dict[str, Any]:
    """Preserve validated observations; absent historical evidence stays absent."""
    raw = resource_check.get("static_preflight_evidence")
    if raw is None:
        return {}
    evidence = StaticPreflightEvidence.model_validate(raw)
    outcome = resource_check.get("preflight_outcome")
    expected = "STATIC_PREFLIGHT_REFUSAL" if evidence.binding_caps else "COMPLETED_MEASUREMENT"
    if outcome != expected:
        raise ValueError("Static preflight outcome contradicts its decision evidence")
    result = {
        "static_preflight_evidence": evidence.model_dump(mode="json"),
        "preflight_outcome": outcome,
    }
    from core.runtime_control.inference_refusal_verification import verification_from_result

    verification = verification_from_result(resource_check)
    if verification is not None:
        result["inference_verification"] = verification.model_dump(mode="json")
    return result
