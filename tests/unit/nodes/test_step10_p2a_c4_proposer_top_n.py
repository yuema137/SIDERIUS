"""Step 10 / P2a — C4: the proposer's ``top_n`` cut follows the declared direction.

Design: ``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p2a_golden_metric_order_closure.md`` §4.2 (Q-P2a-1), §6; parent §8.1 and
§11.3 (the named executable requirement).

The defect this file owns
-------------------------
``nodes/proposal_helpers.py``'s ``top_n`` branch sorted with
``reverse=True``. Under a lower-is-better metric that does not merely mislabel
a display — it hands the PROPOSER the worst N architectures and tells it they
are the best, so the next iteration's whole hypothesis is built on the models
that performed worst. This is the one site on the P2a surface where a wrong
direction changes what the system DOES.

No existing test module owned ``proposal_helpers``, so this creates the owner.
"""

from __future__ import annotations

from typing import Any, ClassVar

from agent.schemas.proposal import ModelSelectionStrategy
from agent.schemas.proposer_evidence import (
    ProposerInterpretationEvidence,
    build_proposer_evidence,
)
from execute_tools.evaluation_metric import METRIC_IDENTITY_UNAVAILABLE
from nodes.proposal_helpers import select_candidate_models

TIDMAD_ID = {"metric_id": "tidmad_denoising_score", "direction": "higher"}
PETS_ID = {"metric_id": "fixture_accuracy", "direction": "higher"}
DAVIS_ID = {"metric_id": "fixture_mse", "direction": "lower"}


def _interpretation(
    scores: dict[str, float | None], identity: dict[str, str] | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model_types": list(scores),
        "per_model_best_valid": dict(scores),
        "per_model_best": dict(scores),
    }
    if identity is not None:
        payload["metric_identity"] = identity
    return payload


def _evidence(scores, identity) -> ProposerInterpretationEvidence:
    """The same fixture payload, through the P3 typed projection.

    Step 10 / P3 C2 changed the helper's INPUT CARRIER from the raw dump to
    the typed evidence. The fixture DATA below is deliberately untouched — the
    scores, the identities and every expectation in this module are P2a's, and
    they must stay green across the mechanism swap. That is the whole point of
    leaving them alone: if a P2a expectation had to be edited to survive P3,
    the comparison semantics would have moved, which P3 is not allowed to do.
    """
    return build_proposer_evidence(_interpretation(scores, identity))


def _top_n(scores, identity, n: int) -> list[str]:
    selected = select_candidate_models(
        _evidence(scores, identity),
        ModelSelectionStrategy(method="top_n", params={"n": n}),
    )
    return [m["model_type"] for m in selected]


def _all(scores, identity) -> list[str]:
    selected = select_candidate_models(
        _evidence(scores, identity), ModelSelectionStrategy(method="all", params={})
    )
    return [m["model_type"] for m in selected]


class TestTheDavisInversion:
    """The parent's named executable requirement (§11.3)."""

    #: Hand-computed. DAVIS global MSE, LOWER is better:
    #:   0.0172 (b) is best, 0.0174 (a) second, 0.0210 (c) worst.
    #: So top_n(2) must be {b, a} — under the pre-migration `reverse=True`
    #: it returned {c, a}, i.e. the WORST two.
    DAVIS_SCORES: ClassVar[dict[str, float]] = {"a": 0.0174, "b": 0.0172, "c": 0.0210}

    def test_top_n_returns_the_BEST_two_under_a_lower_metric(self):
        assert _top_n(self.DAVIS_SCORES, DAVIS_ID, 2) == ["b", "a"]

    def test_top_n_1_selects_the_single_minimum(self):
        assert _top_n(self.DAVIS_SCORES, DAVIS_ID, 1) == ["b"]


