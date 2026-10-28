"""Deterministic SELECT arithmetic over a ``Combined`` candidate set.

SELECT returns unit indices; values are never edited here. ``all`` and
``threshold`` keep declared order; only ``top-k`` follows a ranking.
"""

from execute_tools.evaluation_metric import MetricSpec
from execute_tools.metric_order import MetricOrder
from workflows.definition.adaptor_strategies import (
    AllSelect,
    FirstAdmissibleSelect,
    SelectStrategy,
    ThresholdSelect,
    TopKSelect,
)
from workflows.definition.catalog import METRIC_SCORED_CONTRACTS

from .combine import Combined, Ranking, Unit, with_list
from .items import AdaptorStrategyError


def select(
    strategy: SelectStrategy, combined: Combined, metric: MetricSpec | None
) -> tuple[int, ...]:
    """Indices into ``combined.units``, in the order DISTRIBUTE receives them."""
    match strategy:
        case AllSelect():
            return tuple(range(len(combined.units)))
        case FirstAdmissibleSelect():
            if combined.combine_kind != "pass/v1":
                raise AdaptorStrategyError(
                    f"first-admissible/v1 requires pass/v1, not {combined.combine_kind}"
                )
            return (0,) if combined.units else ()
        case TopKSelect(k=k):
            ranking = _ranking(combined, strategy.kind)
            if ranking.basis in ("rubric", "judge") and any(
                unit.element_contract in METRIC_SCORED_CONTRACTS for unit in combined.units
            ):
                # Q-B2-2: an LLM may filter metric-scored items, never reorder them.
                raise AdaptorStrategyError(
                    f"top-k/v1 over a {ranking.basis} ranking of metric-scored items is refused"
                )
            return tuple(entry.unit for entry in ranking.entries[:k])
        case ThresholdSelect():
            return _threshold(strategy, _ranking(combined, strategy.kind), metric)


def chosen_units(combined: Combined, indices: tuple[int, ...]) -> tuple[Unit, ...]:
    """The selected values; list-entry selections rebuild their one parent value."""
    if combined.parent is None:
        return tuple(combined.units[index] for index in indices)
    if not indices:
        return ()
    if combined.list_field is None:
        raise AdaptorStrategyError(f"{combined.combine_kind} names a parent without a list field")
    picked = [combined.units[index] for index in indices]
    value = with_list(combined.parent.value, combined.list_field, [unit.value for unit in picked])
    entry_refs = tuple(unit.inputs[0] for unit in picked)
    return (
        Unit(
            value=value,
            element_contract=combined.parent.element_contract,
            inputs=(combined.parent.inputs[0], *entry_refs),
            role="selected",
            entry_refs=entry_refs,
        ),
    )


def _ranking(combined: Combined, kind: str) -> Ranking:
    if combined.ranking is None:
        raise AdaptorStrategyError(f"{kind} requires a ranking; {combined.combine_kind} has none")
    return combined.ranking


def _threshold(
    strategy: ThresholdSelect, ranking: Ranking, metric: MetricSpec | None
) -> tuple[int, ...]:
    if ranking.basis != strategy.basis:
        raise AdaptorStrategyError(
            f"threshold/v1 basis {strategy.basis!r} cannot read a {ranking.basis!r} ranking"
        )
    if strategy.basis == "metric":
        if metric is None or strategy.metric_id != metric.id or ranking.metric_id != metric.id:
            raise AdaptorStrategyError(
                f"threshold/v1 names metric {strategy.metric_id!r}; the run metric is "
                f"{metric.id if metric else None!r} and the ranking used {ranking.metric_id!r}"
            )
        order = MetricOrder(metric)
        kept = {
            entry.unit
            for entry in ranking.entries
            if entry.value is not None and order.is_at_least(entry.value, strategy.at_least)
        }
    else:
        # A rubric total is higher-is-better by the rubric type, never by a metric.
        kept = {
            entry.unit
            for entry in ranking.entries
            if entry.value is not None and entry.value >= strategy.at_least
        }
    return tuple(sorted(kept))
