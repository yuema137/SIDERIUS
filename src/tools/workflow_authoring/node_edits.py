"""Typed node add/remove proposals applied as targeted edits of the exact source.

The catalog decides which routes exist; the source parser and declaration
validator decide whether the result is a document. These helpers only locate
bytes, explain consequences and refuse edits that would need implicit rewiring.
"""

import json

from pydantic import ValidationError

from workflows.definition import (
    AdaptorSource,
    AuthoredWorkflowDocument,
    ExternalRequest,
    ExternalSource,
    ManagedCandidateBinding,
    NodeInstance,
    NodePosition,
    ProtocolRequest,
    ResultSource,
    SelectedSource,
    parse_workflow_source,
)
from workflows.definition.catalog import PROTOCOLS
from workflows.definition.draft import BindingPatch, DraftProblem, WorkflowDraft, inspect_draft
from workflows.definition.source import WorkflowSourceError, render_workflow_source
from workflows.definition.source_edits import (
    SourceEditError,
    insert_external,
    insert_node,
    remove_nodes,
)

from .models import (
    AddNodeProposal,
    NodeDraftsProposal,
    NodeDraftsView,
    NodeDraftView,
    NodeEditSummary,
    PendingNode,
    PortInventoryEntry,
    RemoveNodeProposal,
)
from .options import binding_projection, pending_node_ports


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

    def __init__(self, code: str, message: str, problems: tuple[DraftProblem, ...] = ()) -> None:
        self.code, self.problems = code, problems
        super().__init__(message)


def _node(proposal: PendingNode) -> NodeInstance:
    request = (
        ExternalRequest(binding=proposal.binding or "")
        if proposal.protocol is None
        else ProtocolRequest(protocol=proposal.protocol, arguments=proposal.arguments)
    )
    return NodeInstance(id=proposal.node, capability=proposal.capability, request=request)


def _offered(document: AuthoredWorkflowDocument, proposal: PendingNode) -> list[str]:
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


def _projection(
    proposal: NodeDraftsProposal,
) -> tuple[AuthoredWorkflowDocument, AuthoredWorkflowDocument]:
    """The edited base document and an unvalidated choice projection that adds the draft.

    The projection only feeds ``port_choices`` (ids, capabilities, contracts); it is
    never validated, rendered or returned, because pending nodes may be incomplete.
    """
    base = proposal.document or parse_workflow_source(proposal.source)
    definition = base.definition
    removed = set(proposal.removed)
    pending = tuple(
        NodeInstance.model_construct(id=item.node, capability=item.capability)
        for item in proposal.nodes
    )
    projected = type(definition).model_construct(
        **{
            **{name: getattr(definition, name) for name in type(definition).model_fields},
            "externals": (*definition.externals, *proposal.externals),
            # Deleted nodes offer no result to any socket.
            "nodes": (*(node for node in definition.nodes if node.id not in removed), *pending),
        }
    )
    return base, type(base).model_construct(
        **{
            **{name: getattr(base, name) for name in type(base).model_fields},
            "definition": projected,
        }
    )


def node_drafts_ports(proposal: NodeDraftsProposal) -> tuple[PortInventoryEntry, ...]:
    """Ports of every projected node; choices include pending results and new externals."""
    base, projected = _projection(proposal)
    existing = binding_projection(base, choices_from=projected)[1]
    return existing + tuple(
        port for item in proposal.nodes for port in pending_node_ports(projected, item)
    )


def _removal(
    base: AuthoredWorkflowDocument, proposal: NodeDraftsProposal
) -> tuple[tuple[BindingPatch, ...], tuple[DraftProblem, ...]]:
    """Disconnect patches for inputs that read a deleted node, plus removal problems.

    Explicit patches of the proposal win; every other reader of a deleted result is
    disconnected (a required one then reports ``required_unbound`` in inspection).
    """
    removed = set(proposal.removed)
    definition = base.definition
    unknown = removed - {node.id for node in definition.nodes}
    if unknown:
        raise NodeEditRefusal("node_edit", f"unknown node: {', '.join(sorted(unknown))}")
    patched = {(item.node, item.argument) for item in proposal.bindings}
    patches = list(proposal.bindings)
    for node in definition.nodes:
        if node.id in removed or not isinstance(node.request, ProtocolRequest):
            continue
        for argument in node.request.arguments:
            source = argument.source
            if (
                isinstance(source, ResultSource)
                and source.node in removed
                and (node.id, argument.name) not in patched
            ):
                patches.append(BindingPatch(node=node.id, argument=argument.name, source=None))
    if len(removed) == len(definition.nodes) and not proposal.nodes:
        # An empty canvas has one thing to fix; the loop problem returns with the first module.
        return tuple(patches), (
            DraftProblem(code="workflow_empty", message="add at least one module"),
        )
    loop = definition.loop
    if loop is not None and {loop.feedback.source.node, loop.feedback.target} & removed:
        # Stays while either endpoint is deleted, whatever else the draft adds.
        return tuple(patches), (
            DraftProblem(
                code="loop_feedback_missing",
                message="the research loop feeds back between deleted modules; "
                "add them back or remove the research loop",
            ),
        )
    return tuple(patches), ()


