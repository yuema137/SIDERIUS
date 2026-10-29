"""Admission for explicit proposal families and complete native branches."""

from dataclasses import dataclass

from .adaptor_strategies import (
    AllSelect,
    CollectCombine,
    FirstAdmissibleSelect,
    PassCombine,
    PerItemDistribute,
    SingleDistribute,
    SplitItemsDistribute,
    derive_cardinality,
)
from .adaptor_validation import check_strategies, output_contract
from .candidate import check_tuning_edge, refuse_declaration_only
from .llm_strategies import LLM_STRATEGY_TYPES
from .models import (
    AdaptorInstance,
    AdaptorSource,
    ExternalRequest,
    ExternalSource,
    ProtocolRequest,
    Request,
    ResultSource,
    ReusableWorkflowDefinition,
    WorkflowDefinition,
)
from .routes import branch_arms
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


@dataclass(frozen=True)
class LiteratureReview:
    """One admitted review node and its external ``literature.input`` binding."""

    node: str
    binding: str


@dataclass(frozen=True)
class LiteratureProposal:
    """One proposal fed by the literature adaptor: its seed and the output it reads."""

    node: str
    seed_binding: str
    index: int | None  # the adaptor output index; None for the unindexed single/v1 output


@dataclass(frozen=True)
class LiteratureAdaptorEdges:
    """Reviews -> one declared adaptor -> proposals (B6 S2 collection, S3 split).

    ``reviews`` follow the adaptor's declared binding order; ``protocol`` is the
    one catalogued proposal protocol every proposal applies to its adaptor output.
    """

    adaptor: str
    reviews: tuple[LiteratureReview, ...]
    protocol: str
    proposals: tuple[LiteratureProposal, ...]

    def proposal(self, node_id: str) -> LiteratureProposal:
        return next(item for item in self.proposals if item.node == node_id)


# S1 (B6-3): fanout branches -> first passing validator -> one tuner.
SELECTION_PROFILE = "native-proposal-fanout-selection/v1"
# B1-PR5: the S1 node set plus declared routes, e.g. a fallback branch that runs
# only when the first validator rejects (B1-Q1/Q2). The only profile admitting routes.
ROUTED_PROFILE = "native-routed-candidate/v1"
# S2 (B6-4): N reviews -> collect/v1 -> one proposal through
# literature-collection-to-proposal -> its complete branches.
LITERATURE_COLLECTION_PROFILE = "native-literature-collection/v1"
# S3 (B6-4): one review -> split-items/v1 into M outputs -> M proposals through
# literature-to-proposal -> one complete family each.
LITERATURE_SPLIT_PROFILE = "native-literature-split/v1"
# B6-8a: N reviews -> one LLM COMBINE kind (B2) -> single/v1 or per-item/v1(M) -> one
# proposal per output through literature-to-proposal -> its complete branches. The
# only profile that executes an LLM COMBINE kind.
LITERATURE_JUDGED_PROFILE = "native-literature-judged/v1"
ADAPTOR_PROFILES = (
    SELECTION_PROFILE,
    ROUTED_PROFILE,
    LITERATURE_COLLECTION_PROFILE,
    LITERATURE_SPLIT_PROFILE,
    LITERATURE_JUDGED_PROFILE,
)
LLM_COMBINE_NOT_ADMITTED = (
    f"an LLM COMBINE kind executes only under the {LITERATURE_JUDGED_PROFILE} profile"
)


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
    literature_adaptor: LiteratureAdaptorEdges | None = None

    @property
    def branches(self) -> tuple[tuple[str, str], ...]:
        return tuple(branch for family in self.families for branch in family.branches)

    @property
    def literature_reviews(self) -> tuple[str, ...]:
        """Every admitted review node, from either literature shape."""
        if self.literature is not None:
            return (self.literature.review,)
        if self.literature_adaptor is not None:
            return tuple(item.node for item in self.literature_adaptor.reviews)
        return ()

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
    refuse_declaration_only(
        definition,
        admits_adaptors=profile in ADAPTOR_PROFILES,
        admits_routes=profile == ROUTED_PROFILE,
    )
    if profile != LITERATURE_JUDGED_PROFILE and any(
        isinstance(adaptor.combine, LLM_STRATEGY_TYPES) for adaptor in definition.adaptors
    ):
        raise ValueError(LLM_COMBINE_NOT_ADMITTED)
    if profile == LITERATURE_JUDGED_PROFILE:
        return literature_judged_candidate(definition)
    if profile == SELECTION_PROFILE:
        return selection_candidate(definition)
    if profile == LITERATURE_COLLECTION_PROFILE:
        return literature_collection_candidate(definition)
    if profile == LITERATURE_SPLIT_PROFILE:
        return literature_split_candidate(definition)
    if profile == ROUTED_PROFILE:
        return routed_candidate(definition)
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


