"""Peak concurrent demand of a parallel run: the envelope a host ledger reserves (B3-4a).

Only declared capabilities run concurrently; two units may overlap only when no
dependency path joins them, so the peak of any quantity is a maximum-weight
antichain of the declared units in the graph's dependency order (paths through
adaptors and undeclared nodes count). An undeclared unit runs alone, so its
demand is the run's own serial declaration. Each quantity takes its own peak:
every value is reachable, though not necessarily in the same instant. Route
exclusivity is not used (conservative only when arms of one route can never
both run). Pure: no I/O. Contract: candidate-worker-contract.md, "Parallel dispatch".
"""

from collections import deque
from collections.abc import Callable, Mapping
from fractions import Fraction

from core.runtime_control.scheduling import HostBudget, ResourceRequest
from workflows.definition.fanout import execution_families

from .models import CandidateRunRequest
from .parallel_models import CapabilityResources


def declared_units(request: CandidateRunRequest) -> dict[str, CapabilityResources]:
    """Node id -> declared resources, for nodes whose capability has a declaration."""
    if request.parallel is None:
        raise ValueError("a serial request has no parallel units")
    table = {str(key): value for key, value in request.parallel.capabilities.items()}
    return {
        node.id: table[node.capability]
        for node in request.preview.document.definition.nodes
        if node.capability in table
    }


def dependency_ancestors(predecessors: Mapping[str, frozenset[str]]) -> dict[str, frozenset[str]]:
    closed: dict[str, frozenset[str]] = {}

    def visit(key: str) -> frozenset[str]:
        if key not in closed:
            direct = predecessors.get(key, frozenset())
            closed[key] = frozenset(direct).union(*(visit(item) for item in direct))
        return closed[key]

    for key in predecessors:
        visit(key)
    return closed


def max_weight_antichain(
    units: Mapping[str, Fraction], ancestors: Mapping[str, frozenset[str]]
) -> Fraction:
    """Largest total weight of units pairwise unjoined by a dependency path.

    Weighted Dilworth: the peak equals total weight minus the maximum flow from
    each unit's ``out`` copy (capacity = its weight) through every comparable
    successor's ``in`` copy (unbounded) to the sink (capacity = its weight).
    """
    keys = [key for key, weight in units.items() if weight > 0]
    source, sink = ("s",), ("t",)
    capacity: dict[tuple, dict[tuple, Fraction | None]] = {source: {}, sink: {}}
    for key in keys:
        capacity[source][("out", key)] = units[key]
        capacity.setdefault(("out", key), {})
        capacity.setdefault(("in", key), {})[sink] = units[key]
        capacity[sink].setdefault(("in", key), Fraction(0))
    for later in keys:
        for earlier in keys:
            if earlier in ancestors.get(later, frozenset()):
                capacity[("out", earlier)][("in", later)] = None  # unbounded
    return sum((units[key] for key in keys), Fraction(0)) - _max_flow(capacity, source, sink)


def _max_flow(capacity: dict[tuple, dict[tuple, Fraction | None]], source, sink) -> Fraction:
    """Edmonds-Karp on exact rationals; ``None`` capacity is unbounded."""
    flow: dict[tuple, dict[tuple, Fraction]] = {u: {} for u in capacity}

    def residual(u, v) -> Fraction | None:
        forward = capacity.get(u, {}).get(v, Fraction(0))
        used = flow[u].get(v, Fraction(0)) - flow.get(v, {}).get(u, Fraction(0))
        return None if forward is None else forward - used

    def neighbours(u):
        return set(capacity.get(u, {})) | {v for v in capacity if u in capacity[v]}

    total = Fraction(0)
    while True:
        parent: dict[tuple, tuple] = {source: source}
        queue = deque([source])
        while queue and sink not in parent:
            u = queue.popleft()
            for v in neighbours(u):
                room = residual(u, v)
                if v not in parent and (room is None or room > 0):
                    parent[v] = u
                    queue.append(v)
        if sink not in parent:
            return total
        path, v = [], sink
        while v != source:
            path.append((parent[v], v))
            v = parent[v]
        bottleneck = min(r for u, v in path if (r := residual(u, v)) is not None)
        for u, v in path:
            flow[u][v] = flow[u].get(v, Fraction(0)) + bottleneck
        total += bottleneck


class ParallelUnitTooLarge(ValueError):
    """One declared unit cannot fit the host budget even alone (typed refusal)."""


