"""One typed decision between a candidate and a formal GPU phase.

V20 PR C2 / C2-7.

Owns the whole chain, end to end:

```text
run the isolated pre-phase measurement
  -> classify the typed result
  -> validate that an authoritative requirement exists
  -> deliver it to PR B's admission gate
  -> return ONE disposition
```

**Why a boundary and not four branches in the tuner.**
At the time of the PR C2 extraction, `HyperparamTuningAgent.run()` had
reached 2,487 lines and the historical Pyright complexity limit. Such
limits also apply in basic mode. Keeping measurement, classification,
admission and disposition at this boundary avoids adding those
responsibilities to the orchestrator and makes O-7's accounting explicit.

**The tuner consumes only the disposition.** It never reads an outcome, a
peak, a coverage figure or an admission decision to decide what to do. Each
`PrephaseAdmissionOutcome` answers, as computed properties, every question
O-7 governs -- attempt consumption, round completion, blame, shrink advice,
same-attempt retry, formal launch -- so those rules are enforced by the
type rather than restated at each call site.

**Every result is a value.** Nothing here raises for a measurement outcome;
that is the frozen control-flow rule. `as_admission_entry()` still raises,
but only as a fail-closed misuse guard, and this module never reaches it
without having checked `authoritative` first.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from core.runtime_control.admission import AdmissionDecision, evaluate_gpu_admission
from core.runtime_control.gpu_measurement_classifier import classify_measurement
from core.runtime_control.gpu_measurement_runner import PrephaseMeasurementRun
from core.runtime_control.gpu_requirement import (
    MeasuredGpuRequirement,
    MeasuredRequirementTable,
)

#: What the tuner acts on. Nothing else about a measurement reaches it.
PrephaseDisposition = Literal[
    "PROCEED",
    "STOP_MEASUREMENT_UNAVAILABLE",
    "STOP_OVER_CAP",
    "STOP_MEASURED_OOM",
    "STOP_TIMEOUT",
    #: The measurement PROCESS exceeded its host-RSS allowance. Named for
    #: the probe, not the run, so it cannot be read as a host-memory policy
    #: about formal training -- and deliberately NOT `STOP_OVER_CAP`, which
    #: in a GPU-admission boundary reads as a VRAM verdict. On 2026-07-31 a
    #: candidate reached 60.5 GB of host RSS with the GPU at 273 MiB;
    #: host RSS is never VRAM demand.
    "STOP_PROBE_HOST_MEMORY_EXCEEDED",
    "STOP_INFRASTRUCTURE_FAILURE",
]

#: Dispositions that carry NO GPU requirement and must never be handed to
#: PR B's capacity gate. A host-memory figure reaching `measured_requirements`
#: would be a CPU number admitted as a VRAM one.
NO_GPU_CAPACITY_AUTHORITY: frozenset[str] = frozenset({"STOP_PROBE_HOST_MEMORY_EXCEEDED"})

#: Outcome -> disposition. A table rather than a chain of `if`s, so the
#: mapping is enumerable and a new outcome cannot fall through a gap into
#: an accidental PROCEED.
_OUTCOME_DISPOSITION: dict[str, PrephaseDisposition] = {
    "MEASURED_CUDA_OOM": "STOP_MEASURED_OOM",
    "MEASURED_PEAK_ABOVE_VRAM_CAP": "STOP_OVER_CAP",
    "MEASURED_HARD_TIMEOUT": "STOP_TIMEOUT",
    "MEASURED_HOST_MEMORY_EXCEEDED": "STOP_PROBE_HOST_MEMORY_EXCEEDED",
    "HOST_MEMORY_ALLOCATION_FAILURE": "STOP_PROBE_HOST_MEMORY_EXCEEDED",
    "INCONCLUSIVE_MEASUREMENT": "STOP_MEASUREMENT_UNAVAILABLE",
    # A configuration the validator already accepted being rejected here is
    # an inconsistency in our own pipeline, not a fact about the candidate.
    "SCHEMA_REJECTED": "STOP_INFRASTRUCTURE_FAILURE",
    "PROBE_INFRASTRUCTURE_FAILURE": "STOP_INFRASTRUCTURE_FAILURE",
}

#: PR B refusal statuses that mean "no requirement could be established"
#: rather than "the device cannot hold this".
_UNAVAILABLE_REFUSALS = frozenset({"policy_unavailable", "measurement_unavailable"})


class PrephaseAdmissionOutcome(BaseModel):
    """The single thing the tuner reads, and the evidence behind it.

    O-7 is expressed as computed properties, not as instructions in a
    docstring. A caller cannot consume the attempt twice, record a
    completed round, blame the candidate or shrink a proposal by reading
    the wrong field, because there is no field to read -- only derived
    answers that are the same for every stop.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    disposition: PrephaseDisposition
    #: The classified measurement. Always present, so a refusal can be
    #: explained from the evidence rather than only named.
    requirement: MeasuredGpuRequirement
    #: Present only on PROCEED: what was delivered to admission.
    table: MeasuredRequirementTable | None = None
    #: PR B's decision, when admission was reached at all.
    admission: AdmissionDecision | None = None
    detail: str = ""

    # ── O-7, computed ────────────────────────────────────────────────────
    @property
    def proceeds(self) -> bool:
        return self.disposition == "PROCEED"

    @property
    def may_launch_formal_phase(self) -> bool:
        """Formal GPU work starts only after an authoritative ALLOW."""
        return self.proceeds

    @property
    def attempt_consumed(self) -> bool:
        """Every stop consumes the attempt; a proceed does not.

        The attempt is consumed because the run genuinely spent one -- a
        bounded GPU measurement ran. Not consuming it would let an
        unmeasurable candidate loop against the outer budget forever.
        """
        return not self.proceeds

    @property
    def records_completed_round(self) -> bool:
        """Never on a stop: no phase ran, so no round completed."""
        return False

    @property
    def carries_candidate_blame(self) -> bool:
        """Never. A pre-phase stop is not a scientific result about the
        candidate, whichever outcome produced it."""
        return False

    @property
    def permits_shrink_advice(self) -> bool:
        """Never from this boundary.

        A measured OOM or above-cap result genuinely establishes that the
        candidate does not fit -- `requirement.establishes_insufficient_capacity`
        says so, and it is preserved. But O-7 freezes this boundary as
        "no proposal shrinking", so the fact is recorded and the
        instruction is not issued here.
        """
        return False

    @property
    def carries_gpu_capacity_authority(self) -> bool:
        """Whether this outcome supplies a GPU requirement at all.

        False for every stop, and structurally false for a host-memory
        stop: `MEASURED_HOST_MEMORY_EXCEEDED` is not `COMPLETED_MEASUREMENT`,
        so `authoritative` is False, so PR B's capacity gate is never
        called and no table is built. Stated as a property because "the
        host figure cannot reach `measured_requirements`" is a claim worth
        being able to assert directly.
        """
        return self.proceeds and self.table is not None

    @property
    def permits_same_attempt_retry(self) -> bool:
        """Never. Only the existing outer attempt budget may produce
        another attempt; a retry loop here would be invisible to it."""
        return False


