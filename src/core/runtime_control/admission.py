"""May this phase start on this device right now? (V20 PR B, B-C4a).

Generic runtime infrastructure. It answers one question from *measured*
occupancy and returns a typed decision with the provenance of every
figure it used. It never names a task knob, and a refusal here is a
statement about the machine, not about the candidate.

**Why measured, and why provenance is required.** A6 measured a
candidate admitted at a 6.43 GB predicted estimate go on to hold
12.52 GiB — 1.95x. Comparing a predicted *allocated* estimate against a
driver-visible ceiling is the defect PR B exists to remove, rebuilt
behind a guard that would then look like it was working. So the
requirement carries its provenance, and in formal mode a
non-authoritative provenance is refused rather than used.

**What it deliberately does not do.** It does not obtain, validate or
promote a measurement — that is PR C's responsibility (D-B5), and a
second measurement authority is the shape of defect this whole document
was opened about. It does not know what a peer is (D-B1): occupancy is
split into ours and everything else, measured, with no cross-process
registry. It does not retry, wait, or reschedule.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.runtime_control.pair_admission import (
    PairMember,
    evaluate_pair_admission,
    gib_from_mib,
    pair_ceiling_gib,
)

#: How a run treats an unproven situation. Not a severity — two
#: different postures with different obligations (§B-C4 2b).
#:
#: The spelling is `trial | formal`, matching every other mode field in
#: the project (`time_mode`, `active_mode`, `RuntimeMode.phase`).
#: "Diagnostic" describes what a trial round *does*; it is not a second
#: configuration word for the same policy, and carrying both would put
#: two spellings of one posture into provenance.
AdmissionMode = Literal["formal", "trial"]

#: Frozen with `skipped_resource_admission` in the tuner (B-C4a0 C3).
#: A refusal reason is an infrastructure condition; none of these says
#: anything about the candidate's size.
#:
#: The split, corrected by operator review 2026-08-02:
#:   measurement_unavailable — no trustworthy device fact was obtained
#:   policy_unavailable      — facts exist, but what is needed to DECIDE
#:                             on them does not
#: A successful query that reports unavailable telemetry, or returns
#: figures that cannot be true, is still a *measurement* problem.
AdmissionReason = Literal[
    "insufficient_headroom",
    "measurement_unavailable",
    "policy_unavailable",
    "environment_headroom_unproven",
]

#: The refusals that are a RESOURCE verdict rather than an evidence gap
#: (M5, operator-frozen 2026-08-06).
#:
#: The frozen model is:
#:
#:     current resources + candidate demand + safety policy -> Admission
#:         enough       -> admit
#:         insufficient -> reject, and production must not continue
#:
#: `insufficient_headroom` IS that rejection. The other two are evidence
#: gaps — "no trustworthy device fact" and "facts exist but the deciding
#: input does not" — and an evidence gap is a different disposition, not a
#: resource verdict. They are guarded where the evidence actually exists:
#: the formal prephase gate fails closed on both with a real isolated
#: measurement behind the verdict, and an unresolvable required probe fails
#: closed in the tuner (M6).
#:
#: Consumed by `enforce_resource_limits`, never by `enforce`.
RESOURCE_REJECTIONS: frozenset[str] = frozenset({"insufficient_headroom"})

#: Finer classification of a refusal, so a record says *how* it failed
#: and not only that it did.
#:
#: `device_identity_mismatch` is **RESERVED and not currently emitted**.
#: Comparing the snapshot's UUID against an expected device needs a
#: caller-supplied expectation this layer is not given, and inventing one
#: would widen B-C4b past its scope. Declared so the vocabulary is fixed
#: before a producer exists, not because a producer exists.
AdmissionDetail = Literal[
    # under measurement_unavailable
    "sampler_error",
    "telemetry_unavailable",
    "device_identity_mismatch",
    "inconsistent_accounting",
    # under policy_unavailable
    "invalid_admission_mode",
]

#: Which detail may accompany which refusal. A detail on the wrong code
#: would let a record describe a failure it did not have.
_DETAIL_FOR_REASON: dict[str, frozenset[str]] = {
    "measurement_unavailable": frozenset(
        {
            "sampler_error",
            "telemetry_unavailable",
            "device_identity_mismatch",
            "inconsistent_accounting",
        }
    ),
    "policy_unavailable": frozenset({"invalid_admission_mode"}),
}

#: The only accepted postures. `diagnostic` is deliberately NOT accepted:
#: it was an earlier spelling of this same policy, and supporting both
#: would mean two words for one posture in every record that carries it.
ACCEPTED_MODES: frozenset[str] = frozenset({"formal", "trial"})

#: Whether an adverse decision STOPS the phase, or is only recorded.
#:
#: Deliberately orthogonal to `AdmissionMode`. The phase posture says
#: what a round *is*; this says what the run does about a refusal. Fusing
#: them was rejected (operator, 2026-08-02): mapping a formal round to
#: `trial` to keep it running would make every record claim a posture the
#: round did not have, and provenance that lies is worse than a gate that
#: does not fire.
#:
#: `observe_only` exists because B-G3 made the consequence concrete. Once
#: the gate is reachable, formal + no authoritative measurement refuses —
#: correctly — and PR C, which would supply the measurement, does not
#: exist yet. Merging PR B with enforcement on would stop formal training
#: repository-wide in the interval. So the compatibility default
#: evaluates the real decision, records what it *would* have done, and
#: lets the phase proceed.
#: `enforce_resource_limits` is the V20 PRODUCTION posture (M5,
#: operator-frozen 2026-08-06). It stops the phase on a resource verdict
#: (`RESOURCE_REJECTIONS`) and records an evidence gap as an observation.
#:
#: It is a third value rather than a redefinition of `enforce`, for two
#: reasons found by the tests when the redefinition was attempted:
#:
#:   * `enforce` is the posture the B-G validation harness ran under, and
#:     B-G1/B-G2 are evidence about *that* behaviour. Narrowing it would
#:     have silently disarmed the guard those runs demonstrate, while the
#:     suite still looked green;
#:   * plain `enforce` cannot be the production posture at all. The
#:     prephase measurement covers `phase="training"` only, so
#:     `MeasuredRequirementTable.for_phase("inference")` is structurally
#:     `(None, None)` and every formal INFERENCE phase would refuse
#:     `policy_unavailable` — a campaign that produces no formal result.
#:
#: So: `enforce` keeps meaning "stop on any adverse decision", and the
#: production launcher asks for the resource-verdict posture by name.
AdmissionEnforcement = Literal["observe_only", "enforce", "enforce_resource_limits"]

#: The only accepted enforcement values. An unrecognised one is a
#: misconfiguration, never silently resolved to any of them — resolving it
#: to `observe_only` would disable a guard the operator asked for, and to
#: an enforcing value would stop work they did not ask to stop.
ACCEPTED_ENFORCEMENT: frozenset[str] = frozenset(
    {"observe_only", "enforce", "enforce_resource_limits"}
)


def stops_phase(enforcement: str, reason_code: str | None) -> bool:
    """Whether an ADVERSE decision stops the phase under this posture.

    One home for the enforcement question, so the executor cannot answer
    it slightly differently from a test or a future second call site.

    Args:
        enforcement: the configured posture. An unrecognised value is
            treated as non-enforcing here **only** because
            `GpuAdmissionPolicy` already refuses it at construction; this
            function is not the validation point.
        reason_code: the refusal's `AdmissionReason`, typed Optional
            because `AdmissionDecision.reason_code` is — an admitted
            decision carries none. `_a_refusal_must_say_why` makes `None`
            unreachable for an actual refusal, so this is a type-level
            honesty fix, not a behaviour change. It is still answered
            explicitly rather than left to fall through: a missing reason
            is not a resource rejection, and `enforce`'s "stop on any
            adverse decision" already has an adverse decision in hand.
    """
    # Explicit isolation conditions precede the ordinary observation policy.
    if reason_code == "environment_headroom_unproven":
        return True
    if enforcement == "enforce":
        return True
    if enforcement == "enforce_resource_limits":
        return reason_code is not None and reason_code in RESOURCE_REJECTIONS
    return False


#: Provenance values this module treats as a driver-visible measurement.
#: Anything else — notably a predicted estimate — is not authoritative,
#: and formal mode refuses rather than using it.
AUTHORITATIVE_PROVENANCE: frozenset[str] = frozenset({"measured", "promoted_measurement"})


class GpuAdmissionPolicy(BaseModel):
    """How a run configures the GPU admission gate (V20 B-G3).

    The typed boundary the gate had been missing. Before this, nothing in
    production set `admission_mode` or `measured_requirements`, so the
    `getattr` defaults were the only values the gate ever saw: posture
    permanently `trial`, requirement permanently `None`, hence admit
    unconditionally. The gate was correct and unreachable.

    Deliberately a **reference**, never a figure. There is no
    `requirement_mib` field and no CLI flag that takes one: a raw number
    an operator can type would impersonate a measurement in formal mode,
    which is the estimate-as-fact defect this PR exists to remove.
    `measurement_source` names *where* an authoritative measurement would
    come from. Until PR C exists, resolving it yields nothing and formal
    correctly refuses `policy_unavailable`.

    Posture is **derived, not re-entered**. It comes from the same
    `plan.is_trial` that already drives the time gate and the VRAM budget
    pick. A second independent posture input could disagree with the
    round actually executing, and the disagreement would be invisible.

    Frozen, like `RuntimeControlPolicy`: it is resolved once per attempt
    by the caller and read by the gate, never mutated in flight.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: AdmissionMode = Field(
        description=(
            "Admission posture for this phase, derived from the executing "
            "round. `formal` must demonstrate safety before proceeding; "
            "`trial` proceeds and records what it could not prove."
        ),
    )
    measurement_source: str | None = Field(
        default=None,
        description=(
            "Where an authoritative measurement for this candidate would "
            "be resolved from. A reference, never a value. `None` means no "
            "source is configured, which in formal mode is refused."
        ),
    )
    ceiling_gib: float | None = Field(
        default=None,
        # `gt=0`, not `gt=0.0`: an int bound keeps this module free of
        # float literals, which the genericity test enforces so a
        # capacity constant like 12 or 28 GiB cannot arrive unnoticed.
        # This bound means "positive", not a capacity.
        gt=0,
        description=(
            "Resolved aggregate ceiling. `None` defers to the environment "
            "resolver, preserving pre-B-G3 behaviour."
        ),
    )
    device_uuid: str | None = Field(
        default=None,
        description=(
            "The device this policy was resolved for, carried so a record "
            "can be checked against the card it actually ran on. Never "
            "used to select a device — discovery owns that."
        ),
    )
    enforcement: AdmissionEnforcement = Field(
        default="observe_only",
        description=(
            "Whether an adverse decision stops the phase (`enforce`) or is "
            "only recorded (`observe_only`). Orthogonal to `mode`: the "
            "posture says what the round is, this says what the run does "
            "about a refusal. `observe_only` is the compatibility default "
            "while PR C does not yet supply authoritative measurements, so "
            "that merging PR B does not stop formal training everywhere. "
            "The phase is NEVER relabelled to keep it running."
        ),
    )
    provenance: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "How each field above was obtained (launcher flag, environment "
            "variable, discovery, default). Kept so a refusal can be "
            "audited without re-deriving the configuration."
        ),
    )


