"""Authority is derived from facts, and launch history is not one of them.

V20 PR D, checkpoint D-C2a.

Two properties carry this module, and both are about what CANNOT happen:

- a caller cannot supply a conclusion. The verdict fields are computed, so
  there is no constructor argument for them, and `extra="forbid"` refuses
  a caller that tries — rather than silently dropping the argument and
  leaving them believing it took effect.
- nothing about *why the formal round ran* can reach the verdict. The
  trial winner, `valid_trial_count`, the skip and bypass decisions, the
  comparison reference and `force_formal_round` are all absent from the
  signature, so `no_valid_trial` cannot become a blocking reason by
  accident.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.scientific_authority import ScientificAuthority


def _verdict(mode, authority, validity) -> ScientificAuthority:
    return ScientificAuthority.from_context(
        healthgate_mode=mode,
        declared_result_authority=authority,
        formal_validity=validity,
    )


class TestTheTruthTable:
    """The operator's table, asserted row by row."""

    @pytest.mark.parametrize(
        ("mode", "authority", "validity", "authoritative", "primary"),
        [
            ("blocking", "scientific", "valid", True, "blocking_scientific_formal_valid"),
            ("blocking", "scientific", "invalid", False, "gate_invalidated"),
            ("blocking", "scientific", "unknown", False, "formal_validity_unknown"),
            ("blocking", "diagnostic", "valid", False, "declared_diagnostic"),
            ("blocking", "diagnostic", "invalid", False, "declared_diagnostic"),
            ("blocking", "diagnostic", "unknown", False, "declared_diagnostic"),
            ("observe_only", "diagnostic", "valid", False, "declared_diagnostic"),
            ("observe_only", "diagnostic", "invalid", False, "declared_diagnostic"),
            ("observe_only", "scientific", "valid", False, "non_blocking_mode"),
            ("observe_only", "scientific", "invalid", False, "non_blocking_mode"),
        ],
    )
    def test_each_row(self, mode, authority, validity, authoritative, primary):
        verdict = _verdict(mode, authority, validity)
        assert verdict.authoritative is authoritative
        assert verdict.primary_basis == primary

    def test_exactly_one_combination_is_authoritative(self):
        """The concept, not ten literals: only a fully-declared, enforced,
        scientific run whose own formal record passed may inform science."""
        authoritative = [
            (m, a, v)
            for m in ("blocking", "observe_only")
            for a in ("scientific", "diagnostic")
            for v in ("valid", "invalid", "unknown")
            if _verdict(m, a, v).authoritative
        ]
        assert authoritative == [("blocking", "scientific", "valid")]


class TestHistoricalRecordsStayReadable:
    def test_observe_only_scientific_does_not_raise(self):
        """D-C1b refuses this at launch, but artifacts recorded under it
        exist and document an incident. A pure function that threw on
        historical data would make that history unreadable."""
        verdict = _verdict("observe_only", "scientific", "valid")
        assert verdict.authoritative is False
        assert "non_blocking_mode" in verdict.blocking_reasons

    @pytest.mark.parametrize(
        ("mode", "authority"),
        [(None, None), ("blocking", None), (None, "scientific")],
    )
    def test_an_undeclared_record_is_unknown_not_assumed(self, mode, authority):
        """§12A: a record predating the declaration cannot have its policy
        reconstructed from nothing. UNKNOWN excludes it; it never defaults
        to authoritative."""
        verdict = _verdict(mode, authority, "valid")
        assert verdict.authoritative is False
        assert "legacy_authority_unknown" in verdict.blocking_reasons


class TestLaunchHistoryCannotReachTheVerdict:
    def test_no_trial_concept_appears_in_the_signature(self):
        """MUTATION TARGET: adding a trial-shaped parameter.

        Launch and authority are different questions (§16.D). A first
        formal result that bypassed the budget on the `-inf` bootstrap is
        no less authoritative for it.
        """
        import inspect

        params = set(inspect.signature(ScientificAuthority.from_context).parameters)
        forbidden = {
            "valid_trial_count",
            "trial_winner",
            "best_valid_trial_score",
            "skip_formal",
            "bypass_formal_time_budget",
            "formal_reference_score",
            "force_formal_round",
        }
        assert not (params & forbidden), f"launch history reached the verdict: {params & forbidden}"

    def test_no_valid_trial_is_not_a_blocking_reason(self):
        """The vocabulary itself must not be able to express it."""
        from core.scientific_authority import AuthorityBlocker

        reasons = set(AuthorityBlocker.__args__)  # type: ignore[attr-defined]
        assert "no_valid_trial" not in reasons
        assert not any("trial" in reason for reason in reasons), reasons


