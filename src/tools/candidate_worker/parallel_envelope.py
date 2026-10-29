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

from core.runtime_control.scheduling import ResourceRequest
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


def envelope_request(request: CandidateRunRequest, serial: ResourceRequest) -> ResourceRequest:
    """The one reservation a parallel run takes: the per-quantity peak.

    ``serial`` is the operation's own declaration and the floor of every
    quantity (undeclared units run alone under it; the run never reserves less
    than it declared). Identity, wall time and the time-budget flag come from it. The GPU part is one slot holding
    the peak VRAM sum, so every unit always fits its own envelope (multi-GPU
    envelopes are later work).
    """
    units = declared_units(request)
    # Never below the run's own declaration: a reservation smaller than what the
    # run is declared to use would undercount it beside other runs.
    floor = serial
    shape = execution_families(
        request.preview.document.definition, request.preview.execution_profile
    )
    ancestors = dependency_ancestors(dict(shape.predecessors))

    def peak(weight: Callable[[CapabilityResources], float]) -> Fraction:
        return max_weight_antichain(
            {key: Fraction(weight(item)) for key, item in units.items()}, ancestors
        )

    vram = max(float(peak(lambda item: item.vram_gib or 0.0)), _floor(floor, "vram_gib"))
    gpu = vram > 0
    return ResourceRequest(
        unit_id=serial.unit_id,
        dispatch_ordinal=serial.dispatch_ordinal,
        gpu_count=1 if gpu else 0,
        vram_gib=vram if gpu else None,
        vram_source="configured_cap" if gpu else None,
        host_memory_gib=max(
            float(peak(lambda item: item.host_memory_gib)), _floor(floor, "host_memory_gib")
        ),
        cpu_slots=max(int(peak(lambda item: item.cpu_slots)), int(_floor(floor, "cpu_slots"))),
        wall_seconds=serial.wall_seconds,
        time_budgeted=serial.time_budgeted,
        unit_slots=max(int(peak(lambda item: 1)), 1),
    )


def _floor(serial: ResourceRequest | None, name: str) -> float:
    if serial is None:
        return 0.0
    return float(getattr(serial, name) or 0.0)
