"""Pure supported-candidate shape check shared by preview and resolution."""

from .models import (
    AdaptorSource,
    ExternalRequest,
    ExternalSource,
    ProtocolRequest,
    Request,
    ResultSource,
    ReusableWorkflowDefinition,
    WorkflowDefinition,
)

ROUTING_NOT_ADMITTED = (
    "conditional routing is declared but this execution profile does not admit it"
)


ADAPTORS_NOT_ADMITTED = "adaptors are declared but this execution profile does not admit them"


def refuse_declaration_only(
    definition: WorkflowDefinition | ReusableWorkflowDefinition,
    *,
    admits_adaptors: bool = False,
    admits_routes: bool = False,
) -> None:
    """Routes and adaptors run only where a profile admits them.

    Only the adaptor profiles (``fanout.ADAPTOR_PROFILES``: selection, routed and
    the two literature profiles) pass ``admits_adaptors=True``; only the routed
    profile passes ``admits_routes=True``. The adaptor format gate guarantees
    ``adaptor_format`` is set iff an adaptor is used.
    """
    if definition.routes and not admits_routes:
        raise ValueError(ROUTING_NOT_ADMITTED)
    if definition.adaptor_format is not None and not admits_adaptors:
        raise ValueError(ADAPTORS_NOT_ADMITTED)


def candidate_nodes(definition: WorkflowDefinition | ReusableWorkflowDefinition) -> dict[str, str]:
    refuse_declaration_only(definition)
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
        check_tuning_edge(nodes["tuning"].request, nodes["proposal"].id, nodes["validation"].id)
    return {role: node.id for role, node in nodes.items()}


def check_tuning_edge(request: Request, proposal: str, validation: str | AdaptorSource) -> None:
    """One tuner consumes the selected candidate lineage and explicit native settings.

    ``validation`` names the validator node, or the adaptor output that selects one.
    """
    if (
        not isinstance(request, ProtocolRequest)
        or request.protocol != "validated-candidate-to-tuning"
    ):
        raise ValueError("tuning requires validated-candidate-to-tuning")
    arguments = {arg.name: arg.source for arg in request.arguments}
    expected = {
        "proposal": ResultSource(node=proposal),
        "validation": ResultSource(node=validation) if isinstance(validation, str) else validation,
    }
    for role, source in expected.items():
        if arguments[role] != source:
            raise ValueError(f"tuning.{role} must use this candidate's {role}")
    if not isinstance(arguments["settings"], ExternalSource):
        raise ValueError("tuning.settings requires an external settings file")