class AdmissionDecision(BaseModel):
    """Whether the phase may start, and everything the answer rested on."""

    model_config = ConfigDict(frozen=True)

    admitted: bool
    #: `None` exactly when admitted. Enforced, so a refusal cannot be
    #: recorded without saying what refused it.
    reason_code: AdmissionReason | None = None
    #: Set only under `measurement_unavailable`, naming how the
    #: measurement failed.
    detail: AdmissionDetail | None = None
    #: Which tier of the §2a priority order answered — or `unavailable`
    #: when nothing did, which trial mode records rather than hides.
    requirement_source: str
    reason: str
    #: Every figure used, so the decision is auditable rather than
    #: asserted. Absent keys mean the quantity was unavailable.
    evidence: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _a_refusal_must_say_why(self) -> AdmissionDecision:
        if self.detail is not None:
            allowed = _DETAIL_FOR_REASON.get(self.reason_code or "", frozenset())
            if self.detail not in allowed:
                raise ValueError(
                    f"detail {self.detail!r} does not belong to reason_code "
                    f"{self.reason_code!r}; a record must not describe a failure "
                    "it did not have"
                )
        if self.admitted and self.reason_code is not None:
            raise ValueError(
                f"admitted=True cannot carry reason_code {self.reason_code!r}; "
                "an admission has no refusal reason"
            )
        if not self.admitted and self.reason_code is None:
            raise ValueError(
                "a refusal must carry a reason_code — a phase refused for no "
                "recorded reason cannot be audited or appealed"
            )
        return self


