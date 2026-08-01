"""Parent-side bridge from the isolated pre-flight worker to production.

Why this module exists. The production VRAM pre-flight used to run inside
the chain's long-lived parent, so that process created a CUDA context and
held the allocator's reserved pool for a whole iteration — 6,962 MiB
measured, still held three minutes after its child had exited (V20
`v20_priorities.md` §6.1). `run_isolated_preflight` was built to run that
work in a child, was GPU-validated, and had no production call site.

Wiring it in is not a function substitution. Production consumes a
thirteen-field result contract; the worker returns a bounded typed
disposition. This module restores the former from the latter so the
tuner's consumer needs no change.

Division of responsibility, deliberately strict:

* the **worker** measures, and forwards the agent-facing text the skill
  already produced (`KillerReport.verdict` / `.suggestion`);
* this **adapter** maps and forwards. It composes no operator-facing
  prose, decides no policy, and derives no downsizing recommendation.

That split matters more than it looks. Two text generators — one in the
skill, one here — would drift, and they would drift in the feedback the
agent acts on, where nobody is reading. So the rule is: **if a string
reaches the agent, it came from the worker.**

Two invariants this module exists to hold:

* the parent never imports torch, never constructs the candidate, and
  never initializes CUDA on this path;
* an isolated-worker failure **never** falls back to the in-process CUDA
  pre-flight. A fallback would resurrect the original defect on exactly
  the exception paths nobody watches.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, get_args

from agent.skills.evaluate_vram_skill.isolated_probe import (
    HardwareSnapshot,
    IsolatedProbeSpec,
    PreflightOutcome,
    default_worker_memory_limit_bytes,
    run_isolated_preflight,
)

__all__ = [
    "OUTCOME_TO_LEGACY",
    "PreflightWiringError",
    "adapt_result",
    "build_hardware_snapshot",
    "run_production_preflight",
]


class PreflightWiringError(RuntimeError):
    """The pre-flight could not be *attempted* correctly.

    Distinct from a candidate verdict: this says the measurement system
    was mis-wired, not that the model is too large. It is raised rather
    than degraded into a result, because a configuration error that looks
    like a measurement is the failure mode this whole PR exists to remove.
    """


#: Exhaustive ``PreflightOutcome`` → ``(legacy status, feasible)``.
#:
#: ``feasible=False`` is reserved for the two outcomes that establish the
#: model does not fit. Everything else leaves it ``None``, which the tuner
#: reads through ``.get("feasible", True)``.
#:
#: MEASURED_PEAK_ABOVE_VRAM_CAP and MEASURED_CUDA_OOM deliberately share a
#: legacy pair (operator decision D-A1): PR A does not change control flow
#: while wiring. They stay distinguishable through ``preflight_outcome``.
OUTCOME_TO_LEGACY: dict[str, tuple[str, bool | None]] = {
    "COMPLETED_MEASUREMENT": ("success", True),
    "MEASURED_PEAK_ABOVE_VRAM_CAP": ("success", False),
    "MEASURED_CUDA_OOM": ("success", False),
    "SCHEMA_REJECTED": ("schema_violation", None),
    "MEASURED_HARD_TIMEOUT": ("timeout", None),
    "INCONCLUSIVE_MEASUREMENT": ("inconclusive", None),
    "HOST_MEMORY_ALLOCATION_FAILURE": ("host_memory", None),
    "MEASURED_HOST_MEMORY_EXCEEDED": ("host_memory", None),
    "PROBE_INFRASTRUCTURE_FAILURE": ("error", None),
}


def build_hardware_snapshot(hardware_context: Any) -> HardwareSnapshot:
    """Freeze the hardware facts the worker needs.

    The parent resolves the hardware once and sends these values. A
    worker that discovered for itself could disagree with its parent
    about the cap, the device or the fingerprint, and that disagreement
    would be invisible — it would look like a measurement rather than a
    configuration error (D-A3).
    """
    if hardware_context is None:
        raise PreflightWiringError(
            "hardware_context is required for the production pre-flight. "
            "Discovery fallback is deliberately unavailable here: parent "
            "and worker must share one resolved cap, device and "
            "fingerprint (V20 PR A, D-A3)."
        )
    fingerprint = (
        getattr(hardware_context, "compatibility_id", None)
        or getattr(hardware_context, "fingerprint", None)
        or f"{hardware_context.device_name}|{hardware_context.total_memory_bytes}"
    )
    return HardwareSnapshot(
        usable_cap_bytes=int(hardware_context.usable_cap_bytes),
        usable_cap_gb=float(hardware_context.usable_cap_gb),
        total_memory_bytes=int(hardware_context.total_memory_bytes),
        total_memory_gb=float(hardware_context.total_memory_gb),
        device_name=str(hardware_context.device_name),
        device_available=bool(hardware_context.device_available),
        hardware_fingerprint=str(fingerprint),
        device_index=int(getattr(hardware_context, "logical_index", 0) or 0),
        cuda_visible_devices=os.environ.get("CUDA_VISIBLE_DEVICES"),
    )


#: How production runs the VRAM pre-flight, stamped into the iteration
#: manifest so a run's provenance is auditable after the fact (PR A §11).
#:
#: It lives here, in the module that *is* the isolated path, rather than
#: as a literal in the manifest writer, so the two cannot drift apart
#: independently. What it records is which mechanism this build ships;
#: that production actually reaches it is proven separately, by the
#: reachability guardrails in
#: ``tests/unit/guardrails/test_preflight_production_reachability.py``.
PREFLIGHT_EXECUTION_MODE = "isolated_subprocess"


def _timeout_record(payload: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the shape ``_raise_if_inconclusive`` reads."""
    operation = payload.get("timeout_operation")
    if operation is None and payload.get("phase") is None:
        return {}
    return {
        "operation": operation or payload.get("phase"),
        "budget_seconds": payload.get("timeout_budget_seconds"),
        "elapsed_seconds": payload.get("timeout_elapsed_seconds"),
        "phase": payload.get("phase"),
    }


