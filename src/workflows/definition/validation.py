"""Check declarations without loading referenced objects or executing protocols."""

from typing import TYPE_CHECKING

from .catalog import CAPABILITIES, CONTRACTS, PROTOCOLS

if TYPE_CHECKING:
    from .models import NodeInstance, NodePosition, ReusableWorkflowDefinition, WorkflowDefinition


def validate_definition(definition: "WorkflowDefinition | ReusableWorkflowDefinition") -> None:
    from .models import ExternalRequest, ExternalSource

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
            else:
                if source.node not in nodes:
                    raise ValueError(f"{node.id}.{name}: Unknown source node: {source.node}")
                actual = CAPABILITIES[nodes[source.node].capability].output
                dependencies[node.id].add(source.node)
            if actual != declared[name].contract:
                raise ValueError(
                    f"{node.id}.{name}: requires {declared[name].contract}, got {actual}"
                )

    # Kahn's algorithm avoids recursion depth dependence on declaration size.
    pending = dict(dependencies)
    while pending:
        ready = {node for node, sources in pending.items() if not sources}
        if not ready:
            raise ValueError("Cycles and feedback are unsupported in this declaration version")
        pending = {node: sources - ready for node, sources in pending.items() if node not in ready}


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
