"""Typed contracts for the authoritative GPU requirement (V20 PR C2 / C2-1).

WHAT THIS EXISTS TO FIX. `sandbox_executor.py` reads the requirement PR B
admits on through a duck-typed `getattr(sandbox, "measured_requirements",
None)`, and **nothing in production populates it**. Formal admission therefore
reports `policy_unavailable` forever. §8.A already names that untyped read as
the gap that "survived PR B and its whole test suite"; C2 replaces it with a
typed boundary rather than quietly filling the dict.

THE AUTHORITY RULE, frozen by operator decision 2026-08-03. A requirement may
be admitted as authoritative ONLY when every one of these holds:

  * measured LIVE -- not recalled, not derived from history;
  * on the CURRENT physical GPU, matched by UUID;
  * for the EXACT candidate and configuration;
  * BEFORE formal execution;
  * PHASE-SPECIFIC -- training and inference never merged;
  * from CANDIDATE-OWNED DRIVER-VISIBLE process-tree memory.

Two corollaries the audit showed are easy to get wrong, so they are encoded
here rather than left to callers:

  1. **The PyTorch allocator peak is supplemental diagnostics.** It is
     per-process and excludes the CUDA context, cuDNN workspaces outside the
     caching allocator, and reserved-but-unallocated blocks. It is carried
     alongside the driver figure for explanation, and it can never be the
     authority on its own.
  2. **Incomplete sampling fails closed.** A polled sampler can miss a
     transient peak. A measurement whose sampling was incomplete is not a
     smaller requirement -- it is an unknown one, and it is refused.

WHAT IS DELIBERATELY NOT REDEFINED. The outcome vocabulary is PR A's
`PreflightOutcome`, imported rather than re-declared. A second outcome system
would be a second policy about what a failed measurement means, which is the
defect shape this PR exists to remove.
"""

from __future__ import annotations

from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.skills.evaluate_vram_skill.isolated_probe import (
    VRAM_CAPACITY_OUTCOMES,
    PreflightOutcome,
)
from core.runtime_control.admission import AUTHORITATIVE_PROVENANCE
from core.runtime_control.gpu_measurement_identity import (
    PlannedCandidateIdentity,
    RealizedCandidateIdentity,
)
from core.runtime_control.gpu_requirement_evidence import (
    AdmissionRequirementEvidence,
    GpuRequirementOwnership,
)

#: The provenance category PR B accepts for a driver-visible measurement.
#: Taken FROM `AUTHORITATIVE_PROVENANCE` rather than spelled again, so a
#: change to that frozen set breaks loudly here instead of silently making
#: every C2 requirement non-authoritative.
MEASURED_PROVENANCE = "measured"
if MEASURED_PROVENANCE not in AUTHORITATIVE_PROVENANCE:  # pragma: no cover
    raise RuntimeError(
        f"{MEASURED_PROVENANCE!r} is no longer in admission's "
        f"AUTHORITATIVE_PROVENANCE ({sorted(AUTHORITATIVE_PROVENANCE)}); every "
        "measured requirement would be delivered and silently refused as "
        "policy_unavailable. Not an `assert`: `python -O` would strip it."
    )

#: The phases a requirement may be scoped to. `setup` is measurable and
#: reportable but is NOT a consumer phase: PR B admits training and inference
#: separately, and a setup figure is neither.
MeasuredPhase = Literal["setup", "training", "inference"]

#: Phases PR B actually admits on. A requirement for any other phase may be
#: recorded but never delivered as that phase's authority.
ADMISSIBLE_PHASES: frozenset[str] = frozenset({"training", "inference"})

#: How many valid in-phase driver samples an authoritative measurement
#: needs. Gate 2 Lite-A c7 measured an inference phase in 0.138 s against a
#: 0.25 s cadence: ZERO samples landed inside the window, so the phase was
#: unmeasurable at any speed of candidate. One sample is not much better --
#: a single reading cannot distinguish a steady peak from a transient, and
#: it gives the phase no observed shape at all. Three is the smallest count
#: that shows a phase was watched rather than glanced at.
#:
#: Enforced HERE, on the observation side, because that is where the truth
#: is: the worker can lengthen a phase so samples have time to land, but
#: only the parent knows how many actually did.
MINIMUM_AUTHORITATIVE_SAMPLES = 3