def decide_prephase_admission(
    run: PrephaseMeasurementRun,
    *,
    snapshot: Any,
    mode: str,
    vram_cap_mib: int | None = None,
    ceiling_gib: float | None = None,
    run_name: str = "candidate",
    sampling_error: str | None = None,
) -> PrephaseAdmissionOutcome:
    """Classify one measurement, admit on it, and return one disposition.

    Args:
        run: what the isolated pre-phase measurement observed.
        snapshot: the pre-spawn `GpuAccountingSnapshot` PR B admits against.
        mode: `formal` or `trial`, validated inside `evaluate_gpu_admission`
            so posture policy keeps exactly one home.
        vram_cap_mib: the operator ceiling a measured peak may exceed.
        ceiling_gib: PR B's aggregate ceiling override.
        sampling_error: set when the pre-spawn snapshot could not be taken.

    Returns:
        A `PrephaseAdmissionOutcome`. Never raises for a measurement result.
    """
    requirement = classify_measurement(run, vram_cap_mib=vram_cap_mib)

    if not requirement.authoritative:
        disposition = _OUTCOME_DISPOSITION.get(requirement.outcome, "STOP_MEASUREMENT_UNAVAILABLE")
        # A COMPLETED_MEASUREMENT that is still not authoritative failed a
        # frozen condition -- the wrong device, an inadmissible phase, an
        # incomplete watch. It is unusable, not a capacity fact, so the
        # refusal reason is what the record carries.
        return PrephaseAdmissionOutcome(
            disposition=disposition,
            requirement=requirement,
            detail=(
                f"{requirement.outcome}: {requirement.detail}"
                if requirement.detail
                else f"{requirement.outcome} ({requirement.authority_refusal})"
            )[:400],
        )

    # Authoritative: the requirement is real, and PR B decides whether the
    # device can currently hold it. That is a separate question -- a
    # candidate that fits the card may still not fit beside what is
    # already on it.
    table = MeasuredRequirementTable.from_measurements(requirement)
    requirement_mib, provenance = table.for_phase(run.request.phase)
    decision = evaluate_gpu_admission(
        snapshot=snapshot,
        requirement_mib=requirement_mib,
        requirement_provenance=provenance,
        mode=mode,
        run_name=run_name,
        ceiling_gib=ceiling_gib,
        sampling_error=sampling_error,
    )
    if decision.admitted:
        return PrephaseAdmissionOutcome(
            disposition="PROCEED",
            requirement=requirement,
            table=table,
            admission=decision,
            detail=decision.reason[:400],
        )
    return PrephaseAdmissionOutcome(
        disposition=(
            "STOP_MEASUREMENT_UNAVAILABLE"
            if decision.reason_code in _UNAVAILABLE_REFUSALS
            else "STOP_OVER_CAP"
        ),
        requirement=requirement,
        table=table,
        admission=decision,
        detail=f"{decision.reason_code}: {decision.reason}"[:400],
    )


def attach_measured_requirements(sandbox: Any, outcome: PrephaseAdmissionOutcome) -> bool:
    """Put the requirement where `_phase_requirement` will read it.

    The last link in the producer->consumer chain, and deliberately its own
    named function: an edge that exists only as an assignment buried in an
    orchestrator is the edge that goes missing, which is how
    `measured_requirements` came to have no producer at all.

    Returns whether anything was attached. A stop attaches nothing --
    delivering a non-authoritative requirement is precisely what the
    authority contract exists to prevent.
    """
    if outcome.table is None or not outcome.proceeds:
        return False
    sandbox.measured_requirement_table = outcome.table
    return True
