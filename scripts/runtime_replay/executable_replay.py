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
from typing import Any

from scripts.runtime_replay.schemas import (
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
    *,
    model_config: dict[str, Any],
    train_config: dict[str, Any],
    loss_config: dict[str, Any],
    data_dir: str | None = None,
) -> Callable[[ReplayCandidate], MeasuredRuntime]:
    """The REAL probe (operator-gated: this touches the GPU)."""

    def _probe(candidate: ReplayCandidate) -> MeasuredRuntime:
        from core.runtime_control.probe import ProbeCaps, run_bounded_probe
        from core.runtime_control.probe_production import (
            probe_device_vram_gb,
            production_probe_executors,
        )

        assert candidate.model_name  # eligibility already established
        executors = production_probe_executors(
            model_type=candidate.model_name,
            model_config=model_config,
            train_config=train_config,
            loss_config=loss_config,
            data_dir=data_dir,
        )
        result = run_bounded_probe(
            model_identity=candidate.model_name,
            executors=executors,
            caps=ProbeCaps(max_wall_seconds=90.0),
            device_vram_gb=probe_device_vram_gb(),
        )
        return MeasuredRuntime(
            train_ms_per_step=result.train_ms_per_step,
            inference_ms_per_batch=result.inference_ms_per_batch,
            setup_seconds=result.setup_seconds,
            peak_vram_gb=result.peak_vram_gb,
            realized_parameter_count=(result.realized.parameter_count if result.realized else None),
            concurrency_identity=result.concurrency_identity,
            probe_status=result.status,
        )

    return _probe
