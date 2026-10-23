"""Pure supported-candidate shape check shared by preview and resolution."""

from .models import (
    ExternalRequest,
    ProtocolRequest,
    ResultSource,
    ReusableWorkflowDefinition,
    WorkflowDefinition,
)


def candidate_nodes(definition: WorkflowDefinition | ReusableWorkflowDefinition) -> dict[str, str]:
    nodes = {node.capability: node for node in definition.nodes}
    if len(definition.nodes) != 3 or set(nodes) != {"proposal", "implementation", "validation"}:
        raise ValueError(
            "Unsupported preview: requires exactly one proposal, implementation and validation"
        )
    if not isinstance(nodes["proposal"].request, ExternalRequest):
        raise ValueError("Unsupported preview: proposal requires an external request")
    for role, upstream, protocol in (
        ("implementation", "proposal", "proposal-to-implementation"),
        ("validation", "implementation", "implementation-to-validation"),
    ):
        node = nodes[role]
        request = node.request
        if not isinstance(request, ProtocolRequest) or request.protocol != protocol:
            raise ValueError(f"Unsupported preview: {node.id} requires {protocol}")
        source = next(arg.source for arg in request.arguments if arg.name == "output")
        if not isinstance(source, ResultSource) or source.node != nodes[upstream].id:
            raise ValueError(f"Unsupported preview: {node.id}.output must use {nodes[upstream].id}")
    return {role: node.id for role, node in nodes.items()}
