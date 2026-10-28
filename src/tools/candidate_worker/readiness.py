"""Single authority for serial graph readiness: which declared node acts next.

Both the child dispatcher (`graph.execute_fanout`) and the receipt verifier
(`graph_evidence.verify_graph_trace`) consume `next_dispatch`, so execution and
replay cannot drift. The function is pure: no workspace, no native records.
"""

from collections.abc import Iterable, Mapping

from pydantic import model_validator

from .graph_models import GraphNodeEvidence, GraphReason, GraphState
from .loop_stop import StopModel

# States in which a node has not yet reached a terminal outcome.
_OPEN: frozenset[GraphState] = frozenset(("pending", "running"))


class NodeReadiness(StopModel):
    """One declared node as readiness sees it; `pending` means not yet decided."""

    node_id: str
    predecessors: tuple[str, ...]
    state: GraphState


class ReadinessInput(StopModel):
    nodes: tuple[NodeReadiness, ...]  # declaration order
    aborted: bool  # an earlier native failure stops every later effect

    @model_validator(mode="after")
    def _closed_graph(self) -> "ReadinessInput":
        ids = [node.node_id for node in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("readiness node ids must be unique")
        if any(key not in ids for node in self.nodes for key in node.predecessors):
            raise ValueError("readiness predecessor is not a declared node")
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


def _close_reason(
    node: NodeReadiness, states: Mapping[str, GraphState], aborted: bool
) -> GraphReason | None:
    """Per-node rule for a node whose predecessors are all terminal.

    Returns the reason to close it without dispatch, or None when it may run.
    Today: AND over predecessor success plus failure stop. Additional node
    classes (e.g. adaptors that accept any terminal source) extend this hook.
    """
    if aborted or any(states[key] != "succeeded" for key in node.predecessors):
        return "dependency_not_successful"
    return None


def next_dispatch(value: ReadinessInput) -> ReadinessOutput:
    """Decide the first undecided node, in declaration order, whose inputs are terminal."""
    states: dict[str, GraphState] = {node.node_id: node.state for node in value.nodes}
    for node in value.nodes:
        if node.state != "pending" or any(states[key] in _OPEN for key in node.predecessors):
            continue
        reason = _close_reason(node, states, value.aborted)
        if reason is None:
            return ReadinessOutput(next=node.node_id, terminal=())
        return ReadinessOutput(next=None, terminal=((node.node_id, "blocked", reason),))
    return ReadinessOutput(next=None, terminal=())


def readiness_input(
    slots: Iterable[GraphNodeEvidence], decided: Mapping[str, GraphState], *, aborted: bool
) -> ReadinessInput:
    """Project declared graph slots plus decided terminal states into readiness input."""
    return ReadinessInput(
        nodes=tuple(
            NodeReadiness(
                node_id=slot.node_id,
                predecessors=slot.predecessors,
                state=decided.get(slot.node_id, "pending"),
            )
            for slot in slots
        ),
        aborted=aborted,
    )
