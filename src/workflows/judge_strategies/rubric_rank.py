"""``rubric-rank/v1``: plan the scorer calls and fold their verdicts into a ranking.

Pure. The LLM supplies per-criterion integers only; this module takes the median
of the declared repeats per criterion, computes the weighted mean
(``sum(weight * median) / sum(weight)`` in rubric criterion order, so it lies on
the rubric scale) and orders items by it, higher first, ties in input order. A rubric
score is not a task metric: this module deliberately imports no metric owner (an AST guard enforces it).
"""

from statistics import median

from agent.judge.rubric_template import RUBRIC_TEMPLATE
from agent.schemas.judge import JudgedItem, RubricScoringRequest, RubricVerdict
from workflows.definition.llm_strategies import RubricRankStrategy

from .models import (
    CriterionValue,
    ItemRanking,
    RubricScore,
    StrategyError,
    StrategyInvocation,
)
from .plan import PlannedCall, judged_items


def call_bound(strategy: RubricRankStrategy, n_items: int) -> int:
    """Static number of scorer calls for ``n_items`` admissible items."""
    per_repeat = n_items if strategy.scoring == "per_item" else 1
    return per_repeat * strategy.repeats


def _parts(invocation: StrategyInvocation) -> tuple[RubricRankStrategy, list[JudgedItem]]:
    strategy = invocation.strategy
    if not isinstance(strategy, RubricRankStrategy):
        raise StrategyError(f"rubric-rank/v1 cannot plan {strategy.kind}")
    return strategy, list(judged_items(invocation))


def min_items(strategy: RubricRankStrategy) -> int:
    """A single item is scored too: ``threshold(basis="rubric")`` reads its weighted mean."""
    del strategy
    return 1


def plan_call(invocation: StrategyInvocation, earlier: tuple[object, ...]) -> PlannedCall | None:
    """The next scorer call (repeat-major, then input order), or ``None`` when done."""
    strategy, judged = _parts(invocation)
    call_index = len(earlier)
    if call_index >= call_bound(strategy, len(judged)):
        return None
    if strategy.scoring == "per_item":
        repeat, position = divmod(call_index, len(judged))
        items = (judged[position],)
    else:
        repeat, items = call_index, tuple(judged)
    assert invocation.rubric is not None  # StrategyInvocation requires it for this kind
    content = RubricScoringRequest(
        rubric=invocation.rubric,
        criterion=strategy.criterion,
        repeat=repeat,
        items=items,
        guidance=invocation.task_guidance,
    )
    return PlannedCall(role="scorer", template=RUBRIC_TEMPLATE, content=content)


def fold(invocation: StrategyInvocation, verdicts: tuple[RubricVerdict, ...]) -> ItemRanking:
    """Rank every item from validated verdicts; the mean is never taken from the LLM."""
    strategy, judged = _parts(invocation)
    if len(verdicts) != call_bound(strategy, len(judged)):
        raise StrategyError("rubric-rank/v1 folds only a complete set of scorer verdicts")
    rubric = invocation.rubric
    assert rubric is not None
    samples: dict[tuple[str, str], list[int]] = {}
    for verdict in verdicts:
        for entry in verdict.item_scores:
            for score in entry.scores:
                samples.setdefault((entry.item_id, score.criterion), []).append(score.score)
    scores = []
    for item in judged:
        per_criterion = tuple(
            CriterionValue(
                criterion=criterion.name,
                value=float(median(samples[(item.item_id, criterion.name)])),
            )
            for criterion in rubric.criteria
        )
        weighted = sum(
            criterion.weight * value.value
            for criterion, value in zip(rubric.criteria, per_criterion, strict=True)
        )
        mean = weighted / sum(criterion.weight for criterion in rubric.criteria)
        scores.append(
            RubricScore(
                rubric=strategy.rubric,
                item_id=item.item_id,
                per_criterion=per_criterion,
                weighted_mean=mean,
            )
        )
    # Stable sort: equal means keep input order (tie_break="input_order").
    ranked = tuple(sorted(scores, key=lambda score: -score.weighted_mean))
    return ItemRanking(order=tuple(score.item_id for score in ranked), scores=ranked)