def routed_candidate(
    definition: WorkflowDefinition | ReusableWorkflowDefinition,
) -> ProposalFamilies:
    """S1 plus routes over implementation/validation arms only (B1-Q1(a), not Q1(b)).

    An arm containing the tuner or the selection adaptor would gate training on a
    predicate (Q1(b), not chosen): a body could then complete without training.
    """
    if not definition.routes:
        raise ValueError("the routed profile requires at least one declared route")
    shape = selection_candidate(definition)
    allowed = {
        node.id for node in definition.nodes if node.capability in ("implementation", "validation")
    }
    for branch, arms in branch_arms(definition, predecessor_facts(definition)).items():
        if any(arm - allowed for arm in arms):
            raise ValueError(
                f"route {branch}: the routed profile routes only implementation/validation "
                "arms, never the adaptor or the tuner"
            )
    return shape


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


def literature_collection_candidate(
    definition: WorkflowDefinition | ReusableWorkflowDefinition,
) -> ProposalFamilies:
    """S2: every review collected (declared binding order) into one proposal's evidence."""
    adaptor, reviews = _literature_adaptor(definition)
    if not (
        isinstance(adaptor.combine, CollectCombine)
        and isinstance(adaptor.select, AllSelect)
        and isinstance(adaptor.distribute, SingleDistribute)
    ):
        raise ValueError("literature collection requires collect/v1, all/v1 and single/v1")
    edges, shape = _literature_proposals(
        definition, adaptor, reviews, "literature-collection-to-proposal", "reviews"
    )
    if len(edges.proposals) != 1:
        raise ValueError("literature collection requires exactly one proposal")
    return shape


def literature_split_candidate(
    definition: WorkflowDefinition | ReusableWorkflowDefinition,
) -> ProposalFamilies:
    """S3: one review's findings split into M outputs; output ``i`` feeds family ``i``.

    COMBINE/SELECT are any deterministic pair the declaration validation table
    admits before ``split-items/v1`` (e.g. ``field-rank/v1`` + ``top-k/v1``).
    """
    adaptor, reviews = _literature_adaptor(definition)
    distribute = adaptor.distribute
    if not isinstance(distribute, SplitItemsDistribute) or len(reviews) != 1:
        raise ValueError("literature split requires split-items/v1 over exactly one review")
    edges, shape = _literature_proposals(
        definition, adaptor, reviews, "literature-to-proposal", "output"
    )
    indices = sorted(item.index for item in edges.proposals if item.index is not None)
    if len(indices) != len(edges.proposals) or indices != list(range(distribute.count)):
        raise ValueError("literature split requires one proposal per adaptor output index")
    return shape


def literature_judged_candidate(
    definition: WorkflowDefinition | ReusableWorkflowDefinition,
) -> ProposalFamilies:
    """N reviews -> one LLM COMBINE -> one proposal per output index (B6-8a).

    ``single/v1`` feeds one proposal (``index`` absent); ``per-item/v1(M)`` feeds M
    proposals, indices ``0..M-1`` each bound once. The LLM kind's own static rules
    (``admit_llm_strategy``) are applied here, at profile admission.
    """
    adaptor, reviews = _literature_adaptor(definition)
    if not isinstance(adaptor.combine, LLM_STRATEGY_TYPES):
        raise ValueError("literature judged profile requires an LLM COMBINE kind")
    distribute = adaptor.distribute
    if not isinstance(distribute, SingleDistribute | PerItemDistribute):
        raise ValueError("literature judged profile requires single/v1 or per-item/v1")
    edges, shape = _literature_proposals(
        definition, adaptor, reviews, "literature-to-proposal", "output"
    )
    indices = [item.index for item in edges.proposals]
    expected = [None] if isinstance(distribute, SingleDistribute) else list(range(distribute.count))
    if sorted(indices, key=lambda index: -1 if index is None else index) != expected:
        raise ValueError("literature judged profile requires one proposal per adaptor output")
    admit_llm_combine(adaptor)
    return shape