def adapt_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Map one bounded worker payload onto the legacy result contract.

    Raises on an unmapped outcome. A default branch here would silently
    absorb a contract drift between the worker's vocabulary and this
    table — the class of error that is only discovered in production.
    """
    outcome = payload.get("outcome")
    if outcome not in OUTCOME_TO_LEGACY:
        raise PreflightWiringError(
            f"unmapped pre-flight outcome {outcome!r}. Every "
            f"PreflightOutcome must have an explicit legacy mapping; "
            f"known: {sorted(OUTCOME_TO_LEGACY)}"
        )
    status, feasible = OUTCOME_TO_LEGACY[outcome]

    result: dict[str, Any] = {
        "status": status,
        # Additive, per D-A1: the legacy control flow is unchanged, but
        # the typed cause survives into records and artifacts.
        "preflight_outcome": outcome,
        "message": payload.get("detail", ""),
        # Forwarded, never composed here — see the module docstring.
        "verdict": payload.get("verdict") or payload.get("detail", ""),
        "suggestion": payload.get("suggestion", ""),
    }
    if feasible is not None:
        result["feasible"] = feasible

    for key in (
        "estimated_gb",
        "inference_batch",
        "limit_gb",
        "dominant_phase",
        "memory_killer",
        "violations",
        "offending_config",
        "schema_field",
        "schema_message",
        "truncated",
        # A5 repair — ``truncated`` alone says something was dropped but
        # not how much. The worker measures the count; forwarding one
        # without the other loses the measured part.
        "violations_omitted_count",
    ):
        if payload.get(key) is not None:
            result[key] = payload[key]

    if payload.get("realized_parameter_count") is not None:
        result["num_params"] = payload["realized_parameter_count"]

    record = _timeout_record(payload)
    if record:
        result["timeout_record"] = record

    # ``inference_batch_uncalibrated`` is deliberately absent: the skill
    # removed it (wrapper.py:34) while the tuner still reads it, so both
    # branches are already dead. Synthesizing it here would revive dead
    # code inside a wiring change. Tracked as FU-A-1.
    return result


def run_production_preflight(
    *,
    model_type: str,
    model_config: dict[str, Any],
    train_config: dict[str, Any],
    loss_config: dict[str, Any],
    vram_budget_gb: float | None,
    hardware_context: Any,
    workspace: str | Path,
    label: str,
    deadline_seconds: float = 900.0,
) -> dict[str, Any]:
    """Run one candidate's pre-flight in a child and return the legacy dict.

    ``vram_budget_gb=None`` means *no operator ceiling*, not *unset*: the
    worker then uses the parent's frozen ``usable_cap_gb`` rather than
    rediscovering a cap of its own (D-A4).
    """
    snapshot = build_hardware_snapshot(hardware_context)
    workdir = Path(workspace) / "preflight_workers"
    spec = IsolatedProbeSpec(
        label=label,
        model_type=model_type,
        model_config_payload=dict(model_config or {}),
        train_config=dict(train_config or {}),
        loss_config=dict(loss_config or {}),
        vram_budget_gb=vram_budget_gb,
        result_path=str(workdir / f"{label}.json"),
        worker_memory_limit_bytes=default_worker_memory_limit_bytes(),
        hardware=snapshot,
    )
    # No try/except around this call: a worker failure is already a typed
    # PROBE_INFRASTRUCTURE_FAILURE, and catching it to retry in-process is
    # exactly the silent fallback this module forbids.
    probe = run_isolated_preflight(spec, deadline_seconds=deadline_seconds)
    result = adapt_result(probe.model_dump())
    result["effective_vram_limit_gb"] = spec.effective_cap_gb()
    result["effective_limit_source"] = spec.effective_limit_source()
    result["operator_vram_budget_gb"] = vram_budget_gb
    return result


def _assert_mapping_is_exhaustive() -> None:
    """Fail at import if the vocabulary and the table have diverged."""
    declared = set(get_args(PreflightOutcome))
    mapped = set(OUTCOME_TO_LEGACY)
    if declared != mapped:
        raise PreflightWiringError(
            f"OUTCOME_TO_LEGACY is not exhaustive. "
            f"unmapped={sorted(declared - mapped)} "
            f"unknown={sorted(mapped - declared)}"
        )


_assert_mapping_is_exhaustive()