#: Why a measurement carries no capacity authority. Each value is a distinct
#: operator-actionable cause -- collapsing them into one "failed" would hide
#: which of them happened, and they demand different responses.
AuthorityRefusal = Literal[
    "outcome_has_no_capacity_authority",
    "sampling_incomplete",
    "device_uuid_mismatch",
    "candidate_identity_mismatch",
    "realized_identity_absent",
    "phase_not_admissible",
    "no_driver_visible_evidence",
    "requirement_ownership_unavailable",
]


class MeasurementDeadline(BaseModel):
    """A bounded wall-clock budget, and what actually happened against it.

    `reached_deadline` exists so a `MEASURED_HARD_TIMEOUT` can be VALIDATED
    rather than believed. PR A added the equivalent check after a 65.6 s
    inspection was filed as a timeout on 2026-07-31; the same trap is
    available here and is closed the same way.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    budget_seconds: float = Field(gt=0.0)
    elapsed_seconds: float = Field(ge=0.0)

    @property
    def reached_deadline(self) -> bool:
        return self.elapsed_seconds >= self.budget_seconds


class SamplingCoverage(BaseModel):
    """How completely the parent watched the worker.

    A polled driver query cannot see between samples. This records the cadence
    and whether the watch was continuous, so a requirement derived from a gappy
    watch can be refused instead of quietly under-reporting.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    interval_seconds: float = Field(gt=0.0)
    samples_taken: int = Field(ge=0)
    #: Samples the parent expected but did not get (driver query failed, or the
    #: loop was starved). NOT the same as "GPU was idle".
    samples_missed: int = Field(default=0, ge=0)
    #: False when the parent could not watch the whole phase -- e.g. it started
    #: sampling late, or the worker exited between polls.
    covered_whole_phase: bool = True
    #: The longest stretch of the phase with no sample in it, boundaries
    #: included. This is quantified under-read RISK, deliberately NOT part
    #: of `complete`: a continuous, gapless-by-its-own-cadence watch is
    #: still blind between polls, and a transient peak inside the largest
    #: gap is invisible. Recording the number keeps that exposure with the
    #: measurement instead of leaving it as a known-in-principle caveat.
    max_gap_seconds: float | None = Field(default=None, ge=0.0)

    @property
    def complete(self) -> bool:
        """Complete means: watched the whole phase, missed nothing, and took
        at least `MINIMUM_AUTHORITATIVE_SAMPLES` readings inside it.

        Zero samples is not "0 MiB used"; it is "we did not look". One or two
        are "we glanced" -- enough to produce a number, not enough for that
        number to describe a phase.
        """
        return (
            self.covered_whole_phase
            and self.samples_missed == 0
            and self.samples_taken >= MINIMUM_AUTHORITATIVE_SAMPLES
        )

    @property
    def incompleteness_reason(self) -> str | None:
        if self.samples_taken == 0:
            return "no samples were taken; absence of samples is not absence of memory"
        if self.samples_taken < MINIMUM_AUTHORITATIVE_SAMPLES:
            return (
                f"only {self.samples_taken} in-phase sample(s) at "
                f"{self.interval_seconds}s cadence; "
                f"{MINIMUM_AUTHORITATIVE_SAMPLES} are required before a peak "
                "describes a phase rather than an instant"
            )
        if self.samples_missed:
            return f"{self.samples_missed} sample(s) missed at {self.interval_seconds}s cadence"
        if not self.covered_whole_phase:
            return "sampling did not cover the whole phase"
        return None


