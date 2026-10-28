"""Multi-node drafts and new external inputs: one review over several pending additions.

Each test names a defect the single-node path or the declaration validator alone
cannot see: a second pending node refused or re-rendered, pending nodes unable to
read each other or a new external, an existing socket unable to read a pending
result, an incomplete draft reaching the file, or an input contract offered with
no explanation or with an unsupported managed route.
"""

import difflib

import pytest

from tests.unit.tools.test_workflow_node_edits import commented_canonical, editor_for, review
from tools.workflow_authoring.external_inputs import external_input_catalog
from tools.workflow_authoring.models import NodeDraftsProposal, NodeDraftsRequest, SaveRequest
from tools.workflow_authoring.service import AuthoringError
from workflows.definition import (
    ArgumentBinding,
    ExternalBinding,
    ExternalSource,
    ManagedCandidateBinding,
    ProtocolRequest,
    ResultSource,
    parse_workflow_source,
)
from workflows.definition.catalog import CAPABILITIES, PROTOCOLS
from workflows.definition.draft import BindingPatch

STORE = ExternalBinding(id="store2", contract="storage", location="inputs/store2.json")


def pending(node: str, protocol: str, x: float, **arguments: str) -> dict:
    """A pending node; ``@name`` binds an external, any other value a result."""
    capability = next(
        name for name, item in CAPABILITIES.items() if item.input == PROTOCOLS[protocol].output
    )
    return {
        "node": node,
        "capability": capability,
        "protocol": protocol,
        "arguments": tuple(
            ArgumentBinding(
                name=name,
                source=ExternalSource(binding=value[1:])
                if value.startswith("@")
                else ResultSource(node=value),
            )
            for name, value in arguments.items()
        ),
        "x": x,
        "y": 200.0,
    }


def drafts(source: str, *nodes: dict, **update) -> NodeDraftsProposal:
    return NodeDraftsProposal(kind="node_drafts", source=source, nodes=nodes, **update)


def test_two_pending_nodes_reading_each_other_and_a_new_external_keep_every_byte(tmp_path):
    """Fails if a multi-node review re-renders the file, refuses pending-to-pending wiring
    or cannot bind a new external input that only exists in the same draft."""
    source = commented_canonical()
    editor = editor_for(tmp_path, source)
    proposal = drafts(
        source,
        pending("build2", "proposal-to-implementation", 400.0, output="propose", storage="@store2"),
        pending(
            "check2", "implementation-to-validation", 700.0, output="build2", storage="@store2"
        ),
        externals=(STORE,),
    )
    reviewed = review(editor, proposal)
    changed = [
        line
        for line in difflib.ndiff(source.splitlines(True), reviewed.source.splitlines(True))
        if line[:1] in "+-"
    ]
    assert changed and all(line.startswith("+ ") for line in changed)
    assert reviewed.node_edit is not None and reviewed.node_edit.added == ("build2", "check2")
    definition = reviewed.document.definition
    assert "store2" in {item.id for item in definition.externals}
    check = next(node for node in definition.nodes if node.id == "check2")
    assert isinstance(check.request, ProtocolRequest)
    assert check.request.arguments[0].source == ResultSource(node="build2")
    sha = editor.read().sha256
    editor.save(
        SaveRequest(source=reviewed.source, proposal_sha256=reviewed.sha256, expected_sha256=sha)
    )
    saved = editor.project.source_file.read_text()
    assert "# implement keeps its comment" in saved and "# trailing comment" in saved
    assert [p.node for p in parse_workflow_source(saved).positions] == [
        "propose",
        "build2",
        "check2",
    ]


def test_incomplete_draft_locates_problems_offers_draft_sources_and_never_saves(tmp_path):
    """Fails if unbound inputs of any pending node reach review, if problems lose their
    node/field, or if choices omit pending results and new externals."""
    source = commented_canonical()
    editor = editor_for(tmp_path, source)
    proposal = drafts(
        source,
        pending("build2", "proposal-to-implementation", 400.0, output="propose"),
        pending("check2", "implementation-to-validation", 700.0),
        externals=(STORE,),
    )
    view = editor.inspect_node_drafts(
        NodeDraftsRequest(expected_sha256=editor.read().sha256, proposal=proposal)
    )
    assert view.status == "incomplete"
    assert {(item.node, item.field) for item in view.problems} == {
        ("build2", "storage"),
        ("check2", "output"),
        ("check2", "storage"),
    }
    ports = {(port.node, port.argument): port for port in view.ports}
    assert [c.label for c in ports[("check2", "output")].choices] == [
        "implement.result",
        "build2.result",
    ]
    assert [c.label for c in ports[("build2", "storage")].choices] == ["storage", "store2"]
    # Existing sockets are offered the draft's sources too (wire old -> new).
    assert "build2.result" in [c.label for c in ports[("validate", "output")].choices]
    with pytest.raises(AuthoringError) as refused:
        review(editor, proposal)
    assert refused.value.code == "draft_incomplete"
    assert editor.project.source_file.read_text() == source


def test_existing_socket_rewired_to_a_pending_node_reviews_the_combined_document(tmp_path):
    """Fails if a binding patch on a saved node cannot read a pending node's result,
    or if a moved saved card is dropped from a node draft review."""
    source = commented_canonical()
    editor = editor_for(tmp_path, source)
    base = parse_workflow_source(source)
    moved = base.model_copy(
        update={"positions": (base.positions[0].model_copy(update={"x": 55.0}),)}
    )
    proposal = drafts(
        source,
        pending(
            "build2", "proposal-to-implementation", 400.0, output="propose", storage="@storage"
        ),
        document=moved,
        bindings=(
            BindingPatch(node="validate", argument="output", source=ResultSource(node="build2")),
        ),
    )
    reviewed = review(editor, proposal)
    validate = next(node for node in reviewed.document.definition.nodes if node.id == "validate")
    assert isinstance(validate.request, ProtocolRequest)
    assert validate.request.arguments[0].source == ResultSource(node="build2")
    assert reviewed.document.positions[0].x == 55.0


def test_managed_external_in_a_v1_source_is_reported_invalid_not_saved(tmp_path):
    """Fails if a managed input (reusable v2 only) is admitted into a v1 declaration."""
    source = commented_canonical()
    editor = editor_for(tmp_path, source)
    proposal = drafts(
        source,
        pending(
            "build2", "proposal-to-implementation", 400.0, output="propose", storage="@managed"
        ),
        externals=(ManagedCandidateBinding(id="managed", contract="storage"),),
    )
    view = editor.inspect_node_drafts(
        NodeDraftsRequest(expected_sha256=editor.read().sha256, proposal=proposal)
    )
    assert view.status == "invalid" and view.diagnostics


def test_external_input_catalog_explains_every_socket_contract():
    """Fails if a socket contract an author must supply has no creation entry (the
    inspector would offer no way to set it), or if managed literature (which needs
    explicit settings) or a capability result is offered as an external input."""
    entries = {item.contract.id: item for item in external_input_catalog().entries}
    sockets = {item.contract for protocol in PROTOCOLS.values() for item in protocol.arguments}
    sockets |= {item.input for item in CAPABILITIES.values()}
    results = {item.output for item in CAPABILITIES.values()}
    assert sockets - results <= entries.keys() and not results & entries.keys()
    assert all(entry.summary for entry in entries.values())
    assert entries["storage"].managed and not entries["literature.input"].managed
    assert not entries["llm-provider"].managed
