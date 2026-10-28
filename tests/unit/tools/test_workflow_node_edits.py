"""Node add/remove proposals: targeted source edits, refusals and HTTP draft routes.

Each test names a defect the declaration validator alone cannot see: a lost
comment or byte, a non-catalog capability accepted, an implicit rewire of a
required consumer, or an incomplete node reaching the saved file.
"""

import difflib

import pytest
from pydantic import ValidationError

from tests.unit.tools.test_workflow_authoring import SOURCE
from tests.unit.workflows.test_workflow_definition import definition
from tools.workflow_authoring.models import (
    AddNodeProposal,
    NodeDraftRequest,
    Project,
    RemoveNodeProposal,
    ReviewRequest,
    SaveRequest,
)
from tools.workflow_authoring.node_edits import add_node, remove_node
from tools.workflow_authoring.service import AuthoringError, WorkflowAuthoring
from workflows.definition import (
    ArgumentBinding,
    ExternalSource,
    NodePosition,
    ResultSource,
    WorkflowDocument,
    parse_workflow_source,
)
from workflows.definition.source import render_workflow_source

BOUND = (
    ArgumentBinding(name="output", source=ResultSource(node="implement")),
    ArgumentBinding(name="storage", source=ExternalSource(binding="storage")),
)


def commented_canonical() -> str:
    """Canonical source plus author comments at file, node and trailing positions."""
    source = render_workflow_source(
        WorkflowDocument(
            definition=definition(), positions=(NodePosition(node="propose", x=0.0, y=0.0),)
        )
    )
    source = source.replace("document = ", "# author note: keep me\ndocument = ")
    source = source.replace(
        "            NodeInstance(\n                id='implement'",
        "            # implement keeps its comment\n            NodeInstance(\n                id='implement'",
    )
    return source + "# trailing comment\n"


def editor_for(tmp_path, source: str) -> WorkflowAuthoring:
    path = tmp_path / "workflow.py"
    path.write_text(source)
    recovery = tmp_path / "recovery"
    recovery.mkdir(mode=0o700)
    return WorkflowAuthoring(
        Project(
            project_id="t", project_root=tmp_path, source_file=path, recovery_directory=recovery
        )
    )


def add(source: str, **update) -> AddNodeProposal:
    values = {
        "kind": "add_node",
        "source": source,
        "node": "validate2",
        "capability": "validation",
        "protocol": "implementation-to-validation",
        "x": 400.0,
        "y": 80.0,
    }
    return AddNodeProposal(**(values | update))


def review(editor: WorkflowAuthoring, proposal):
    return editor.review(ReviewRequest(expected_sha256=editor.read().sha256, proposal=proposal))


def test_add_then_remove_preserves_comments_and_every_other_byte(tmp_path):
    """Fails if a node edit re-renders the file (comments lost) or removal leaves residue."""
    source = commented_canonical()
    editor = editor_for(tmp_path, source)
    added = review(editor, add(source, arguments=BOUND))
    assert added.node_edit is not None and added.node_edit.added == ("validate2",)
    # The diff only inserts lines: no existing byte, comment or format changes.
    changed = [
        line
        for line in difflib.ndiff(source.splitlines(True), added.source.splitlines(True))
        if line[:1] in "+-"
    ]
    assert changed and all(line.startswith("+ ") for line in changed)
    assert {"validate2"} <= {node.id for node in added.document.definition.nodes}
    assert [p.node for p in added.document.positions] == ["propose", "validate2"]
    removed = review(
        editor, RemoveNodeProposal(kind="remove_node", source=added.source, nodes=("validate2",))
    )
    assert removed.source == source


