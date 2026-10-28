"""Check declarations without loading referenced objects or executing protocols."""

from collections.abc import Mapping, Set

from .adaptor_validation import (
    Resolve,
    check_adaptor,
    check_adaptor_format,
    check_adaptor_source,
    output_contract,
)
from .catalog import CAPABILITIES, CONTRACTS, PROTOCOLS
from .models import (
    AdaptorRequest,
    AdaptorSource,
    AuthoredLoop,
    ExternalRequest,
    ExternalSource,
    JudgeStop,
    NodeInstance,
    NodePosition,
    NoImprovementStop,
    ProtocolRequest,
    ReusableWorkflowDefinition,
    SelectedSource,
    Source,
    WorkflowDefinition,
)
from .routes import route_entries, validate_routes


def validate_definition(definition: WorkflowDefinition | ReusableWorkflowDefinition) -> None:
    check_adaptor_format(definition)
    facts, order = dependency_graph(definition)
    if definition.loop is not None:
        nodes = {node.id: node for node in definition.nodes}
        feedback = definition.loop.feedback
        source, target = nodes.get(feedback.source.node), nodes.get(feedback.target)
        if (
            source is None
            or source.capability != "tuning"
            or target is None
            or target.capability != "interpretation"
        ):
            raise ValueError("loop feedback requires declared tuning and interpretation nodes")
        validate_stop_conditions(definition.loop)
    # Routes are checked after loop node existence, so their errors never mask it.
    validate_routes(definition, facts, order)


def validate_stop_conditions(loop: AuthoredLoop) -> None:
    """At most one condition per kind; each must be reachable before the final limit."""
    kinds = [condition.kind for condition in loop.stop_conditions]
    if len(set(kinds)) != len(kinds):
        raise ValueError("loop declares more than one stop condition of the same kind")
    for condition in loop.stop_conditions:
        if (
            isinstance(condition, NoImprovementStop)
            and condition.completed_bodies >= loop.final_iteration
        ):
            raise ValueError("no_improvement completed_bodies must be below final_iteration")
        # The final boundary is never judged, so a judge first consulted there never runs.
        if (
            isinstance(condition, JudgeStop)
            and condition.min_completed_bodies >= loop.final_iteration
        ):
            raise ValueError("judge min_completed_bodies must be below final_iteration")


def predecessor_facts(
    definition: WorkflowDefinition | ReusableWorkflowDefinition,
) -> tuple[tuple[str, frozenset[str]], ...]:
    """Validate every argument and return immutable scheduling dependencies."""
    return dependency_graph(definition)[0]


def dependency_graph(
    definition: WorkflowDefinition | ReusableWorkflowDefinition,
) -> tuple[tuple[tuple[str, frozenset[str]], ...], tuple[str, ...]]:
    """Validated dependencies (data and route control edges) and one topological order.

    Adaptors share the node namespace and join the same dependency graph.
    """
    externals = {item.id: item for item in definition.externals}
    nodes = {node.id: node for node in definition.nodes}
    adaptors = {adaptor.id: adaptor for adaptor in definition.adaptors}
    if len(externals) != len(definition.externals) or len(nodes) != len(definition.nodes):
        raise ValueError("External and node IDs must each be unique")
    if len(adaptors) != len(definition.adaptors) or adaptors.keys() & nodes.keys():
        raise ValueError("Adaptor IDs must be unique and distinct from node IDs")
    for external in externals.values():
        if external.contract not in CONTRACTS:
            raise ValueError(f"Unsupported external contract: {external.contract}")
    for node in nodes.values():
        if node.capability not in CAPABILITIES:
            raise ValueError(f"Unsupported capability: {node.capability}")

    dependencies: dict[str, set[str]] = {key: set() for key in (*nodes, *adaptors)}
    contracts = _SourceContracts(definition)
    # Adaptors first, so a consumer never reports a symptom of an invalid adaptor.
    for adaptor in adaptors.values():
        check_adaptor(adaptor, contracts.resolver(dependencies[adaptor.id]))
    for node in nodes.values():
        _check_request(node, contracts.resolver(dependencies[node.id]))

    # A route target waits for its branch source's decision: a control edge, so a
    # route can never create a cycle or target an ancestor of its own source.
    for branch in definition.routes:
        for target in (item for entry in route_entries(branch) for item in entry):
            if branch.source.node not in nodes or target not in nodes:
                raise ValueError(f"route {branch.id}: Unknown route node")
            dependencies[target].add(branch.source.node)

    order = topological_order(dependencies)
    return tuple((node, frozenset(sources)) for node, sources in dependencies.items()), order


