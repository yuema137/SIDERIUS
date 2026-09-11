"""Name what a measurement established, and check the claim before making it.

V20 PR C2 / C2-5.

Turns a `PrephaseMeasurementRun` -- a record of what happened -- into a
`MeasuredGpuRequirement` -- a typed claim about what it established. The two
are separate on purpose: an operator needs to see the evidence that produced
a refusal, not only the refusal.

**The vocabulary is PR A's `PreflightOutcome`, imported, not re-declared.**
A second outcome system would be a second policy about what a failed
measurement means, which is the defect shape this PR exists to remove. So
are PR A's authority predicates: `VRAM_CAPACITY_OUTCOMES` decides which
outcomes prove a candidate does not fit, and `NO_DOWNSIZING_AUTHORITY`
decides which establish nothing about its size.

EVERY CLAIM IS CHECKED AGAINST EVIDENCE BEFORE IT IS MADE.

* **A timeout must have reached a deadline.** On 2026-07-31 a 65.6 s
  inspection was filed as a timeout against a 600 s budget because every
  inconclusive status mapped to it. Two deadlines exist here -- the
  parent's hard one and the worker's soft budget -- and the reported
  evidence is whichever actually fired. Reporting the parent's budget for a
  clean worker-side stop would produce a timeout whose elapsed time never
  reached it.
* **A CUDA OOM needs a real CUDA OOM.** Only the worker can observe one,
  because only it holds the exception. A killed or reaped worker is never
  classified as an OOM: the shape "died while using a lot of memory" is
  precisely the inference that would blame a candidate for the machinery.
* **Above-cap needs an otherwise-authoritative measurement.** See the note
  on that rule below -- it is deliberately conservative, and the cost is
  stated rather than hidden.
* **Incomplete sampling never carries capacity authority.** A gappy watch
  yields an UNKNOWN requirement, not a smaller one.
* **A crash is not a scientific result, and infrastructure is not the
  candidate's fault.** Both land on outcomes inside
  `NO_DOWNSIZING_AUTHORITY`, so neither can tell an agent to shrink a model
  that was never shown to be too big.

**It returns a value for every input.** Classification never raises; that is
the control-flow rule. The only raising accessor is
`MeasuredGpuRequirement.as_admission_entry()`, which is a misuse guard, not
a step in this path.
"""

from __future__ import annotations

from agent.skills.evaluate_vram_skill.isolated_probe import PreflightOutcome
from core.runtime_control.gpu_measurement_identity import compare_identities
from core.runtime_control.gpu_measurement_runner import (
    PhaseMeasurement,
    PrephaseMeasurementRun,
)
from core.runtime_control.gpu_requirement import (
    MeasuredGpuRequirement,
    MeasurementDeadline,
    SamplingCoverage,
)


def classify_measurement(
    run: PrephaseMeasurementRun, *, vram_cap_mib: int | None = None
) -> MeasuredGpuRequirement:
    """The typed claim this run supports.

    Args:
        run: what the measurement observed.
        vram_cap_mib: the operator ceiling a measured peak may exceed.
            `None` means no ceiling was configured, and then above-cap is
            not a verdict that can be reached -- never a guessed one.

    Returns:
        A `MeasuredGpuRequirement`. `authoritative` on it is computed from
        the frozen conditions; nothing here can assert it.
    """
    target = run.target
    mismatch = compare_identities(
        run.request.planned_identity,
        run.realized_identity,
        requested_id=run.request.request_id,
        reported_id=run.reported_request_id,
        phase=run.request.phase,
    )
    outcome, detail = _outcome_for(run, target, vram_cap_mib, mismatch)
    return MeasuredGpuRequirement(
        request=run.request,
        outcome=outcome,
        # Carried whatever the outcome. On a non-authoritative one it is
        # operator information, not an admissible figure: `authority_refusal`
        # reports `outcome_has_no_capacity_authority` before it ever looks
        # at the number, so a partial peak cannot leak into admission --
        # and discarding it would throw away the one clue about how large
        # the candidate was getting.
        driver_tree_peak_mib=target.driver_tree_peak_mib if target is not None else None,
        allocator_peak_mib=target.allocator_peak_mib if target is not None else None,
        observed_device_uuid=run.observed_device_uuid,
        owned_pids=target.own_pids if target is not None else (),
        coverage=target.coverage if target is not None else _no_coverage(run),
        realized_identity=run.realized_identity,
        identity_mismatch=mismatch,
        deadline=_deadline_evidence(run),
        detail=detail[:400],
    )


def _no_coverage(run: PrephaseMeasurementRun) -> SamplingCoverage:
    """Coverage for a run with no measured phase at all.

    Zero samples and `covered_whole_phase=False`, so it fails closed:
    nothing was watched, and nothing may be claimed.
    """
    return SamplingCoverage(
        interval_seconds=run.request.sampling_interval_seconds,
        samples_taken=0,
        covered_whole_phase=False,
    )


