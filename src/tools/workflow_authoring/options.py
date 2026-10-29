"""GUI choices derive exclusively from the native typed catalog."""

from tools.candidate_prepare.resolution import managed_argument_roles, managed_request_supported
from workflows.definition import (
    AuthoredWorkflowDocument,
    ExternalRequest,
    ExternalSource,
    ManagedCandidateBinding,
    ProtocolRequest,
    ResultSource,
    ReusableWorkflowDocument,
)
from workflows.definition.catalog import CAPABILITIES, CONTRACTS, PROTOCOLS

from .capability_guide import catalog_guide, producers
from .models import (
    BindingChoice,
    BindingOptions,
    CatalogArgument,
    CatalogEntry,
    ManagedRole,
    NativeContract,
    NodeCatalog,
    PendingNode,
    PortChoice,
    PortInventoryEntry,
    ProtocolMapping,
)


def contract_info(contract_id: str) -> NativeContract:
    return NativeContract(id=contract_id, native_type=CONTRACTS[contract_id])


def port_choices(
    document: AuthoredWorkflowDocument, contract_id: str, results: bool
) -> tuple[PortChoice, ...]:
    """Declared externals (and node results) whose catalog contract matches exactly."""
    definition = document.definition
    externals = tuple(
        PortChoice(
            label=item.id,
            source=ExternalSource(binding=item.id),
            contract=contract_info(item.contract),
        )
        for item in definition.externals
        if item.contract == contract_id
    )
    nodes = tuple(
        PortChoice(
            label=item.id + ".result",
            source=ResultSource(node=item.id),
            contract=contract_info(CAPABILITIES[item.capability].output),
        )
        for item in definition.nodes
        if CAPABILITIES[item.capability].output == contract_id
    )
    return externals + (nodes if results else ())


def framework_supplied(
    document: AuthoredWorkflowDocument, capability: str, argument: str | None, source
) -> bool:
    """Whether a bound socket is a managed input that candidate preparation generates."""
    if not isinstance(document, ReusableWorkflowDocument) or not isinstance(source, ExternalSource):
        return False
    external = next(
        (item for item in document.definition.externals if item.id == source.binding), None
    )
    if not isinstance(external, ManagedCandidateBinding):
        return False
    profile = document.execution_profile
    if argument is None:
        return managed_request_supported(profile, capability, external.contract)
    return (external.contract, argument) in managed_argument_roles(profile)


def managed_roles(document: AuthoredWorkflowDocument | None) -> tuple[ManagedRole, ...]:
    """Required inputs a new node gets as managed bindings (reusable documents only).

    Required protocol arguments in a managed argument role, and managed request routes;
    optional managed roles stay the author's choice.
    """
    if not isinstance(document, ReusableWorkflowDocument):
        return ()
    profile = document.execution_profile
    roles = managed_argument_roles(profile)
    required = {
        (item.contract, item.name)
        for protocol in PROTOCOLS.values()
        for item in protocol.arguments
        if item.required
    }
    requests = {
        (capability.input, None)
        for name, capability in CAPABILITIES.items()
        if managed_request_supported(profile, name, capability.input)
        # Managed literature also needs explicit literature_settings: the author's choice.
        and capability.input != "literature.input"
    }
    return tuple(
        ManagedRole(contract=contract, argument=argument)
        for contract, argument in sorted(roles & required) + sorted(requests)
    )


