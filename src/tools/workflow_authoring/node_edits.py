"""Typed node add/remove proposals applied as targeted edits of the exact source.

The catalog decides which routes exist; the source parser and declaration
validator decide whether the result is a document. These helpers only locate
bytes, explain consequences and refuse edits that would need implicit rewiring.
"""

from workflows.definition import (
    AdaptorSource,
    AuthoredWorkflowDocument,
    ExternalRequest,
    ExternalSource,
    NodeInstance,
    NodePosition,
    ProtocolRequest,
    ResultSource,
    SelectedSource,
    parse_workflow_source,
)
from workflows.definition.source import WorkflowSourceError
from workflows.definition.source_edits import SourceEditError, insert_node, remove_nodes

from .models import AddNodeProposal, NodeDraftView, NodeEditSummary, RemoveNodeProposal
from .options import pending_node_ports


def _source_label(
    source: ExternalSource | ResultSource | SelectedSource | AdaptorSource,
) -> str:
    """Readable name of one argument source, for every source kind."""
    if isinstance(source, ResultSource):
        return f"{source.node}.result"
    if isinstance(source, SelectedSource):
        return f"{source.branch} selects " + " | ".join(
            f"{c.node}.result" for c in source.candidates
        )
    if isinstance(source, ExternalSource):
        return source.binding
    return f"{source.adaptor}.result" + ("" if source.index is None else f"[{source.index}]")


class NodeEditRefusal(ValueError):
    """A node edit the author must resolve first; ``code`` names the reason."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _node(proposal: AddNodeProposal) -> NodeInstance:
    request = (
        ExternalRequest(binding=proposal.binding or "")
        if proposal.protocol is None
        else ProtocolRequest(protocol=proposal.protocol, arguments=proposal.arguments)
    )
    return NodeInstance(id=proposal.node, capability=proposal.capability, request=request)


def _offered(document: AuthoredWorkflowDocument, proposal: AddNodeProposal) -> list[str]:
    """Bindings the catalog projection does not offer for their socket."""
    refused = []
    for port in pending_node_ports(document, proposal):
        if port.source is not None and port.source not in [item.source for item in port.choices]:
            refused.append(f"{port.node}.{port.argument or 'request'}: source is not offered")
    return refused


def add_node(proposal: AddNodeProposal) -> tuple[str, NodeEditSummary]:
    """Return proposed source with one inserted node, or refuse before rendering."""
    document = parse_workflow_source(proposal.source)
    if any(node.id == proposal.node for node in document.definition.nodes):
        raise NodeEditRefusal("node_edit", f"node id {proposal.node!r} already exists")
    if missing := proposal.missing_inputs():
        raise NodeEditRefusal("draft_incomplete", "\n".join(missing))
    if refused := _offered(document, proposal):
        raise NodeEditRefusal("draft_invalid", "\n".join(refused))
    try:
        source = insert_node(
            proposal.source,
            _node(proposal),
            NodePosition(node=proposal.node, x=proposal.x, y=proposal.y),
        )
    except SourceEditError as error:
        raise NodeEditRefusal("node_edit", str(error)) from error
    return source, NodeEditSummary(
        added=(proposal.node,),
        message=f"Adds {proposal.capability} node {proposal.node!r} and its layout position; "
        "all other source bytes are unchanged.",
    )


def inspect_node(proposal: AddNodeProposal) -> NodeDraftView:
    """Inert draft inspection: ports and diagnostics for a node that may be incomplete."""
    document = parse_workflow_source(proposal.source)
    ports = pending_node_ports(document, proposal)
    try:
        source, _ = add_node(proposal)
        parse_workflow_source(source)
    except NodeEditRefusal as error:
        status = "incomplete" if error.code == "draft_incomplete" else "invalid"
        return NodeDraftView(
            proposal=proposal, status=status, diagnostics=tuple(str(error).split("\n")), ports=ports
        )
    except WorkflowSourceError as error:
        return NodeDraftView(
            proposal=proposal,
            status="invalid",
            diagnostics=tuple(item.message for item in error.diagnostics),
            ports=ports,
        )
    return NodeDraftView(proposal=proposal, status="complete", ports=ports)


def remove_node(proposal: RemoveNodeProposal) -> tuple[str, NodeEditSummary]:
    """Remove nodes with their own inputs; refuse while a remaining node reads them."""
    definition = parse_workflow_source(proposal.source).definition
    removed = set(proposal.nodes)
    if unknown := removed - {node.id for node in definition.nodes}:
        raise NodeEditRefusal("node_edit", f"unknown node: {', '.join(sorted(unknown))}")
    if len(removed) == len(definition.nodes):
        raise NodeEditRefusal("node_dependants", "a workflow keeps at least one capability")
    blockers: list[str] = []
    incoming: list[str] = []
    loop = definition.loop
    if loop is not None and {loop.feedback.source.node, loop.feedback.target} & removed:
        blockers.append("the research loop feedback uses it (remove the research loop first)")
    for node in definition.nodes:
        if not isinstance(node.request, ProtocolRequest):
            continue
        for argument in node.request.arguments:
            source = argument.source
            label = _source_label(source)
            if node.id in removed:
                incoming.append(f"{label} -> {node.id}.{argument.name}")
            elif isinstance(source, ResultSource) and source.node in removed:
                blockers.append(f"{node.id}.{argument.name} reads {source.node}.result")
    names = ", ".join(proposal.nodes)
    if blockers:
        raise NodeEditRefusal(
            "node_dependants",
            f"Cannot remove {names}: "
            + "; ".join(blockers)
            + ". Rebind or remove those consumers first (or remove them together); "
            "nothing was changed.",
        )
    try:
        source = remove_nodes(proposal.source, proposal.nodes)
    except SourceEditError as error:
        raise NodeEditRefusal("node_edit", str(error)) from error
    # Consumers the check above does not name (routes, merges, adaptors) are caught by the
    # declaration validator: a removal is never returned as a dangling source.
    try:
        parse_workflow_source(source)
    except WorkflowSourceError as error:
        raise NodeEditRefusal(
            "node_dependants",
            f"Cannot remove {names}: "
            + "; ".join(item.message for item in error.diagnostics)
            + " Nothing was changed.",
        ) from error
    message = f"Removes {names} with its layout position"
    message += f" and its input connections ({'; '.join(incoming)})." if incoming else "."
    return source, NodeEditSummary(
        removed=proposal.nodes, disconnected=tuple(incoming), message=message
    )
