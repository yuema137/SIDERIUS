"""The ONE authority that interprets a golden metric's declared direction.

Step 07 PR 07b, P1-order. Design:
``docs/design/generic_framework_upgrade/step_07_tuner_policy_and_training_diagnostics/
pr_07b_tuner_policy.md`` §3.2 (the frozen API and its consumer table).

Why this module exists
----------------------
Before 07b the tuner spelled "bigger is better" twenty-one times — ``max()``
over ``denoising_score``, ``<`` in the skip gate, ``>=`` in the bypass gate,
``sorted(reverse=True)`` for the reflector's rank, ``float("-inf")`` for the
bootstrap and the skip-disabled sentinel, ``float("inf")`` for the
bypass-disabled sentinel. Every one of them was a private re-derivation of
the TIDMAD convention, and none of them read
:attr:`~execute_tools.evaluation_metric.MetricSpec.direction`, which Step 06
had already made the metric's own declaration.

``MetricOrder`` is where ``direction`` is interpreted — and the ONLY place.
The parent design forbids a second direction field (no ``higher_is_better``
boolean, no per-consumer literal, no direction flag on a record), because two
authorities that agree today are a latent contradiction, not a design.

Ordering only
-------------
This class answers *which of two values is better* and nothing else. It does
NOT know:

* **validity** — whether a record is eligible to be an incumbent at all is
  HealthGate's question (``is_valid_candidate``), and folding it in here would
  make an invalid record's score participate in the comparison it must not
  reach (design §3.4). Selection FILTERS, then orders.
* **scale** — a threshold margin, an efficiency band or a collapse penalty
  depends on the metric's units, not merely on its direction. Those rules are
  classified per rule in §3.3 and resolve through :meth:`toward_better` /
  :meth:`toward_worse`, which apply the direction to an ALREADY-declared
  quantity. Nothing here invents a magnitude.
* **losses** — a training loss is lower-is-better by definition of a loss and
  is unrelated to the golden metric. The tuner's same-loss ``final_loss`` rank
  must NOT flip with the metric direction and therefore must not use this
  class.

Importable by the tuner today and by the peripheral direction consumers when
Steps 09/10/M2 migrate them. Deliberately NOT imported by the scoring path:
``execute_tools`` scoring computes a number, it does not rank.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import TypeVar

from execute_tools.evaluation_metric import MetricDeclaration, MetricDirection

_T = TypeVar("_T")

_HIGHER: MetricDirection = "higher"


class MetricOrder:
    """Ordering over a golden metric's values, derived from its declaration.

    Construct ONCE per run from the bound metric's spec and pass it to every
    ordering consumer. Constructing a second instance with the opposite
    direction in order to obtain "the worst" is exactly the second
    interpretation site this class exists to prevent — use :meth:`worst`.

    Args:
        spec: the golden metric's declaration — either the whole
            :class:`~execute_tools.evaluation_metric.MetricSpec` or the
            minimum comparison identity
            :class:`~execute_tools.evaluation_metric.MetricIdentityKey`
            a persisted record carries. Only ``direction`` is read, from
            either.

    Example:
        >>> from execute_tools.evaluation_metric import MetricSpec, PresenceScoreabilityContract
        >>> spec = MetricSpec(id="score", direction="higher", aggregation="mean",
        ...                   scoreability=PresenceScoreabilityContract())
        >>> order = MetricOrder(spec)
        >>> order.direction
        'higher'
        >>> order.is_better(-2.55, -2.91)
        True

    Note (Step 10 P2a C3, deviation D-P2a-4): the parameter accepts
    ``MetricIdentityKey`` as well as ``MetricSpec``. This is a TYPE-LEVEL
    widening with no behavioural change — the class reads ``direction`` and
    nothing else, exactly as before, and remains the single site where the
    declaration is interpreted. It exists because the design's §4.4 states
    that a persisted artifact carries ``metric_id`` + ``direction`` and NOT a
    whole spec, while requiring those consumers (dashboard, diagnostic
    scripts, proposer) to rank; without this the only alternatives were to
    synthesise a fake ``MetricSpec`` — inventing ``aggregation`` and
    ``scoreability`` a record never declared — or to add a second comparator
    outside this class. Both are things P2a exists to prevent.
    """

    __slots__ = ("_higher", "direction")

    def __init__(self, spec: MetricDeclaration) -> None:
        self.direction: MetricDirection = spec.direction
        self._higher: bool = spec.direction == _HIGHER

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return f"MetricOrder(direction={self.direction!r})"

    # -- comparison ---------------------------------------------------------

    def is_better(self, a: float, b: float) -> bool:
        """Whether ``a`` is STRICTLY better than ``b``.

        ``higher`` → ``a > b``; ``lower`` → ``a < b``. Equal values are not
        better, which is what keeps "is this a new best?" from firing on a tie.
        """
        return a > b if self._higher else a < b

    def is_at_least(self, a: float, b: float) -> bool:
        """Whether ``a`` is at least as good as ``b`` (better OR equal).

        ``higher`` → ``a >= b``; ``lower`` → ``a <= b``. The bypass gate and
        the efficiency band both mean "clears the bar", tie included.
        """
        return a >= b if self._higher else a <= b

    @property
    def comparison_symbol(self) -> str:
        """The operator a human-readable banner should print for "worse than".

        ``<`` under ``higher``, ``>`` under ``lower``. Banner formatting only —
        never a decision. It lives here rather than at the two banner call
        sites for the same reason every comparison does: a literal ``<`` in a
        log line is a second reading of ``direction``, and an operator
        debugging a ``lower`` campaign would be told the gate fired for the
        opposite reason.
        """
        return "<" if self._higher else ">"

    @property
    def direction_words(self) -> dict[str, str]:
        """The direction in words, for prose that must state it.

        ``verb`` — maximize / minimize; ``comparative`` — higher / lower;
        ``antonym`` — the opposite of ``comparative``.

        These live here for the same reason the two banner symbols do, and the
        reason is enforced by a test: ``direction`` may be interpreted in
        exactly ONE module. A prompt renderer that computed "maximize" from
        ``spec.direction == "higher"`` would be a second reading of the same
        declaration — the pattern 07b removed from twenty-one tuner sites — and
        Step 06's C5 guard fails on exactly that.
        """
        return {
            "verb": "maximize" if self._higher else "minimize",
            "comparative": "higher" if self._higher else "lower",
            "antonym": "lower" if self._higher else "higher",
        }

    @property
    def penalty_convention_applies(self) -> bool:
        """Whether the ``degenerate_penalty_score`` convention is meaningful here.

        That convention — "a large negative number, strictly below any healthy
        success" — is a statement about a metric that is MAXIMISED. On a
        minimised metric the very same number is the BEST score in the run, so
        a collapsed round would be handed to the planner looking like the
        campaign's finest result.

        This is deliberately not a direction flag for consumers to branch on:
        it answers one question — *does this declared policy have a meaning
        under the bound metric?* — and the only caller uses it to REFUSE at
        startup rather than to reinterpret the operator's number (design §3.3
        row 5, classification (iv): inapplicable → fail closed). Validity
        semantics stay Step 08's.
        """
        return self._higher

    @property
    def at_least_symbol(self) -> str:
        """The operator a banner should print for "at least as good as".

        ``>=`` under ``higher``, ``<=`` under ``lower``. Formatting only —
        the bypass banner's counterpart to :attr:`comparison_symbol`.
        """
        return ">=" if self._higher else "<="

    # -- extremes -----------------------------------------------------------

    def best(self, items: Iterable[_T], key: Callable[[_T], float]) -> _T:
        """The best item by ``key``.

        Ties resolve to the FIRST item, matching the ``max()``/``min()``
        semantics every rewired call site had before 07b (Checkpoint-0 pins a
        tie case precisely so this cannot drift).

        Raises:
            ValueError: if ``items`` is empty — same as ``max()``. Every
                production caller already guards on emptiness, and inventing a
                ``None`` here would hide a missing guard.
        """
        return max(items, key=key) if self._higher else min(items, key=key)

    def worst(self, items: Iterable[_T], key: Callable[[_T], float]) -> _T:
        """The worst item by ``key`` — ties resolve to the FIRST item.

        A first-class member so that no consumer ever builds an
        opposite-direction ``MetricOrder`` to answer this (design §3.2).
        """
        return min(items, key=key) if self._higher else max(items, key=key)

    def rank(self, values: Sequence[float], value: float) -> int:
        """1-based rank of ``value`` among ``values`` — 1 is the best.

        Defined as ``1 + (number of values strictly better than value)``, which
        equals the pre-07b ``sorted(values, reverse=True).index(value) + 1``
        under ``higher`` (ties share the best rank in both formulations) and
        inverts correctly under ``lower``.
        """
        return 1 + sum(1 for other in values if self.is_better(other, value))

    # -- sentinels ----------------------------------------------------------

    @property
    def worst_sentinel(self) -> float:
        """The value nothing can be worse than: ``-inf`` under ``higher``.

        Two distinct meanings share it, both order facts: the bootstrap
        reference ("no incumbent yet, so anything clears it") and the
        skip-gate's disable value.
        """
        return float("-inf") if self._higher else float("inf")

    @property
    def best_sentinel(self) -> float:
        """The value nothing can be better than: ``+inf`` under ``higher``.

        The bypass gate's disable value: a threshold nothing can reach.
        """
        return float("inf") if self._higher else float("-inf")

    # -- movement along the metric's axis -----------------------------------

    def toward_better(self, reference: float, signed_delta: float) -> float:
        """Move ``reference`` by ``signed_delta`` on the BETTER-direction axis.

        ``signed_delta`` is a coordinate, not a magnitude: positive moves
        toward better, negative moves toward worse — under BOTH directions. So
        an operator's declared skip margin of ``-1.0`` loosens the threshold by
        one metric unit whether the metric is maximised or minimised, and the
        documented ``-inf`` / ``+inf`` disable values keep meaning "disabled"
        under both.

        The magnitude itself is never invented here; it arrives already
        declared in the golden metric's own units (design §3.3 row 1).
        """
        return reference + signed_delta if self._higher else reference - signed_delta

    def toward_worse(self, reference: float, magnitude: float) -> float:
        """Move ``reference`` ``magnitude`` units toward worse.

        ``magnitude`` is non-negative. Used by the efficiency band, whose
        width is a fraction of the run's OBSERVED score range and is therefore
        a magnitude, not a coordinate (design §3.3 row 4).
        """
        return self.toward_better(reference, -magnitude)
