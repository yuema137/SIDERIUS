"""Which formal results may inform a scientific aggregate — and which may not.

V20 PR D, checkpoint D-C5. A pure typed boundary: summaries in, a partition
out, no call sites of its own and no model involvement.

**The rule** (§16.D, §4.7):

```text
authoritative formal      -> included in the scientific aggregate
non-authoritative formal  -> retained as evidence
                          -> excluded from the aggregate
                          -> reported with an explicit typed reason
```

**Nothing is deleted.** An excluded result is still a fact about what the
campaign did; it simply cannot contribute to a scientific claim. The
failure mode this prevents is a *silently smaller sample* — an aggregate
that looks like a clean campaign because the results that would have
complicated it quietly vanished.

**The exclusion is rendered deterministically, never by a model** (§4.7,
operator decision 2026-08-04). Two reasons, and the second is the one that
usually gets missed: a model might simply not mention the exclusion, and
exclusion text placed inside a prompt can steer the scientific
interpretation the model then writes. So this module derives the counts and
reasons, and the report renders them from the typed object.

**Policy is delegated to its existing owners.** Stored verdicts go through
:mod:`core.scientific_authority`; independent formal-record facts go through
:mod:`execute_tools.health_checks.candidate_eligibility`. This boundary
requires their agreement and checks transport identity. It does not infer
scientific membership from gate names or enforcement actions.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, computed_field

from core.scientific_authority import RecordAuthority, resolve_record_authority
from execute_tools.formal_evidence import FormalResultEvidence
from execute_tools.health_checks.candidate_eligibility import (
    CandidateHealthValidity,
    classify_candidate_health,
)

#: What ``provenance_lines`` calls its own scope when the caller names none.
#:
#: N-3. The all-excluded sentence used to say "this CAMPAIGN produced no
#: scientifically authoritative result" from a partition that knows nothing
#: about a campaign — the interpreter renders it once per iteration over that
#: iteration's evidence, so a campaign with authoritative results in other
#: iterations was told, in the operator's own chain log, that it had none.
#: A default must not out-scope the object it is rendered from.
DEFAULT_AGGREGATION_SCOPE_NAME = "this aggregation"


class HasScientificAuthority(Protocol):
    """The minimum a record must expose to be partitioned.

    Structural rather than nominal so the boundary stays task-generic: any
    summary type carrying an identity and an authority verdict can be
    aggregated, regardless of which task produced it.
    """

    model_type: str
    run_name: str | None
    scientific_authority: dict[str, Any] | None
    formal_score: float | None
    formal_evidence: FormalResultEvidence | None


class ExcludedResult(BaseModel):
    """One result kept as evidence but barred from the aggregate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Identity as the operator knows it — whatever the caller uses to name
    #: the result in its own reports.
    record_id: str
    #: Machine-readable, from the authority verdict. Never free prose, so a
    #: report can group by it and an operator can act on it.
    reason: str
    #: How authority was established, or why it could not be.
    basis: str


