"""
core/runtime_control/realized_memory.py

V21 PR B2 — join a phase's REALIZED peak memory to what it was ADMITTED
against, as measured facts and nothing more.

The gap this closes (PR B design doc §0.3, §0.7): the system admitted a
phase against a *predicted* peak and never looked back. Realized memory
was not merely uncompared — it was not measured anywhere in the
production path. So the only symptom of a bad forecast was a crash, and a
crash is reported as a crash, not as a broken forecast.

    admitted   evaluate_vram_skill -> estimated_gb / limit_gb / vram_budget_gb
    realized   RuntimeVerificationSession.record_phase_peak_memory
                 -> sidecar -> runtime_verification block
    joined     HERE

**This module chooses no semantics.** Q-B-1 — whether the operator's VRAM
budget means an admission estimate (S1), an enforced cap (S2), or an
estimate plus recorded exceedance (S3) — is deliberately unfrozen until
B0, and all three must remain expressible as readings of the same row.
So the vocabulary here is comparative, never judgmental:

    realized_above_threshold      one measured number exceeded another
    NOT budget_breach             a verdict, which presumes S2 or S3

The two deltas are kept SEPARATE on purpose:

    realized - estimated   forecast error     "the prediction was wrong"
    realized - threshold   headroom consumed  "the budget was tight"

They diverge whenever the physical cap rather than the operator budget was
binding, and collapsing them into one number would destroy exactly the
signal B0 needs to tell those two situations apart.

Design doc: docs/design/v21_priorities/pr_b_resource_budget_semantics.md
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.runtime_control.records import MemoryCompleteness

_MIB_PER_GB = 1024.0

BindingConstraint = Literal["operator_budget", "physical_cap", "none", "unknown"]


class RealizedVsAdmittedMemory(BaseModel):
    """Measured facts about one phase's memory, admitted vs realized.

    Every field is either something that was measured, something the
    operator configured, or arithmetic over those two. Nothing here is a
    policy decision, and a reviewer must not be able to infer S1/S2/S3
    from the schema.
    """

    model_config = ConfigDict(frozen=True)

    phase: str = Field(min_length=1)

    # ── what the candidate was admitted against ──────────────────────────
    admission_estimated_peak_mib: int | None = Field(
        default=None, ge=0, description="The forecast peak the admission decision used."
    )
    effective_admission_threshold_mib: int | None = Field(
        default=None,
        ge=0,
        description="The cap the forecast was compared against: min(physical, operator budget).",
    )
    operator_budget_mib: int | None = Field(default=None, ge=0)
    physical_cap_mib: int | None = Field(default=None, ge=0)
    binding_constraint: BindingConstraint = Field(
        default="unknown",
        description=(
            "Which cap actually set the threshold. Distinguishes 'the operator "
            "budget was tight' from 'the card was small', which the two deltas "
            "below cannot express on their own."
        ),
    )

    # ── what actually happened ───────────────────────────────────────────
    realized_peak_mib: int | None = Field(default=None, ge=0)
    realized_peak_source: Literal["reserved", "allocator", "none"] = Field(
        default="none",
        description=(
            "Which counter the realized peak came from. `reserved` includes "
            "allocator blocks held but unused and is closer to driver-visible "
            "usage; `allocator` is tensor memory only and is a strict floor."
        ),
    )
    measurement_completeness: MemoryCompleteness = "unavailable"
    owning_process_pid: int | None = None

    # ── the two deltas, deliberately not merged ──────────────────────────
    realized_minus_estimated_mib: int | None = Field(
        default=None, description="FORECAST ERROR. None when either side is unknown."
    )
    realized_minus_threshold_mib: int | None = Field(
        default=None, description="HEADROOM CONSUMED. None when either side is unknown."
    )
    realized_above_threshold: bool | None = Field(
        default=None,
        description=(
            "A comparison, not a verdict. **None means unknown** — never False. "
            "Inferring compliance from a missing measurement is how a silent "
            "regression comes to look exactly like a healthy run."
        ),
    )

    @model_validator(mode="after")
    def _unknown_stays_unknown(self) -> RealizedVsAdmittedMemory:
        if self.realized_peak_mib is None and self.realized_above_threshold is not None:
            raise ValueError(
                "realized_above_threshold must be None when there is no realized "
                "peak. A missing measurement is 'unknown', never 'within threshold'."
            )
        return self


def read_process_peak_mib() -> tuple[int | None, int | None, int | None]:
    """This process's peak CUDA memory, as ``(allocator, reserved, device)``.

    Called from inside a phase's own subprocess, which is what makes the
    attribution structural: the counters are per-process, so a peer using
    the same card cannot inflate them. That is the mechanism behind the
    binding rule that contention is context, never candidate usage.

    Returns ``(None, None, None)`` when there is no CUDA device or the
    read fails. **Never raises and never substitutes a zero** — a failed
    read is missing evidence, and a measured 0 MiB would be a different
    and much stronger claim.
    """
    try:
        import torch

        if not torch.cuda.is_available():
            return None, None, None
        index = torch.cuda.current_device()
        allocator = int(torch.cuda.max_memory_allocated(index) // (1024 * 1024))
        reserved = int(torch.cuda.max_memory_reserved(index) // (1024 * 1024))
        return allocator, reserved, index
    except Exception:  # pragma: no cover — defensive; absence must not crash a phase
        return None, None, None


def reset_process_peak() -> None:
    """Zero the peak counters so the next reading covers one phase only.

    Without this the peak is cumulative over the process lifetime, so a
    phase would inherit the high-water mark of everything before it —
    including setup and any verification warm-up — and the recorded
    "phase peak" would silently be a process peak.
    """
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
    except Exception:  # pragma: no cover — defensive
        pass


def _gb_to_mib(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return max(round(float(value) * _MIB_PER_GB), 0)
    except (TypeError, ValueError):
        return None


def _binding(operator_mib: int | None, physical_mib: int | None) -> BindingConstraint:
    if operator_mib is None and physical_mib is None:
        return "unknown"
    if operator_mib is None:
        return "physical_cap"
    if physical_mib is None:
        return "operator_budget"
    return "operator_budget" if operator_mib < physical_mib else "physical_cap"


def realized_vs_admitted(
    phase: str,
    *,
    resource_check: dict[str, Any] | None,
    runtime_verification: dict[str, Any] | None,
    physical_cap_gb: float | None = None,
) -> RealizedVsAdmittedMemory | None:
    """Join the admission forecast to the realized peak for one phase.

    Args:
        phase: the phase name as keyed in the observation's ``components``.
        resource_check: ``evaluate_vram_skill.run_skill``'s returned dict —
            supplies ``estimated_gb`` (the forecast), ``limit_gb`` (the
            effective threshold) and ``vram_budget_gb`` (the operator's
            configured budget, ``None`` when unset).
        runtime_verification: the sidecar block the phase's subprocess
            wrote, as read by ``_read_runtime_observation_sidecar``.
        physical_cap_gb: the hardware ceiling, when the caller knows it.

    Returns:
        ``None`` only when there is nothing at all to record — neither an
        admission forecast nor a realized measurement. A row with an
        ``unavailable`` measurement is still worth persisting: it says the
        phase ran and was not measured, which is different from silence.
    """
    rc = resource_check or {}
    estimated_mib = _gb_to_mib(rc.get("estimated_gb"))
    threshold_mib = _gb_to_mib(rc.get("limit_gb"))
    operator_mib = _gb_to_mib(rc.get("vram_budget_gb"))
    physical_mib = _gb_to_mib(physical_cap_gb)

    component = ((runtime_verification or {}).get("components") or {}).get(phase) or {}
    realized_block = component.get("realized_memory") or {}

    reserved = realized_block.get("reserved_peak_mib")
    allocator = realized_block.get("allocator_peak_mib")
    if reserved is not None:
        realized_mib, source = int(reserved), "reserved"
    elif allocator is not None:
        realized_mib, source = int(allocator), "allocator"
    else:
        realized_mib, source = None, "none"

    completeness: MemoryCompleteness = realized_block.get("measurement_completeness") or (
        "unavailable"
    )

    if estimated_mib is None and threshold_mib is None and realized_mib is None:
        return None

    # Both deltas are None unless BOTH of their operands are known. A
    # delta computed against a missing operand would be a fabricated
    # number wearing the same field name as a measured one.
    minus_estimated = (
        realized_mib - estimated_mib
        if realized_mib is not None and estimated_mib is not None
        else None
    )
    minus_threshold = (
        realized_mib - threshold_mib
        if realized_mib is not None and threshold_mib is not None
        else None
    )
    above = (
        realized_mib > threshold_mib
        if realized_mib is not None and threshold_mib is not None
        else None
    )

    return RealizedVsAdmittedMemory(
        phase=phase,
        admission_estimated_peak_mib=estimated_mib,
        effective_admission_threshold_mib=threshold_mib,
        operator_budget_mib=operator_mib,
        physical_cap_mib=physical_mib,
        binding_constraint=_binding(operator_mib, physical_mib),
        realized_peak_mib=realized_mib,
        realized_peak_source=source,
        measurement_completeness=completeness,
        owning_process_pid=realized_block.get("owning_process_pid"),
        realized_minus_estimated_mib=minus_estimated,
        realized_minus_threshold_mib=minus_threshold,
        realized_above_threshold=above,
    )
