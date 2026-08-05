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
