"""Executable replay — bounded probes for candidates that still exist (C11).

Metadata replay says what the stopped run BELIEVED. Executable replay
measures what is actually true, but only for candidates with a loadable
implementation. That restriction is the whole design: the drafts the
uncalibrated formula rejected were never implemented, so no amount of
tooling can recover their real cost, and a report that quietly probed
"something similar" would manufacture the evidence it was meant to find.

Every probe here goes through the SAME bounded-probe path production
uses (C6/C9b), so a measurement produced by replay is comparable with
one produced by a live run — same caps, same contention discipline, same
observation records.

Real GPU execution is operator-gated. `plan_executable_replay` reports
what WOULD run without touching a device.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tools.runtime_replay.probe_config import ReplayProbeConfig

from tools.runtime_replay.schemas import (
    MeasuredRuntime,
    ReplayCandidate,
    ReplayReport,
)


def eligible_candidates(report: ReplayReport) -> tuple[ReplayCandidate, ...]:
    """Candidates a probe could actually run: implementation present and
    not a pre-implementation draft."""
    return tuple(
        candidate
        for candidate in report.candidates
        if candidate.implementation_available and candidate.stage == "surviving_proposal"
    )


def plan_executable_replay(report: ReplayReport) -> dict[str, Any]:
    """What an executable replay would do. Touches nothing."""
    eligible = eligible_candidates(report)
    skipped = [c for c in report.candidates if c not in eligible]
    return {
        "eligible": [c.model_name for c in eligible],
        "skipped": [
            {
                "model_name": c.model_name,
                "stage": c.stage,
                "reason": c.implementation_detail or "no loadable implementation",
            }
            for c in skipped
        ],
        "probes": len(eligible),
        "gpu_required": bool(eligible),
    }


def run_executable_replay(
    report: ReplayReport,
    *,
    probe: Callable[[ReplayCandidate], MeasuredRuntime],
    model_config: dict[str, Any] | None = None,
) -> ReplayReport:
    """Probe every eligible candidate and return an EXECUTABLE report.

    Candidates without an implementation are carried through UNCHANGED —
    they keep `measured=None`, which the schema then reads as "no runtime
    truth for this candidate". They are never dropped: a report that
    silently omitted them would read as though every candidate had been
    validated.
    """
    eligible = {id(c) for c in eligible_candidates(report)}
    updated: list[ReplayCandidate] = []
    for candidate in report.candidates:
        if id(candidate) not in eligible:
            updated.append(candidate)
            continue
        measured = probe(candidate)
        updated.append(candidate.model_copy(update={"measured": measured}))
    return ReplayReport(
        mode="executable",
        snapshot_root=report.snapshot_root,
        snapshot_integrity=report.snapshot_integrity,
        integrity_detail=report.integrity_detail,
        candidates=tuple(updated),
        notes=(
            *report.notes,
            "Measured numbers come from the same bounded probe production uses; "
            "they describe the candidate AS IT EXISTS TODAY, on this machine.",
            "Candidates without a measurement were never implemented — their "
            "original verdicts remain unverifiable in both directions.",
        ),
    )


def production_probe(
    *, config: ReplayProbeConfig, output_dir: str
) -> Callable[[ReplayCandidate], MeasuredRuntime]:
    """Run real workers with caller-owned artifacts and explicit task semantics."""
    from pathlib import Path
    from tempfile import mkdtemp
    from typing import cast

    from core.runtime_control.probe_production import probe_device_vram_gb
    from core.runtime_control.probe_subprocess import (
        ProbeInfrastructureFailure,
        ProbeWorkerSpec,
        run_worker,
    )
    from core.runtime_control.probe_task import StandaloneProbeDevice, bind_probe_task

    # Validate binding and objective before creating output or touching CUDA.
    with bind_probe_task(config.task_probe_data) as composition:
        loss = config.loss_config or composition.objective
        if loss is None:
            raise ValueError("replay requires loss_config or a task-declared objective")
        if composition.objective is not None and loss != composition.objective:
            raise ValueError("replay loss_config disagrees with the task-declared objective")
    vram = config.device_vram_gb
    if vram is None:
        if not config.train_config.device.startswith("cuda"):
            raise ValueError("CPU replay requires an explicit device_vram_gb classifier threshold")
        vram = probe_device_vram_gb()
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)

    def _probe(candidate: ReplayCandidate) -> MeasuredRuntime:
        assert candidate.model_name  # eligibility already established
        # Unique directories prevent a failed invocation reading a stale result.
        result_path = Path(mkdtemp(prefix="probe-", dir=root)) / "result.json"
        outcome = run_worker(
            ProbeWorkerSpec(
                model_type=candidate.model_name,
                model_config_payload=config.model_config_payload,
                train_config=config.train_config.model_dump(mode="json"),
                loss_config=loss.model_dump(mode="json"),
                task_probe_data=config.task_probe_data,
                device=cast(StandaloneProbeDevice, config.train_config.device),
                caps=config.caps.model_dump(mode="json"),
                device_vram_gb=vram,
                result_path=str(result_path),
            ),
            hard_cap_seconds=config.caps.max_wall_seconds,
        )
        if outcome.classification == "infrastructure_failure":
            raise ProbeInfrastructureFailure(outcome.detail)
        result = outcome.result
        return MeasuredRuntime(
            train_ms_per_step=result.train_ms_per_step if result else None,
            inference_ms_per_batch=result.inference_ms_per_batch if result else None,
            setup_seconds=result.setup_seconds if result else None,
            peak_vram_gb=result.peak_vram_gb if result else None,
            realized_parameter_count=(
                result.realized["parameter_count"] if result and result.realized else None
            ),
            concurrency_identity=result.concurrency_identity if result else None,
            probe_status=(
                result.status
                if result is not None
                else "wall_cap"
                if outcome.termination.timed_out
                else "measured_failure"
            ),
        )

    return _probe
