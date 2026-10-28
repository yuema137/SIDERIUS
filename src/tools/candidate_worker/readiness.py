"""Single authority for serial graph readiness: which declared node acts next.

Both the child dispatcher (`graph.execute_fanout`) and the receipt verifier
(`graph_evidence.verify_graph_trace`) consume `next_dispatch`, so execution and
replay cannot drift. The function is pure: no workspace, no native records.
Route decisions enter as recorded `RouteEvaluationOutput` values; readiness
never evaluates a predicate.
"""

from collections.abc import Iterable, Mapping
from typing import Literal

from pydantic import Field, model_validator

from .graph_models import GraphNodeEvidence, GraphReason, GraphState
from .loop_stop import StopModel
from .route_eval import RouteEvaluationOutput

# States in which a node has not yet reached a terminal outcome.
_OPEN: frozenset[GraphState] = frozenset(("pending", "running"))
# Terminal states that close every consumer as blocked; blocked beats skipped.
_UNSUCCESSFUL: frozenset[GraphState] = frozenset(("failed", "rejected", "blocked"))
# Reasons a node may be `skipped` with; a consumer of a skipped source inherits it.
SKIP_REASONS: frozenset[GraphReason] = frozenset(("route_not_selected",))

BodyStatus = Literal["failed", "rejected", "completed", "accepted"]
Closure = tuple[GraphState, GraphReason]


class MergeCandidate(StopModel):
    node: str
    entry: tuple[str, ...]  # entry targets of the arm the candidate lies in (`route_entries`)


class MergeReadiness(StopModel):
    """One `SelectedSource` argument: the candidate of the selected arm is the input."""

    branch: str
    candidates: tuple[MergeCandidate, ...] = Field(min_length=2)


class NodeRouting(StopModel):
    """Route facts of one node, projected from its declaration; empty when unrouted."""

    route: str | None = None  # branch whose entry target this node is
    merges: tuple[MergeReadiness, ...] = ()


class NodeReadiness(StopModel):
    """One declared node as readiness sees it; `pending` means not yet decided."""

    node_id: str
    # Required sources, including a route's control edge, excluding merge candidates.
    predecessors: tuple[str, ...]
    state: GraphState
    reason: GraphReason | None = None  # recorded reason; a skip is inherited from it
    routing: NodeRouting = NodeRouting()

    @model_validator(mode="after")
    def _skip_has_reason(self) -> "NodeReadiness":
        if self.state == "skipped" and self.reason not in SKIP_REASONS:
            raise ValueError("a skipped node must carry a skip reason")
        if set(self.predecessors) & set(_merged(self.routing)):
            raise ValueError("a merge candidate is not also a required predecessor")
        return self