def admit_llm_combine(adaptor: AdaptorInstance) -> None:
    """Refuse an LLM COMBINE kind ``admit_llm_strategy`` does not admit for this adaptor."""
    from workflows.judge_strategies import admit_llm_strategy

    strategy = adaptor.combine
    assert isinstance(strategy, LLM_STRATEGY_TYPES)
    admission = admit_llm_strategy(
        strategy,
        inputs=adaptor.inputs,
        output_contract=output_contract(adaptor),
        select=adaptor.select,
        cardinality=derive_cardinality(adaptor.select, adaptor.distribute),
    )
    if not admission.admitted:
        reasons = "; ".join(f"{item.code}: {item.message}" for item in admission.refusals)
        raise ValueError(f"adaptor {adaptor.id}: {strategy.kind} is not admitted: {reasons}")
    if strategy.on_failure != "fail":
        # The fallback replaces only COMBINE: the same deterministic validation table
        # must admit it with this adaptor's SELECT and DISTRIBUTE.
        fallback = adaptor.model_copy(update={"combine": strategy.on_failure.combine})
        try:
            check_strategies(fallback)
        except ValueError as error:
            raise ValueError(
                f"adaptor {adaptor.id}: fallback {strategy.on_failure.combine.kind} is not "
                f"admitted with {adaptor.select.kind} and {adaptor.distribute.kind}: {error}"
            ) from error


def _literature_adaptor(
    definition: WorkflowDefinition | ReusableWorkflowDefinition,
) -> tuple[AdaptorInstance, tuple[LiteratureReview, ...]]:
    """The one adaptor over every external review, each bound exactly once."""
    if len(definition.adaptors) != 1:
        raise ValueError("literature adaptor profiles require exactly one adaptor")
    adaptor = definition.adaptors[0]
    if len(adaptor.inputs) != 1 or adaptor.inputs[0].contract != "literature.output":
        raise ValueError("the literature adaptor requires one literature.output input port")
    nodes = {node.id: node for node in definition.nodes}
    declared = [node.id for node in definition.nodes if node.capability == "literature"]
    sources = adaptor.bindings[0].sources
    bound = [source.node for source in sources if isinstance(source, ResultSource)]
    if len(bound) != len(sources) or sorted(bound) != sorted(declared) or not declared:
        raise ValueError("the literature adaptor must bind every review result exactly once")
    reviews = []
    for node_id in bound:
        request = nodes[node_id].request
        if not isinstance(request, ExternalRequest):
            raise ValueError("literature adaptor profiles require external review requests")
        reviews.append(LiteratureReview(node_id, request.binding))
    return adaptor, tuple(reviews)


def _literature_proposals(
    definition: WorkflowDefinition | ReusableWorkflowDefinition,
    adaptor: AdaptorInstance,
    reviews: tuple[LiteratureReview, ...],
    protocol: str,
    argument: str,
) -> tuple[LiteratureAdaptorEdges, ProposalFamilies]:
    """Proposals reading the adaptor through ``protocol``; then exact branch ownership."""
    facts = predecessor_facts(definition)
    proposals = []
    for node in definition.nodes:
        if node.capability != "proposal":
            continue
        request = node.request
        if not isinstance(request, ProtocolRequest) or request.protocol != protocol:
            raise ValueError(f"each literature-fed proposal requires {protocol}")
        sources = {arg.name: arg.source for arg in request.arguments}
        output, seed = sources.get(argument), sources.get("proposal_input")
        if (
            not isinstance(output, AdaptorSource)
            or output.adaptor != adaptor.id
            or not isinstance(seed, ExternalSource)
        ):
            raise ValueError("proposal must consume the literature adaptor and an external seed")
        proposals.append(LiteratureProposal(node.id, seed.binding, output.index))
    seeds = {item.node: item.seed_binding for item in proposals}
    review_ids = {item.node for item in reviews}
    # Existing branch ownership remains the authority for implementation/validation.
    candidate = definition.model_copy(
        update={
            "nodes": tuple(
                node.model_copy(update={"request": ExternalRequest(binding=seeds[node.id])})
                if node.id in seeds
                else node
                for node in definition.nodes
                if node.id not in review_ids
            )
        }
    )
    shape = _proposal_branches(candidate, facts, external_proposals=True)
    edges = LiteratureAdaptorEdges(adaptor.id, reviews, protocol, tuple(proposals))
    return edges, ProposalFamilies(shape.families, facts, literature_adaptor=edges)
