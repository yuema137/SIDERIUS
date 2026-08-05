"""Whether a formal result may inform science — derived, never asserted.

V20 PR D, checkpoint D-C2a. A pure typed value: facts in, verdict out, no
call sites.

**The conclusions are computed fields, not settable ones.** A caller
supplies only the three facts; `authoritative`, `primary_basis`,
`blocking_reasons`, `enters_incumbent_selection` and
`enters_scientific_aggregation` are derived. That is structural rather
than validated — there is no constructor argument for them, so a caller
cannot supply a conclusion that contradicts its own premises, and no
validator has to catch it after the fact.

**Launch and authority are different questions** (§16.D). Nothing about
*why the formal round ran* appears here: not the trial winner, not
`valid_trial_count`, not the skip or bypass decision, not the comparison
reference, not `force_formal_round`. Those decide whether it was worth
spending the round. This decides whether the result it produced may be
believed. A first formal result that bypassed the time budget on the
`-inf` bootstrap is no less authoritative for it.

So `no_valid_trial` is **not** a blocking reason and must never become
one.

**Historical records must remain expressible.** `observe_only +
scientific` is refused for a new launch (D-C1b), but artifacts recorded
under it exist and document an incident. This function returns a
non-authoritative verdict for them; it does not raise. A pure function
that throws on historical data makes the history unreadable.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, computed_field

#: What the formal record's own role-aware HealthGate verdict says.
#: ``unknown`` is a first-class outcome — a gap is never a pass.
FormalValidity = Literal["valid", "invalid", "unknown"]

#: Why a result cannot inform science. Machine-readable, so a report can
#: state the reason rather than a count.
AuthorityBlocker = Literal[
    # The run never claimed scientific standing.
    "declared_diagnostic",
    # Gates only recorded, so nothing was enforced. Also the verdict for a
    # historical `observe_only + scientific` artifact, which D-C1b now
    # refuses at launch but which remains readable.
    "non_blocking_mode",
    # The formal record's own blocking gates failed.
    "gate_invalidated",
    # The formal record's validity could not be established.
    "formal_validity_unknown",
    # The artifact predates the declaration and its policy cannot be
    # reconstructed (§12A).
    "legacy_authority_unknown",
]

#: Order in which blockers are reported, most categorical first: a run that
#: never claimed science is not "invalid", it is out of scope, and saying
#: so first is more useful to an operator than a gate detail.
_BLOCKER_PRECEDENCE: tuple[AuthorityBlocker, ...] = (
    "legacy_authority_unknown",
    "declared_diagnostic",
    "non_blocking_mode",
    "gate_invalidated",
    "formal_validity_unknown",
)


class ScientificAuthority(BaseModel):
    """The authority verdict for one formal record.

    Construct through :meth:`from_context`. The three fields below are the
    facts; everything else is derived.
    """

    # `frozen` so a verdict cannot be edited after derivation; `extra`
    # forbidden so a caller that TRIES to supply a conclusion is refused
    # rather than silently ignored. Without `forbid`, Pydantic drops
    # `authoritative=True` and the caller believes it took effect — the
    # verdict would still be correct, but for a reason the caller does not
    # know, which is how a wrong mental model survives review.
    model_config = ConfigDict(frozen=True, extra="forbid")

    #: The declared enforcement mode; ``None`` on a pre-declaration record.
    healthgate_mode: Literal["blocking", "observe_only"] | None
    #: The declared result authority; ``None`` on a pre-declaration record.
    declared_result_authority: Literal["scientific", "diagnostic"] | None
    #: The formal record's OWN role-aware HealthGate verdict.
    formal_validity: FormalValidity

    @classmethod
    def from_context(
        cls,
        *,
        healthgate_mode: str | None,
        declared_result_authority: str | None,
        formal_validity: FormalValidity,
    ) -> ScientificAuthority:
        """The verdict for these facts.

        Args:
            healthgate_mode: ``blocking`` / ``observe_only`` / ``None``.
            declared_result_authority: ``scientific`` / ``diagnostic`` /
                ``None``.
            formal_validity: the formal record's own verdict, from the
                shared role-aware resolver — never re-derived from a gate
                id, action, suffix or filename.

        Returns:
            A frozen verdict. Never raises for a historical combination.
        """
        return cls(
            healthgate_mode=healthgate_mode,  # type: ignore[arg-type]
            declared_result_authority=declared_result_authority,  # type: ignore[arg-type]
            formal_validity=formal_validity,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def blocking_reasons(self) -> list[AuthorityBlocker]:
        """Every reason this result cannot inform science, in report order.

        All of them, not the first — an operator fixing one should be able
        to see the others without re-running.
        """
        found: set[AuthorityBlocker] = set()
        if self.healthgate_mode is None or self.declared_result_authority is None:
            found.add("legacy_authority_unknown")
        if self.declared_result_authority == "diagnostic":
            found.add("declared_diagnostic")
        if self.healthgate_mode == "observe_only":
            found.add("non_blocking_mode")
        if self.formal_validity == "invalid":
            found.add("gate_invalidated")
        elif self.formal_validity == "unknown":
            found.add("formal_validity_unknown")
        return [reason for reason in _BLOCKER_PRECEDENCE if reason in found]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def authoritative(self) -> bool:
        """Whether this result may inform science.

        True only for a fully-declared, enforced, scientific run whose own
        formal record passed. Every other combination is blocked, and says
        why.
        """
        return not self.blocking_reasons

    @computed_field  # type: ignore[prop-decorator]
    @property
    def primary_basis(self) -> str:
        """The single most useful sentence-worth of the verdict."""
        reasons = self.blocking_reasons
        return reasons[0] if reasons else "blocking_scientific_formal_valid"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def enters_incumbent_selection(self) -> bool:
        """A non-authoritative result must never become the incumbent."""
        return self.authoritative

    @computed_field  # type: ignore[prop-decorator]
    @property
    def enters_scientific_aggregation(self) -> bool:
        """…nor be averaged into a scientific claim.

        Kept separate from :attr:`enters_incumbent_selection` even though
        the two currently agree: they are different consumers, and a future
        divergence should be a visible edit here rather than a surprise at
        one of the call sites.
        """
        return self.authoritative