class TestHigherIsBetterIsUnchanged:
    """Backward parity — the cut a TIDMAD or Pets run already produced."""

    #: Pets 37-way accuracy. 0.027 is the real D14 constant-prediction
    #: collapse (chance = 1/37); 0.61 best, 0.33 second.
    PETS_SCORES: ClassVar[dict[str, float]] = {"collapse": 0.027, "good": 0.61, "mid": 0.33}

    #: TIDMAD, higher-is-better with NEGATIVE values: -1.4 beats -3.2 beats -7.9.
    TIDMAD_SCORES: ClassVar[dict[str, float]] = {"a": -3.2, "b": -1.4, "c": -7.9}

    def test_pets_top_2(self):
        assert _top_n(self.PETS_SCORES, PETS_ID, 2) == ["good", "mid"]

    def test_tidmad_top_2_in_the_negative_regime(self):
        assert _top_n(self.TIDMAD_SCORES, TIDMAD_ID, 2) == ["b", "a"]

    def test_tidmad_order_is_byte_equal_to_the_pre_migration_sort(self):
        """Under `higher`, the returned LIST — including its order — must be
        exactly what `sorted(reverse=True)` produced."""
        expected = sorted(self.TIDMAD_SCORES, key=self.TIDMAD_SCORES.get, reverse=True)
        assert _top_n(self.TIDMAD_SCORES, TIDMAD_ID, 3) == expected

    def test_the_two_directions_disagree_on_the_same_scores(self):
        """Anti-vacuity: identical numbers, two declarations, opposite cuts."""
        scores = {"low": 1.0, "high": 5.0}
        assert _top_n(scores, TIDMAD_ID, 1) == ["high"]
        assert _top_n(scores, DAVIS_ID, 1) == ["low"]


class TestQP2a1TheUnavailableIdentityFallback:
    """Frozen ruling: fall back to the EXISTING order-free ``all`` semantics."""

    SCORES: ClassVar[dict[str, float]] = {"a": -3.2, "b": -1.4, "c": -7.9}

    def test_absent_identity_returns_exactly_the_all_path_result(self):
        """Asserted by EQUALITY against a direct ``all`` invocation on the
        same fixture, which is what makes "the existing semantics" a checked
        claim rather than a description."""
        assert _top_n(self.SCORES, None, 2) == _all(self.SCORES, None)

    def test_the_fallback_is_not_a_first_N_cut(self):
        """No new selection policy: the result is not truncated to n at all.

        A "first N by declaration order" fallback would have returned 2 of 3
        here. Returning all 3 is what distinguishes the ruled behaviour from
        the rejected one.
        """
        assert len(_top_n(self.SCORES, None, 2)) == 3

    def test_the_named_notice_fires(self, capsys):
        _top_n(self.SCORES, None, 2)
        out = capsys.readouterr().out
        assert METRIC_IDENTITY_UNAVAILABLE in out
        assert "NOT ranked" in out

    def test_a_malformed_direction_takes_the_fallback_rather_than_guessing(self):
        bad = {"metric_id": "m", "direction": "sideways"}
        assert _top_n(self.SCORES, bad, 2) == _all(self.SCORES, bad)

    def test_an_identity_with_no_metric_id_takes_the_fallback(self):
        assert _top_n(self.SCORES, {"direction": "higher"}, 2) == _all(self.SCORES, None)

    def test_the_fallback_never_calls_itself_best_or_top(self):
        """Nothing about the returned structure claims a ranking happened."""
        selected = select_candidate_models(
            _evidence(self.SCORES, None),
            ModelSelectionStrategy(method="top_n", params={"n": 2}),
        )
        for model in selected:
            assert "rank" not in model
            assert not any(str(key).startswith(("top_", "best_n")) for key in model), (
                f"the unranked fallback labelled a candidate: {sorted(model)}"
            )


class TestEdgeCasesPreserved:
    def test_n_larger_than_the_candidate_count_returns_everything(self):
        scores = {"a": -1.0, "b": -2.0}
        assert sorted(_top_n(scores, TIDMAD_ID, 10)) == ["a", "b"]

    def test_all_scores_none_yields_an_empty_cut(self):
        """The existing `best_score is None` filter empties `scored`; with a
        usable identity the cut is legitimately empty rather than a fallback."""
        assert _top_n({"a": None, "b": None}, TIDMAD_ID, 2) == []

    def test_a_none_score_is_excluded_but_the_rest_still_rank(self):
        assert _top_n({"a": -3.2, "b": None, "c": -1.4}, TIDMAD_ID, 2) == ["c", "a"]

    def test_an_empty_model_set_returns_empty(self):
        assert _top_n({}, TIDMAD_ID, 2) == []

    def test_ties_keep_discovery_order(self):
        """Direction-independent, and unchanged from the stable `reverse=True`
        sort: equal scores keep the order they were discovered in."""
        for identity in (TIDMAD_ID, DAVIS_ID):
            assert _top_n({"first": 1.0, "second": 1.0}, identity, 2) == ["first", "second"]