class CandidateMeasurementRequest(BaseModel):
    """Exactly what is to be measured. Every field is identity, not preference.

    This travels INTO the worker and is echoed back on the result, so a result
    can be checked against the request it claims to answer. A measurement of a
    different candidate is not a weaker measurement, it is a different one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_type: str = Field(min_length=1)
    #: What the parent asserts it is asking for. Request-binding and audit
    #: evidence, NEVER capacity authority -- the authoritative measurement
    #: identity is the worker's realized one (D-C2-7).
    planned_identity: PlannedCandidateIdentity
    #: Nonce. Echoed back by the worker so a stale or misrouted result
    #: cannot be read as this request's answer.
    request_id: str = Field(min_length=1)
    device_uuid: str = Field(min_length=1)
    phase: MeasuredPhase
    deadline_seconds: float = Field(gt=0.0)
    #: Driver-sampling cadence the parent will use.
    sampling_interval_seconds: float = Field(default=0.25, gt=0.0)


class MeasuredGpuRequirement(BaseModel):
    """One phase-specific measurement, and whether it may carry authority.

    `authoritative` is COMPUTED, never supplied. A caller cannot assert that a
    measurement is trustworthy; it either satisfies every frozen condition or
    it is refused with a named reason.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    request: CandidateMeasurementRequest
    outcome: PreflightOutcome

    #: THE AUTHORITY FIGURE: candidate-owned, driver-visible, process-tree.
    #: None when no driver evidence was obtained -- which is refusal, not zero.
    driver_tree_peak_mib: int | None = Field(default=None, ge=0)
    #: Supplemental diagnostics only. Per-process, allocator-visible; excludes
    #: the CUDA context and non-allocator workspaces. Never the authority.
    allocator_peak_mib: int | None = Field(default=None, ge=0)

    #: The device actually measured on, as the driver reported it. Compared
    #: against `request.device_uuid`; a mismatch is refused rather than
    #: substituted, because answering about the wrong GPU is worse than not
    #: answering.
    observed_device_uuid: str | None = None
    #: PIDs attributed to the candidate's own tree. Retained so an operator can
    #: audit what was counted as "ours".
    owned_pids: tuple[int, ...] = ()
    ownership: GpuRequirementOwnership | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    #: THE authoritative measurement identity: what the worker actually
    #: built, hashed by C1's canonical builder. `None` means the worker
    #: never got far enough to state it, which is refusal -- a requirement
    #: whose subject is unverified is not a requirement.
    realized_identity: RealizedCandidateIdentity | None = None
    #: Set when the planned request and the realized measurement do not
    #: describe the same candidate. An integrity failure of the measurement
    #: system; never candidate blame.
    identity_mismatch: str | None = None

    coverage: SamplingCoverage
    deadline: MeasurementDeadline
    detail: str = ""

    @model_validator(mode="after")
    def _a_timeout_must_have_reached_its_deadline(self) -> MeasuredGpuRequirement:
        """Mirrors PR A's guard. A timeout claim that did not reach its
        deadline is a mislabelled failure, and mislabelling it hides whatever
        actually went wrong."""
        if self.outcome == "MEASURED_HARD_TIMEOUT" and not self.deadline.reached_deadline:
            raise ValueError(
                f"MEASURED_HARD_TIMEOUT claims a deadline was reached, but "
                f"{self.deadline.elapsed_seconds}s < {self.deadline.budget_seconds}s budget"
            )
        return self

    @model_validator(mode="after")
    def _a_completed_measurement_must_carry_evidence(self) -> MeasuredGpuRequirement:
        """COMPLETED_MEASUREMENT with no driver figure is the silent-success
        shape this PR exists to remove: it reads as a successful measurement
        and contains nothing."""
        if self.outcome == "COMPLETED_MEASUREMENT" and self.driver_tree_peak_mib is None:
            raise ValueError(
                "COMPLETED_MEASUREMENT carries no driver-visible process-tree "
                "peak; a completed measurement with no evidence is not a "
                "measurement"
            )
        return self

    # ── authority ────────────────────────────────────────────────────────
    @property
    def authority_refusal(self) -> AuthorityRefusal | None:
        """The single reason this measurement may not be authoritative.

        Ordered most-fundamental first, so the reported reason is the one an
        operator should act on rather than an incidental downstream symptom.
        """
        if self.outcome != "COMPLETED_MEASUREMENT":
            return "outcome_has_no_capacity_authority"
        if self.driver_tree_peak_mib is None:
            return "no_driver_visible_evidence"
        if self.observed_device_uuid != self.request.device_uuid:
            return "device_uuid_mismatch"
        if self.identity_mismatch is not None:
            return "candidate_identity_mismatch"
        if self.realized_identity is None:
            # The parent asked for candidate X; nothing here proves that is
            # what was measured. Admitting on it would attribute a real
            # figure to an unverified subject.
            return "realized_identity_absent"
        if self.request.phase not in ADMISSIBLE_PHASES:
            return "phase_not_admissible"
        if not self.coverage.complete:
            return "sampling_incomplete"
        if (
            self.ownership is None
            or self.ownership.device_uuid != self.observed_device_uuid
            or self.ownership.completion_refusal is not None
        ):
            return "requirement_ownership_unavailable"
        return None

    @property
    def authoritative(self) -> bool:
        """True only when every frozen condition holds. Computed, never set."""
        return self.authority_refusal is None

    @property
    def establishes_insufficient_capacity(self) -> bool:
        """Whether this measurement proves the candidate does not fit.

        Distinct from `authoritative`: a measured OOM or above-cap result
        carries no *requirement* figure to admit on, but it does establish that
        the candidate is too large. Reuses PR A's frozen capacity set rather
        than re-deciding which outcomes mean that.
        """
        return self.outcome in VRAM_CAPACITY_OUTCOMES

    def as_admission_entry(self) -> dict[str, object]:
        """The phase entry `sandbox_executor` reads, or refusal.

        Returns the numeric/category entry together with typed worker ownership.
        Raises rather than emitting a placeholder when the measurement is not
        authoritative: a substituted figure would be, in that module's own
        words, "an assumption wearing a measurement's provenance".

        `provenance` is the CATEGORY `admission.AUTHORITATIVE_PROVENANCE`
        accepts, not a description. That set is
        `{"measured", "promoted_measurement"}`, and
        `evaluate_gpu_admission` tests membership in it directly
        (`admission.py:429`) -- so a descriptive string here would be
        delivered, judged non-authoritative, and refused as
        `policy_unavailable`. That is the exact failure C2 exists to fix,
        one layer deeper and harder to see, because the requirement would
        be *present* and still not count.

        The description travels beside it as `measurement_detail`, which
        `_phase_requirement` ignores. Nothing is lost: the full
        `MeasuredGpuRequirement` travels with the disposition.
        """
        refusal = self.authority_refusal
        if refusal is not None:
            raise ValueError(
                f"measurement for phase {self.request.phase!r} is not "
                f"authoritative ({refusal}); it must not be delivered to admission"
            )
        # authority_refusal has already proved the realized identity exists.
        realized = cast(RealizedCandidateIdentity, self.realized_identity)
        return {
            "requirement_mib": self.driver_tree_peak_mib,
            "provenance": MEASURED_PROVENANCE,
            "ownership": self.ownership.model_dump(mode="json") if self.ownership else None,
            "measurement_detail": (
                f"isolated_prephase_measurement:{self.request.phase}"
                f":{self.request.model_type}"
                f":realized={realized.realized_config_hash}"
                f":planned={self.request.planned_identity.planned_config_hash}"
                f":{self.observed_device_uuid}"
            ),
        }


