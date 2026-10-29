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
from workflows.definition.catalog import CAPABILITIES, COLLECTION_CONTRACTS, PROTOCOLS
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
    # A collect/v1 adaptor assembles collection contracts; they are never externals.
    results = {item.output for item in CAPABILITIES.values()} | set(COLLECTION_CONTRACTS.values())
    assert sockets - results <= entries.keys() and not results & entries.keys()
    assert all(entry.summary for entry in entries.values())
    assert entries["storage"].managed and not entries["literature.input"].managed
    assert not entries["llm-provider"].managed


def test_deleting_a_read_node_succeeds_as_a_draft_with_not_connected_problems(tmp_path):
    """Fails if a draft deletion is refused (operator rule: delete always succeeds in the
    draft), if the reader of the deleted node loses its located problem, or if review
    saves an invalid document; rewiring the reader to a pending node then reviews."""
    source = commented_canonical()
    editor = editor_for(tmp_path, source)
    deleted = drafts(source, removed=("implement",))
    view = editor.inspect_node_drafts(
        NodeDraftsRequest(expected_sha256=editor.read().sha256, proposal=deleted)
    )
    assert view.status == "incomplete"
    assert {(item.code, item.node, item.field) for item in view.problems} == {
        ("required_unbound", "validate", "output")
    }
    ports = {(port.node, port.argument): port for port in view.ports}
    assert "implement.result" not in [c.label for c in ports[("validate", "output")].choices]
    with pytest.raises(AuthoringError) as refused:
        review(editor, deleted)
    assert refused.value.code == "draft_incomplete"
    rewired = drafts(
        source,
        pending(
            "build2", "proposal-to-implementation", 400.0, output="propose", storage="@storage"
        ),
        removed=("implement",),
        bindings=(
            BindingPatch(node="validate", argument="output", source=ResultSource(node="build2")),
        ),
    )
    reviewed = review(editor, rewired)
    assert [node.id for node in reviewed.document.definition.nodes] == [
        "propose",
        "validate",
        "build2",
    ]
    assert reviewed.node_edit is not None and reviewed.node_edit.removed == ("implement",)
    assert editor.project.source_file.read_text() == source, "review never writes"


def test_deleting_every_module_is_a_problem_not_a_refusal(tmp_path):
    """Fails if emptying the canvas is refused outright (it is a draft state) or if an
    empty workflow can be reviewed for saving."""
    source = commented_canonical()
    editor = editor_for(tmp_path, source)
    everything = drafts(source, removed=("propose", "implement", "validate"))
    view = editor.inspect_node_drafts(
        NodeDraftsRequest(expected_sha256=editor.read().sha256, proposal=everything)
    )
    assert view.status == "incomplete"
    assert "workflow_empty" in {item.code for item in view.problems}
    with pytest.raises(AuthoringError) as refused:
        review(editor, everything)
    assert refused.value.code == "draft_incomplete"


def test_problems_after_emptying_a_loop_workflow_name_only_what_remains(tmp_path):
    """Fails if an emptied canvas lists more than "add at least one module", or if adding
    one incomplete module hides the loop problem while its feedback endpoints are still
    deleted (red-team E-1: the pending node's missing input used to short-circuit)."""
    from tests.browser.workflow_editor_server import interpretation_profile_source

    source = interpretation_profile_source()
    editor = editor_for(tmp_path, source)
    sha = editor.read().sha256
    every = tuple(node.id for node in parse_workflow_source(source).definition.nodes)
    emptied = editor.inspect_node_drafts(
        NodeDraftsRequest(expected_sha256=sha, proposal=drafts(source, removed=every))
    )
    assert [(item.code, item.message) for item in emptied.problems] == [
        ("workflow_empty", "add at least one module")
    ]
    one = drafts(
        source,
        pending("build2", "proposal-to-implementation", 0.0, storage="@proposal_store"),
        removed=every,
    )
    view = editor.inspect_node_drafts(NodeDraftsRequest(expected_sha256=sha, proposal=one))
    assert {(item.code, item.node) for item in view.problems} == {
        ("loop_feedback_missing", None),
        ("required_unbound", "build2"),
    }
    unbound = next(item for item in view.problems if item.node == "build2")
    assert unbound.message == "build2.output: required input is not connected"