def test_inline_source_gains_imports_and_positions_and_keeps_comments(tmp_path):
    """Fails if a one-line (non-canonical) source cannot take a node without re-rendering."""
    source = "# header comment\n" + SOURCE.replace("))\n", "))  # tail comment\n")
    editor = editor_for(tmp_path, source)
    proposal = AddNodeProposal(
        kind="add_node",
        source=source,
        node="implement",
        capability="implementation",
        protocol="proposal-to-implementation",
        arguments=(
            ArgumentBinding(name="output", source=ResultSource(node="p")),
            ArgumentBinding(name="storage", source=ExternalSource(binding="store")),
        ),
        x=1.0,
        y=2.0,
    )
    # "store" is not declared: the catalog projection refuses it before rendering.
    with pytest.raises(AuthoringError) as refused:
        review(editor, proposal)
    assert refused.value.code == "draft_invalid"
    proposal = proposal.model_copy(update={"arguments": proposal.arguments[:1]})
    with pytest.raises(AuthoringError) as incomplete:
        review(editor, proposal)
    assert incomplete.value.code == "draft_incomplete"
    assert "implement.storage: required input is unbound" in str(incomplete.value)
    widened = source.replace(
        'location="old.json"),)',
        'location="old.json"), ExternalBinding(id="store", contract="storage", location="s.json"))',
    )
    editor.project.source_file.write_text(widened)
    proposal = proposal.model_copy(
        update={
            "source": widened,
            "arguments": (
                *proposal.arguments,
                ArgumentBinding(name="storage", source=ExternalSource(binding="store")),
            ),
        }
    )
    added = review(editor, proposal)
    assert "# header comment" in added.source and "# tail comment" in added.source
    assert added.source.startswith("# header comment\n" + widened.split("\n")[1])
    assert "ProtocolRequest" in added.source.split("\n")[1]
    back = review(
        editor, RemoveNodeProposal(kind="remove_node", source=added.source, nodes=("implement",))
    )
    assert back.document == parse_workflow_source(widened)
    assert "# tail comment" in back.source


@pytest.mark.parametrize(
    ("update", "message"),
    [
        ({"capability": "teleport"}, "not in the native catalog"),
        ({"protocol": "proposal-to-implementation"}, "does not produce"),
        (
            {"arguments": [{"name": "bogus", "source": {"kind": "external", "binding": "s"}}]},
            "unique protocol sockets",
        ),
    ],
)
def test_non_catalog_routes_are_refused_by_the_request_schema(update, message):
    """Fails if a capability/protocol/socket outside the server catalog reaches source editing."""
    payload = add("x").model_dump(mode="json") | update
    with pytest.raises(ValidationError, match=message):
        ReviewRequest.model_validate({"expected_sha256": "0" * 64, "proposal": payload})


def test_remove_refuses_dependants_and_explains_removed_connections(tmp_path):
    """Fails if removal silently breaks a consumer, or hides the connections it drops."""
    source = commented_canonical()
    editor = editor_for(tmp_path, source)
    with pytest.raises(AuthoringError) as refused:
        review(editor, RemoveNodeProposal(kind="remove_node", source=source, nodes=("implement",)))
    assert refused.value.code == "node_dependants"
    assert "validate.output reads implement.result" in str(refused.value)
    assert editor.project.source_file.read_text() == source
    # Removing the whole dependent chain together is allowed and explained.
    chain = review(
        editor,
        RemoveNodeProposal(kind="remove_node", source=source, nodes=("implement", "validate")),
    )
    assert [node.id for node in chain.document.definition.nodes] == ["propose"]
    assert "# implement keeps its comment" in chain.source
    assert chain.node_edit is not None
    assert chain.node_edit.disconnected == (
        "propose.result -> implement.output",
        "storage -> implement.storage",
        "implement.result -> validate.output",
        "storage -> validate.storage",
    )
    with pytest.raises(AuthoringError, match="at least one capability"):
        review(
            editor,
            RemoveNodeProposal(
                kind="remove_node", source=source, nodes=("propose", "implement", "validate")
            ),
        )


def test_remove_refuses_a_research_loop_endpoint(tmp_path):
    """Fails if removing a loop endpoint reaches the validator instead of an explanation."""
    from tools.workflow_authoring.loop import loop_template
    from workflows.definition import ExternalBinding, ExternalRequest, NodeInstance, ProtocolRequest

    graph = definition()
    graph = graph.model_copy(
        update={
            "externals": (
                *graph.externals,
                ExternalBinding(id="evidence", contract="interpretation.input", location="e.json"),
                ExternalBinding(id="settings", contract="native-training.settings", location="t"),
            ),
            "nodes": (
                *graph.nodes,
                NodeInstance(
                    id="tune",
                    capability="tuning",
                    request=ProtocolRequest(
                        protocol="validated-candidate-to-tuning",
                        arguments=(
                            ArgumentBinding(
                                name="validation", source=ResultSource(node="validate")
                            ),
                            ArgumentBinding(name="proposal", source=ResultSource(node="propose")),
                            ArgumentBinding(
                                name="settings", source=ExternalSource(binding="settings")
                            ),
                        ),
                    ),
                ),
                NodeInstance(
                    id="interpret",
                    capability="interpretation",
                    request=ExternalRequest(binding="evidence"),
                ),
            ),
        }
    )
    document = WorkflowDocument(definition=graph)
    looped = graph.model_copy(update={"loop": loop_template(document)})
    source = render_workflow_source(WorkflowDocument(definition=looped))
    editor = editor_for(tmp_path, source)
    with pytest.raises(AuthoringError, match="research loop feedback uses it"):
        review(editor, RemoveNodeProposal(kind="remove_node", source=source, nodes=("interpret",)))


