"""Admission for explicit proposal families and complete native branches."""

from dataclasses import dataclass

from .adaptor_strategies import FirstAdmissibleSelect, PassCombine, SingleDistribute
from .candidate import check_tuning_edge, refuse_declaration_only
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
from .validation import predecessor_facts


@dataclass(frozen=True)
class ProposalFanout:
    proposal: str
    branches: tuple[tuple[str, str], ...]
    predecessors: tuple[tuple[str, frozenset[str]], ...]


@dataclass(frozen=True)
class LiteratureEdge:
    review: str
    proposal: str
    review_binding: str
    seed_binding: str


@dataclass(frozen=True)
class InterpretationEdge:
    interpretation: str
    proposal: str
    input_binding: str


# S1 (B6-3): fanout branches -> first passing validator -> one tuner.
SELECTION_PROFILE = "native-proposal-fanout-selection/v1"


@dataclass(frozen=True)
class AdaptorSelection:
    """The one admitted selection adaptor and its bound validators, in declared order."""

    adaptor: str
    validators: tuple[str, ...]


@dataclass(frozen=True)
class ProposalFamilies:
    families: tuple[ProposalFanout, ...]
    predecessors: tuple[tuple[str, frozenset[str]], ...]
    literature: LiteratureEdge | None = None
    interpretation: InterpretationEdge | None = None
    tuning: str | None = None
    selection: AdaptorSelection | None = None

    @property
    def branches(self) -> tuple[tuple[str, str], ...]:
        return tuple(branch for family in self.families for branch in family.branches)

    def proposal_for(self, node_id: str) -> str:
        """Select lineage from admitted edges, never scientific candidate identity."""
        return next(
            family.proposal
            for family in self.families
            if node_id == family.proposal or any(node_id in branch for branch in family.branches)
        )


def proposal_fanout(definition: WorkflowDefinition | ReusableWorkflowDefinition) -> ProposalFanout:
    """Retain the one-proposal profile's admission contract."""
    shape = proposal_families(definition)
    if len(shape.families) != 1:
        raise ValueError("fanout requires one external proposal and complete validation branches")
    return shape.families[0]


def execution_families(
    definition: WorkflowDefinition | ReusableWorkflowDefinition, profile: str | None
) -> ProposalFamilies:
    """Select only an explicitly supported native graph profile."""
    refuse_declaration_only(definition, admits_adaptors=profile == SELECTION_PROFILE)
    if profile == SELECTION_PROFILE:
        return selection_candidate(definition)
    if profile == "native-interpretation-candidate/v1":
        return interpretation_candidate(definition)
    if profile == "native-literature-candidate/v1":
        return literature_candidate(definition)
    if profile == "native-proposal-families/v1":
        return proposal_families(definition)
    if profile == "native-proposal-fanout/v1":
        family = proposal_fanout(definition)
        return ProposalFamilies((family,), family.predecessors)
    raise ValueError("unsupported native graph profile")


def proposal_families(
    definition: WorkflowDefinition | ReusableWorkflowDefinition,
) -> ProposalFamilies:
    """Admit independent external proposals with exact typed branch ownership."""
    return _proposal_branches(definition, predecessor_facts(definition), external_proposals=True)