def _refuse(
    reason_code: AdmissionReason,
    reason: str,
    *,
    source: str,
    evidence: dict[str, Any],
    detail: AdmissionDetail | None = None,
) -> AdmissionDecision:
    return AdmissionDecision(
        admitted=False,
        reason_code=reason_code,
        detail=detail,
        requirement_source=source,
        reason=reason,
        evidence=evidence,
    )


def _admit(reason: str, *, source: str, evidence: dict[str, Any]) -> AdmissionDecision:
    return AdmissionDecision(
        admitted=True,
        reason_code=None,
        requirement_source=source,
        reason=reason,
        evidence=evidence,
    )


def evaluate_gpu_admission(
    *,
    snapshot: Any,
    requirement_mib: float | None,
    requirement_provenance: str | None,
    mode: str,
    run_name: str = "candidate",
    ceiling_gib: float | None = None,
    sampling_error: str | None = None,
) -> AdmissionDecision:
    """Decide whether to start a GPU phase, from measured occupancy.

    Args:
        snapshot: a `GpuAccountingSnapshot` taken before spawn.
        requirement_mib: how much this phase is expected to need. `None`
            means unknown — which is refused in formal mode and recorded
            in trial mode, **never** silently treated as zero.
        requirement_provenance: where that figure came from. Only
            `AUTHORITATIVE_PROVENANCE` counts as a measurement.
        mode: `formal` demonstrates safety before proceeding; `trial`
            proceeds and records what it could not prove.
            Typed as `str` and validated **here**, so an unrecognised
            posture is a recorded misconfiguration rather than something
            the caller silently resolves — and never masquerades as a
            deliberate `formal`.
        ceiling_gib: aggregate ceiling override. Defaults to the stricter
            of configured policy and the device's measured capacity —
            policy may be tighter than the hardware, never looser.
        sampling_error: set when the caller could not obtain a reading at
            all. Handled **here** rather than by the caller, so that a
            broken sampler cannot become an unconditional "proceed": mode
            policy has exactly one home.

    The two modes differ **only** where safety is unproven. Where
    occupancy is measured and the requirement does not fit, both refuse:
    headroom is a fact, not a posture.
    """
    from core.runtime_control.process_visibility import requires_isolated_admission

    if requires_isolated_admission(snapshot):
        from core.runtime_control.isolated_admission import evaluate_isolated_admission

        return evaluate_isolated_admission(
            snapshot=snapshot,
            requirement_mib=requirement_mib,
            requirement_provenance=requirement_provenance,
            mode=mode,
            ceiling_gib=ceiling_gib,
            sampling_error=sampling_error,
        )

    if mode not in ACCEPTED_MODES:
        # An invalid posture refuses, like formal — but the record must
        # not SAY formal. Conflating a configuration error with a
        # deliberate choice would make the audit trail lie about what
        # was configured.
        return _refuse(
            "policy_unavailable",
            f"admission_mode {mode!r} is not one of {sorted(ACCEPTED_MODES)}; an "
            "unknown posture cannot demonstrate safety, and this is a "
            "configuration error rather than a decision about the candidate",
            source="unavailable",
            evidence={"mode": mode, "accepted_modes": sorted(ACCEPTED_MODES)},
            detail="invalid_admission_mode",
        )

    if sampling_error is not None:
        # No reading was obtained. This is deliberately not a caller-side
        # `return None`: swallowing it there would make formal mode fail
        # OPEN exactly when it is supposed to protect, which is the
        # fail-open posture this commit exists to remove.
        failed = {"mode": mode, "sampling_error": sampling_error}
        if mode == "formal":
            return _refuse(
                "measurement_unavailable",
                f"device occupancy could not be sampled ({sampling_error}), so no "
                "measurement exists to admit on; refusing is an infrastructure "
                "condition and says nothing about the candidate",
                source="unavailable",
                evidence=failed,
                detail="sampler_error",
            )
        return _admit(
            f"device occupancy could not be sampled ({sampling_error}); proceeding "
            "under trial mode with no safety claim",
            source="unavailable",
            evidence=failed,
        )

    telemetry = bool(getattr(snapshot, "telemetry_available", False))
    total_mib = getattr(snapshot, "device_total_mib", None)
    used_mib = getattr(snapshot, "device_used_mib", None)
    other_mib = getattr(snapshot, "other_mib", None)
    device = getattr(snapshot, "device", None)

    evidence: dict[str, Any] = {
        "mode": mode,
        "telemetry_available": telemetry,
        "device_total_mib": total_mib,
        "device_used_mib": used_mib,
        "other_mib": other_mib,
        "device_uuid": getattr(device, "uuid", None),
        "requirement_mib": requirement_mib,
        "requirement_provenance": requirement_provenance,
    }

    # --- telemetry ---------------------------------------------------
    if not telemetry or total_mib is None or used_mib is None or other_mib is None:
        if mode == "formal":
            return _refuse(
                "measurement_unavailable",
                "device occupancy could not be measured, so safety has not been "
                "demonstrated; refusing is an infrastructure condition, not a "
                "statement about the candidate",
                source="unavailable",
                evidence=evidence,
                detail="telemetry_unavailable",
            )
        return _admit(
            "device occupancy could not be measured; proceeding under trial "
            "mode with no safety claim",
            source="unavailable",
            evidence=evidence,
        )

    if used_mib > total_mib:
        return _refuse(
            "measurement_unavailable",
            f"the device reports {used_mib} MiB used of {total_mib} MiB total, "
            "which cannot be true; an inconsistent reading is not a headroom figure",
            source="unavailable",
            evidence=evidence,
            detail="inconsistent_accounting",
        )

    # FU-B-17. The ceiling triple is recorded as soon as the device
    # figures are trustworthy, not only on the headroom path. A
    # `policy_unavailable` refusal returns before the headroom block, so
    # without this a record could not be audited for which ceiling
    # applied — and for `insufficient_headroom` the ceiling *is* the
    # decision. Configured policy and measured hardware stay separate
    # fields, because "the operator asked for 6 GiB" and "the card holds
    # 31.8 GiB" are different facts and the effective value is derived.
    evidence |= {
        "configured_ceiling_gib": (pair_ceiling_gib() if ceiling_gib is None else ceiling_gib),
        "measured_device_capacity_gib": gib_from_mib(total_mib),
        "effective_ceiling_gib": min(
            (pair_ceiling_gib() if ceiling_gib is None else ceiling_gib),
            gib_from_mib(total_mib),
        ),
    }

    # --- requirement -------------------------------------------------
    authoritative_requirement: float | None = None
    if (
        requirement_mib is not None
        and requirement_mib > 0
        and requirement_provenance in AUTHORITATIVE_PROVENANCE
    ):
        # Bound rather than re-derived: a boolean flag does not narrow
        # the Optional, and a checker that cannot follow the reasoning
        # is telling us a reader cannot either.
        authoritative_requirement = float(requirement_mib)
    if authoritative_requirement is None:
        if mode == "formal":
            return _refuse(
                "policy_unavailable",
                "device occupancy was measured, but no applicable authoritative "
                "requirement for this candidate exists, and a predicted estimate "
                "is not a resource fact; producing one is PR C's responsibility "
                "(D-B5)",
                source="unavailable",
                evidence=evidence,
            )
        return _admit(
            "no authoritative requirement available; proceeding under trial "
            "mode and recording that the guard asserted nothing",
            source="unavailable",
            evidence=evidence,
        )

    # --- headroom, from measurement ----------------------------------
    # Policy may be stricter than the hardware, never looser: a
    # configured ceiling above the device's capacity would admit work
    # the card cannot hold.
    measured_capacity_gib = gib_from_mib(total_mib)
    configured = pair_ceiling_gib() if ceiling_gib is None else ceiling_gib
    effective_ceiling = min(configured, measured_capacity_gib)

    members = [
        PairMember(
            run_name=run_name,
            predicted_peak_vram_gb=gib_from_mib(authoritative_requirement),
            provenance=str(requirement_provenance),
        )
    ]
    if other_mib > 0:
        # Everything else on the device, measured. Deliberately not a
        # named peer: identifying one would need a cross-process
        # registry this layer does not have (D-B1).
        members.append(
            PairMember(
                run_name="other_occupancy",
                predicted_peak_vram_gb=gib_from_mib(float(other_mib)),
                provenance="measured",
            )
        )

    pair = evaluate_pair_admission(members, ceiling_gib=effective_ceiling)
    evidence |= {
        # The ceiling triple is already recorded above (FU-B-17); these
        # are the headroom figures that only exist once a requirement
        # has been established.
        "aggregate_gib": pair.aggregate_gib,
        "headroom_gib": pair.headroom_gib,
        "host_quota_gib": pair.host_quota_gib,
        "pair_reasons": list(pair.reasons),
    }

    if not pair.feasible:
        return _refuse(
            "insufficient_headroom",
            f"{pair.aggregate_gib:.2f} GiB predicted against a "
            f"{effective_ceiling:.2f} GiB effective ceiling — short by "
            f"{-pair.headroom_gib:.2f} GiB. The environment does not currently "
            "permit this phase",
            source=str(requirement_provenance),
            evidence=evidence,
        )

    return _admit(
        f"{pair.aggregate_gib:.2f} GiB predicted against a "
        f"{effective_ceiling:.2f} GiB effective ceiling, {pair.headroom_gib:.2f} GiB "
        "headroom remaining",
        source=str(requirement_provenance),
        evidence=evidence,
    )
