"""Deterministic COMBINE: admissible items -> candidate units and an optional ranking.

Metric ranking goes through ``MetricOrder`` under the reconciled run ``MetricSpec``;
nothing here reads a direction from a metric name or a field value.
"""

from collections.abc import Callable
from functools import cmp_to_key
from typing import Literal, Self

from pydantic import BaseModel, Field, SerializeAsAny, model_validator

from execute_tools.evaluation_metric import (
    MetricDirection,
    MetricSpec,
    StampedMetricSpec,
    reconcile_metric_specs,
)
from execute_tools.metric_order import MetricOrder
from workflows.definition.adaptor_strategies import (
    CollectCombine,
    ConcatItemsCombine,
    DeterministicCombine,
    FieldRankCombine,
    MetricRankCombine,
    PassCombine,
)
from workflows.definition.catalog import (
    RANKABLE_FIELDS,
    SPLITTABLE_ITEMS,
)
from workflows.definition.models import ResultSource

from .items import AdaptorInputRef, AdaptorItem, AdaptorModel, AdaptorStrategyError, tuning_output

Role = Literal["selected", "collected", "concatenated", "replicated"]
RankBasis = Literal["metric", "field", "rubric", "judge"]


class Unit(AdaptorModel):
    """One candidate SELECT can keep: a whole value, or one list entry of a value.

    ``element_contract`` is the catalogue contract of a whole value, or
    ``"<contract>:<list_field>"`` for a list entry. ``inputs[0]`` owns a list-bearing
    value's non-list fields; ``entry_refs`` (when set) names the owner of each list
    entry, aligned with the list.
    """

    value: SerializeAsAny[BaseModel]
    element_contract: str
    inputs: tuple[AdaptorInputRef, ...] = Field(min_length=1)
    role: Role
    entry_refs: tuple[AdaptorInputRef, ...] | None = None

    @model_validator(mode="after")
    def entry_refs_align_with_list(self) -> Self:
        """Refuse an owner list that cannot be indexed by the value's list entries."""
        if self.entry_refs is None:
            return self
        field = SPLITTABLE_ITEMS.get(self.element_contract)
        if field is None or len(getattr(self.value, field)) != len(self.entry_refs):
            raise ValueError("entry_refs must name one owner per entry of the catalogued list")
        return self


class CollectedEntry(AdaptorModel):
    contribution_id: str = Field(min_length=1)
    contract: str
    value: SerializeAsAny[BaseModel]


class CollectedItems(AdaptorModel):
    """Every admissible value with its attribution, in declared order."""

    entries: tuple[CollectedEntry, ...] = Field(min_length=1)


class RankEntry(AdaptorModel):
    unit: int = Field(ge=0)
    ref: AdaptorInputRef
    value: float | None = Field(allow_inf_nan=False)  # None for an ordinal-only judge ranking


class Ranking(AdaptorModel):
    """Units best-first; unranked units (no value) are absent and never top-k eligible."""

    basis: RankBasis
    entries: tuple[RankEntry, ...]
    metric_id: str | None = None
    direction: MetricDirection | None = None
    provenance: str | None = None  # e.g. "self-reported" for a field ranking

    @model_validator(mode="after")
    def distinct_units(self) -> Self:
        if len({entry.unit for entry in self.entries}) != len(self.entries):
            raise ValueError("a ranking lists each unit at most once")
        is_metric = self.basis == "metric"
        if is_metric != (self.metric_id is not None) or is_metric != (self.direction is not None):
            raise ValueError(
                "a ranking names metric_id and direction if and only if its basis is 'metric'"
            )
        return self


class Combined(AdaptorModel):
    """COMBINE result. ``parent`` is set iff ``units`` are list entries of that one value."""

    combine_kind: str
    units: tuple[Unit, ...]
    ranking: Ranking | None = None
    parent: Unit | None = None
    list_field: str | None = None


def combine(
    strategy: DeterministicCombine, items: tuple[AdaptorItem, ...], metric: MetricSpec | None
) -> Combined:
    """Apply one deterministic COMBINE kind to the admissible items (declared order)."""
    if not items:
        raise AdaptorStrategyError("COMBINE requires at least one admissible item")
    match strategy:
        case PassCombine():
            return Combined(combine_kind=strategy.kind, units=_whole_units(items))
        case CollectCombine():
            return Combined(combine_kind=strategy.kind, units=(_collect(items),))
        case ConcatItemsCombine(field=field):
            return Combined(combine_kind=strategy.kind, units=(_concat(items, field),))
        case MetricRankCombine():
            return _metric_rank(strategy, items, metric)
        case FieldRankCombine():
            return _field_rank(strategy, items)


def with_list(value: BaseModel, list_field: str, entries: list[BaseModel]) -> BaseModel:
    """``value`` with one list replaced, revalidated by its own native model."""
    updated = value.model_copy(update={list_field: type(getattr(value, list_field))(entries)})
    return type(value).model_validate_json(updated.model_dump_json())


def _whole_units(items: tuple[AdaptorItem, ...]) -> tuple[Unit, ...]:
    return tuple(
        Unit(
            value=_value(item), element_contract=item.contract, inputs=(item.ref,), role="selected"
        )
        for item in items
    )


