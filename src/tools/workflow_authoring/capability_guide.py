"""Palette guidance projected from the native catalog: descriptions, stages and edges.

The description table is the single owner of the plain-language one-liners the
workflow editor palette shows. Stage order, ``connects_from``/``connects_to`` and the
start guide derive only from ``CAPABILITIES`` and ``PROTOCOLS``; the browser renders
them and never decides compatibility itself.
"""

from types import MappingProxyType

from workflows.definition.catalog import CAPABILITIES, PROTOCOLS

from .models import CapabilityGuide, CatalogGuide

# One plain-language sentence per catalog capability (a unit census binds the keys to
# CAPABILITIES). Presentation text only: no prompt or execution input reads it.
CAPABILITY_DESCRIPTIONS = MappingProxyType(
    {
        "interpretation": "Turns earlier tuning results into evidence and diagnoses "
        "for the next proposal.",
        "literature": "Searches published papers for findings that address the current "
        "bottlenecks.",
        "proposal": "Proposes the next model architecture to try, as a structured plan.",
        "implementation": "Writes the proposed model as runnable PyTorch plugin code "
        "with its tests.",
        "validation": "Checks the generated model code (loading, tests, gradient flow, "
        "code review) before training.",
        "tuning": "Trains the validated model and tunes its hyperparameters, "
        "reporting scored results.",
    }
)


def _upstream(capability: str) -> tuple[str, ...]:
    """Capabilities whose output some route into ``capability`` accepts as an argument."""
    target = CAPABILITIES[capability].input
    contracts = {
        argument.contract
        for protocol in PROTOCOLS.values()
        if protocol.output == target
        for argument in protocol.arguments
    }
    return tuple(name for name, item in CAPABILITIES.items() if item.output in contracts)


def producers(contract_id: str) -> tuple[str, ...]:
    """Capabilities whose output carries ``contract_id``; empty means an external input."""
    return tuple(name for name, item in CAPABILITIES.items() if item.output == contract_id)


def _stage_order(upstream: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    """Stable topological order of the capability graph (catalog order breaks ties)."""
    order: list[str] = []
    remaining = list(CAPABILITIES)
    while remaining:
        ready = [
            name
            for name in remaining
            if all(item in order or item == name for item in upstream[name])
        ]
        if not ready:  # a cycle: keep the remaining capabilities in catalog order
            ready = remaining[:1]
        order.append(ready[0])
        remaining.remove(ready[0])
    return tuple(order)


def catalog_guide() -> CatalogGuide:
    upstream = {name: _upstream(name) for name in CAPABILITIES}
    order = _stage_order(upstream)
    downstream = {
        name: tuple(item for item in order if name in upstream[item] and item != name)
        for name in CAPABILITIES
    }
    # Capabilities without an upstream capability only add context; the build chain
    # starts at the first capability another capability feeds into.
    context = tuple(name for name in order if not upstream[name] and downstream[name])
    chain = tuple(name for name in order if name not in context)
    capabilities = tuple(
        CapabilityGuide(
            capability=name,
            stage=index,
            description=CAPABILITY_DESCRIPTIONS[name],
            connects_from=tuple(item for item in order if item in upstream[name]),
            connects_to=downstream[name],
        )
        for index, name in enumerate(order)
    )
    return CatalogGuide(capabilities=capabilities, chain=chain, context=context)
