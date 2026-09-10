"""Step 10 / P3 — C2: the pipeline on typed evidence, and the F-P3-1 clamp.

Design: ``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p3_proposer_typed_evidence.md`` §4.3 (the serializer), §4.7 + §14.1
(Q-P3-4 = INCLUDE / BOUNDED — the clamp migration), §7 C2.

Two claims live here, and neither is provable anywhere else.

**The serializer is byte-equal to the comprehension it replaced.** The prompt
goldens prove the whole prompt did not move, but they cannot show WHY, and a
serializer that quietly re-ordered keys while some other change compensated
would still pass them. The differential below builds the block BOTH ways over
the same dump and requires deep equality — including key ORDER, which is what
the LLM reads.

**The clamp retains the BEST entries under the run's declared direction.** This
site is provably invisible to the P2a AST scanner (the golden name is read
inside a helper the sort key merely calls), and the ruling deliberately did NOT
widen that scanner. So these hand-computed fixtures ARE the standing guard for
F-P3-1 — there is no other.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from agent.schemas.proposer_evidence import build_proposer_evidence
from execute_tools.dataset_config import bind_dataset_profile
from execute_tools.evaluation_metric import MetricIdentityKey
from execute_tools.metric_order import MetricOrder
from nodes.ml_model_proposal_agent.evidence_rendering import (
    INTERPRETATION_SUMMARY_KEYS,
    build_interpretation_summary,
)
from nodes.proposal_helpers import clamp_comparative_analysis, evidence_order
from tests.helpers.two_family_profile import make_two_family_profile
from tests.unit.agent.ml_model_proposal_agent.test_step00_prompt_goldens import (
    fixture_interpretation,
)
from tests.unit.agent.ml_model_proposal_agent.test_step10_p3_c0_baselines import (
    full_coverage_interpretation,
    legacy_absence_interpretation,
)

HIGHER = MetricOrder(MetricIdentityKey(id="tidmad_denoising_score", direction="higher"))


LOWER = MetricOrder(MetricIdentityKey(id="fixture_mse", direction="lower"))
_INTERPRETATION_PROFILE = make_two_family_profile(num_files=20)


@pytest.fixture(autouse=True)
def _bind_interpretation_profile():
    """Exercise every schema projection under its explicit test topology."""
    with bind_dataset_profile(_INTERPRETATION_PROFILE):
        yield


def _production_shaped(dump: dict) -> dict:
    """Round-trip a hand-written fixture through the PRODUCER's schema.

    The parity claim is about dumps production can actually emit, and the
    protocol passes ``InterpretationOutput.model_dump()`` — every optional
    field already materialised at its default. A hand-written fixture may omit
    defaults that the typed projection then fills in on re-serialization, which
    is a difference between the fixture and a real dump, not between the two
    code paths. Normalising here keeps the oracle honest in both directions:
    the full-coverage and legacy fixtures are used RAW (one is already a real
    dump, the other models a real legacy artifact), so the comparison is not
    quietly normalising everything until it agrees.
    """
    from agent.schemas.interpretation import InterpretationOutput

    with bind_dataset_profile(_INTERPRETATION_PROFILE):
        return InterpretationOutput.model_validate(dump).model_dump()


#: The 18 whitelist keys as the PRE-P3 source spelled them, in the PRE-P3 order,
#: transcribed from `_run_pipeline`'s inline tuple at base `c5f95ff0`.
#:
#: Hardcoded ON PURPOSE. Iterating the production constant would have made the
#: "oracle" read its key set and order from the very code under test, so a key
#: dropped, added or reordered would move BOTH sides together and the key-order
#: assertion below could never fire. That is the self-referential parity trap
#: this module claims to avoid, and an earlier version of this file walked
#: straight into it — caught in adversarial review.
PRE_P3_WHITELIST_KEYS: tuple[str, ...] = (
    "model_types",
    "total_experiments",
    "best_denoising_score",
    "worst_denoising_score",
    "key_findings",
    "bottlenecks",
    "take_home_message",
    "per_model_best",
    "per_model_worst",
    "per_model_score_tables",
    "scientific_accuracy",
    "cumulative_information_gain",
    "prediction_outcomes_history",
    "prediction_outcomes_by_semantics",
    "cumulative_information_gain_by_semantics",
    "prediction_pool_sizes",
    "prediction_evaluation_semantics",
    "vocab_diversity_ratio",
)


def legacy_summary(dump: dict) -> dict:
    """The PRE-P3 comprehension, reproduced verbatim from the C0 source.

    This is the oracle:

        {k: interp.get(k) for k in (...) if interp.get(k) is not None}

    with the key tuple transcribed rather than imported, so the comparison is
    against what the code USED to do and not against what it does now.
    """
    return {k: dump.get(k) for k in PRE_P3_WHITELIST_KEYS if dump.get(k) is not None}


class TestTheSerializerIsByteEqualToTheComprehension:
    """§4.3 — same keys, same order, same filtering, same JSON shapes."""

    @pytest.mark.parametrize(
        ("name", "dump"),
        [
            ("full coverage", full_coverage_interpretation()),
            ("legacy absence", legacy_absence_interpretation()),
            ("PB-3 fixture", _production_shaped(fixture_interpretation())),
        ],
    )
    def test_the_two_paths_agree(self, name: str, dump: dict) -> None:
        expected = legacy_summary(dump)
        actual = build_interpretation_summary(build_proposer_evidence(dump))
        assert actual == expected, f"{name}: serializer diverged from the dict path"
        assert list(actual) == list(expected), (
            f"{name}: the KEY ORDER moved. It is the JSON order the LLM reads, "
            "so a reordering is a prompt change even when the values match."
        )

    def test_the_production_constant_still_matches_the_pre_p3_key_tuple(self) -> None:
        """The transcription is only an oracle while it still describes production.

        Asserted separately from the differential so the two failures read
        differently: THIS one means the whitelist itself moved (a prompt change
        needing its own declared delta), while a differential failure means the
        serializer diverged from the dict path on the same keys.
        """
        assert INTERPRETATION_SUMMARY_KEYS == PRE_P3_WHITELIST_KEYS

    def test_the_differential_is_not_vacuous(self) -> None:
        """The three fixtures must actually exercise different key subsets.

        If every fixture produced the same block, the parametrization would be
        one test wearing three hats.
        """
        blocks = [
            frozenset(legacy_summary(d))
            for d in (
                full_coverage_interpretation(),
                legacy_absence_interpretation(),
                fixture_interpretation(),
            )
        ]
        assert len(set(blocks)) == 3

    def test_absent_and_present_empty_stay_distinguishable(self) -> None:
        """The ``is not None`` filter, preserved exactly.

        An absent key is omitted; a present-but-empty container renders. The
        old comprehension did this and the CLI's legacy artifacts depend on it.
        """
        base = {"model_types": [], "model_descriptions": {}}
        absent = build_interpretation_summary(build_proposer_evidence(base))
        present = build_interpretation_summary(
            build_proposer_evidence({**base, "per_model_best": {}})
        )
        assert "per_model_best" not in absent
        assert present["per_model_best"] == {}

    def test_an_absent_model_types_is_the_one_DECLARED_divergence(self) -> None:
        """The single place the two paths deliberately disagree — pinned, not argued.

        Under the dict path a dump MISSING ``model_types`` produced ``None``
        and the ``is not None`` filter dropped the key. The typed field
        defaults to ``[]``, which renders. Production cannot reach this —
        ``model_types`` is REQUIRED on ``InterpretationOutput`` — but a
        hand-edited legacy CLI artifact can, so the delta is recorded here
        rather than left to an unreachability argument.

        The differential fixtures cannot cover it: on this input the two paths
        genuinely differ, so agreement would be the bug. That is exactly why it
        needs its own test — and why the production docstring must not claim
        the differential covers it.
        """
        empty: dict = {}
        assert legacy_summary(empty) == {}
        typed = build_interpretation_summary(build_proposer_evidence(empty))
        assert typed == {"model_types": []}, (
            "the declared divergence changed shape; if this is intentional it "
            "is a prompt-bytes change and needs its own declared delta"
        )

    def test_typed_values_are_serialized_not_left_as_objects(self) -> None:
        """The §4.3 parity hazard, asserted directly.

        ``accumulated`` is ``json.dumps``-ed with ``default=str``. A typed
        object left in the block would serialize as a repr string and silently
        change the prompt — visible in a golden only as a wall of noise.
        """
        summary = build_interpretation_summary(
            build_proposer_evidence(full_coverage_interpretation())
        )
        tables = summary["per_model_score_tables"]
        assert isinstance(tables, dict)
        for table in tables.values():
            assert isinstance(table, dict), "a typed ScoreComparisonTable leaked into accumulated"
            assert "rendered_markdown" in table


def _entry(model_type: str, source: str, best_score: float | None) -> dict:
    return {"model_type": model_type, "source": source, "best_score": best_score}


class TestFP31TheClampRetainsTheBestUnderTheDeclaredDirection:
    """The hand-computed retention fixtures — F-P3-1's only standing guard.

    Six entries against ``top_k=3``. Both numbers are load-bearing: at or
    under the cap the function returns the list untouched by design, and with
    ``top_k=5`` over six entries only ONE entry is dropped, so Draw A's choice
    would be invisible — five of six survive whatever the direction. At
    ``top_k=3`` the final truncation is decided by the order, which is the
    thing under test.

    Recency is held CONSTANT across the score-carrying entries so the only
    thing that can move the result is the score draw — a fixture where recency
    could explain the outcome would prove nothing about direction.
    """

    #: DAVIS-shaped MSE, LOWER is better. best three = 0.0170, 0.0172, 0.0174.
    #: The two clamped out are the WORST: 0.0402 and 0.0398.
    DAVIS: ClassVar[list[dict]] = [
        _entry("worst", "proposed_iter_3", 0.0402),
        _entry("second_worst", "proposed_iter_3", 0.0398),
        _entry("best", "proposed_iter_3", 0.0170),
        _entry("second", "proposed_iter_3", 0.0172),
        _entry("third", "proposed_iter_3", 0.0174),
        _entry("recent", "proposed_iter_9", 0.0300),
    ]

    def test_davis_lower_retains_the_lowest_mse(self) -> None:
        kept = {e["model_type"] for e in clamp_comparative_analysis(self.DAVIS, 3, order=LOWER)}
        assert {"best", "second", "third"} <= kept, (
            "the three LOWEST-mse entries must survive Draw A under a "
            f"lower-is-better metric; kept={sorted(kept)}"
        )

    def test_davis_lower_clamps_the_known_worst_model_out(self) -> None:
        """The actual harm: the worst model's evidence curated INTO the prompt."""
        kept = {e["model_type"] for e in clamp_comparative_analysis(self.DAVIS, 3, order=LOWER)}
        assert "worst" not in kept

    def test_the_pre_migration_draw_would_have_kept_the_worst(self) -> None:
        """The counterfactual, hand-computed, so the fix is shown to MOVE something.

        The old Draw A was ``sorted(key=lambda it: (-best_score, index))[:3]``,
        which on these scores selects 0.0402, 0.0398, 0.0300 — the three worst.
        """
        direction_blind = sorted(self.DAVIS, key=lambda e: (-e["best_score"],))[:3]
        assert [e["model_type"] for e in direction_blind] == [
            "worst",
            "second_worst",
            "recent",
        ]
        kept = {e["model_type"] for e in clamp_comparative_analysis(self.DAVIS, 3, order=LOWER)}
        assert "second_worst" not in kept

    #: TIDMAD-shaped, HIGHER is better with negative values.
    HIGHER_REGIME: ClassVar[list[dict]] = [
        _entry("worst", "proposed_iter_3", -7.9),
        _entry("second_worst", "proposed_iter_3", -6.5),
        _entry("best", "proposed_iter_3", -1.4),
        _entry("second", "proposed_iter_3", -2.0),
        _entry("third", "proposed_iter_3", -3.2),
        _entry("recent", "proposed_iter_9", -5.0),
    ]

    def test_higher_regime_retains_the_highest(self) -> None:
        kept = {
            e["model_type"] for e in clamp_comparative_analysis(self.HIGHER_REGIME, 3, order=HIGHER)
        }
        assert {"best", "second", "third"} <= kept
        assert "worst" not in kept

    def test_the_two_directions_disagree_on_the_same_pool(self) -> None:
        """Anti-vacuity: identical entries, two declarations, opposite retention.

        Without this, a clamp that ignored ``order`` entirely could satisfy
        both regime tests by accident of how the fixtures were written.
        """
        pool = [
            _entry("low", "proposed_iter_3", 1.0),
            _entry("mid_low", "proposed_iter_3", 2.0),
            _entry("mid", "proposed_iter_3", 3.0),
            _entry("mid_high", "proposed_iter_3", 4.0),
            _entry("high", "proposed_iter_3", 5.0),
            _entry("highest", "proposed_iter_3", 6.0),
        ]
        under_higher = {e["model_type"] for e in clamp_comparative_analysis(pool, 3, order=HIGHER)}
        under_lower = {e["model_type"] for e in clamp_comparative_analysis(pool, 3, order=LOWER)}
        assert under_higher == {"highest", "high", "mid_high"}
        assert under_lower == {"low", "mid_low", "mid"}
        assert under_higher.isdisjoint(under_lower)

    def test_a_missing_score_sorts_as_worst_under_BOTH_directions(self) -> None:
        """``order.worst_sentinel`` replaced a hardcoded ``-inf``.

        ``-inf`` is "worst" only under higher-is-better; under ``lower`` it is
        the BEST possible value, so a missing score would have been promoted
        into Draw A ahead of every real measurement.
        """
        pool = [
            _entry("missing", "proposed_iter_3", None),
            _entry("a", "proposed_iter_3", 0.01),
            _entry("b", "proposed_iter_3", 0.02),
            _entry("c", "proposed_iter_3", 0.03),
            _entry("d", "proposed_iter_3", 0.04),
            _entry("e", "proposed_iter_3", 0.05),
        ]
        under_lower = {e["model_type"] for e in clamp_comparative_analysis(pool, 3, order=LOWER)}
        assert under_lower == {"a", "b", "c"}
        assert "missing" not in under_lower

    def test_absent_identity_skips_the_score_draw_entirely(self) -> None:
        """Q-P2a-1's shape: no identity ⇒ no metric ranking, recency only.

        The pool is built so the two answers are DIFFERENT: the most recent
        entries are also the worst-scoring ones, so a retention that silently
        kept ranking by score would be visible here.
        """
        pool = [
            _entry("old_best", "proposed_iter_1", 0.0170),
            _entry("old_second", "proposed_iter_2", 0.0172),
            _entry("old_third", "proposed_iter_3", 0.0174),
            _entry("new_worst", "proposed_iter_8", 0.0402),
            _entry("new_second_worst", "proposed_iter_9", 0.0398),
            _entry("newest", "proposed_iter_10", 0.0500),
        ]
        kept = [e["model_type"] for e in clamp_comparative_analysis(pool, 3, order=None)]
        assert kept == ["newest", "new_second_worst", "new_worst"], (
            "without an identity the clamp must fall back to the existing "
            f"direction-independent recency behaviour; got {kept}"
        )

    def test_absent_identity_differs_from_both_ranked_regimes(self) -> None:
        """Anti-vacuity for the absence path."""
        pool = [
            _entry("old_best", "proposed_iter_1", 0.0170),
            _entry("old_second", "proposed_iter_2", 0.0172),
            _entry("old_third", "proposed_iter_3", 0.0174),
            _entry("new_worst", "proposed_iter_8", 0.0402),
            _entry("new_second_worst", "proposed_iter_9", 0.0398),
            _entry("newest", "proposed_iter_10", 0.0500),
        ]
        none_kept = {e["model_type"] for e in clamp_comparative_analysis(pool, 3, order=None)}
        lower_kept = {e["model_type"] for e in clamp_comparative_analysis(pool, 3, order=LOWER)}
        assert none_kept != lower_kept

    def test_at_or_under_the_cap_nothing_is_reordered_in_any_regime(self) -> None:
        """The n <= top_k early return is direction-independent and untouched."""
        pool = self.DAVIS[:4]
        for order in (HIGHER, LOWER, None):
            assert clamp_comparative_analysis(pool, 5, order=order) == pool

    def test_the_order_argument_is_required(self) -> None:
        """A silently-defaulted ``None`` would quietly drop the score draw.

        Every caller must state which regime it has — that is what stops a
        future call site from getting recency-only retention by omission.
        """
        with pytest.raises(TypeError):
            clamp_comparative_analysis(self.DAVIS, 3)  # type: ignore[call-arg]


class TestTheOrderComesFromTheDeclaredIdentityAlone:
    """No re-derivation: the clamp's order is the evidence's identity."""

    def test_the_order_matches_the_declared_direction(self) -> None:
        order = evidence_order(build_proposer_evidence(full_coverage_interpretation()))
        assert order is not None
        assert order.direction == "lower"

    def test_an_absent_identity_yields_no_order(self) -> None:
        order = evidence_order(build_proposer_evidence(legacy_absence_interpretation()))
        assert order is None

    def test_a_malformed_identity_yields_no_order_rather_than_a_guess(self) -> None:
        dump = dict(full_coverage_interpretation())
        dump["metric_identity"] = {"metric_id": "m", "direction": "sideways"}
        assert evidence_order(build_proposer_evidence(dump)) is None
