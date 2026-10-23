"""GUI choices derive exclusively from the native typed catalog."""

from workflows.definition import (
    AuthoredWorkflowDocument,
    ExternalRequest,
    ExternalSource,
    ResultSource,
)
from workflows.definition.catalog import CAPABILITIES, PROTOCOLS

from .models import BindingChoice, BindingOptions


def binding_options(document: AuthoredWorkflowDocument) -> tuple[BindingOptions, ...]:
    definition = document.definition

    def choices(contract: str, results: bool) -> tuple[BindingChoice, ...]:
        externals = tuple(
            BindingChoice(label=item.id, source=ExternalSource(binding=item.id))
            for item in definition.externals
            if item.contract == contract
        )
        nodes = tuple(
            BindingChoice(
                label=item.id + ".result",
                source=ResultSource(node=item.id),
            )
            for item in definition.nodes
            if CAPABILITIES[item.capability].output == contract
        )
        return externals + (nodes if results else ())

    options = []
    for node in definition.nodes:
        if isinstance(node.request, ExternalRequest):
            options.append(
                BindingOptions(
                    node=node.id,
                    argument=None,
                    choices=choices(CAPABILITIES[node.capability].input, False),
                )
            )
        else:
            contracts = {
                item.name: item.contract for item in PROTOCOLS[node.request.protocol].arguments
            }
            for argument in node.request.arguments:
                options.append(
                    BindingOptions(
                        node=node.id,
                        argument=argument.name,
                        choices=choices(contracts[argument.name], True),
                    )
                )
    return tuple(options)