def _used_bindings(nodes) -> set[str]:
    """External binding ids that these nodes' requests read."""
    used: set[str] = set()
    for node in nodes:
        if isinstance(node.request, ExternalRequest):
            used.add(node.request.binding)
            continue
        used.update(
            item.source.binding
            for item in node.request.arguments
            if isinstance(item.source, ExternalSource)
        )
    return used


def _orphaned_managed(document: AuthoredWorkflowDocument, removed: set[str]) -> set[str]:
    """Managed bindings that only deleted nodes read: preparation refuses unused bindings."""
    nodes = document.definition.nodes
    lost = _used_bindings(nodes) - _used_bindings(node for node in nodes if node.id not in removed)
    return {
        item.id
        for item in document.definition.externals
        if isinstance(item, ManagedCandidateBinding) and item.id in lost
    }


def _remaining(
    base: AuthoredWorkflowDocument,
    proposal: NodeDraftsProposal,
    patches: tuple[BindingPatch, ...],
    orphans: set[str],
) -> tuple[dict, list[DraftProblem]]:
    """The document payload without the deleted nodes, their positions and orphaned managed
    bindings, with every binding patch applied, plus the remaining nodes' missing inputs.

    Built before validation: a document holding both a deleted node and its replacement
    (e.g. two proposals) need not be valid. Problems name only nodes that remain.
    """
    removed = set(proposal.removed)
    payload = base.model_dump(mode="json")
    definition = payload["definition"]
    definition["externals"] = [
        item for item in definition["externals"] if item["id"] not in orphans
    ] + [item.model_dump(mode="json") for item in proposal.externals]
    definition["nodes"] = [node for node in definition["nodes"] if node["id"] not in removed]
    payload["positions"] = [item for item in payload["positions"] if item["node"] not in removed]
    problems: list[DraftProblem] = []
    for node in definition["nodes"]:
        request = node["request"]
        mine = [patch for patch in patches if patch.node == node["id"]]
        if request["kind"] == "external":
            for patch in mine:
                if patch.source is None:
                    problems.append(_required(node["id"], "request"))
                elif isinstance(patch.source, ExternalSource):
                    request["binding"] = patch.source.binding
            continue
        arguments = {item["name"]: item for item in request["arguments"]}
        for patch in mine:
            if patch.argument is None:
                continue
            if patch.source is None:
                arguments.pop(patch.argument, None)
            else:
                arguments[patch.argument] = {
                    "name": patch.argument,
                    "source": patch.source.model_dump(mode="json"),
                }
        request["arguments"] = list(arguments.values())
        problems.extend(
            _required(node["id"], item.name)
            for item in PROTOCOLS[request["protocol"]].arguments
            if item.required and item.name not in arguments
        )
    return payload, problems


def _deleted(
    base: AuthoredWorkflowDocument, proposal: NodeDraftsProposal, payload: dict
) -> AuthoredWorkflowDocument:
    """The complete remaining ``payload`` (see ``_remaining``) with the pending additions,
    validated by the native document model."""
    definition = payload["definition"]
    definition["nodes"].extend(_node(item).model_dump(mode="json") for item in proposal.nodes)
    payload["positions"].extend(
        NodePosition(node=item.node, x=item.x, y=item.y).model_dump(mode="json")
        for item in proposal.nodes
    )
    try:
        return type(base).model_validate_json(json.dumps(payload))
    except ValidationError as error:
        raise NodeEditRefusal(
            "draft_invalid", "\n".join(item["msg"] for item in error.errors(include_url=False))
        ) from error


def _required(node: str, field: str) -> DraftProblem:
    return DraftProblem(
        code="required_unbound",
        node=node,
        field=field,
        message=f"{node}.{field}: required input is not connected",
    )


def _collisions(base: AuthoredWorkflowDocument, proposal: NodeDraftsProposal) -> list[str]:
    nodes = {node.id for node in base.definition.nodes}
    externals = {item.id for item in base.definition.externals}
    return [
        f"node id {item.node!r} already exists" for item in proposal.nodes if item.node in nodes
    ] + [
        f"external input id {item.id!r} already exists"
        for item in proposal.externals
        if item.id in externals
    ]


