"""Pure supported-candidate shape check shared by preview and resolution."""

from .models import (
    ExternalRequest,
    ExternalSource,
    ProtocolRequest,
    ResultSource,
    ReusableWorkflowDefinition,
    WorkflowDefinition,
)


def candidate_nodes(definition: WorkflowDefinition | ReusableWorkflowDefinition) -> dict[str, str]:
    nodes = {node.capability: node for node in definition.nodes}
    expected = {"proposal", "implementation", "validation"}
    if set(nodes) not in (expected, expected | {"tuning"}) or len(nodes) != len(definition.nodes):
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
    if "tuning" in nodes:
        if isinstance(definition, ReusableWorkflowDefinition):
            raise ValueError(
                "four-stage native training requires schema version 1; reusable preparation is unsupported"
            )
        request = nodes["tuning"].request
        if (
            not isinstance(request, ProtocolRequest)
            or request.protocol != "validated-candidate-to-tuning"
        ):
            raise ValueError("tuning requires validated-candidate-to-tuning")
        arguments = {arg.name: arg.source for arg in request.arguments}
        for role in ("proposal", "validation"):
            source = arguments[role]
            if not isinstance(source, ResultSource) or source.node != nodes[role].id:
                raise ValueError(f"tuning.{role} must use this candidate's {role}")
        if not isinstance(arguments["settings"], ExternalSource):
            raise ValueError("tuning.settings requires an external settings file")
    return {role: node.id for role, node in nodes.items()}
