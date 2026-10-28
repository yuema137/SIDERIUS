"""Static admission of a declared LLM strategy (pure, no I/O). B6 calls it at
declaration validation and launch admission and refuses on any refusal."""

from workflows.definition.adaptor_strategies import (
    AllSelect,
    CardinalityBound,
    SelectStrategy,
    ThresholdSelect,
    TopKSelect,
)
from workflows.definition.catalog import METRIC_SCORED_CONTRACTS
from workflows.definition.llm_strategies import LLMStrategy
from workflows.definition.models import InputPort

from .kinds import IMPLEMENTED_KINDS
from .models import StrategyAdmission, StrategyRefusal
from .projection import ITEM_PROJECTORS


def _item_capacity(inputs: tuple[InputPort, ...]) -> int | None:
    """Most admissible items the ports can hold; ``None`` if a ``many`` port is unbounded."""
    capacity = 0
    for port in inputs:
        if port.cardinality == "one":
            capacity += 1
        elif port.max_items is None:
            return None
        else:
            capacity += port.max_items
    return capacity


def _select_refusals(kind: str, contract: str, select: SelectStrategy) -> list[StrategyRefusal]:
    """SELECT rules for a rubric ranking (the only implemented kind)."""
    refusals: list[StrategyRefusal] = []
    rubric_threshold = isinstance(select, ThresholdSelect) and select.basis == "rubric"
    if not (isinstance(select, AllSelect | TopKSelect) or rubric_threshold):
        refusals.append(
            StrategyRefusal(
                code="select_incompatible",
                message=f"{kind} ranks by rubric; {select.kind} cannot consume it"
                + (
                    " (threshold basis must be 'rubric')"
                    if isinstance(select, ThresholdSelect)
                    else ""
                ),
            )
        )
    if contract in METRIC_SCORED_CONTRACTS and isinstance(select, TopKSelect):
        # Q-B2-2: an LLM may filter metric-scored items, never reorder them against the metric.
        refusals.append(
            StrategyRefusal(
                code="metric_scored_reorder",
                message=f"{contract} carries formal metric results; {kind} may only feed "
                "threshold/v1 (basis rubric) or all/v1",
            )
        )
    return refusals


def admit_llm_strategy(
    strategy: LLMStrategy,
    *,
    inputs: tuple[InputPort, ...],
    output_contract: str,
    select: SelectStrategy,
    cardinality: CardinalityBound,
) -> StrategyAdmission:
    """Every reason ``strategy`` cannot occupy this adaptor's COMBINE slot.

    ``cardinality`` (B6 ``derive_cardinality``) bounds combining kinds' output count;
    a ranking kind returns a permutation that SELECT bounds, so it does not use it.
    Fallback admissibility is B6's: it validates ``on_failure.combine`` in place of
    the LLM kind with the deterministic validation table.
    """
    del cardinality  # used by combining kinds only (none implemented yet)
    slot = strategy.route_slot
    kind = IMPLEMENTED_KINDS.get(strategy.kind)
    if kind is None:
        refusal = StrategyRefusal(
            code="kind_not_implemented",
            message=f"{strategy.kind} is declared but its implementation has not landed",
        )
        return StrategyAdmission(
            static_call_bound=None, required_route_slot=slot, refusals=(refusal,)
        )
    refusals: list[StrategyRefusal] = []
    contracts = sorted({port.contract for port in inputs})
    if len(contracts) != 1:
        refusals.append(
            StrategyRefusal(code="mixed_contracts", message=f"input contracts differ: {contracts}")
        )
    contract = contracts[0]
    if contract not in ITEM_PROJECTORS:
        refusals.append(
            StrategyRefusal(
                code="unprojectable_contract",
                message=f"no LLM item projector is registered for {contract!r}",
            )
        )
    if output_contract != contract:
        refusals.append(
            StrategyRefusal(
                code="output_contract_mismatch",
                message=f"a ranking passes {contract} values through, not {output_contract}",
            )
        )
    refusals += _select_refusals(strategy.kind, contract, select)
    capacity = _item_capacity(inputs)
    bound = None if capacity is None else kind.call_bound(strategy, capacity)
    if capacity is None:
        refusals.append(
            StrategyRefusal(
                code="unbounded_port",
                message="every 'many' port of an LLM strategy declares max_items (static call bound)",
            )
        )
    elif bound is not None and bound > strategy.max_calls:
        refusals.append(
            StrategyRefusal(
                code="call_bound_exceeds_max_calls",
                message=f"{strategy.kind} may make {bound} calls; max_calls is {strategy.max_calls}",
            )
        )
    return StrategyAdmission(
        static_call_bound=bound, required_route_slot=slot, refusals=tuple(refusals)
    )