class TestConclusionsCannotBeSupplied:
    @pytest.mark.parametrize(
        "conclusion",
        [
            "authoritative",
            "primary_basis",
            "blocking_reasons",
            "enters_incumbent_selection",
            "enters_scientific_aggregation",
        ],
    )
    def test_a_caller_supplying_a_conclusion_is_refused(self, conclusion):
        """MUTATION TARGET: dropping `extra="forbid"`.

        Without it Pydantic silently DISCARDS the argument. The verdict
        would still be right, but the caller would believe they had set it
        — which is how a wrong mental model survives review.
        """
        with pytest.raises(ValidationError):
            ScientificAuthority(
                healthgate_mode="observe_only",
                declared_result_authority="scientific",
                formal_validity="invalid",
                **{conclusion: True},
            )

    def test_a_verdict_cannot_be_mutated_after_derivation(self):
        verdict = _verdict("blocking", "scientific", "valid")
        with pytest.raises(ValidationError):
            verdict.formal_validity = "invalid"  # type: ignore[misc]


class TestTheVerdictSerialisesForPersistence:
    def test_every_consumer_field_is_present(self):
        dumped = _verdict("blocking", "diagnostic", "invalid").model_dump()
        assert dumped["authoritative"] is False
        assert dumped["enters_incumbent_selection"] is False
        assert dumped["enters_scientific_aggregation"] is False
        assert dumped["blocking_reasons"] == ["declared_diagnostic", "gate_invalidated"]
        assert dumped["primary_basis"] == "declared_diagnostic"

    def test_all_blocking_reasons_are_reported_not_just_the_first(self):
        """An operator fixing one should see the others without re-running."""
        verdict = _verdict("observe_only", "diagnostic", "invalid")
        assert verdict.blocking_reasons == [
            "declared_diagnostic",
            "non_blocking_mode",
            "gate_invalidated",
        ]


# ---------------------------------------------------------------------------
# V20 PR D (D-C4) — resolving the verdict for a PERSISTED record
# ---------------------------------------------------------------------------


class TestRecordAuthorityIsFailClosed:
    """`ScientificAuthority` trusts its three facts. `RecordAuthority` does
    not trust anything: its input is an artifact a later writer could have
    edited, so whatever it cannot independently justify is excluded.

    The returned `verdict` is ALWAYS a fresh derivation. A hand-edited
    `authoritative: true` in the stored dict buys nothing — which is the
    point of D-C2b having persisted the facts beside the conclusions.
    """

    def _stored(self, mode, authority, validity) -> dict:
        return _verdict(mode, authority, validity).model_dump()

    def _resolve(self, record, *, mode="blocking", authority="scientific", commit="valid"):
        from core.scientific_authority import resolve_record_authority

        return resolve_record_authority(
            record,
            declared_healthgate_mode=mode,
            declared_result_authority=authority,
            commit_time_validity=commit,
        )

    def test_a_coherent_stored_verdict_is_used(self):
        res = self._resolve(
            {"scientific_authority": self._stored("blocking", "scientific", "valid")}
        )
        assert res.basis == "stored_verdict"
        assert res.authoritative is True
        assert res.exclusion_reason is None

    def test_a_stored_verdict_that_blocks_is_reported_with_its_own_reason(self):
        res = self._resolve(
            {"scientific_authority": self._stored("blocking", "diagnostic", "valid")}
        )
        assert res.basis == "stored_verdict"
        assert res.authoritative is False
        assert res.exclusion_reason == "declared_diagnostic"

    def test_a_flipped_conclusion_is_refused(self):
        """MUTATION TARGET: reading `authoritative` out of the dict."""
        stored = self._stored("blocking", "diagnostic", "valid")
        stored["authoritative"] = True
        res = self._resolve({"scientific_authority": stored})
        assert res.authoritative is False
        assert res.basis == "verdict_inconsistent_with_its_facts"

    @pytest.mark.parametrize(
        "conclusion",
        [
            "primary_basis",
            "blocking_reasons",
            "enters_incumbent_selection",
            "enters_scientific_aggregation",
        ],
    )
    def test_every_conclusion_field_is_checked_not_just_authoritative(self, conclusion):
        """The concept, not one field: any derived field that disagrees
        with the facts condemns the verdict, because a writer who edits
        one has demonstrated the block is not trustworthy."""
        stored = self._stored("blocking", "diagnostic", "valid")
        stored[conclusion] = "tampered" if isinstance(stored[conclusion], str) else True
        res = self._resolve({"scientific_authority": stored})
        assert res.basis == "verdict_inconsistent_with_its_facts"

    def test_an_older_verdict_missing_a_newer_field_is_not_condemned(self):
        """Only keys the stored block actually CARRIES are compared. A
        verdict written before a conclusion field existed must stay
        readable — otherwise every schema addition retroactively
        invalidates history."""
        stored = self._stored("blocking", "scientific", "valid")
        del stored["enters_scientific_aggregation"]
        res = self._resolve({"scientific_authority": stored})
        assert res.basis == "stored_verdict"
        assert res.authoritative is True

    @pytest.mark.parametrize("junk", ["a string", 42, ["list"], {"formal_validity": "bogus"}, {}])
    def test_a_malformed_verdict_is_refused(self, junk):
        res = self._resolve({"scientific_authority": junk})
        assert res.authoritative is False
        assert res.basis == "malformed_verdict"
        assert res.exclusion_reason == "malformed_verdict"

    def test_a_stored_validity_contradicting_commit_time_evidence_is_refused(self):
        """Fact-level tampering. The verdict is internally coherent, but it
        claims its gates passed while the iteration's own commit-time
        evidence says they failed."""
        res = self._resolve(
            {"scientific_authority": self._stored("blocking", "scientific", "valid")},
            commit="invalid",
        )
        assert res.authoritative is False
        assert res.basis == "stored_validity_contradicts_commit_time"

    def test_commit_time_unknown_is_a_gap_not_a_contradiction(self):
        """SCOPING. A missing effective-policy artifact yields UNKNOWN, and
        widening the cross-check to treat that as a contradiction would
        empty the incumbent for every workspace whose policy artifact was
        merely lost."""
        res = self._resolve(
            {"scientific_authority": self._stored("blocking", "scientific", "valid")},
            commit="unknown",
        )
        assert res.basis == "stored_verdict"
        assert res.authoritative is True

    def test_the_returned_verdict_is_never_the_stored_object(self):
        """Structural: consumers read `res.verdict`, so it must be the
        derivation, not the artifact."""
        stored = self._stored("blocking", "scientific", "valid")
        stored["primary_basis"] = "blocking_scientific_formal_valid"
        res = self._resolve({"scientific_authority": stored})
        assert res.verdict is not None
        assert isinstance(res.verdict, ScientificAuthority)


