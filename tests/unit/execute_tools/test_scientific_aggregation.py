"""Only an authoritative formal result may inform a scientific aggregate.

V20 PR D, checkpoint D-C5.

**The failure mode being prevented is a silently smaller sample.** Before
this boundary, a diagnostic or gate-invalid formal score entered the
aggregate exactly like a certified one, and an aggregate that quietly
dropped or quietly included results looked identical to a clean campaign.

Two properties carry this module:

- an excluded result is **retained**, with a machine-readable reason. It
  is still a fact about what the campaign did; it just cannot support a
  scientific claim.
- `all_excluded` is a **stated outcome**, never an empty aggregate. "Every
  result was excluded" and "the campaign found nothing" are opposite
  conclusions that would otherwise render identically.
"""

from __future__ import annotations

import json

import pytest

from core.scientific_authority import ScientificAuthority
from execute_tools.scientific_aggregation import (
    AggregationScope,
    partition_for_aggregation,
)
from tests.helpers.formal_evidence import disabled_formal_evidence


def _verdict(mode: str | None, authority: str | None, validity: str) -> dict:
    return ScientificAuthority.from_context(
        healthgate_mode=mode,
        declared_result_authority=authority,
        formal_validity=validity,  # type: ignore[arg-type]
    ).model_dump()


AUTHORITATIVE = _verdict("blocking", "scientific", "valid")
DIAGNOSTIC = _verdict("blocking", "diagnostic", "valid")
GATE_INVALID = _verdict("blocking", "scientific", "invalid")
UNKNOWN_VALIDITY = _verdict("blocking", "scientific", "unknown")
OBSERVE_ONLY = _verdict("observe_only", "scientific", "valid")


class _Summary:
    """The structural shape the boundary consumes — deliberately not the
    real `ModelRunSummary`, so the contract stays task-generic."""

    def __init__(self, model_type: str, verdict: dict | None, score: float | None = 1.0):
        self.model_type = model_type
        self.run_name = "v1"
        self.scientific_authority = verdict
        self.formal_score = score
        self.formal_evidence = disabled_formal_evidence(model_type, score)


class TestWhatIsIncluded:
    def test_an_authoritative_result_is_included(self):
        scope = partition_for_aggregation([_Summary("m", AUTHORITATIVE)])
        assert scope.included == ["m"]
        assert scope.excluded == []
        assert scope.included_count == 1

    def test_only_the_authoritative_combination_is_included(self):
        """The concept, not five literals: the same truth table D-C2a
        derives must govern here, or the aggregate has its own opinion."""
        summaries = [
            _Summary(f"{m}_{a}_{v}", _verdict(m, a, v))
            for m in ("blocking", "observe_only")
            for a in ("scientific", "diagnostic")
            for v in ("valid", "invalid", "unknown")
        ]
        scope = partition_for_aggregation(summaries)
        assert scope.included == ["blocking_scientific_valid"]


class TestWhatIsExcluded:
    @pytest.mark.parametrize(
        ("verdict", "reason"),
        [
            (GATE_INVALID, "gate_invalidated"),
            (DIAGNOSTIC, "declared_diagnostic"),
            (UNKNOWN_VALIDITY, "formal_validity_unknown"),
            (OBSERVE_ONLY, "non_blocking_mode"),
        ],
        ids=["invalid", "diagnostic", "unknown", "observe_only"],
    )
    def test_a_non_authoritative_result_is_excluded_with_its_reason(self, verdict, reason):
        """MUTATION TARGET: including on anything but the verdict.

        The score is 999.0 — far above anything else — so a boundary that
        consulted the score, or that treated HealthGate validity as
        authority, would include every one of these.
        """
        scope = partition_for_aggregation([_Summary("hot", verdict, score=999.0)])
        assert scope.included == []
        assert scope.excluded_count == 1
        assert scope.excluded[0].reason == reason
        assert scope.excluded[0].record_id == "hot"

    def test_a_summary_with_no_verdict_is_excluded(self):
        """A record missing the authority contract establishes nothing —
        the frozen rule. It is not silently admitted, and not deleted."""
        scope = partition_for_aggregation([_Summary("legacy", None)])
        assert scope.included == []
        assert scope.excluded[0].reason == "unreconstructable_legacy"

    @pytest.mark.parametrize("junk", ["a string", 42, [], {"formal_validity": "bogus"}])
    def test_a_malformed_verdict_fails_closed(self, junk):
        """MUTATION TARGET: trusting a verdict that cannot be parsed."""
        scope = partition_for_aggregation([_Summary("junk", junk)])  # type: ignore[arg-type]
        assert scope.included == []
        assert scope.excluded[0].basis == "malformed_verdict"

    def test_a_tampered_verdict_fails_closed(self):
        """The stored conclusions are re-derived from the stored facts, so
        flipping `authoritative` in the artifact buys nothing here either."""
        tampered = dict(DIAGNOSTIC)
        tampered["authoritative"] = True
        tampered["enters_scientific_aggregation"] = True

        scope = partition_for_aggregation([_Summary("forged", tampered)])

        assert scope.included == []
        assert scope.excluded[0].reason == "verdict_inconsistent_with_its_facts"


