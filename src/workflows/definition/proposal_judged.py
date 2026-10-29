"""Admission of ``native-proposal-judged/v1`` (B6-8b).

N external proposals -> one LLM COMBINE adaptor over every ``proposal.output`` ->
``single/v1`` or ``per-item/v1(M)`` -> one branch per output: its implementation
reads the adaptor output through ``proposal-to-implementation`` and its validation
reads that implementation (``implementation-to-validation``) or the same adaptor
output and the implementation (``proposed-implementation-to-validation``).
No tuner, loop, route, review or interpretation is admitted.
"""

from .adaptor_strategies import PerItemDistribute, SingleDistribute
from .fanout import (
    JudgedBranch,
    ProposalFamilies,
    ProposalFanout,
    ProposalSelection,
    admit_llm_combine,
)
from .llm_strategies import LLM_STRATEGY_TYPES
from .models import (
    AdaptorInstance,
    AdaptorSource,
    ExternalRequest,
    NodeInstance,
    ProtocolRequest,
    ResultSource,
    ReusableWorkflowDefinition,
    WorkflowDefinition,
)
from .validation import predecessor_facts

Definition = WorkflowDefinition | ReusableWorkflowDefinition


def proposal_judged_candidate(definition: Definition) -> ProposalFamilies:
    facts = predecessor_facts(definition)
    adaptor, proposals = _proposal_adaptor(definition)
    indices = _output_indices(adaptor)
    implementations = [node for node in definition.nodes if node.capability == "implementation"]
    validations = [node for node in definition.nodes if node.capability == "validation"]
    if len(definition.nodes) != len(proposals) + len(implementations) + len(validations):
        raise ValueError(
            "proposal judged profile admits proposals, implementations and validations"
        )
    branches = []
    for implementation in implementations:
        source = _source(implementation, "proposal-to-implementation", "output", AdaptorSource)
        if source.adaptor != adaptor.id:
            raise ValueError(f"{implementation.id} must read the proposal adaptor output")
        validation = _validator_of(implementation, validations, source)
        branches.append(JudgedBranch(source.index, implementation.id, validation.id))
    if sorted((item.index for item in branches), key=_index_key) != indices:
        raise ValueError("proposal judged profile requires one branch per adaptor output index")
    if len(validations) != len(branches):
        raise ValueError("every validation must belong to exactly one judged branch")
    admit_llm_combine(adaptor)
    families = tuple(ProposalFanout(node, (), facts) for node in proposals)
    selection = ProposalSelection(adaptor.id, tuple(sorted(branches, key=_order)))
    return ProposalFamilies(families, facts, proposal_selection=selection)


def _order(branch: JudgedBranch) -> int:
    return _index_key(branch.index)


def _index_key(index: int | None) -> int:
    return -1 if index is None else index


def _proposal_adaptor(definition: Definition) -> tuple[AdaptorInstance, tuple[str, ...]]:
    """The one LLM adaptor binding every external proposal exactly once."""
    if len(definition.adaptors) != 1:
        raise ValueError("proposal judged profile requires exactly one adaptor")
    adaptor = definition.adaptors[0]
    if not isinstance(adaptor.combine, LLM_STRATEGY_TYPES):
        raise ValueError("proposal judged profile requires an LLM COMBINE kind")
    if len(adaptor.inputs) != 1 or adaptor.inputs[0].contract != "proposal.output":
        raise ValueError("the proposal adaptor requires one proposal.output input port")
    declared = [node for node in definition.nodes if node.capability == "proposal"]
    sources = adaptor.bindings[0].sources
    bound = [source.node for source in sources if isinstance(source, ResultSource)]
    if len(bound) != len(sources) or sorted(bound) != sorted(node.id for node in declared):
        raise ValueError("the proposal adaptor must bind every proposal result exactly once")
    if not all(isinstance(node.request, ExternalRequest) for node in declared):
        raise ValueError("proposal judged profile requires external proposal requests")
    return adaptor, tuple(bound)


def _output_indices(adaptor: AdaptorInstance) -> list[int | None]:
    distribute = adaptor.distribute
    if isinstance(distribute, SingleDistribute):
        return [None]
    if isinstance(distribute, PerItemDistribute):
        return list(range(distribute.count))
    raise ValueError("proposal judged profile requires single/v1 or per-item/v1")


def _source[T](node: NodeInstance, protocol: str, argument: str, kind: type[T]) -> T:
    request = node.request
    if not isinstance(request, ProtocolRequest) or request.protocol != protocol:
        raise ValueError(f"{node.id} requires {protocol}")
    source = next((arg.source for arg in request.arguments if arg.name == argument), None)
    if not isinstance(source, kind):
        raise ValueError(f"{node.id} argument {argument!r} has an unsupported source")
    return source


def _validator_of(
    implementation: NodeInstance, validations: list[NodeInstance], output: AdaptorSource
) -> NodeInstance:
    """The one validator reading ``implementation`` (and, if declared, the same output)."""
    owned = []
    for node in validations:
        request = node.request
        if not isinstance(request, ProtocolRequest):
            continue
        sources = {arg.name: arg.source for arg in request.arguments}
        reads = {"implementation-to-validation": "output"}.get(request.protocol, "implementation")
        if sources.get(reads) != ResultSource(node=implementation.id):
            continue
        if request.protocol == "proposed-implementation-to-validation" and (
            sources.get("proposal") != output
        ):
            raise ValueError(f"{node.id} must read the same adaptor output as its implementation")
        owned.append(node)
    if len(owned) != 1:
        raise ValueError(f"{implementation.id} requires exactly one validation")
    return owned[0]