def _deadline_evidence(run: PrephaseMeasurementRun) -> MeasurementDeadline:
    """The deadline a timeout claim would be checked against.

    When the worker stopped itself on its own budget, THAT is the deadline
    that fired, and reporting the parent's would make the claim fail its
    own validator -- the soft budget sits below the hard one by
    construction.
    """
    if run.worker_status == "DEADLINE_EXCEEDED" and run.soft_deadline_seconds is not None:
        return MeasurementDeadline(
            budget_seconds=run.soft_deadline_seconds,
            elapsed_seconds=max(run.deadline.elapsed_seconds, run.soft_deadline_seconds),
        )
    return run.deadline


def _outcome_for(
    run: PrephaseMeasurementRun,
    target: PhaseMeasurement | None,
    vram_cap_mib: int | None,
    identity_mismatch: str | None,
) -> tuple[PreflightOutcome, str]:
    """Which outcome the evidence supports, and why.

    Ordered so the most specific established fact wins. Host memory comes
    first because the parent observed it directly and it is a HOST verdict
    that must never be phrased as a VRAM one -- the candidate may fit the
    GPU perfectly and still have exhausted CPU memory.
    """
    if identity_mismatch is not None and run.report_present:
        # D-C2-7. The result does not describe the candidate that was
        # requested. That is an integrity failure of the measurement
        # SYSTEM -- never candidate blame, never capacity evidence, never
        # a scientific result. Checked before any outcome that could carry
        # authority, so an unverified subject cannot acquire one.
        return (
            "PROBE_INFRASTRUCTURE_FAILURE",
            f"identity integrity failure ({identity_mismatch}): the measurement "
            "does not describe the candidate that was requested",
        )

    if run.host_memory.exceeded:
        return (
            "MEASURED_HOST_MEMORY_EXCEEDED",
            f"the worker tree reached {run.host_memory.peak_tree_rss_gib} GiB against a "
            f"{round(run.host_memory.limit_bytes / 1024**3, 2)} GiB host allowance; this is "
            "a HOST memory result and says nothing about VRAM",
        )

    if not run.report_present:
        return _no_report_outcome(run)

    status = run.worker_status
    if status == "CONFIG_REJECTED":
        return "SCHEMA_REJECTED", run.detail or "the candidate configuration was rejected"
    if status in ("DEVICE_UNAVAILABLE", "DEVICE_MISMATCH"):
        # An environment fault, not a property of the candidate.
        return "PROBE_INFRASTRUCTURE_FAILURE", run.detail or f"device unusable ({status})"
    if status == "CUDA_OOM":
        return (
            "MEASURED_CUDA_OOM",
            run.detail or f"the candidate ran out of GPU memory during {run.request.phase}",
        )
    if status == "DEADLINE_EXCEEDED":
        return (
            "MEASURED_HARD_TIMEOUT",
            run.detail or "the worker stopped on its own bounded budget",
        )
    if status == "WORKER_FAILURE":
        return (
            "PROBE_INFRASTRUCTURE_FAILURE",
            run.detail or "the measurement worker failed before producing a result",
        )

    if target is None or target.status != "COMPLETED":
        return (
            "INCONCLUSIVE_MEASUREMENT",
            f"phase {run.request.phase!r} did not complete "
            f"({'absent' if target is None else target.status})",
        )
    if target.driver_tree_peak_mib is None:
        return (
            "INCONCLUSIVE_MEASUREMENT",
            "no driver-visible process-tree memory was observed during the phase; "
            "an unobserved requirement is unknown, not zero",
        )
    if not target.coverage.complete:
        return (
            "INCONCLUSIVE_MEASUREMENT",
            f"sampling was incomplete ({target.coverage.incompleteness_reason}); "
            f"the {target.driver_tree_peak_mib} MiB observed is a lower bound, "
            "not a requirement",
        )
    if vram_cap_mib is not None and target.driver_tree_peak_mib > vram_cap_mib:
        return (
            "MEASURED_PEAK_ABOVE_VRAM_CAP",
            f"measured {target.driver_tree_peak_mib} MiB against a {vram_cap_mib} MiB cap",
        )
    return "COMPLETED_MEASUREMENT", ""


def _no_report_outcome(run: PrephaseMeasurementRun) -> tuple[PreflightOutcome, str]:
    """The worker left nothing structured behind.

    Deliberately NEVER `MEASURED_CUDA_OOM`. Only the worker can observe a
    CUDA OOM, because only it holds the exception; inferring one from "died
    while holding a lot of memory" would blame the candidate for the
    machinery, and PR A's `HOST_MEMORY` inference exists precisely because
    that inference is only safe for the bound the PARENT measured itself.

    The journal still says which phase was in flight, so the operator
    detail is specific even when the outcome cannot be.
    """
    where = f" during {run.in_flight_phase}" if run.in_flight_phase else ""
    if run.deadline.reached_deadline:
        return (
            "MEASURED_HARD_TIMEOUT",
            f"the worker exceeded its {run.deadline.budget_seconds}s deadline{where} "
            f"and was terminated (TERM sent={run.process.term_sent}, "
            f"KILL sent={run.process.kill_sent})",
        )
    return (
        "PROBE_INFRASTRUCTURE_FAILURE",
        f"the worker exited without a structured result{where} "
        f"(exit={run.process.exit_code}, signal={run.process.signal_number}); "
        f"{run.detail}"[:380],
    )
