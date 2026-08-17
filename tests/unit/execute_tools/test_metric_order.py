"""Step 07 PR 07b — the ONE order authority, tested as a pure object.

Design: ``docs/design/generic_framework_upgrade/step_07_tuner_policy_and_training_diagnostics/
pr_07b_tuner_policy.md`` §3.2.

What only this module can catch: an arithmetic defect in the authority
itself — a rank formula that miscounts ties, a sentinel on the wrong side, a
``toward_better`` that treats its argument as a magnitude rather than a
coordinate. The consumer rung (``test_step07b_c2_order_consumers.py``) proves
the tuner *calls* this object; it cannot prove the object is right, because
it compares the tuner against the same authority.

Deliberately NOT here: that ``MetricSpec.direction`` only accepts
``higher``/``lower`` (a ``Literal``, enforced by Pydantic), or that a frozen
model is frozen. Those are declarations, and CLAUDE.md forbids pytesting what
a declaration already enforces.
"""

from __future__ import annotations

import pytest

from execute_tools.metric_order import MetricOrder
from tests.helpers.metric_fixtures import (
    accuracy_like_spec,
    direction_only_spec,
    error_like_spec,
    shipped_spec,
)

HIGHER = MetricOrder(shipped_spec())
LOWER = MetricOrder(direction_only_spec())


def test_direction_comes_from_the_spec_and_nowhere_else():
    """The authority reads the metric's own declaration.

    Fails if a future edit reintroduces a default, an env override or a
    constructor flag — every one of which would be the second direction
    field the parent design forbids.
    """
    assert MetricOrder(shipped_spec()).direction == "higher"
    assert MetricOrder(direction_only_spec()).direction == "lower"
    assert MetricOrder(accuracy_like_spec()).direction == "higher"
    assert MetricOrder(error_like_spec()).direction == "lower"


class TestComparison:
    def test_is_better_is_strict_and_inverts(self):
        assert HIGHER.is_better(-2.55, -2.91)
        assert not HIGHER.is_better(-2.91, -2.55)
        assert LOWER.is_better(-2.91, -2.55)
        assert not LOWER.is_better(-2.55, -2.91)

    def test_a_tie_is_not_better_under_either_direction(self):
        """The property ``is_new_best`` depends on: equal is not an improvement."""
        assert not HIGHER.is_better(1.0, 1.0)
        assert not LOWER.is_better(1.0, 1.0)

    def test_is_at_least_admits_the_tie(self):
        """The bypass gate and the efficiency band both mean "clears the bar"."""
        assert HIGHER.is_at_least(1.0, 1.0)
        assert LOWER.is_at_least(1.0, 1.0)
        assert HIGHER.is_at_least(1.1, 1.0)
        assert not HIGHER.is_at_least(0.9, 1.0)
        assert LOWER.is_at_least(0.9, 1.0)
        assert not LOWER.is_at_least(1.1, 1.0)


class TestExtremes:
    ITEMS = ({"id": "a", "s": 1.0}, {"id": "b", "s": 3.0}, {"id": "c", "s": 2.0})

    def _key(self, item):
        return item["s"]

    def test_best_and_worst_invert(self):
        assert HIGHER.best(self.ITEMS, key=self._key)["id"] == "b"
        assert HIGHER.worst(self.ITEMS, key=self._key)["id"] == "a"
        assert LOWER.best(self.ITEMS, key=self._key)["id"] == "a"
        assert LOWER.worst(self.ITEMS, key=self._key)["id"] == "b"

    def test_ties_resolve_to_the_first_item(self):
        """Pre-07b every call site was ``max()``/``min()``, which keep the
        FIRST maximal item. A "clearer" implementation using ``sorted()[-1]``
        or a reduce that prefers ``>=`` would silently promote the LAST tied
        record, changing which config the formal round inherits."""
        tied = ({"id": "first", "s": 5.0}, {"id": "second", "s": 5.0})
        assert HIGHER.best(tied, key=self._key)["id"] == "first"
        assert LOWER.best(tied, key=self._key)["id"] == "first"
        assert HIGHER.worst(tied, key=self._key)["id"] == "first"
        assert LOWER.worst(tied, key=self._key)["id"] == "first"

    def test_best_of_nothing_raises_rather_than_inventing_a_winner(self):
        with pytest.raises(ValueError):
            HIGHER.best([], key=self._key)


