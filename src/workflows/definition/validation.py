"""Check declarations without loading referenced objects or executing protocols."""

from collections.abc import Mapping, Set
from typing import TYPE_CHECKING

from .catalog import CAPABILITIES, CONTRACTS, PROTOCOLS
from .routes import route_entries, validate_routes

if TYPE_CHECKING:
    from .models import (
        AuthoredLoop,
        NodeInstance,
        NodePosition,
        ReusableWorkflowDefinition,
        WorkflowDefinition,
    )


def validate_definition(definition: "WorkflowDefinition | ReusableWorkflowDefinition") -> None:
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


def validate_stop_conditions(loop: "AuthoredLoop") -> None:
    """At most one condition per kind; each must be reachable before the final limit."""
    from .models import NoImprovementStop

    kinds = [condition.kind for condition in loop.stop_conditions]
    if len(set(kinds)) != len(kinds):
        raise ValueError("loop declares more than one stop condition of the same kind")
    for condition in loop.stop_conditions:
        if (
            isinstance(condition, NoImprovementStop)
            and condition.completed_bodies >= loop.final_iteration
        ):
            raise ValueError("no_improvement completed_bodies must be below final_iteration")


def predecessor_facts(
    definition: "WorkflowDefinition | ReusableWorkflowDefinition",
) -> tuple[tuple[str, frozenset[str]], ...]:
    """Validate every argument and return immutable scheduling dependencies."""
    return dependency_graph(definition)[0]


def dependency_graph(
    definition: "WorkflowDefinition | ReusableWorkflowDefinition",
) -> tuple[tuple[tuple[str, frozenset[str]], ...], tuple[str, ...]]:
    """Validated dependencies (data and route control edges) and one topological order."""
    from .models import ExternalRequest, ExternalSource, SelectedSource

    externals = {item.id: item for item in definition.externals}
    nodes = {node.id: node for node in definition.nodes}
    if len(externals) != len(definition.externals) or len(nodes) != len(definition.nodes):
        raise ValueError("External and node IDs must each be unique")
    for external in externals.values():
        if external.contract not in CONTRACTS:
            raise ValueError(f"Unsupported external contract: {external.contract}")
    for node in nodes.values():
        if node.capability not in CAPABILITIES:
            raise ValueError(f"Unsupported capability: {node.capability}")

    dependencies: dict[str, set[str]] = {key: set() for key in nodes}

    def external_contract(binding: str, context: str) -> str:
        if binding not in externals:
            raise ValueError(f"{context}: Unknown external binding: {binding}")
        return externals[binding].contract

    for node in nodes.values():
        expected = CAPABILITIES[node.capability].input
        request = node.request
        if isinstance(request, ExternalRequest):
            actual = external_contract(request.binding, node.id)
            if actual != expected:
                raise ValueError(f"{node.id}: request requires {expected}, got {actual}")
            continue
        if request.protocol not in PROTOCOLS:
            raise ValueError(f"{node.id}: Unsupported protocol: {request.protocol}")
        protocol = PROTOCOLS[request.protocol]
        if protocol.output != expected:
            raise ValueError(f"{node.id}: protocol does not produce {expected}")
        arguments = {arg.name: arg for arg in request.arguments}
        declared = {arg.name: arg for arg in protocol.arguments}
        if len(arguments) != len(request.arguments):
            raise ValueError(f"{node.id}: duplicate protocol arguments")
        if unknown := arguments.keys() - declared.keys():
            raise ValueError(f"{node.id}: unknown protocol arguments: {sorted(unknown)}")
        missing = [
            arg.name for arg in protocol.arguments if arg.required and arg.name not in arguments
        ]
        if missing:
            raise ValueError(f"{node.id}: missing protocol arguments: {missing}")
        for name, argument in arguments.items():
            source = argument.source
            if isinstance(source, ExternalSource):
                actual = external_contract(source.binding, f"{node.id}.{name}")
            elif isinstance(source, SelectedSource):
                if unknown := {item.node for item in source.candidates} - nodes.keys():
                    raise ValueError(
                        f"{node.id}.{name}: Unknown merge candidates: {sorted(unknown)}"
                    )
                outputs = {
                    CAPABILITIES[nodes[item.node].capability].output for item in source.candidates
                }
                if len(outputs) != 1:
                    raise ValueError(f"{node.id}.{name}: merge candidates differ in contract")
                actual = outputs.pop()
                dependencies[node.id].update(item.node for item in source.candidates)
            else:
                if source.node not in nodes:
                    raise ValueError(f"{node.id}.{name}: Unknown source node: {source.node}")
                actual = CAPABILITIES[nodes[source.node].capability].output
                dependencies[node.id].add(source.node)
            if actual != declared[name].contract:
                raise ValueError(
                    f"{node.id}.{name}: requires {declared[name].contract}, got {actual}"
                )

    # A route target waits for its branch source's decision: a control edge, so a
    # route can never create a cycle or target an ancestor of its own source.
    for branch in definition.routes:
        for target in (item for entry in route_entries(branch) for item in entry):
            if branch.source.node not in nodes or target not in nodes:
                raise ValueError(f"route {branch.id}: Unknown route node")
            dependencies[target].add(branch.source.node)

    order = topological_order(dependencies)
    return tuple((node, frozenset(sources)) for node, sources in dependencies.items()), order


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
    nodes: tuple["NodeInstance", ...], positions: tuple["NodePosition", ...]
) -> None:
    """One layout-reference check for both declaration formats."""
    node_ids = {node.id for node in nodes}
    seen: set[str] = set()
    for position in positions:
        if position.node not in node_ids or position.node in seen:
            raise ValueError(f"Unknown or duplicate layout node: {position.node}")
        seen.add(position.node)