class MeasuredRequirementTable(BaseModel):
    """The typed channel from a measurement to PR B's admission gate.

    §8.A names the duck-typed `getattr(sandbox, "measured_requirements",
    None)` as the gap that *"survived PR B and its whole test suite"* --
    a read no production code satisfied, so the gate was correct and
    unreachable. C2 replaces it with this rather than quietly filling the
    dict, because a typed object is something a test can prove is present
    and a `getattr` default is not.

    **Only authoritative measurements may enter.** The constructor calls
    `as_admission_entry()` per phase, which raises on a refused one, so an
    inconclusive or wrong-device measurement cannot be assembled into a
    table at all. There is no path that turns a refusal into an absent key
    and an absent key into a silent proceed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Keyed by phase, exactly the shape `_phase_requirement` reads.
    entries: dict[str, dict[str, object]] = Field(default_factory=dict)
    #: The measurements the entries came from, retained so a record can be
    #: traced back to the evidence rather than only to the number.
    measurements: tuple[MeasuredGpuRequirement, ...] = ()

    @classmethod
    def from_measurements(cls, *measurements: MeasuredGpuRequirement) -> MeasuredRequirementTable:
        """Assemble a table, refusing anything that is not authoritative.

        Raises on a non-authoritative measurement rather than skipping it.
        Skipping would produce a table missing a phase, which
        `_phase_requirement` reads as `(None, None)` -- indistinguishable
        from never having measured at all, and in trial mode that proceeds.
        """
        admissible = [m for m in measurements if m.request.phase in ADMISSIBLE_PHASES]
        return cls(
            entries={m.request.phase: m.as_admission_entry() for m in admissible},
            measurements=tuple(admissible),
        )

    def for_phase(self, phase: str) -> tuple[float | None, str | None]:
        """The `(requirement_mib, provenance)` pair, or `(None, None)`.

        A phase with no entry is deliberately not a fallback to the other
        phase, to the larger of the two, or to a model-name match. B-G0
        measured one PUNet candidate 1.8x apart across the two phases.
        """
        evidence = self.for_phase_evidence(phase)
        return evidence.requirement_mib, evidence.provenance

    def for_phase_evidence(self, phase: str) -> AdmissionRequirementEvidence:
        """Keep the number, ownership and validation gap together at consumption."""
        return AdmissionRequirementEvidence.from_entry(self.entries.get(phase))