def require_units_fit(request: CandidateRunRequest, budget: HostBudget) -> None:
    """Refuse a declared unit that fits no GPU slot, host memory or CPU slots alone.

    This is the only parallel-specific refusal: anything larger than one unit is
    clamped (``envelope_request``) and merely runs with less concurrency.
    """
    by_capability = {node.id: node.capability for node in request.preview.document.definition.nodes}
    slot = max(budget.gpus, key=lambda item: item.ceiling.effective_gib, default=None)
    for node_id, item in declared_units(request).items():
        capability = by_capability[node_id]
        remedy = (
            f"lower {capability!r} in parallel.capabilities, or remove {capability!r} from it "
            "so its units run alone under the operation's resources declaration"
        )
        if item.gpu and item.vram_gib is not None:
            if slot is None:
                raise ParallelUnitTooLarge(
                    f"parallel unit {node_id!r} ({capability}) needs {item.vram_gib:.2f} GiB VRAM "
                    f"but the host budget declares no GPU slot; {remedy}"
                )
            if item.vram_gib > slot.ceiling.effective_gib:
                raise ParallelUnitTooLarge(
                    f"parallel unit {node_id!r} ({capability}) needs {item.vram_gib:.2f} GiB VRAM; "
                    f"the largest GPU slot {slot.uuid} holds {slot.ceiling.effective_gib:.2f} GiB; "
                    f"{remedy}"
                )
        if item.host_memory_gib > budget.host_memory_gib:
            raise ParallelUnitTooLarge(
                f"parallel unit {node_id!r} ({capability}) needs {item.host_memory_gib:.2f} GiB "
                f"host memory; the host budget declares {budget.host_memory_gib:.2f} GiB; {remedy}"
            )
        if item.cpu_slots > budget.cpu_slots:
            raise ParallelUnitTooLarge(
                f"parallel unit {node_id!r} ({capability}) needs {item.cpu_slots} CPU slots; "
                f"the host budget declares {budget.cpu_slots}; {remedy}"
            )


def envelope_request(
    request: CandidateRunRequest, serial: ResourceRequest, budget: HostBudget
) -> ResourceRequest:
    """The one reservation a parallel run takes: its peak, clamped to the host's capacity.

    Each quantity is the peak concurrent demand of the declared units, at least
    ``serial`` when a node is undeclared (such a unit runs alone under it), then
    clamped to what the budget can hold (VRAM to the largest slot's effective
    ceiling, memory, CPU slots and unit slots to the budget totals) but never
    below the largest single unit. Units that do not fit together then wait in
    FIFO order inside the grant: concurrency degrades, admission does not fail.
    Identity, wall time and the time-budget flag come from ``serial``. The GPU
    part is one slot (multi-GPU envelopes are later work).
    """
    require_units_fit(request, budget)
    units = declared_units(request)
    alone = len(units) < len(request.preview.document.definition.nodes)
    floor = serial if alone else None
    shape = execution_families(
        request.preview.document.definition, request.preview.execution_profile
    )
    ancestors = dependency_ancestors(dict(shape.predecessors))

    def peak(weight: Callable[[CapabilityResources], float]) -> float:
        return float(
            max_weight_antichain(
                {key: Fraction(weight(item)) for key, item in units.items()}, ancestors
            )
        )

    def single(weight: Callable[[CapabilityResources], float]) -> float:
        return max((weight(item) for item in units.values()), default=0.0)

    def clamped(weight: Callable[[CapabilityResources], float], name: str, capacity: float):
        least = max(single(weight), _floor(floor, name))
        return max(min(max(peak(weight), _floor(floor, name)), capacity), least)

    largest_slot = max((slot.ceiling.effective_gib for slot in budget.gpus), default=0.0)
    vram = clamped(lambda item: item.vram_gib or 0.0, "vram_gib", largest_slot)
    gpu = vram > 0
    return ResourceRequest(
        unit_id=serial.unit_id,
        dispatch_ordinal=serial.dispatch_ordinal,
        gpu_count=1 if gpu else 0,
        vram_gib=vram if gpu else None,
        vram_source="configured_cap" if gpu else None,
        host_memory_gib=clamped(
            lambda item: item.host_memory_gib, "host_memory_gib", budget.host_memory_gib
        ),
        cpu_slots=int(clamped(lambda item: item.cpu_slots, "cpu_slots", budget.cpu_slots)),
        wall_seconds=serial.wall_seconds,
        time_budgeted=serial.time_budgeted,
        unit_slots=int(max(min(peak(lambda item: 1), budget.max_concurrent_units), 1)),
    )


def _floor(serial: ResourceRequest | None, name: str) -> float:
    if serial is None:
        return 0.0
    return float(getattr(serial, name) or 0.0)
