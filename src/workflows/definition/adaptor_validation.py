"""Static checks for inert adaptor declarations: the B6 validation table.

Nothing here admits items or runs a strategy. The deterministic strategy core
(``workflows.adaptors``) re-checks at run time every rule it relies on; this module
refuses the same declarations earlier, with one owner per rule.
"""

from collections.abc import Callable

from .adaptor_strategies import (
    AllSelect,
    CollectCombine,
    ConcatItemsCombine,
    FieldRankCombine,
    FirstAdmissibleSelect,
    MetricRankCombine,
    PassCombine,
    SingleDistribute,
    SplitItemsDistribute,
    ThresholdSelect,
    TopKSelect,
    derive_cardinality,
    incompatible_pair,
)
from .catalog import (
    COLLECTION_CONTRACTS,
    CONTRACTS,
    METRIC_SCORED_CONTRACTS,
    RANKABLE_FIELDS,
    SPLITTABLE_ITEMS,
)
from .models import (
    AdaptorInstance,
    AdaptorRequest,
    AdaptorSource,
    InputPort,
    PortBinding,
    ProtocolRequest,
    ReusableWorkflowDefinition,
    Source,
    WorkflowDefinition,
)

ADAPTOR_FORMAT = "siderius.adaptors/v1"
# Resolves one bound source to its exact contract (recording the dependency).
Resolve = Callable[[Source, str], str]


def check_adaptor_format(definition: WorkflowDefinition | ReusableWorkflowDefinition) -> None:
    """Adaptor use and ``adaptor_format`` must coincide; neither changes identity silently."""
    used = bool(definition.adaptors) or any(
        isinstance(node.request, AdaptorRequest)
        or (
            isinstance(node.request, ProtocolRequest)
            and any(isinstance(arg.source, AdaptorSource) for arg in node.request.arguments)
        )
        for node in definition.nodes
    )
    if used and definition.adaptor_format is None:
        raise ValueError(f"adaptor declarations require adaptor_format={ADAPTOR_FORMAT!r}")
    if not used and definition.adaptor_format is not None:
        raise ValueError("adaptor_format is declared but no adaptor is used")


def output_contract(adaptor: AdaptorInstance) -> str:
    """Derived, never authored: ``collect/v1`` yields the element contract's catalogued
    collection; every other admitted kind preserves the element contract."""
    element = adaptor.inputs[0].contract
    if isinstance(adaptor.combine, CollectCombine):
        return COLLECTION_CONTRACTS[element]  # _check_combine refuses an uncatalogued one
    return element


def output_count(adaptor: AdaptorInstance) -> int | None:
    """Number of indexed outputs, or ``None`` for the one unindexed ``single/v1`` output."""
    distribute = adaptor.distribute
    return None if isinstance(distribute, SingleDistribute) else distribute.count


def check_adaptor_source(adaptor: AdaptorInstance, source: AdaptorSource, context: str) -> None:
    count = output_count(adaptor)
    if count is None and source.index is not None:
        raise ValueError(f"{context}: single/v1 adaptor {adaptor.id} has no indexed outputs")
    if count is not None and (source.index is None or source.index >= count):
        raise ValueError(f"{context}: adaptor {adaptor.id} output index must be below {count}")


def check_adaptor(adaptor: AdaptorInstance, resolve: Resolve) -> None:
    """Ports, bindings and the COMBINE/SELECT/DISTRIBUTE combination table."""
    context = f"adaptor {adaptor.id}"
    bindings = _bindings(adaptor, context)
    for port in adaptor.inputs:
        _check_port(port, bindings[port.name], resolve, f"{context}.{port.name}")
    if not any(binding.sources for binding in adaptor.bindings):
        raise ValueError(f"{context}: binds no source")
    if len({port.contract for port in adaptor.inputs}) != 1:
        raise ValueError(f"{context}: deterministic strategies require one input contract")
    try:
        _check_strategies(adaptor)
    except ValueError as error:
        raise ValueError(f"{context}: {error}") from error


def _bindings(adaptor: AdaptorInstance, context: str) -> dict[str, PortBinding]:
    ports = {port.name for port in adaptor.inputs}
    bindings = {binding.port: binding for binding in adaptor.bindings}
    if len(ports) != len(adaptor.inputs) or len(bindings) != len(adaptor.bindings):
        raise ValueError(f"{context}: duplicate input ports or port bindings")
    if bindings.keys() != ports:
        raise ValueError(f"{context}: every input port requires exactly one binding")
    return bindings