def test_deleting_an_unread_node_keeps_every_other_byte(tmp_path):
    """Fails if a draft deletion nobody reads re-renders the file (comments lost) instead
    of the targeted removal, so add-then-delete would no longer be byte-identical."""
    source = commented_canonical()
    editor = editor_for(tmp_path, source)
    reviewed = review(editor, drafts(source, removed=("validate",)))
    assert "# author note: keep me" in reviewed.source and "# trailing comment" in reviewed.source
    assert "id='validate'" not in reviewed.source
    changed = [
        line
        for line in difflib.ndiff(source.splitlines(True), reviewed.source.splitlines(True))
        if line[:1] in "+-"
    ]
    assert changed and all(line.startswith("- ") for line in changed), "only deletions"


def test_deleting_a_node_drops_its_managed_storage_binding(tmp_path):
    """Fails if a deleted node's generated storage binding stays behind: candidate
    preparation refuses unused external bindings, so the saved workflow could not run."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[3] / "examples/workflow_declarations/reusable_candidate.py"
    ).read_text()
    editor = editor_for(tmp_path, source)
    reviewed = review(editor, drafts(source, removed=("check",)))
    externals = {item.id for item in reviewed.document.definition.externals}
    assert "check_store" not in externals and "build_store" in externals


def test_framework_supplied_inputs_are_marked_only_where_preparation_supplies_them():
    """Fails if a generated input (managed per-node storage, managed proposal request)
    is presented as a user requirement, or if a v1 source's literal storage (which the
    author must supply) is hidden; the roles come from candidate preparation."""
    from pathlib import Path

    from tools.workflow_authoring.options import binding_projection, managed_roles

    root = Path(__file__).resolve().parents[3]
    reusable = parse_workflow_source(
        (root / "examples/workflow_declarations/reusable_candidate.py").read_text()
    )
    supplied = {
        (port.node, port.argument)
        for port in binding_projection(reusable)[1]
        if port.framework_supplied
    }
    assert supplied == {("hypothesis", None), ("build", "storage"), ("check", "storage")}
    assert ("storage", "storage") in {(r.contract, r.argument) for r in managed_roles(reusable)}
    legacy = parse_workflow_source(commented_canonical())
    assert not any(port.framework_supplied for port in binding_projection(legacy)[1])
    assert managed_roles(legacy) == ()


def test_blank_then_rebuilt_reusable_workflow_reviews_with_managed_storage(tmp_path):
    """Fails if replacing every module (Blank, then new Propose/Implement/Validate with
    managed storage) is refused because old and new modules were validated together, or
    if the deleted modules' generated bindings survive."""
    from pathlib import Path

    from workflows.definition import ManagedCandidateBinding

    source = (
        Path(__file__).resolve().parents[3] / "examples/workflow_declarations/reusable_candidate.py"
    ).read_text()
    editor = editor_for(tmp_path, source)
    proposal = drafts(
        source,
        {
            "node": "proposal",
            "capability": "proposal",
            "protocol": None,
            "binding": "proposal_initial",
            "x": 0.0,
            "y": 0.0,
        },
        pending(
            "implementation",
            "proposal-to-implementation",
            300.0,
            output="proposal",
            storage="@implementation_store",
        ),
        pending(
            "validation",
            "implementation-to-validation",
            600.0,
            output="implementation",
            storage="@validation_store",
        ),
        externals=(
            ManagedCandidateBinding(id="proposal_initial", contract="proposal.input"),
            ManagedCandidateBinding(id="implementation_store", contract="storage"),
            ManagedCandidateBinding(id="validation_store", contract="storage"),
        ),
        removed=("hypothesis", "build", "check"),
    )
    reviewed = review(editor, proposal)
    ids = {item.id for item in reviewed.document.definition.externals}
    assert {"implementation_store", "validation_store", "proposal_initial"} <= ids
    assert not ids & {"initial", "build_store", "check_store"}
    assert [node.id for node in reviewed.document.definition.nodes] == [
        "proposal",
        "implementation",
        "validation",
    ]
