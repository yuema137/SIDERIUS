"""``debate-judge/v1``: advocates (and an optional critic) debate, then one judge decides.

Calls are serial and round-major: in each of ``rounds`` rounds, one advocate per
item in declared order, then the critic when declared; then one final judge call.
Static call bound: ``rounds × (N + critic) + 1``. Each call carries every earlier
turn verbatim, and its request names every earlier call's digest, so a turn cannot
be dropped, reordered or edited without replay refusing.

``judge_output="rank"``: the judge returns an ordinal permutation of all items
(``ItemRanking`` without scores; B6 applies ``top-k/v1`` or ``all/v1``). One item
needs no debate: the outcome is ``skipped`` with the trivial ranking.
``judge_output="synthesize"``: the judge writes ``synthesize_count`` values of the
output contract (``CombinedItems``); fewer than two items is ``insufficient_items``.
No score arithmetic is involved.
"""

from __future__ import annotations

from agent.schemas.judge import (
    AdvocacyRequest,
    CritiqueRequest,
    DebateTurn,
    DebateVerdictRequest,
    RankVerdict,
    SynthesisVerdict,
)
from workflows.definition.llm_strategies import DebateJudgeStrategy

from .debate_templates import ADVOCATE_TEMPLATE, CRITIC_TEMPLATE, RANK_TEMPLATE, SYNTHESIZE_TEMPLATE
from .models import CombinedItems, ItemRanking, StrategyError, StrategyInvocation
from .plan import PlannedCall, judged_items
from .synthesis import combined_items

Payload = DebateTurn | RankVerdict | SynthesisVerdict


def _strategy(invocation: StrategyInvocation) -> DebateJudgeStrategy:
    strategy = invocation.strategy
    if not isinstance(strategy, DebateJudgeStrategy):
        raise StrategyError(f"debate-judge/v1 cannot plan {strategy.kind}")
    return strategy


def call_bound(strategy: DebateJudgeStrategy, n_items: int) -> int:
    return strategy.rounds * (n_items + int(strategy.critic)) + 1


def min_items(strategy: DebateJudgeStrategy) -> int:
    """A synthesis needs two items to debate; a ranking of one item is skipped instead."""
    return 2 if strategy.judge_output == "synthesize" else 1


def output_count(strategy: DebateJudgeStrategy) -> int | None:
    """``synthesize_count`` values in synthesize mode; ``None`` (a ranking) in rank mode."""
    return strategy.synthesize_count


def trivial(invocation: StrategyInvocation) -> ItemRanking | None:
    """The ranking of a single item needs no call."""
    strategy = _strategy(invocation)
    if strategy.judge_output == "rank" and len(invocation.items) == 1:
        return ItemRanking(order=(invocation.items[0].item_id,))
    return None


def plan_call(invocation: StrategyInvocation, earlier: tuple[Payload, ...]) -> PlannedCall | None:
    strategy = _strategy(invocation)
    items = judged_items(invocation)
    per_round = len(items) + int(strategy.critic)
    turns = strategy.rounds * per_round
    index = len(earlier)
    if index > turns:
        return None
    transcript = tuple(turn for turn in earlier if isinstance(turn, DebateTurn))
    common = {
        "criterion": strategy.criterion,
        "items": items,
        "transcript": transcript,
        "guidance": invocation.task_guidance,
    }
    if index < turns:
        round_index, position = divmod(index, per_round)
        if position < len(items):
            advocacy = AdvocacyRequest(
                **common, round=round_index + 1, item_id=items[position].item_id
            )
            return PlannedCall(role="advocate", template=ADVOCATE_TEMPLATE, content=advocacy)
        critique = CritiqueRequest(**common, round=round_index + 1)
        return PlannedCall(role="critic", template=CRITIC_TEMPLATE, content=critique)
    synthesize = strategy.judge_output == "synthesize"
    verdict = DebateVerdictRequest(
        **common,
        judge_output=strategy.judge_output,
        synthesize_count=strategy.synthesize_count,
        output_contract=invocation.output_contract if synthesize else None,
    )
    template = SYNTHESIZE_TEMPLATE if synthesize else RANK_TEMPLATE
    return PlannedCall(role="judge", template=template, content=verdict)


def fold(
    invocation: StrategyInvocation, payloads: tuple[Payload, ...]
) -> ItemRanking | CombinedItems:
    """The judge's decision; the turns are evidence, never output."""
    strategy = _strategy(invocation)
    if len(payloads) != call_bound(strategy, len(invocation.items)):
        raise StrategyError("debate-judge/v1 folds only a complete debate")
    verdict = payloads[-1]
    if isinstance(verdict, RankVerdict):
        return ItemRanking(order=verdict.order)
    if isinstance(verdict, SynthesisVerdict) and strategy.synthesize_count is not None:
        return combined_items(invocation, verdict.items, declared=strategy.synthesize_count)
    raise StrategyError("debate-judge/v1 chain does not end with its judge verdict")