def binding_projection(
    document: AuthoredWorkflowDocument,
    choices_from: AuthoredWorkflowDocument | None = None,
) -> tuple[tuple[BindingOptions, ...], tuple[PortInventoryEntry, ...]]:
    """Project catalog ports and preserve the legacy bound-option wire shape/order.

    ``choices_from`` (default ``document``) supplies the offered sources, e.g. a
    node draft projection that adds pending nodes and new externals.
    """
    definition = document.definition

    def choices(contract_id: str, results: bool) -> tuple[PortChoice, ...]:
        return port_choices(choices_from or document, contract_id, results)

    inventory: list[PortInventoryEntry] = []
    for node in definition.nodes:
        capability = CAPABILITIES[node.capability]
        if isinstance(node.request, ExternalRequest):
            inventory.append(
                PortInventoryEntry(
                    node=node.id,
                    argument=None,
                    choices=choices(capability.input, False),
                    socket_contract=contract_info(capability.input),
                    required=True,
                    bound=True,
                    source=ExternalSource(binding=node.request.binding),
                    node_input_contract=contract_info(capability.input),
                    node_output_contract=contract_info(capability.output),
                    protocol_mapping=None,
                    framework_supplied=framework_supplied(
                        choices_from or document,
                        node.capability,
                        None,
                        ExternalSource(binding=node.request.binding),
                    ),
                )
            )
        else:
            request = node.request
            assert isinstance(request, ProtocolRequest)
            protocol = PROTOCOLS[request.protocol]
            bound_arguments = {item.name: item for item in request.arguments}
            mapping = ProtocolMapping(
                id=request.protocol,
                owner=protocol.owner,
                output_contract=contract_info(protocol.output),
            )
            for argument_contract in protocol.arguments:
                argument = bound_arguments.get(argument_contract.name)
                inventory.append(
                    PortInventoryEntry(
                        node=node.id,
                        argument=argument_contract.name,
                        choices=choices(argument_contract.contract, True),
                        socket_contract=contract_info(argument_contract.contract),
                        required=argument_contract.required,
                        bound=argument is not None,
                        source=argument.source if argument is not None else None,
                        node_input_contract=contract_info(capability.input),
                        node_output_contract=contract_info(capability.output),
                        protocol_mapping=mapping,
                        framework_supplied=argument is not None
                        and framework_supplied(
                            choices_from or document,
                            node.capability,
                            argument.name,
                            argument.source,
                        ),
                    )
                )
    ports = tuple(inventory)
    by_socket = {(port.node, port.argument): port for port in ports}
    legacy: list[BindingOptions] = []
    for node in definition.nodes:
        if isinstance(node.request, ExternalRequest):
            port = by_socket[(node.id, None)]
            legacy.append(
                BindingOptions(
                    node=port.node,
                    argument=port.argument,
                    choices=tuple(
                        BindingChoice(label=choice.label, source=choice.source)
                        for choice in port.choices
                    ),
                )
            )
            continue
        assert isinstance(node.request, ProtocolRequest)
        for argument in node.request.arguments:
            port = by_socket[(node.id, argument.name)]
            legacy.append(
                BindingOptions(
                    node=port.node,
                    argument=port.argument,
                    choices=tuple(
                        BindingChoice(label=choice.label, source=choice.source)
                        for choice in port.choices
                    ),
                )
            )
    return tuple(legacy), ports


def node_catalog() -> NodeCatalog:
    """Every addable capability route: one per producing protocol, plus external."""
    entries: list[CatalogEntry] = []
    for name, capability in CAPABILITIES.items():
        common = {
            "capability": name,
            "input_contract": contract_info(capability.input),
            "output_contract": contract_info(capability.output),
        }
        for protocol_id, protocol in PROTOCOLS.items():
            if protocol.output == capability.input:
                entries.append(
                    CatalogEntry(
                        **common,
                        protocol=protocol_id,
                        owner=protocol.owner,
                        arguments=tuple(
                            CatalogArgument(
                                name=item.name,
                                contract=contract_info(item.contract),
                                required=item.required,
                                produced_by=producers(item.contract),
                            )
                            for item in protocol.arguments
                        ),
                    )
                )
        entries.append(CatalogEntry(**common, protocol=None, owner=None, arguments=()))
    return NodeCatalog(entries=tuple(entries), guide=catalog_guide())


def pending_node_ports(
    document: AuthoredWorkflowDocument, proposal: PendingNode
) -> tuple[PortInventoryEntry, ...]:
    """Inventory entries for a node that is not yet part of a valid document."""
    capability = CAPABILITIES[proposal.capability]
    node_input, node_output = contract_info(capability.input), contract_info(capability.output)
    if proposal.protocol is None:
        source = None if proposal.binding is None else ExternalSource(binding=proposal.binding)
        return (
            PortInventoryEntry(
                node=proposal.node,
                argument=None,
                choices=port_choices(document, capability.input, False),
                socket_contract=node_input,
                required=True,
                bound=source is not None,
                source=source,
                node_input_contract=node_input,
                node_output_contract=node_output,
                protocol_mapping=None,
                framework_supplied=framework_supplied(document, proposal.capability, None, source),
            ),
        )
    protocol = PROTOCOLS[proposal.protocol]
    mapping = ProtocolMapping(
        id=proposal.protocol, owner=protocol.owner, output_contract=contract_info(protocol.output)
    )
    bound = {item.name: item.source for item in proposal.arguments}
    return tuple(
        PortInventoryEntry(
            node=proposal.node,
            argument=item.name,
            choices=port_choices(document, item.contract, True),
            socket_contract=contract_info(item.contract),
            required=item.required,
            bound=item.name in bound,
            source=bound.get(item.name),
            node_input_contract=node_input,
            node_output_contract=node_output,
            protocol_mapping=mapping,
            framework_supplied=framework_supplied(
                document, proposal.capability, item.name, bound.get(item.name)
            ),
        )
        for item in protocol.arguments
    )