class TestRank:
    def test_rank_matches_the_pre_07b_formula_under_higher(self):
        """``1 + #(strictly better)`` == ``sorted(reverse=True).index(x) + 1``.

        The equality is the parity claim C2 rests on; the expectations are
        hardcoded, never recomputed from either formula.
        """
        values = [-2.91, -2.55, -3.40]
        assert HIGHER.rank(values, -2.55) == 1
        assert HIGHER.rank(values, -2.91) == 2
        assert HIGHER.rank(values, -3.40) == 3

    def test_rank_inverts_under_lower(self):
        values = [-2.91, -2.55, -3.40]
        assert LOWER.rank(values, -3.40) == 1
        assert LOWER.rank(values, -2.91) == 2
        assert LOWER.rank(values, -2.55) == 3

    def test_tied_values_share_the_better_rank(self):
        """``sorted().index()`` returns the FIRST occurrence, so two records
        tied at the top are both rank 1 and the next is rank 3. The
        count-of-strictly-better formula must reproduce that, not renumber
        them 1/2/3."""
        values = [5.0, 5.0, 4.0]
        assert HIGHER.rank(values, 5.0) == 1
        assert HIGHER.rank(values, 4.0) == 3


class TestSentinels:
    def test_worst_and_best_sentinels_swap_with_direction(self):
        assert HIGHER.worst_sentinel == float("-inf")
        assert HIGHER.best_sentinel == float("inf")
        assert LOWER.worst_sentinel == float("inf")
        assert LOWER.best_sentinel == float("-inf")

    @pytest.mark.parametrize("order", [HIGHER, LOWER], ids=["higher", "lower"])
    def test_no_value_is_better_than_the_best_sentinel(self, order):
        """The sentinels' defining property, stated without naming ±inf.

        A sentinel pair copied from the wrong direction would still be two
        infinities and would still compare — this is what catches it.
        """
        for probe in (-1e9, -1.0, 0.0, 1.0, 1e9):
            assert not order.is_better(probe, order.best_sentinel)
            assert not order.is_better(order.worst_sentinel, probe)


class TestMovementAlongTheAxis:
    def test_toward_better_treats_its_argument_as_a_coordinate(self):
        """Positive moves toward better, negative toward worse — under BOTH
        directions. The operator's declared skip margin of ``-1.0`` must
        loosen the threshold whichever way the metric points."""
        assert HIGHER.toward_better(10.0, 1.0) == 11.0
        assert HIGHER.toward_better(10.0, -1.0) == 9.0
        assert LOWER.toward_better(10.0, 1.0) == 9.0
        assert LOWER.toward_better(10.0, -1.0) == 11.0

    def test_toward_worse_moves_a_magnitude_the_other_way(self):
        assert HIGHER.toward_worse(10.0, 0.5) == 9.5
        assert LOWER.toward_worse(10.0, 0.5) == 10.5

    @pytest.mark.parametrize("order", [HIGHER, LOWER], ids=["higher", "lower"])
    def test_the_disable_convention_survives_both_directions(self, order):
        """The operator disables the skip gate with ``delta = -inf`` and the
        bypass gate with ``delta = +inf``. Under ``lower`` those become
        ``ref - (-inf) = +inf`` and ``ref - inf = -inf`` — which are exactly
        that direction's worst and best sentinels, so the gates stay disabled
        without the operator learning a second convention."""
        assert order.toward_better(-2.5, float("-inf")) == order.worst_sentinel
        assert order.toward_better(-2.5, float("inf")) == order.best_sentinel


class TestPenaltyConventionPredicate:
    def test_it_answers_whether_the_declared_convention_has_a_meaning(self):
        """``degenerate_penalty_score``'s documented convention ("a large
        negative number, strictly below any healthy success") describes a
        MAXIMISED metric. The predicate says so; the caller REFUSES rather than
        reinterpreting the operator's number.

        It is not a direction flag for consumers to branch on — it is the only
        member phrased as a policy question, and exactly one caller uses it.
        """
        assert HIGHER.penalty_convention_applies is True
        assert MetricOrder(accuracy_like_spec()).penalty_convention_applies is True
        assert LOWER.penalty_convention_applies is False
        assert MetricOrder(error_like_spec()).penalty_convention_applies is False


class TestBannerSymbols:
    def test_symbols_follow_the_direction(self):
        """Formatting only, but an operator reading ``<`` on a lower-is-better
        campaign is told the gate fired for the opposite reason."""
        assert (HIGHER.comparison_symbol, HIGHER.at_least_symbol) == ("<", ">=")
        assert (LOWER.comparison_symbol, LOWER.at_least_symbol) == (">", "<=")
