"""The pure deterministic adaptor: admit -> COMBINE -> SELECT -> DISTRIBUTE.

No I/O and no state: the outcome is a function of the typed items (in declared
order), the three declared strategies and the run metric.
"""

from typing import Literal, Self

from pydantic import BaseModel, SerializeAsAny, model_validator

from execute_tools.evaluation_metric import MetricSpec
from workflows.definition.adaptor_strategies import (
    DeterministicCombine,
    DistributeStrategy,
    PerItemDistribute,
    ReplicateDistribute,
    SelectStrategy,
    SingleDistribute,
    SplitItemsDistribute,
    derive_cardinality,
    incompatible_pair,
)
from workflows.definition.catalog import SPLITTABLE_ITEMS

from .combine import Combined, Ranking, Role, Unit, combine, with_list
from .items import (
    AdaptorInputRef,
    AdaptorItem,
    AdaptorModel,
    AdaptorStrategyError,
    ItemAdmission,
    admit_items,
)
from .select import chosen_units, select

AdaptorReason = Literal[
    "no_admissible_input", "insufficient_items", "too_many_items", "judge_failure"
]


class AdaptorOutput(AdaptorModel):
    index: int | None  # None for single/v1
    status: Literal["emitted", "skipped"]
    value: SerializeAsAny[BaseModel] | None = None
    inputs: tuple[AdaptorInputRef, ...] = ()
    role: Role | None = None

    @model_validator(mode="after")
    def emitted_has_value(self) -> Self:
        if (self.status == "emitted") != (self.value is not None):
            raise ValueError("an emitted output carries a value; a skipped one does not")
        return self


class AdaptorOutcome(AdaptorModel):
    status: Literal["succeeded", "rejected", "failed"]
    reason: AdaptorReason | None = None
    admissions: tuple[ItemAdmission, ...]
    ranking: Ranking | None = None
    outputs: tuple[AdaptorOutput, ...] = ()

    @model_validator(mode="after")
    def reason_iff_not_succeeded(self) -> Self:
        if (self.status == "succeeded") == (self.reason is not None):
            raise ValueError("a non-succeeded adaptor outcome requires exactly one reason")
        return self


def run_deterministic_adaptor(
    items: tuple[AdaptorItem, ...],
    *,
    combine_strategy: DeterministicCombine,
    select_strategy: SelectStrategy,
    distribute_strategy: DistributeStrategy,
    metric: MetricSpec | None,
) -> AdaptorOutcome:
    """Decide one adaptor's outputs; ``items`` must already be in declared order."""
    if (incompatible := incompatible_pair(combine_strategy, distribute_strategy)) is not None:
        raise AdaptorStrategyError(incompatible)
    admissions, admissible = admissible_items(items)
    if not admissible:
        return AdaptorOutcome(
            status="rejected", reason="no_admissible_input", admissions=admissions
        )
    combined = combine(combine_strategy, admissible, metric)
    return select_and_distribute(
        combined,
        admissions,
        select_strategy=select_strategy,
        distribute_strategy=distribute_strategy,
        metric=metric,
    )


def admissible_items(
    items: tuple[AdaptorItem, ...],
) -> tuple[tuple[ItemAdmission, ...], tuple[AdaptorItem, ...]]:
    """Every item's admission and the admissible items, in declared order."""
    admissions = admit_items(items)
    admissible = tuple(
        item
        for item, admission in zip(items, admissions, strict=True)
        if admission.admission == "admissible"
    )
    return admissions, admissible


def select_and_distribute(
    combined: Combined,
    admissions: tuple[ItemAdmission, ...],
    *,
    select_strategy: SelectStrategy,
    distribute_strategy: DistributeStrategy,
    metric: MetricSpec | None,
) -> AdaptorOutcome:
    """SELECT then DISTRIBUTE one COMBINE result (deterministic or an LLM kind's)."""
    bound = derive_cardinality(select_strategy, distribute_strategy)
    chosen = chosen_units(combined, select(select_strategy, combined, metric))
    if len(chosen) > bound.max:
        raise AdaptorStrategyError(
            f"{select_strategy.kind} kept {len(chosen)} values; {distribute_strategy.kind} "
            f"accepts at most {bound.max}"
        )
    if len(chosen) < bound.min:  # bound.min >= 1, so this includes an empty selection
        status, reason, outputs = _short(distribute_strategy)
    else:
        status, reason, outputs = _distribute(distribute_strategy, chosen)
    return AdaptorOutcome(
        status=status,
        reason=reason,
        admissions=admissions,
        ranking=combined.ranking,
        outputs=outputs,
    )


_Decision = tuple[
    Literal["succeeded", "rejected", "failed"], AdaptorReason | None, tuple[AdaptorOutput, ...]
]


def _short(strategy: DistributeStrategy) -> _Decision:
    """Shortfall is monotonic: under ``on_short="fail"`` any shortfall fails."""
    fails = isinstance(strategy, PerItemDistribute | SplitItemsDistribute) and (
        strategy.on_short == "fail"
    )
    return ("failed" if fails else "rejected"), "insufficient_items", ()


def _distribute(strategy: DistributeStrategy, chosen: tuple[Unit, ...]) -> _Decision:
    match strategy:
        case SingleDistribute():
            return "succeeded", None, (_emit(None, chosen[0]),)
        case PerItemDistribute(count=count):
            return "succeeded", None, _indexed(chosen, count)
        case ReplicateDistribute(count=count):
            replica = chosen[0].model_copy(update={"role": "replicated"})
            return "succeeded", None, tuple(_emit(index, replica) for index in range(count))
        case SplitItemsDistribute():
            return _split(chosen[0], strategy)


def _emit(index: int | None, unit: Unit) -> AdaptorOutput:
    return AdaptorOutput(
        index=index, status="emitted", value=unit.value, inputs=unit.inputs, role=unit.role
    )


def _indexed(units: tuple[Unit, ...], count: int) -> tuple[AdaptorOutput, ...]:
    return tuple(
        _emit(index, units[index])
        if index < len(units)
        else AdaptorOutput(index=index, status="skipped")
        for index in range(count)
    )


def _split(unit: Unit, strategy: SplitItemsDistribute) -> _Decision:
    if SPLITTABLE_ITEMS.get(unit.element_contract) != strategy.field:
        raise AdaptorStrategyError(
            f"split-items/v1 field {strategy.field!r} is not catalogued for {unit.element_contract!r}"
        )
    entries = list(getattr(unit.value, strategy.field))
    if len(entries) > strategy.count:
        return "failed", "too_many_items", ()
    if not entries or (len(entries) < strategy.count and strategy.on_short == "fail"):
        return _short(strategy)
    pieces = tuple(
        unit.model_copy(
            update={
                "value": with_list(unit.value, strategy.field, [entry]),
                "inputs": _split_refs(unit, strategy.field, index),
                "entry_refs": None,
            }
        )
        for index, entry in enumerate(entries)
    )
    return "succeeded", None, _indexed(pieces, strategy.count)


def _split_refs(unit: Unit, field: str, index: int) -> tuple[AdaptorInputRef, AdaptorInputRef]:
    """Owner of the non-list fields, then the owner of list entry ``index``."""
    owner = unit.inputs[0]
    entry = unit.entry_refs[index] if unit.entry_refs is not None else owner.entry(field, index)
    return owner, entry