def _check_port(port: InputPort, binding: PortBinding, resolve: Resolve, context: str) -> None:
    if port.contract not in CONTRACTS:
        raise ValueError(f"{context}: Unsupported port contract: {port.contract}")
    count = len(binding.sources)
    most = 1 if port.cardinality == "one" else port.max_items
    if count < port.min_items or (most is not None and count > most):
        raise ValueError(f"{context}: {count} sources are outside the declared item bounds")
    for position, source in enumerate(binding.sources):
        actual = resolve(source, f"{context}[{position}]")
        if actual != port.contract:
            raise ValueError(f"{context}[{position}]: requires {port.contract}, got {actual}")


def _capacity(adaptor: AdaptorInstance) -> int:
    """Most items the ports can hold: the bound sources (topology is static, B6-D6)."""
    return sum(len(binding.sources) for binding in adaptor.bindings)


def _check_strategies(adaptor: AdaptorInstance) -> None:
    combine, select, distribute = adaptor.combine, adaptor.select, adaptor.distribute
    contract = adaptor.inputs[0].contract  # the element contract (one per adaptor)
    if (incompatible := incompatible_pair(combine, distribute)) is not None:
        raise ValueError(incompatible)
    _check_combine(adaptor, contract)
    if isinstance(select, FirstAdmissibleSelect) and not isinstance(combine, PassCombine):
        raise ValueError(f"first-admissible/v1 requires pass/v1, not {combine.kind}")
    if isinstance(select, TopKSelect | ThresholdSelect) and not isinstance(
        combine, MetricRankCombine | FieldRankCombine
    ):
        raise ValueError(f"{select.kind} requires a ranking combine, not {combine.kind}")
    if isinstance(select, ThresholdSelect) and not (
        select.basis == "metric" and isinstance(combine, MetricRankCombine)
    ):
        raise ValueError(f"threshold/v1 basis {select.basis!r} cannot read {combine.kind}")
    if isinstance(distribute, SplitItemsDistribute) and (
        SPLITTABLE_ITEMS.get(contract) != distribute.field
    ):
        raise ValueError(f"split-items/v1 field {distribute.field!r} is not catalogued")
    bound = derive_cardinality(select, distribute)
    _check_value_count(adaptor, bound.max)


def _check_combine(adaptor: AdaptorInstance, contract: str) -> None:
    combine = adaptor.combine
    if isinstance(combine, CollectCombine) and contract not in COLLECTION_CONTRACTS:
        # A collection joins the catalogue together with its consumer protocol.
        raise ValueError(f"collect/v1 has no catalogued collection contract for {contract}")
    if isinstance(combine, ConcatItemsCombine) and SPLITTABLE_ITEMS.get(contract) != combine.field:
        raise ValueError(f"concat-items/v1 field {combine.field!r} is not catalogued")
    if isinstance(combine, MetricRankCombine) and contract not in METRIC_SCORED_CONTRACTS:
        raise ValueError(f"metric-rank/v1 cannot rank {contract}")
    if isinstance(combine, FieldRankCombine):
        rankable = RANKABLE_FIELDS.get(contract)
        if rankable is None or rankable.item_field != combine.field:
            raise ValueError(f"field-rank/v1 field {combine.field!r} is not catalogued")
        if _capacity(adaptor) != 1:
            raise ValueError("field-rank/v1 ranks the entries of exactly one bound value")


def _check_value_count(adaptor: AdaptorInstance, bound_max: int) -> None:
    """SELECT must never keep more values (or list entries) than DISTRIBUTE accepts.

    ``derive_cardinality`` caps its bound at ``k`` and ignores the source count, so
    ``k`` is checked against DISTRIBUTE alone and ``all``/``threshold`` against capacity.
    """
    select, distribute = adaptor.select, adaptor.distribute
    if isinstance(adaptor.combine, FieldRankCombine):
        # Entries of one value: only split-items/v1 distributes them, one per output.
        if isinstance(select, TopKSelect) and isinstance(distribute, SplitItemsDistribute):
            if select.k > distribute.count:
                raise ValueError(f"top-k/v1 k={select.k} exceeds split-items/v1 count")
            if distribute.on_short == "fail" and distribute.count > select.k:
                # At most k entries survive, so a fail policy could never fill count outputs.
                raise ValueError(
                    f"split-items/v1 count={distribute.count} with on_short='fail' can never "
                    f"be filled by top-k/v1 k={select.k}"
                )
        return
    if not isinstance(adaptor.combine, PassCombine | MetricRankCombine):
        return  # one combined value
    accepted = derive_cardinality(AllSelect(), distribute).max
    if isinstance(select, TopKSelect) and select.k > accepted:
        raise ValueError(f"top-k/v1 k={select.k} exceeds the {accepted} {distribute.kind} accepts")
    if isinstance(select, AllSelect | ThresholdSelect) and _capacity(adaptor) > bound_max:
        raise ValueError(
            f"{select.kind} may keep {_capacity(adaptor)} values; {distribute.kind} "
            f"accepts at most {bound_max}"
        )
