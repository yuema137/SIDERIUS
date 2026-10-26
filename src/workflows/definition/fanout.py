"""Admission for one proposal and complete implementation/validation branches."""

from dataclasses import dataclass

from .models import (
    ExternalRequest,
    ProtocolRequest,
    ResultSource,
    ReusableWorkflowDefinition,
    WorkflowDefinition,
)
from .validation import predecessor_facts


@dataclass(frozen=True)
class ProposalFanout:
    proposal: str
    branches: tuple[tuple[str, str], ...]
    predecessors: tuple[tuple[str, frozenset[str]], ...]


def proposal_fanout(definition: WorkflowDefinition | ReusableWorkflowDefinition) -> ProposalFanout:
    """Check the executable shape without imposing a topology-size budget."""
    facts = predecessor_facts(definition)
    proposals = [node for node in definition.nodes if node.capability == "proposal"]
    implementations = [node for node in definition.nodes if node.capability == "implementation"]
    validations = [node for node in definition.nodes if node.capability == "validation"]
    if (
        len(proposals) != 1
        or not implementations
        or len(validations) != len(implementations)
        or len(definition.nodes) != 1 + len(implementations) + len(validations)
        or not isinstance(proposals[0].request, ExternalRequest)
    ):
        raise ValueError("fanout requires one external proposal and complete validation branches")
    proposal = proposals[0].id

    def sources(request: ExternalRequest | ProtocolRequest, protocol: str) -> dict[str, str]:
        if not isinstance(request, ProtocolRequest) or request.protocol != protocol:
            raise ValueError(f"fanout requires {protocol}")
        return {
            arg.name: arg.source.node
            for arg in request.arguments
            if isinstance(arg.source, ResultSource)
        }

    validators: dict[str, str] = {}
    for node in validations:
        refs = sources(node.request, "proposed-implementation-to-validation")
        if refs.get("proposal") != proposal or "implementation" not in refs:
            raise ValueError("validation requires both this proposal and an implementation result")
        parent = refs["implementation"]
        if parent in validators:
            raise ValueError("each implementation requires exactly one validator")
        validators[parent] = node.id
    for node in implementations:
        if sources(node.request, "proposal-to-implementation") != {"output": proposal}:
            raise ValueError("each implementation must consume this proposal result")
    if set(validators) != {node.id for node in implementations}:
        raise ValueError("validation branches must cover exactly the declared implementations")
    return ProposalFanout(
        proposal, tuple((node.id, validators[node.id]) for node in implementations), facts
    )