class AggregationScope(BaseModel):
    """The partition, with the excluded side kept rather than dropped."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    included: list[str] = Field(
        default_factory=list,
        description="record_ids whose authority permits scientific aggregation.",
    )
    excluded: list[ExcludedResult] = Field(
        default_factory=list,
        description="Results retained as evidence but barred from the aggregate.",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def included_count(self) -> int:
        return len(self.included)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def excluded_count(self) -> int:
        return len(self.excluded)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_excluded(self) -> bool:
        """Every result present was excluded.

        Explicit because "everything was excluded" must read as a stated
        outcome. An empty aggregate alone is ambiguous — it looks identical
        to a campaign that simply found nothing, which is the opposite
        conclusion.
        """
        return bool(self.excluded) and not self.included

    @computed_field  # type: ignore[prop-decorator]
    @property
    def no_records(self) -> bool:
        """Nothing was submitted at all — distinct from all_excluded."""
        return not self.included and not self.excluded

    @computed_field  # type: ignore[prop-decorator]
    @property
    def exclusion_reason_counts(self) -> dict[str, int]:
        """Reasons in descending frequency, ties broken alphabetically, so
        the rendered provenance is byte-stable across runs."""
        counts: dict[str, int] = {}
        for item in self.excluded:
            counts[item.reason] = counts.get(item.reason, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    def provenance_lines(self, *, scope: str = DEFAULT_AGGREGATION_SCOPE_NAME) -> list[str]:
        """The fixed provenance section, derived — never model-written.

        Returns lines rather than one blob so a caller can indent or prefix
        them without re-parsing text.

        Args:
            scope: what this partition actually covers, named as a noun
                phrase that can follow "available in" — ``"iteration 3"``,
                ``"this campaign"``. **A conclusion may not out-scope its
                partition** (N-3): this object knows only the results it was
                handed, so it cannot know whether a campaign produced an
                authoritative result in some other iteration. The default
                names the object's own scope and is therefore always true;
                a caller that knows a wider or narrower scope says so.
        """
        if self.no_records:
            return ["Scientific aggregation used 0 results: none were submitted."]
        head = (
            f"Scientific aggregation used {self.included_count} "
            f"authoritative result{'' if self.included_count == 1 else 's'}."
        )
        if not self.excluded:
            return [head]
        lines = [
            head,
            f"{self.excluded_count} non-authoritative "
            f"result{'' if self.excluded_count == 1 else 's'} excluded:",
        ]
        lines += [f"  - {n} {reason}" for reason, n in self.exclusion_reason_counts.items()]
        if self.all_excluded:
            lines.append(
                f"EVERY result was excluded — no scientifically authoritative "
                f"result is available in {scope}."
            )
        return lines


def _independent_exclusion(summary: HasScientificAuthority) -> str | None:
    """Verify a stored positive claim against transported record facts."""
    raw = getattr(summary, "formal_evidence", None)
    if raw is None:
        return "formal_evidence_missing"
    try:
        evidence = (
            raw
            if isinstance(raw, FormalResultEvidence)
            else FormalResultEvidence.model_validate_json(json.dumps(raw), strict=True)
        )
    except (ValidationError, TypeError):
        return "formal_evidence_malformed"
    if (
        isinstance(summary.formal_score, bool)
        or not isinstance(summary.formal_score, int | float)
        or evidence.model_type != summary.model_type
        or evidence.run_name != getattr(summary, "run_name", None)
        or evidence.denoising_score != summary.formal_score
        or evidence.is_trial
    ):
        return "formal_evidence_mismatch"
    validity = classify_candidate_health(evidence, required_gate_ids=evidence.required_gate_ids)
    if validity is not CandidateHealthValidity.VALID:
        return (
            "formal_validity_unknown"
            if validity is CandidateHealthValidity.UNKNOWN
            else "gate_invalidated"
        )
    stored = summary.scientific_authority or {}
    for declared, field in (
        (evidence.healthgate_mode, "healthgate_mode"),
        (evidence.result_authority, "declared_result_authority"),
    ):
        if declared is not None and declared != stored.get(field):
            return "formal_declaration_mismatch"
    return None


def partition_for_aggregation(
    summaries: Iterable[Any],
    *,
    record_id: str = "model_type",
) -> AggregationScope:
    """Split summaries into what may inform science and what may not.

    Args:
        summaries: objects exposing ``scientific_authority`` (a persisted
            verdict dict, or ``None``) plus the attribute named by
            ``record_id``.
        record_id: attribute to use as the operator-facing identity.

    Returns:
        An :class:`AggregationScope`. Never raises for a malformed or
        missing verdict — such a result is EXCLUDED, because a record whose
        authority cannot be established must not inform a scientific claim.
    """
    included: list[str] = []
    excluded: list[ExcludedResult] = []

    for summary in summaries:
        identity = str(getattr(summary, record_id, None) or "<unidentified>")
        stored = getattr(summary, "scientific_authority", None)
        # `resolve_record_authority` re-derives the conclusions from the
        # record's own facts and refuses a verdict that disagrees with
        # itself, so a hand-edited `authoritative: true` buys nothing here.
        # The resolver takes the RECORD and reads `scientific_authority`
        # off it, so the verdict is wrapped rather than passed directly.
        # `declared_*` are None on purpose: a summary carrying no verdict
        # has no declaration to fall back on, which resolves to
        # `unreconstructable_legacy` and excludes it — the frozen rule for
        # anything missing the authority contract.
        resolution: RecordAuthority = resolve_record_authority(
            {"scientific_authority": stored},
            declared_healthgate_mode=None,
            declared_result_authority=None,
            commit_time_validity="unknown",
        )
        reason = (
            _independent_exclusion(summary)
            if resolution.authoritative
            else resolution.exclusion_reason or "authority_not_established"
        )
        if reason is None:
            included.append(identity)
        else:
            excluded.append(
                ExcludedResult(
                    record_id=identity,
                    reason=reason,
                    basis="independent_formal_evidence"
                    if resolution.authoritative
                    else resolution.basis,
                )
            )
    return AggregationScope(included=included, excluded=excluded)