def test_incomplete_node_is_draft_only_and_complete_node_saves(tmp_path):
    """Fails if an unbound required input reaches review/save or the draft lacks its ports."""
    source = commented_canonical()
    editor = editor_for(tmp_path, source)
    sha = editor.read().sha256
    draft = editor.inspect_node_draft(NodeDraftRequest(expected_sha256=sha, proposal=add(source)))
    assert draft.status == "incomplete"
    assert {port.argument: port.required for port in draft.ports}["output"] is True
    output = next(port for port in draft.ports if port.argument == "output")
    assert [choice.label for choice in output.choices] == ["implement.result"]
    with pytest.raises(AuthoringError) as refused:
        review(editor, add(source))
    assert refused.value.code == "draft_incomplete"
    assert editor.project.source_file.read_text() == source
    complete = editor.inspect_node_draft(
        NodeDraftRequest(expected_sha256=sha, proposal=add(source, arguments=BOUND))
    )
    assert complete.status == "complete" and complete.diagnostics == ()
    reviewed = review(editor, add(source, arguments=BOUND))
    editor.save(
        SaveRequest(source=reviewed.source, proposal_sha256=reviewed.sha256, expected_sha256=sha)
    )
    saved = editor.project.source_file.read_text()
    assert "# author note: keep me" in saved and "# trailing comment" in saved
    assert "validate2" in {node.id for node in parse_workflow_source(saved).definition.nodes}


INLINE_PAIR = (
    SOURCE.replace(" ExternalRequest\n", " ExternalRequest, NodePosition\n")
    .replace(
        '(binding="seed")),)',
        '(binding="seed")),  # a, b\n NodeInstance(id="q", capability="proposal", '
        'request=ExternalRequest(binding="seed")))',
    )
    .replace(
        "))\n",
        '), positions=(NodePosition(node="p", x=0.0, y=0.0), NodePosition(node="q", x=1.0, y=1.0)))\n',
    )
)


def test_removing_the_first_of_two_comma_less_elements_keeps_a_tuple():
    """Fails if ``(A, B)`` minus ``A`` leaves ``(B)``: a parenthesised value, not a tuple."""
    from workflows.definition.source_edits import remove_nodes

    source = INLINE_PAIR.replace("),  # a, b\n", "), ")
    assert 'NodePosition(node="q", x=1.0, y=1.0)))' in source  # no trailing comma in either
    left = remove_nodes(source, ("p",))
    document = parse_workflow_source(left)
    assert [node.id for node in document.definition.nodes] == ["q"]
    assert [position.node for position in document.positions] == ["q"]


def test_removal_keeps_a_comment_owned_by_the_previous_element():
    """Fails if removing the last element also deletes the comment trailing its predecessor."""
    from workflows.definition.source_edits import remove_nodes

    left = remove_nodes(INLINE_PAIR, ("q",))
    assert '(binding="seed")),  # a, b\n' in left
    assert [node.id for node in parse_workflow_source(left).definition.nodes] == ["p"]


def test_insertion_leaves_a_trailing_comment_on_its_own_element():
    """Fails if a new node is spliced between the last node and its trailing comment."""
    source = commented_canonical().replace(
        "            ),\n        ),\n    ),\n    positions=(",
        "            ),  # last node note\n        ),\n    ),\n    positions=(",
    )
    added = add_node(add(source, arguments=BOUND))[0]
    assert (
        "            ),  # last node note\n            NodeInstance(\n                id='validate2'"
        in added
    )
    back = remove_node(RemoveNodeProposal(kind="remove_node", source=added, nodes=("validate2",)))
    assert back[0] == source


def test_crlf_source_round_trips_byte_identically():
    """Fails if inserted lines use bare LF in a CRLF file, or add-then-remove changes bytes."""
    source = commented_canonical().replace("\n", "\r\n")
    added = add_node(add(source, arguments=BOUND))[0]
    assert "validate2" in added and "\n" not in added.replace("\r\n", "")
    back = remove_node(RemoveNodeProposal(kind="remove_node", source=added, nodes=("validate2",)))
    assert back[0] == source
