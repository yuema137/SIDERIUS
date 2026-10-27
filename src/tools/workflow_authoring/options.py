"""GUI choices derive exclusively from the native typed catalog."""

from workflows.definition import (
    AuthoredWorkflowDocument,
    ExternalRequest,
    ExternalSource,
    ProtocolRequest,
    ResultSource,
)
from workflows.definition.catalog import CAPABILITIES, CONTRACTS, PROTOCOLS

from .models import (
    BindingChoice,
    BindingOptions,
    NativeContract,
    PortChoice,
    PortInventoryEntry,
    ProtocolMapping,
)


def binding_projection(
    document: AuthoredWorkflowDocument,
) -> tuple[tuple[BindingOptions, ...], tuple[PortInventoryEntry, ...]]:
    """Project catalog ports and preserve the legacy bound-option wire shape/order."""
    definition = document.definition

    def contract_info(contract_id: str) -> NativeContract:
        return NativeContract(id=contract_id, native_type=CONTRACTS[contract_id])

    def choices(contract_id: str, results: bool) -> tuple[PortChoice, ...]:
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