class TestTheMixedAndBoundaryStates:
    def test_a_mixed_campaign_reports_both_sides(self):
        scope = partition_for_aggregation(
            [
                _Summary("good_a", AUTHORITATIVE),
                _Summary("diag", DIAGNOSTIC),
                _Summary("good_b", AUTHORITATIVE),
                _Summary("bad", GATE_INVALID),
            ]
        )
        assert scope.included == ["good_a", "good_b"]
        assert scope.included_count == 2
        assert scope.excluded_count == 2
        assert scope.all_excluded is False
        assert scope.no_records is False

    def test_all_excluded_is_a_stated_outcome(self):
        """THE ROW THAT MATTERS. An empty aggregate alone reads exactly
        like a campaign that found nothing — the opposite conclusion."""
        scope = partition_for_aggregation([_Summary("d", DIAGNOSTIC), _Summary("i", GATE_INVALID)])

        assert scope.all_excluded is True
        assert scope.no_records is False
        assert "EVERY result was excluded" in "\n".join(scope.provenance_lines())

    def test_no_records_is_distinct_from_all_excluded(self):
        scope = partition_for_aggregation([])
        assert scope.no_records is True
        assert scope.all_excluded is False
        assert "none were submitted" in "\n".join(scope.provenance_lines())

    def test_reason_counts_are_grouped_and_stable(self):
        """Rendered provenance must be byte-stable across runs, so a
        report diff shows real change rather than dict ordering."""
        scope = partition_for_aggregation(
            [
                _Summary("a", DIAGNOSTIC),
                _Summary("b", GATE_INVALID),
                _Summary("c", DIAGNOSTIC),
            ]
        )
        assert scope.exclusion_reason_counts == {"declared_diagnostic": 2, "gate_invalidated": 1}
        assert list(scope.exclusion_reason_counts) == ["declared_diagnostic", "gate_invalidated"]


class TestTheProvenanceIsRenderedNotWritten:
    def test_the_lines_state_the_count_and_every_reason(self):
        scope = partition_for_aggregation(
            [_Summary("g", AUTHORITATIVE), _Summary("d", DIAGNOSTIC), _Summary("i", GATE_INVALID)]
        )
        text = "\n".join(scope.provenance_lines())

        assert "used 1 authoritative result." in text
        assert "2 non-authoritative results excluded:" in text
        assert "1 declared_diagnostic" in text
        assert "1 gate_invalidated" in text

    def test_singular_and_plural_read_correctly(self):
        one = partition_for_aggregation([_Summary("g", AUTHORITATIVE), _Summary("d", DIAGNOSTIC)])
        text = "\n".join(one.provenance_lines())
        assert "used 1 authoritative result." in text
        assert "1 non-authoritative result excluded:" in text

    def test_the_all_excluded_conclusion_never_out_scopes_its_own_partition(self):
        """N-3 — the defect only this case catches.

        ``AggregationScope`` knows the results it was handed and nothing else.
        The all-excluded sentence used to conclude *"this campaign produced no
        scientifically authoritative result"*, which the interpreter then
        printed once per iteration from that iteration's evidence — telling
        the operator a campaign had no authoritative result while other
        iterations had produced several.

        The DEFAULT must therefore be true for any caller: it names the
        object's own scope. A caller that knows a wider or narrower one says
        so, and the sentence follows.
        """
        scope = partition_for_aggregation([_Summary("d", DIAGNOSTIC)])
        assert scope.all_excluded is True

        default = "\n".join(scope.provenance_lines())
        assert "campaign" not in default
        assert (
            "EVERY result was excluded — no scientifically authoritative "
            "result is available in this aggregation." in default
        )

        named = "\n".join(scope.provenance_lines(scope="iteration 3"))
        assert (
            "EVERY result was excluded — no scientifically authoritative "
            "result is available in iteration 3." in named
        )

    def test_the_scope_word_governs_only_the_conclusion(self):
        """The scope names a CONCLUSION's reach, not a decoration.

        A partition that excluded nothing states no scope-bearing conclusion,
        so passing one must change no byte — otherwise the parameter would be
        free to drift into lines it does not govern.
        """
        clean = partition_for_aggregation([_Summary("g", AUTHORITATIVE)])
        assert clean.provenance_lines(scope="iteration 3") == clean.provenance_lines()

        empty = partition_for_aggregation([])
        assert empty.provenance_lines(scope="iteration 3") == empty.provenance_lines()

    def test_the_scope_survives_json(self):
        """It is persisted on the interpretation output, so a report reads
        it back rather than re-deriving anything."""
        scope = partition_for_aggregation([_Summary("g", AUTHORITATIVE), _Summary("d", DIAGNOSTIC)])
        restored = json.loads(json.dumps(scope.model_dump(), allow_nan=False))

        assert restored["included"] == ["g"]
        assert restored["excluded_count"] == 1
        assert restored["exclusion_reason_counts"] == {"declared_diagnostic": 1}
        assert restored["all_excluded"] is False


class TestTheBoundaryConsumesAuthorityRatherThanRederivingIt:
    def test_nothing_in_the_source_reaches_for_a_score_gate_or_name(self):
        """MUTATION TARGET: a second authority implementation.

        The predecessor hotfix `af5339ce` existed because two authority
        sources disagreed. This boundary must consume D-C2a's verdict, not
        restate it — so its source may not reach for a score, a gate id, a
        configured action, or a model name.
        """
        import inspect

        from execute_tools import scientific_aggregation

        src = inspect.getsource(scientific_aggregation.partition_for_aggregation)
        for forbidden in (
            "denoising_score",
            "formal_score",
            "health_gate_results",
            "_blocking",
            "on_fail",
            "resolved_action",
            "gate_name",
        ):
            assert forbidden not in src, f"authority re-derived from {forbidden!r}"
        assert "resolve_record_authority(" in src

    def test_conclusions_cannot_be_supplied_to_the_scope(self):
        """`extra="forbid"` plus computed fields: a caller cannot hand in
        a count that disagrees with the lists it came from."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AggregationScope(included=[], excluded=[], excluded_count=99)  # type: ignore[call-arg]