def _proposal_branches(
    definition: WorkflowDefinition | ReusableWorkflowDefinition,
    facts: tuple[tuple[str, frozenset[str]], ...],
    *,
    external_proposals: bool,
) -> ProposalFamilies:
    proposals = [node for node in definition.nodes if node.capability == "proposal"]
    implementations = [node for node in definition.nodes if node.capability == "implementation"]
    validations = [node for node in definition.nodes if node.capability == "validation"]
    if (
        not proposals
        or not implementations
        or len(validations) != len(implementations)
        or len(definition.nodes) != len(proposals) + len(implementations) + len(validations)
        or (
            external_proposals
            and any(not isinstance(node.request, ExternalRequest) for node in proposals)
        )
    ):
        raise ValueError("fanout requires external proposals and complete validation branches")
    proposal_ids = {node.id for node in proposals}

    def sources(request: Request, protocol: str) -> dict[str, str]:
        if not isinstance(request, ProtocolRequest) or request.protocol != protocol:
            raise ValueError(f"fanout requires {protocol}")
        return {
            arg.name: arg.source.node
            for arg in request.arguments
            if isinstance(arg.source, ResultSource)
        }

    owners: dict[str, str] = {}
    for node in implementations:
        refs = sources(node.request, "proposal-to-implementation")
        if set(refs) != {"output"} or refs["output"] not in proposal_ids:
            raise ValueError("each implementation must consume a declared proposal result")
        owners[node.id] = refs["output"]
    if set(owners.values()) != proposal_ids:
        raise ValueError("each proposal requires a complete implementation/validation branch")
    validators: dict[str, str] = {}
    for node in validations:
        refs = sources(node.request, "proposed-implementation-to-validation")
        parent = refs.get("implementation")
        if parent not in owners or refs.get("proposal") != owners[parent]:
            raise ValueError("validation requires both this proposal and an implementation result")
        if parent in validators:
            raise ValueError("each implementation requires exactly one validator")
        validators[parent] = node.id
    if set(validators) != set(owners):
        raise ValueError("validation branches must cover exactly the declared implementations")
    return ProposalFamilies(
        tuple(
            ProposalFanout(
                proposal.id,
                tuple(
                    (node.id, validators[node.id])
                    for node in implementations
                    if owners[node.id] == proposal.id
                ),
                facts,
            )
            for proposal in proposals
        ),
        facts,
    )


def selection_candidate(
    definition: WorkflowDefinition | ReusableWorkflowDefinition,
) -> ProposalFamilies:
    """S1: one proposal's complete branches, a first-admissible adaptor, one tuner.

    The adaptor binds every validator result exactly once; its declared binding
    order is the selection order. Only the deterministic S1 strategy triple is
    admitted, so the adaptor emits at most one validation result.
    """
    facts = predecessor_facts(definition)
    tuners = [node for node in definition.nodes if node.capability == "tuning"]
    if len(tuners) != 1 or len(definition.adaptors) != 1:
        raise ValueError("selection requires exactly one adaptor and one tuning node")
    tuner, adaptor = tuners[0], definition.adaptors[0]
    candidate = definition.model_copy(
        update={"nodes": tuple(node for node in definition.nodes if node.id != tuner.id)}
    )
    shape = _proposal_branches(candidate, facts, external_proposals=True)
    if len(shape.families) != 1:
        raise ValueError("selection requires one external proposal")
    family = shape.families[0]
    if not (
        isinstance(adaptor.combine, PassCombine)
        and isinstance(adaptor.select, FirstAdmissibleSelect)
        and isinstance(adaptor.distribute, SingleDistribute)
    ):
        raise ValueError("selection requires pass/v1, first-admissible/v1 and single/v1")
    if len(adaptor.inputs) != 1 or adaptor.inputs[0].contract != "validation.output":
        raise ValueError("selection requires one validation.output input port")
    sources = adaptor.bindings[0].sources
    validators = tuple(source.node for source in sources if isinstance(source, ResultSource))
    if len(validators) != len(sources) or sorted(validators) != sorted(
        validation for _, validation in family.branches
    ):
        raise ValueError("the selection adaptor must bind every validator result exactly once")
    check_tuning_edge(tuner.request, family.proposal, AdaptorSource(adaptor=adaptor.id))
    return ProposalFamilies(
        shape.families,
        facts,
        tuning=tuner.id,
        selection=AdaptorSelection(adaptor.id, validators),
    )