class TestRecordAuthorityLegacyLadder:
    def _resolve(self, record, *, mode, authority, commit="valid"):
        from core.scientific_authority import resolve_record_authority

        return resolve_record_authority(
            record,
            declared_healthgate_mode=mode,
            declared_result_authority=authority,
            commit_time_validity=commit,
        )

    def test_a_declared_iteration_reconstructs_a_verdictless_record(self):
        """§12A steps 1-2: the record predates the per-record verdict but
        its iteration declared its policy, so authority is reconstructable
        WITHOUT modifying the artifact."""
        res = self._resolve({}, mode="blocking", authority="scientific")
        assert res.basis == "reconstructed_legacy"
        assert res.authoritative is True

    def test_reconstruction_still_obeys_the_truth_table(self):
        res = self._resolve({}, mode="blocking", authority="diagnostic")
        assert res.basis == "reconstructed_legacy"
        assert res.authoritative is False
        assert res.exclusion_reason == "declared_diagnostic"

    def test_reconstruction_uses_commit_time_validity_for_the_third_fact(self):
        res = self._resolve({}, mode="blocking", authority="scientific", commit="invalid")
        assert res.authoritative is False
        assert res.exclusion_reason == "gate_invalidated"

    @pytest.mark.parametrize(
        ("mode", "authority"),
        [(None, None), ("blocking", None), (None, "scientific")],
    )
    def test_an_undeclared_iteration_is_unreconstructable(self, mode, authority):
        """§12A step 3. UNKNOWN is never a licence to assume, and a high
        score cannot buy the declaration back."""
        res = self._resolve({}, mode=mode, authority=authority)
        assert res.basis == "unreconstructable_legacy"
        assert res.authoritative is False
        assert res.exclusion_reason == "unreconstructable_legacy"


class TestRecordAuthorityIsAConsumerNotASecondImplementation:
    def test_it_never_looks_at_gates_actions_scores_or_trial_evidence(self):
        """MUTATION TARGET: re-deriving authority here.

        The predecessor hotfix `af5339ce` existed because two authority
        sources disagreed. This resolver must consume D-C2a's rules, not
        restate them — so nothing in its source may reach for a gate id, a
        configured action, a `_blocking` suffix, a score, or trial
        evidence.
        """
        import inspect

        from core import scientific_authority

        src = inspect.getsource(scientific_authority.resolve_record_authority)
        for forbidden in (
            "denoising_score",
            "health_gate_results",
            "_blocking",
            "on_fail",
            "resolved_action",
            "is_trial",
            "gate_name",
        ):
            assert forbidden not in src, f"authority re-derived from {forbidden!r}"

    def test_the_conclusions_come_only_from_from_context(self):
        import inspect

        from core import scientific_authority

        src = inspect.getsource(scientific_authority.resolve_record_authority)
        assert "ScientificAuthority.from_context(" in src
