"""The authority-producing read seam for measured calibration evidence.

V20 PR C1 / C-C5a.

THE DEFECT THIS EXISTS TO CLOSE. `CalibrationRegistry.as_estimate` granted
measured, blocking-eligible authority whenever a bucket was `validated` and
the environment was local. It never received the candidate the estimate was
being produced FOR, so it could not have checked applicability even in
principle. That is the frozen invariant §8.A violated structurally: *a bucket
match is not applicability*.

It was not a live production bug -- at the time of writing nothing in
production read the registry back at all (System B had only write paths). It
was worse in a quiet way: an interface that would have mis-granted authority
the moment anyone wired it up, with tests asserting that it did.

THE ORDER IS THE CONTRACT. An estimate may carry measured authority only
after all four steps succeed, in this order:

  1. exact identity match          -- is this measurement about the same thing?
  2. validated bucket state        -- is the bucket's evidence trustworthy?
  3. applicability to the candidate-- does it cover THIS request?
  4. otherwise: downgrade          -- missing, inconclusive or false all fail.

Steps 1 and 3 are deliberately different kinds of check and must not be
collapsed. Identity is equality: task, phase, device instance, measurement
kind, family, config, data shape, stack. Applicability is a bounded range:
the candidate's batch size and segment length inside what was actually
observed. A measurement can pass either and fail the other.

FAIL CLOSED, ALWAYS. No candidate context, no identity on the record, no
measured range for a requested dimension, an unknown model family -- every
one of these yields non-authoritative evidence. Absent evidence is never
supporting evidence, and a caller that forgets to pass a candidate gets a
historical prior rather than a silent promotion to blocking authority.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_control.registry_schemas import MeasurementIdentity

if TYPE_CHECKING:  # pragma: no cover - typing only
    from core.runtime_control.calibration_policy import ApplicabilityEnvelope


class CandidateRequest(BaseModel):
    """WHO an estimate is being requested for.

    The counterpart to `MeasurementIdentity`, which says who a measurement is
    ABOUT. Authority requires the two to match exactly and, on top of that,
    the candidate's dimensions to fall inside what the bucket observed.

    Requiring this object is the point: the previous seam took no candidate
    at all, so "does this evidence apply here?" was a question the code had
    no vocabulary to ask.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Exact-match dimensions. Must equal the observation's identity.
    identity: MeasurementIdentity
    #: Bounded-range dimensions of the concrete candidate -- batch size,
    #: segment length. Checked against the bucket's observed spans, never
    #: against a threshold.
    dimensions: dict[str, float] = Field(default_factory=dict)


class AuthorityDecision(BaseModel):
    """Whether measured authority may be granted, and why not when it may not.

    A refusal always carries its reason. "This estimate is only a prior" is
    not actionable; "requested batch_size 64 outside measured range [2, 8]"
    is.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    granted: bool
    #: The applicability label, when evaluation got far enough to produce
    #: one. `None` means the request failed before applicability was
    #: reached -- identity mismatch, or no candidate supplied at all.
    applicability: str | None = None
    reasons: tuple[str, ...] = ()


#: Returned whenever a caller supplies no candidate context. Named so the
#: fail-closed path is greppable and cannot be mistaken for an oversight.
NO_CANDIDATE = AuthorityDecision(
    granted=False,
    reasons=(
        "no candidate request supplied: applicability cannot be evaluated, "
        "so measured evidence cannot carry blocking authority",
    ),
)


def evaluate_candidate_authority(
    observation: Any,
    request: CandidateRequest | None,
    *,
    envelope: ApplicabilityEnvelope | None,
) -> AuthorityDecision:
    """Steps 1 and 3 of the contract; the caller owns step 2.

    Separated from the bucket-state check because they fail for different
    reasons and a caller must be able to report which one refused. The
    registry method composes the two.

    Never raises: an unusable record is a refusal, not an exception, so a
    malformed identity cannot take down a run that was only asking for an
    estimate.
    """
    if request is None:
        return NO_CANDIDATE

    identity = getattr(observation, "identity", None)
    if identity is None:
        return AuthorityDecision(
            granted=False,
            reasons=(
                "observation carries no measurement identity (pre-C-C2 record): "
                "the task, device instance, phase and measurement kind it "
                "describes are unknown, so it cannot be shown to match",
            ),
        )

    if identity != request.identity:
        differing = tuple(
            f"{name}: measured {getattr(identity, name)!r} != requested "
            f"{getattr(request.identity, name)!r}"
            for name in MeasurementIdentity.model_fields
            if getattr(identity, name, None) != getattr(request.identity, name, None)
        )
        return AuthorityDecision(
            granted=False,
            reasons=("identity mismatch -- this measurement is about something else:", *differing),
        )

    # An unclassifiable family may be recorded as evidence but may never be
    # authoritative (frozen invariant §8.A).
    if not identity.family_is_known:
        return AuthorityDecision(
            granted=False,
            reasons=(
                "model family could not be classified; unknown-family evidence is never authoritative",
            ),
        )

    if envelope is None:
        return AuthorityDecision(
            granted=False,
            reasons=(
                "no applicability envelope for this bucket: nothing records what was observed",
            ),
        )

    label, reasons = envelope.classify(request.dimensions)
    if label != "interpolation":
        return AuthorityDecision(granted=False, applicability=label, reasons=reasons)
    return AuthorityDecision(granted=True, applicability=label, reasons=reasons)