class _SourceContracts:
    """Resolve bound sources to exact contracts, recording each consumer's dependencies."""

    def __init__(self, definition: WorkflowDefinition | ReusableWorkflowDefinition) -> None:
        self.externals = {item.id: item.contract for item in definition.externals}
        self.outputs = {node.id: CAPABILITIES[node.capability].output for node in definition.nodes}
        self.adaptors = {adaptor.id: adaptor for adaptor in definition.adaptors}

    def resolver(self, dependencies: set[str]) -> Resolve:
        return lambda source, context: self.resolve(source, context, dependencies)

    def resolve(self, source: Source, context: str, dependencies: set[str]) -> str:
        if isinstance(source, ExternalSource):
            if source.binding not in self.externals:
                raise ValueError(f"{context}: Unknown external binding: {source.binding}")
            return self.externals[source.binding]
        if isinstance(source, AdaptorSource):
            adaptor = self.adaptors.get(source.adaptor)
            if adaptor is None:
                raise ValueError(f"{context}: Unknown adaptor: {source.adaptor}")
            check_adaptor_source(adaptor, source, context)
            dependencies.add(adaptor.id)
            return output_contract(adaptor)
        if isinstance(source, SelectedSource):
            if unknown := {item.node for item in source.candidates} - self.outputs.keys():
                raise ValueError(f"{context}: Unknown merge candidates: {sorted(unknown)}")
            outputs = {self.outputs[item.node] for item in source.candidates}
            if len(outputs) != 1:
                raise ValueError(f"{context}: merge candidates differ in contract")
            dependencies.update(item.node for item in source.candidates)
            return outputs.pop()
        if source.node not in self.outputs:
            raise ValueError(f"{context}: Unknown source node: {source.node}")
        dependencies.add(source.node)
        return self.outputs[source.node]


def _check_request(node: NodeInstance, resolve: Resolve) -> None:
    expected = CAPABILITIES[node.capability].input
    request = node.request
    if isinstance(request, ExternalRequest):
        actual = resolve(ExternalSource(binding=request.binding), node.id)
    elif isinstance(request, AdaptorRequest):
        actual = resolve(request.source, node.id)
    else:
        _check_protocol_arguments(node.id, expected, request, resolve)
        return
    if actual != expected:
        raise ValueError(f"{node.id}: request requires {expected}, got {actual}")


def _check_protocol_arguments(
    node_id: str, expected: str, request: ProtocolRequest, resolve: Resolve
) -> None:
    if request.protocol not in PROTOCOLS:
        raise ValueError(f"{node_id}: Unsupported protocol: {request.protocol}")
    protocol = PROTOCOLS[request.protocol]
    if protocol.output != expected:
        raise ValueError(f"{node_id}: protocol does not produce {expected}")
    arguments = {arg.name: arg for arg in request.arguments}
    declared = {arg.name: arg for arg in protocol.arguments}
    if len(arguments) != len(request.arguments):
        raise ValueError(f"{node_id}: duplicate protocol arguments")
    if unknown := arguments.keys() - declared.keys():
        raise ValueError(f"{node_id}: unknown protocol arguments: {sorted(unknown)}")
    missing = [arg.name for arg in protocol.arguments if arg.required and arg.name not in arguments]
    if missing:
        raise ValueError(f"{node_id}: missing protocol arguments: {missing}")
    for name, argument in arguments.items():
        actual = resolve(argument.source, f"{node_id}.{name}")
        if actual != declared[name].contract:
            raise ValueError(f"{node_id}.{name}: requires {declared[name].contract}, got {actual}")


def topological_order(dependencies: Mapping[str, Set[str]]) -> tuple[str, ...]:
    """Kahn's algorithm avoids recursion depth dependence on declaration size."""
    order: list[str] = []
    pending = dict(dependencies)
    while pending:
        ready = [node for node, sources in pending.items() if not sources]
        if not ready:
            raise ValueError("Cycles and feedback are unsupported in this declaration version")
        order.extend(ready)
        done = frozenset(ready)
        pending = {node: sources - done for node, sources in pending.items() if node not in done}
    return tuple(order)


def validate_positions(
    nodes: tuple[NodeInstance, ...], positions: tuple[NodePosition, ...]
) -> None:
    """One layout-reference check for both declaration formats."""
    node_ids = {node.id for node in nodes}
    seen: set[str] = set()
    for position in positions:
        if position.node not in node_ids or position.node in seen:
            raise ValueError(f"Unknown or duplicate layout node: {position.node}")
        seen.add(position.node)
