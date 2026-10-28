"""GUI choices derive exclusively from the native typed catalog."""

from workflows.definition import (
    AuthoredWorkflowDocument,
    ExternalRequest,
    ExternalSource,
    ProtocolRequest,
    ResultSource,
)
from workflows.definition.catalog import CAPABILITIES, CONTRACTS, PROTOCOLS

from .capability_guide import catalog_guide, producers
from .models import (
    AddNodeProposal,
    BindingChoice,
    BindingOptions,
    CatalogArgument,
    CatalogEntry,
    NativeContract,
    NodeCatalog,
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


def binding_projection(
    document: AuthoredWorkflowDocument,
) -> tuple[tuple[BindingOptions, ...], tuple[PortInventoryEntry, ...]]:
    """Project catalog ports and preserve the legacy bound-option wire shape/order."""
    definition = document.definition

    def choices(contract_id: str, results: bool) -> tuple[PortChoice, ...]:
        return port_choices(document, contract_id, results)

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
    document: AuthoredWorkflowDocument, proposal: AddNodeProposal
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
        )
        for item in protocol.arguments
    )
