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

from collections.abc import Mapping
from typing import Any, Literal

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


# ---------------------------------------------------------------------------
# Resolving the verdict for a PERSISTED record (V20 PR D, D-C4)
# ---------------------------------------------------------------------------

#: How a persisted record's authority was established — or why it could not
#: be. The three failure bases all exclude, and each names a different
#: distrust so an operator can tell a tampered artifact from an old one.
AuthorityBasis = Literal[
    # The record carried a verdict whose conclusions match a fresh
    # derivation from its own facts.
    "stored_verdict",
    # No verdict on the record, but its policy was reconstructable from the
    # output-level declaration plus commit-time validity (§12A ladder).
    "reconstructed_legacy",
    # No verdict and the policy cannot be reconstructed — UNKNOWN, which is
    # never a licence to assume.
    "unreconstructable_legacy",
    # A verdict was present but its conclusions contradict its own facts:
    # somebody edited the dict after it was written.
    "verdict_inconsistent_with_its_facts",
    # The verdict claims its formal round passed while the iteration's own
    # commit-time evidence says it failed.
    "stored_validity_contradicts_commit_time",
    # Present but unusable — not a mapping, or missing/invalid facts.
    "malformed_verdict",
]

_FAILURE_BASES: frozenset[str] = frozenset(
    {
        "unreconstructable_legacy",
        "verdict_inconsistent_with_its_facts",
        "stored_validity_contradicts_commit_time",
        "malformed_verdict",
    }
)

_VALIDITIES: frozenset[str] = frozenset({"valid", "invalid", "unknown"})


class RecordAuthority(BaseModel):
    """Whether one PERSISTED formal record may inform decision state.

    The distinction from :class:`ScientificAuthority` is the input. That one
    takes three trusted facts. This one takes an artifact that a later
    writer could have edited, and is therefore **fail-closed**: anything it
    cannot independently justify is excluded.

    **The stored conclusions are never believed.** ``verdict`` is always a
    fresh derivation. D-C2b made the persisted block *tamper-evident* by
    writing the facts beside the conclusions; this is the consumer that
    actually acts on that, so a hand-edited ``authoritative: true`` buys
    nothing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: The freshly derived verdict, or ``None`` when nothing could be
    #: derived. NEVER the stored dict's conclusions.
    verdict: ScientificAuthority | None
    basis: AuthorityBasis

    @computed_field  # type: ignore[prop-decorator]
    @property
    def authoritative(self) -> bool:
        """May this record become the chain incumbent?"""
        if self.basis in _FAILURE_BASES or self.verdict is None:
            return False
        return self.verdict.authoritative

    @computed_field  # type: ignore[prop-decorator]
    @property
    def exclusion_reason(self) -> str | None:
        """Why it may not — machine-readable, ``None`` when it may.

        A distrust basis outranks the verdict's own reason: "this artifact
        disagrees with itself" is a different operator action from "this
        run was diagnostic".
        """
        if self.authoritative:
            return None
        if self.basis in _FAILURE_BASES:
            return self.basis
        return self.verdict.primary_basis if self.verdict is not None else "malformed_verdict"


def resolve_record_authority(
    record: Mapping[str, Any],
    *,
    declared_healthgate_mode: str | None,
    declared_result_authority: str | None,
    commit_time_validity: FormalValidity,
) -> RecordAuthority:
    """Fail-closed authority for one persisted formal record.

    Args:
        record: the record as serialized in ``all_records``.
        declared_healthgate_mode: the OUTPUT-level declaration, used only
            to reconstruct a record that carries no verdict of its own.
        declared_result_authority: same.
        commit_time_validity: the iteration's own commit-time verdict for
            this record, resolved by the caller against the workspace's
            materialized effective policy — never against the repo-current
            config.

    Returns:
        A :class:`RecordAuthority`. Never raises: a historical or corrupt
        artifact must stay readable, and is excluded rather than fatal.
    """
    stored = record.get("scientific_authority")

    if stored is None:
        # --- legacy ladder (§12A) -------------------------------------
        verdict = ScientificAuthority.from_context(
            healthgate_mode=declared_healthgate_mode,
            declared_result_authority=declared_result_authority,
            formal_validity=commit_time_validity,
        )
        basis: AuthorityBasis = (
            "unreconstructable_legacy"
            if "legacy_authority_unknown" in verdict.blocking_reasons
            else "reconstructed_legacy"
        )
        return RecordAuthority(verdict=verdict, basis=basis)

    if not isinstance(stored, Mapping):
        return RecordAuthority(verdict=None, basis="malformed_verdict")

    validity = stored.get("formal_validity")
    if validity not in _VALIDITIES:
        # The one fact with no safe default. Without it the verdict cannot
        # be re-derived at all, so there is nothing to check it against.
        return RecordAuthority(verdict=None, basis="malformed_verdict")

    recomputed = ScientificAuthority.from_context(
        healthgate_mode=stored.get("healthgate_mode"),
        declared_result_authority=stored.get("declared_result_authority"),
        formal_validity=validity,  # type: ignore[arg-type]
    )

    # Conclusions must match a fresh derivation from the record's own
    # facts. Only keys actually present are compared, so a verdict written
    # by an older schema is not condemned for lacking a field that did not
    # exist — but any key it DOES carry must agree.
    fresh = recomputed.model_dump()
    for key, value in stored.items():
        if key in fresh and fresh[key] != value:
            return RecordAuthority(verdict=None, basis="verdict_inconsistent_with_its_facts")

    # The facts themselves can be edited too, so cross-check the one that
    # the iteration independently recorded. Deliberately narrow: only a
    # WEAKENING contradiction counts (stored says its gates passed, the
    # commit-time evidence says they failed). A commit-time ``unknown`` is
    # an evidence gap, not a contradiction, and must not retroactively
    # condemn a record whose effective-policy artifact is simply missing.
    if commit_time_validity == "invalid" and validity == "valid":
        return RecordAuthority(verdict=None, basis="stored_validity_contradicts_commit_time")

    return RecordAuthority(verdict=recomputed, basis="stored_verdict")
