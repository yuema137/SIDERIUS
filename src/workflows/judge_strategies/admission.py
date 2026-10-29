"""Static admission of a declared LLM strategy (pure, no I/O). B6 calls it at
declaration validation and launch admission and refuses on any refusal."""

from agent.schemas.judge import MAX_SCORED_ITEMS_PER_CALL
from workflows.definition.adaptor_strategies import (
    AllSelect,
    CardinalityBound,
    SelectStrategy,
    ThresholdSelect,
    TopKSelect,
)
from workflows.definition.catalog import CUSTOM_EMITTABLE, METRIC_SCORED_CONTRACTS
from workflows.definition.llm_strategies import LLMStrategy, RubricRankStrategy
from workflows.definition.models import InputPort

from .kinds import IMPLEMENTED_KINDS
from .models import StrategyAdmission, StrategyRefusal, StrategyRefusalCode, lists_every_item
from .plan import StrategyKind
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


def _refusal(code: StrategyRefusalCode, message: str) -> StrategyRefusal:
    return StrategyRefusal(code=code, message=message)


def _ranking_refusals(kind: str, contract: str, select: SelectStrategy) -> list[StrategyRefusal]:
    """SELECT rules for a rubric ranking."""
    refusals: list[StrategyRefusal] = []
    rubric_threshold = isinstance(select, ThresholdSelect) and select.basis == "rubric"
    if not (isinstance(select, AllSelect | TopKSelect) or rubric_threshold):
        refusals.append(
            _refusal(
                "select_incompatible",
                f"{kind} ranks by rubric; {select.kind} cannot consume it"
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
            _refusal(
                "metric_scored_reorder",
                f"{contract} carries formal metric results; {kind} may only feed "
                "threshold/v1 (basis rubric) or all/v1",
            )
        )
    return refusals


def _combined_refusals(
    strategy: LLMStrategy,
    count: int,
    contract: str,
    select: SelectStrategy,
    cardinality: CardinalityBound,
) -> list[StrategyRefusal]:
    """Rules for a kind that synthesizes ``count`` new values of ``contract``."""
    refusals: list[StrategyRefusal] = []
    if contract not in CUSTOM_EMITTABLE:
        refusals.append(
            _refusal(
                "output_not_emittable",
                f"{strategy.kind} cannot synthesize {contract}: authority contracts stay "
                "with the framework",
            )
        )
    if not isinstance(select, AllSelect):
        refusals.append(
            _refusal(
                "select_incompatible",
                f"{strategy.kind} produces new values, not a ranking; it feeds all/v1 only",
            )
        )
    if not cardinality.min <= count <= cardinality.max:
        refusals.append(
            _refusal(
                "cardinality_mismatch",
                f"{strategy.kind} produces {count} values; SELECT/DISTRIBUTE take "
                f"{cardinality.min}..{cardinality.max}",
            )
        )
    return refusals


def _contract_refusals(
    strategy: LLMStrategy, inputs: tuple[InputPort, ...], output_contract: str
) -> tuple[str, list[StrategyRefusal]]:
    """The one input contract and the refusals about input and output contracts."""
    refusals: list[StrategyRefusal] = []
    contracts = sorted({port.contract for port in inputs})
    if len(contracts) != 1:
        refusals.append(_refusal("mixed_contracts", f"input contracts differ: {contracts}"))
    contract = contracts[0]
    if contract not in ITEM_PROJECTORS:
        refusals.append(
            _refusal(
                "unprojectable_contract", f"no LLM item projector is registered for {contract!r}"
            )
        )
    if output_contract != contract:
        refusals.append(
            _refusal(
                "output_contract_mismatch",
                f"{strategy.kind} emits {contract} values over {contract} inputs, "
                f"not {output_contract}",
            )
        )
    return contract, refusals


def _capacity_refusals(
    kind: StrategyKind, strategy: LLMStrategy, capacity: int | None
) -> list[StrategyRefusal]:
    """The ports' item capacity: bounded, enough for the kind, within the per-call cap."""
    if capacity is None:
        return [
            _refusal(
                "unbounded_port",
                "every 'many' port of an LLM strategy declares max_items (static call bound)",
            )
        ]
    if capacity < kind.min_items(strategy):
        return [
            _refusal(
                "insufficient_capacity",
                f"{strategy.kind} needs at least {kind.min_items(strategy)} items; "
                f"the ports hold at most {capacity}",
            )
        ]
    if lists_every_item(strategy) and capacity > MAX_SCORED_ITEMS_PER_CALL:
        hint = "; use per_item scoring" if isinstance(strategy, RubricRankStrategy) else ""
        return [
            _refusal(
                "batch_too_large",
                f"{strategy.kind} lists every item in one call; up to {capacity} items "
                f"exceed {MAX_SCORED_ITEMS_PER_CALL} items per call{hint}",
            )
        ]
    return []


def admit_llm_strategy(
    strategy: LLMStrategy,
    *,
    inputs: tuple[InputPort, ...],
    output_contract: str,
    select: SelectStrategy,
    cardinality: CardinalityBound,
) -> StrategyAdmission:
    """Every reason ``strategy`` cannot occupy this adaptor's COMBINE slot.

    ``cardinality`` (B6 ``derive_cardinality``) bounds a combining kind's output
    count; a ranking kind returns a permutation that SELECT bounds, so it does not
    use it.
    Fallback admissibility is B6's: it validates ``on_failure.combine`` in place of
    the LLM kind with the deterministic validation table.
    """
    slot = strategy.route_slot
    kind = IMPLEMENTED_KINDS.get(strategy.kind)
    if kind is None or not inputs:
        refusal = (
            _refusal(
                "kind_not_implemented",
                f"{strategy.kind} is declared but its implementation has not landed",
            )
            if kind is None
            else _refusal("no_input_ports", "an adaptor declares no input port")
        )
        return StrategyAdmission(
            static_call_bound=None, required_route_slot=slot, refusals=(refusal,)
        )
    contract, refusals = _contract_refusals(strategy, inputs, output_contract)
    if kind.output_count is None:
        refusals += _ranking_refusals(strategy.kind, contract, select)
    else:
        count = kind.output_count(strategy)
        refusals += _combined_refusals(strategy, count, contract, select, cardinality)
    capacity = _item_capacity(inputs)
    refusals += _capacity_refusals(kind, strategy, capacity)
    bound = None if capacity is None else kind.call_bound(strategy, capacity)
    if bound is not None and bound > strategy.max_calls:
        refusals.append(
            _refusal(
                "call_bound_exceeds_max_calls",
                f"{strategy.kind} may make {bound} calls; max_calls is {strategy.max_calls}",
            )
        )
    return StrategyAdmission(
        static_call_bound=bound, required_route_slot=slot, refusals=tuple(refusals)
    )