class ReadinessInput(StopModel):
    nodes: tuple[NodeReadiness, ...]  # declaration order
    aborted: bool  # an earlier native failure stops every later effect
    decisions: tuple[RouteEvaluationOutput, ...] = ()  # recorded so far, one per branch

    @model_validator(mode="after")
    def _closed_graph(self) -> "ReadinessInput":
        ids = [node.node_id for node in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("readiness node ids must be unique")
        if any(key not in ids for node in self.nodes for key in _sources(node)):
            raise ValueError("readiness predecessor is not a declared node")
        branches = [decision.branch_id for decision in self.decisions]
        if len(set(branches)) != len(branches):
            raise ValueError("readiness has two decisions for one route")
        return self


class ReadinessOutput(StopModel):
    """Either dispatch `next`, close `terminal` nodes without dispatch, or neither (done)."""

    next: str | None
    terminal: tuple[tuple[str, GraphState, GraphReason], ...]

    @model_validator(mode="after")
    def _one_action(self) -> "ReadinessOutput":
        if self.next is not None and self.terminal:
            raise ValueError("readiness decides one action per step")
        return self


def _merged(routing: NodeRouting) -> tuple[str, ...]:
    return tuple(item.node for merge in routing.merges for item in merge.candidates)


def _sources(node: NodeReadiness) -> tuple[str, ...]:
    """Every node whose terminal state this node waits for."""
    return (*node.predecessors, *_merged(node.routing))


def _merge_input(
    node_id: str,
    merge: MergeReadiness,
    nodes: Mapping[str, NodeReadiness],
    decisions: Mapping[str, RouteEvaluationOutput],
) -> NodeReadiness:
    """The source a merge consumes: the candidate in the arm its branch selected.

    Without a decision the branch source never succeeded, so every candidate is
    blocked or skipped; that representative closes the consumer the same way.
    """
    candidates = [nodes[item.node] for item in merge.candidates]
    decision = decisions.get(merge.branch)
    if decision is None:
        unsuccessful = [item for item in candidates if item.state in _UNSUCCESSFUL]
        if unsuccessful:
            return unsuccessful[0]
        if all(item.state == "skipped" for item in candidates):
            return candidates[0]
        raise ValueError(f"{node_id}: merge over route {merge.branch} lacks its decision")
    # Arm identity is the entry-target set; declared order carries no meaning.
    selected = frozenset(decision.selected_targets)
    chosen = [item for item in merge.candidates if frozenset(item.entry) == selected]
    if len(chosen) != 1:
        raise ValueError(f"{node_id}: route {merge.branch} selected no single merge candidate")
    return nodes[chosen[0].node]


def _route_closure(
    node: NodeReadiness, decisions: Mapping[str, RouteEvaluationOutput]
) -> Closure | None:
    """A route entry target runs only when its branch decision selected it."""
    branch = node.routing.route
    if branch is None:
        return None
    decision = decisions.get(branch)
    if decision is None:
        raise ValueError(f"{node.node_id}: route {branch} has no recorded decision")
    if node.node_id in decision.selected_targets:
        return None
    if node.node_id in decision.skipped_targets:
        return ("skipped", "route_not_selected")
    raise ValueError(f"{node.node_id}: route {branch} decision does not name this target")


def _close_reason(
    node: NodeReadiness,
    nodes: Mapping[str, NodeReadiness],
    decisions: Mapping[str, RouteEvaluationOutput],
    aborted: bool,
) -> Closure | None:
    """Per-node rule for a node whose sources are all terminal.

    Returns the state and reason to close it without dispatch, or None when it may
    run. AND over required sources: failure stop, then blocked (a failed, rejected
    or blocked source) beats skipped (a skipped source's reason is inherited, the
    generic propagation for any skip reason), then the node's own route decision.
    Additional node classes (e.g. adaptors that accept any terminal source) extend
    this hook.
    """
    if aborted:
        return ("blocked", "dependency_not_successful")
    sources = [nodes[key] for key in node.predecessors]
    sources += [_merge_input(node.node_id, item, nodes, decisions) for item in node.routing.merges]
    if any(source.state in _UNSUCCESSFUL for source in sources):
        return ("blocked", "dependency_not_successful")
    skipped = next((source for source in sources if source.state == "skipped"), None)
    if skipped is not None:
        if skipped.reason is None:  # unreachable: NodeReadiness refuses a reasonless skip
            raise ValueError(f"{skipped.node_id}: skipped without a reason")
        return ("skipped", skipped.reason)
    return _route_closure(node, decisions)


def next_dispatch(value: ReadinessInput) -> ReadinessOutput:
    """Decide the first undecided node, in declaration order, whose inputs are terminal."""
    nodes = {node.node_id: node for node in value.nodes}
    decisions = {decision.branch_id: decision for decision in value.decisions}
    for node in value.nodes:
        if node.state != "pending" or any(nodes[key].state in _OPEN for key in _sources(node)):
            continue
        closure = _close_reason(node, nodes, decisions, value.aborted)
        if closure is None:
            return ReadinessOutput(next=node.node_id, terminal=())
        return ReadinessOutput(next=None, terminal=((node.node_id, *closure),))
    return ReadinessOutput(next=None, terminal=())


def body_status(states: Iterable[GraphState], *, tuning: bool) -> BodyStatus:
    """Aggregate one body; `skipped` is neutral, a selected arm's rejection still counts."""
    decided = frozenset(states)
    if "failed" in decided:
        return "failed"
    if "rejected" in decided:
        return "rejected"
    return "completed" if tuning else "accepted"


def readiness_input(
    slots: Iterable[GraphNodeEvidence],
    decided: Mapping[str, GraphNodeEvidence],
    *,
    aborted: bool,
    decisions: tuple[RouteEvaluationOutput, ...] = (),
    routing: Mapping[str, NodeRouting] | None = None,
) -> ReadinessInput:
    """Project declared graph slots plus decided terminal evidence into readiness input."""
    routes = routing or {}

    def project(slot: GraphNodeEvidence) -> NodeReadiness:
        item = decided.get(slot.node_id)
        routing = routes.get(slot.node_id, NodeRouting())
        # Declared dependency facts list every merge candidate; readiness consumes only
        # the selected one, so candidates leave the AND set (PR2 refuses a plain
        # dependence on a merged arm, so nothing required is dropped).
        merged = frozenset(_merged(routing))
        return NodeReadiness(
            node_id=slot.node_id,
            predecessors=tuple(key for key in slot.predecessors if key not in merged),
            state="pending" if item is None else item.state,
            reason=None if item is None else item.reason,
            routing=routing,
        )

    return ReadinessInput(
        nodes=tuple(project(slot) for slot in slots),
        aborted=aborted,
        decisions=decisions,
    )
