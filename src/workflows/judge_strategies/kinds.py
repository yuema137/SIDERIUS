"""Implemented LLM strategy kinds. A declared kind absent here is refused until its PR lands."""

from types import MappingProxyType

from workflows.definition.llm_strategies import LLMStrategy

from . import debate_judge, judge_merge, primary_advisors, rubric_rank
from .models import StrategyError
from .plan import StrategyKind

IMPLEMENTED_KINDS: MappingProxyType[str, StrategyKind] = MappingProxyType(
    {
        "debate-judge/v1": StrategyKind(
            call_bound=debate_judge.call_bound,
            min_items=debate_judge.min_items,
            plan_call=debate_judge.plan_call,
            fold=debate_judge.fold,
            output_count=debate_judge.output_count,
            trivial=debate_judge.trivial,
        ),
        "rubric-rank/v1": StrategyKind(
            call_bound=rubric_rank.call_bound,
            min_items=rubric_rank.min_items,
            plan_call=rubric_rank.plan_call,
            fold=rubric_rank.fold,
            threshold_basis="rubric",
        ),
        "judge-merge/v1": StrategyKind(
            call_bound=judge_merge.call_bound,
            min_items=judge_merge.min_items,
            plan_call=judge_merge.plan_call,
            fold=judge_merge.fold,
            output_count=judge_merge.output_count,
        ),
        "primary-advisors-llm/v1": StrategyKind(
            call_bound=primary_advisors.call_bound,
            min_items=primary_advisors.min_items,
            plan_call=primary_advisors.plan_call,
            fold=primary_advisors.fold,
            output_count=primary_advisors.output_count,
            precheck=primary_advisors.precheck,
            admit_parameters=primary_advisors.admit_parameters,
        ),
    }
)


def implemented_kind(strategy: LLMStrategy) -> StrategyKind:
    kind = IMPLEMENTED_KINDS.get(strategy.kind)
    if kind is None:
        raise StrategyError(f"LLM strategy kind {strategy.kind} is declared but not implemented")
    return kind


def strategy_call_bound(strategy: LLMStrategy, n_items: int) -> int:
    """Static call bound of ``strategy`` over ``n_items`` items (pure)."""
    return implemented_kind(strategy).call_bound(strategy, n_items)