def apply_node_drafts(proposal: NodeDraftsProposal) -> tuple[str, NodeEditSummary]:
    """Return proposed source for every pending addition, or refuse before rendering.

    Without existing-content edits the anchor bytes stay and each addition is a
    targeted insertion; otherwise the combined document is rendered canonically.
    The caller re-parses the result with the declaration validator.
    """
    base, projected = _projection(proposal)
    if collisions := _collisions(base, proposal):
        raise NodeEditRefusal("node_edit", "\n".join(collisions))
    removed = set(proposal.removed)
    patches, removal_problems = _removal(base, proposal) if removed else (proposal.bindings, ())
    orphans = _orphaned_managed(base, removed) if removed else set()
    remaining, reader_problems = (
        _remaining(base, proposal, patches, orphans) if removed else (None, [])
    )
    # Every problem of the draft at once: a pending node's missing input must not hide
    # the loop or a remaining reader (they are all fixed before saving).
    problems = (
        *removal_problems,
        *reader_problems,
        *(problem for item in proposal.nodes for problem in item.missing_problems()),
    )
    if problems:
        raise NodeEditRefusal(
            "draft_incomplete", "\n".join(item.message for item in problems), problems
        )
    refused = [message for item in proposal.nodes for message in _offered(projected, item)]
    if refused:
        raise NodeEditRefusal("draft_invalid", "\n".join(refused))
    if proposal.document is None and not patches and not removal_problems and not orphans:
        # Targeted edits: deletions without readers and insertions keep every other byte.
        source = proposal.source
        try:
            if removed:
                source = remove_nodes(source, proposal.removed)
            for external in proposal.externals:
                source = insert_external(source, external)
            for item in proposal.nodes:
                source = insert_node(
                    source, _node(item), NodePosition(node=item.node, x=item.x, y=item.y)
                )
        except SourceEditError as error:
            raise NodeEditRefusal("node_edit", str(error)) from error
        kept = "all other source bytes are unchanged."
    elif remaining is not None:
        source = render_workflow_source(_deleted(base, proposal, remaining))
        kept = "the other edits of this draft are rendered as canonical source."
    else:
        payload = base.model_dump(mode="json")
        payload["definition"]["externals"].extend(
            item.model_dump(mode="json") for item in proposal.externals
        )
        payload["definition"]["nodes"].extend(
            _node(item).model_dump(mode="json") for item in proposal.nodes
        )
        payload["positions"].extend(
            NodePosition(node=item.node, x=item.x, y=item.y).model_dump(mode="json")
            for item in proposal.nodes
        )
        try:
            combined = type(base).model_validate_json(json.dumps(payload))
        except ValidationError as error:
            raise NodeEditRefusal(
                "draft_invalid",
                "\n".join(item["msg"] for item in error.errors(include_url=False)),
            ) from error
        inspection = inspect_draft(WorkflowDraft(base_document=combined, bindings=patches))
        if inspection.document is None:
            raise NodeEditRefusal(
                "draft_" + inspection.status,
                "\n".join(inspection.diagnostics),
                inspection.problems,
            )
        source = render_workflow_source(inspection.document)
        kept = "the other edits of this draft are rendered as canonical source."
    added = tuple(item.node for item in proposal.nodes)
    parts = [f"{len(added)} node(s) ({', '.join(added)}) with layout positions"] if added else []

    if proposal.externals:
        parts.append(
            f"{len(proposal.externals)} external input(s) "
            f"({', '.join(item.id for item in proposal.externals)})"
        )
    clauses = [f"Adds {' and '.join(parts)}"] if parts else []
    if removed:
        clauses.append(f"Removes {len(removed)} node(s) ({', '.join(proposal.removed)})")
    return source, NodeEditSummary(
        added=added, removed=proposal.removed, message=f"{'; '.join(clauses)}; {kept}"
    )


def inspect_node_drafts(proposal: NodeDraftsProposal) -> NodeDraftsView:
    """Inert inspection of a multi-node draft that may be incomplete; nothing is saved."""
    ports = node_drafts_ports(proposal)
    try:
        source, _ = apply_node_drafts(proposal)
        parse_workflow_source(source)
    except NodeEditRefusal as error:
        status = "incomplete" if error.code == "draft_incomplete" else "invalid"
        return NodeDraftsView(
            status=status,
            diagnostics=tuple(str(error).split("\n")),
            problems=error.problems,
            ports=ports,
        )
    except WorkflowSourceError as error:
        return NodeDraftsView(
            status="invalid",
            diagnostics=tuple(item.message for item in error.diagnostics),
            ports=ports,
        )
    return NodeDraftsView(status="complete", ports=ports)