def _collect(items: tuple[AdaptorItem, ...]) -> Unit:
    entries = tuple(
        CollectedEntry(
            contribution_id=_contribution_id(item.ref),
            contract=item.contract,
            value=_value(item),
        )
        for item in items
    )
    return Unit(
        value=CollectedItems(entries=entries),
        element_contract=_one_contract(items, "collect/v1"),
        inputs=tuple(item.ref for item in items),
        role="collected",
    )


def _concat(items: tuple[AdaptorItem, ...], field: str) -> Unit:
    contract = _one_contract(items, "concat-items/v1")
    _require_catalogued(SPLITTABLE_ITEMS.get(contract), field, "concat-items/v1", contract)
    owned = [
        (item.ref.entry(field, index), entry)
        for item in items
        for index, entry in enumerate(getattr(_value(item), field))
    ]
    return Unit(
        value=with_list(_value(items[0]), field, [entry for _, entry in owned]),
        element_contract=contract,
        inputs=tuple(item.ref for item in items),
        role="concatenated",
        entry_refs=tuple(ref for ref, _ in owned),
    )


def _metric_rank(
    strategy: MetricRankCombine, items: tuple[AdaptorItem, ...], metric: MetricSpec | None
) -> Combined:
    if metric is None:
        raise AdaptorStrategyError("metric-rank/v1 requires the run metric; none is bound")
    outputs = [tuning_output(item) for item in items]
    stamped = [
        StampedMetricSpec(label=f"adaptor input {item.ref.port}:{item.ref.position}", spec=spec)
        for item, spec in zip(items, (output.metric_spec for output in outputs), strict=True)
    ]
    reconcile_metric_specs(stamped, bound=metric, bound_label="the run metric")
    scores: dict[int, float] = {}
    for index, output in enumerate(outputs):
        score = output.best_valid_formal_denoising_score
        if score is None:
            raise AdaptorStrategyError(
                "metric-rank/v1 received an item without a Health-valid score"
            )
        scores[index] = score
    order = MetricOrder(metric)
    entries = tuple(
        RankEntry(unit=i, ref=items[i].ref, value=value)
        for i, value in _stable_rank(scores, order.is_better)
    )
    ranking = Ranking(
        basis="metric", entries=entries, metric_id=metric.id, direction=order.direction
    )
    return Combined(combine_kind=strategy.kind, units=_whole_units(items), ranking=ranking)


def _field_rank(strategy: FieldRankCombine, items: tuple[AdaptorItem, ...]) -> Combined:
    if len(items) != 1:
        raise AdaptorStrategyError(
            f"field-rank/v1 ranks the entries of exactly one value; {len(items)} are admissible"
        )
    (item,) = items
    field = RANKABLE_FIELDS.get(item.contract)
    if field is None or field.item_field != strategy.field:
        raise AdaptorStrategyError(
            f"field-rank/v1 field {strategy.field!r} is not catalogued for {item.contract!r}"
        )
    parent = _whole_units(items)[0]
    entries = list(getattr(parent.value, field.list_field))
    units = tuple(
        Unit(
            value=entry,
            element_contract=f"{item.contract}:{field.list_field}",
            inputs=(item.ref.entry(field.list_field, index),),
            role="selected",
        )
        for index, entry in enumerate(entries)
    )
    # Entries without the field are unranked: kept by all/v1, never chosen by top-k/v1.
    values = {
        index: value
        for index, entry in enumerate(entries)
        if (value := getattr(entry, field.item_field)) is not None
    }
    sign = 1.0 if strategy.order == "descending" else -1.0
    ranking = Ranking(
        basis="field",
        entries=tuple(
            RankEntry(unit=i, ref=units[i].inputs[0], value=value)
            for i, value in _stable_rank(values, lambda a, b: sign * a > sign * b)
        ),
        provenance=field.provenance,
    )
    return Combined(
        combine_kind=strategy.kind,
        units=units,
        ranking=ranking,
        parent=parent,
        list_field=field.list_field,
    )


def _stable_rank(
    values: dict[int, float], better: Callable[[float, float], bool]
) -> list[tuple[int, float]]:
    """``(unit, value)`` best first; ties keep declared order (``sorted`` is stable)."""

    def compare(a: tuple[int, float], b: tuple[int, float]) -> int:
        return -1 if better(a[1], b[1]) else (1 if better(b[1], a[1]) else 0)

    return sorted(values.items(), key=cmp_to_key(compare))


def _value(item: AdaptorItem) -> BaseModel:
    if item.value is None:
        raise AdaptorStrategyError(
            f"adaptor input {item.ref.port}:{item.ref.position} has no value"
        )
    return item.value


def _one_contract(items: tuple[AdaptorItem, ...], kind: str) -> str:
    contracts = {item.contract for item in items}
    if len(contracts) != 1:
        raise AdaptorStrategyError(f"{kind} requires one input contract; got {sorted(contracts)}")
    return contracts.pop()


def _require_catalogued(catalogued: str | None, declared: str, kind: str, contract: str) -> None:
    if catalogued != declared:
        raise AdaptorStrategyError(
            f"{kind} field {declared!r} is not catalogued for {contract!r} (catalogued: {catalogued!r})"
        )


def _contribution_id(ref: AdaptorInputRef) -> str:
    return ref.source.node if isinstance(ref.source, ResultSource) else ref.source.binding