def literature_candidate(
    definition: WorkflowDefinition | ReusableWorkflowDefinition,
) -> ProposalFamilies:
    """Validate the review edge, then reuse branch admission for its candidate."""
    facts = predecessor_facts(definition)
    reviews = [node for node in definition.nodes if node.capability == "literature"]
    proposals = [node for node in definition.nodes if node.capability == "proposal"]
    if len(definition.nodes) != 4 or len(reviews) != 1 or len(proposals) != 1:
        raise ValueError("literature candidate requires one review and one complete candidate")
    review, proposal = reviews[0], proposals[0]
    if (
        not isinstance(review.request, ExternalRequest)
        or not isinstance(proposal.request, ProtocolRequest)
        or proposal.request.protocol != "literature-to-proposal"
    ):
        raise ValueError("literature candidate requires an external review and typed proposal edge")
    sources = {arg.name: arg.source for arg in proposal.request.arguments}
    output, seed = sources.get("output"), sources.get("proposal_input")
    if (
        not isinstance(output, ResultSource)
        or output.node != review.id
        or not isinstance(seed, ExternalSource)
    ):
        raise ValueError("proposal must consume this review result and an external proposal seed")
    # Existing branch ownership remains the authority for implementation/validation.
    candidate = definition.model_copy(
        update={
            "nodes": tuple(
                node.model_copy(update={"request": ExternalRequest(binding=seed.binding)})
                if node.id == proposal.id
                else node
                for node in definition.nodes
                if node.id != review.id
            )
        }
    )
    shape = proposal_families(candidate)
    return ProposalFamilies(
        shape.families,
        facts,
        LiteratureEdge(review.id, proposal.id, review.request.binding, seed.binding),
    )


def interpretation_candidate(
    definition: WorkflowDefinition | ReusableWorkflowDefinition,
) -> ProposalFamilies:
    """One explicit native interpretation edge and one complete candidate branch."""
    facts = predecessor_facts(definition)
    interpreters = [node for node in definition.nodes if node.capability == "interpretation"]
    proposals = [node for node in definition.nodes if node.capability == "proposal"]
    tuners = [node for node in definition.nodes if node.capability == "tuning"]
    if (
        len(tuners) > 1
        or len(definition.nodes) != 4 + len(tuners)
        or len(interpreters) != 1
        or len(proposals) != 1
    ):
        raise ValueError("interpretation candidate requires one interpreter and complete candidate")
    interpreter, proposal = interpreters[0], proposals[0]
    if (
        not isinstance(interpreter.request, ExternalRequest)
        or not isinstance(proposal.request, ProtocolRequest)
        or proposal.request.protocol != "interpretation-to-proposal"
    ):
        raise ValueError("interpretation candidate requires an external input and typed edge")
    if not {"data_dir", "task_composition_ref"}.issubset(
        arg.name for arg in proposal.request.arguments
    ):
        raise ValueError(
            "composed interpretation requires explicit data_dir and task_composition_ref"
        )
    for arg in proposal.request.arguments:
        if arg.name == "output":
            if not isinstance(arg.source, ResultSource) or arg.source.node != interpreter.id:
                raise ValueError("proposal must consume the declared interpretation result")
        elif not isinstance(arg.source, ExternalSource):
            raise ValueError("interpretation protocol context requires explicit external bindings")
    # The complete declaration already passed contract validation. Reuse branch
    # ownership without inventing a proposal seed or changing its request type.
    candidate = definition.model_copy(
        update={
            "nodes": tuple(
                node
                for node in definition.nodes
                if node.id != interpreter.id and node.capability != "tuning"
            )
        }
    )
    shape = _proposal_branches(candidate, facts, external_proposals=False)
    if tuners:
        check_tuning_edge(tuners[0].request, proposal.id, shape.branches[0][1])
    return ProposalFamilies(
        shape.families,
        facts,
        interpretation=InterpretationEdge(interpreter.id, proposal.id, interpreter.request.binding),
        tuning=tuners[0].id if tuners else None,
    )
