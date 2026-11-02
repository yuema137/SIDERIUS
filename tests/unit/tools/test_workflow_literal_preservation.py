"""Issue 961: unrelated browser edits must not rewrite Professional source values."""

import json
import math
from pathlib import Path

import pytest

from tests.unit.tools.test_workflow_node_edits import editor_for
from tools.workflow_authoring.models import ReviewRequest, SaveRequest
from workflows.definition import parse_workflow_source
from workflows.definition.source_updates import update_workflow_source

EXAMPLE = (
    Path(__file__).resolve().parents[3] / "examples/workflow_declarations/reusable_training.py"
)


def literal_source() -> str:
    source = EXAMPLE.read_text().replace(
        '"trial_time_budget_minutes": 2.0,',
        '"trial_time_budget_minutes": 2.0,\n'
        '            "formal_vram_budget_gb": 1e-3,\n'
        '            "degenerate_penalty_score": -0.0,\n'
        '            "max_steps_per_attempt": 9007199254740993,\n'
        '            "human_advice_tune": "\\u96ea\\n",\n'
        '            "trial_max_epochs": None,',
    )
    return source.replace(
        'positions=(NodePosition(node="build", x=120.0, y=-30.0),),',
        'positions=(NodePosition(node="build", x=120.0, y=-30.0), '
        'NodePosition(node="hypothesis", x=0.0, y=0.0), '
        'NodePosition(node="check", x=640.0, y=0.0), '
        'NodePosition(node="fit", x=960.0, y=0.0)),',
    )


def _browser_number(value: str) -> int | float | None:
    number = float(value)
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def browser_document(source: str) -> dict:
    """Model Number losses; the browser witness exercises real JS serialization."""
    return json.loads(
        parse_workflow_source(source).model_dump_json(),
        parse_int=_browser_number,
        parse_float=_browser_number,
    )


@pytest.mark.parametrize("integer", ["9007199254740993", "1" + "0" * 310])
@pytest.mark.parametrize("edit", ["none", "task", "training", "position", "draft", "nodes"])
def test_browser_review_and_save_preserve_untouched_literals(tmp_path, edit, integer):
    """Byte equality catches type, notation, precision, escape and comment losses."""
    source = literal_source().replace("9007199254740993", integer)
    editor = editor_for(tmp_path, source)
    base = editor.read()
    document = browser_document(source)
    expected = source
    if edit == "task":
        document["definition"]["task"]["manifest"] = "changed.yaml"
        expected = source.replace('"task.yaml"', "'changed.yaml'")
    elif edit in ("training", "draft", "nodes"):
        document["training_settings"]["launch"]["formal_time_budget_minutes"] = 7
        expected = source.replace(
            '"formal_time_budget_minutes": 5.0', '"formal_time_budget_minutes": 7.0'
        )
    elif edit == "position":
        document["positions"][0]["x"] = 321
        expected = source.replace("x=120.0", "x=321.0")
    proposal = {"kind": "document", "document": document, "source": source}
    if edit == "draft":
        proposal = {
            "kind": "draft",
            "source": source,
            "draft": {"base_document": document, "bindings": []},
        }
    elif edit == "nodes":
        proposal = {
            "kind": "node_drafts",
            "source": source,
            "document": document,
            "externals": [{"id": "extra", "contract": "storage"}],
        }
    review = editor.review(
        ReviewRequest.model_validate_json(
            json.dumps(
                {
                    "expected_sha256": base.sha256,
                    "proposal": proposal,
                }
            )
        )
    )
    if edit != "nodes":
        assert review.source == expected
    else:
        for literal in ("1e-3", "-0.0", integer, '"\\u96ea\\n"'):
            assert literal in review.source
        assert '"formal_time_budget_minutes": 7.0' in review.source
    saved = editor.save(
        SaveRequest(
            source=review.source, proposal_sha256=review.sha256, expected_sha256=base.sha256
        )
    )
    assert editor.project.source_file.read_bytes() == review.source.encode()
    assert saved.unchanged == (edit == "none")


def test_recursive_changes_keep_sibling_literals_and_exact_source_edit_semantics():
    source = literal_source().replace("\n", "\r\n")
    document = parse_workflow_source(source)
    payload = document.model_dump(mode="json")
    payload["training_settings"]["launch"]["formal_vram_budget_gb"] = 0.5
    changed = type(document).model_validate_json(json.dumps(payload))
    assert update_workflow_source(source, changed) == source.replace("1e-3", "0.5")
    payload["training_settings"]["launch"]["trial_time_budget_minutes"] = 2
    changed = type(document).model_validate_json(json.dumps(payload))
    assert '"trial_time_budget_minutes": 2,' in update_workflow_source(source, changed)


@pytest.mark.parametrize("kind", ["document", "draft"])
def test_browser_overflow_is_restored_before_document_admission(kind):
    """Removing transport recovery rejects a valid authored iteration budget as null."""
    source = EXAMPLE.with_name("research_loop_request_input.py").read_text()
    source = source.replace("final_iteration=3,", "final_iteration=" + "1" + "0" * 310 + ",")
    document = browser_document(source)
    assert document["definition"]["loop"]["final_iteration"] is None
    proposal = {"kind": kind, "source": source}
    if kind == "document":
        proposal["document"] = document
    else:
        proposal["draft"] = {"base_document": document, "bindings": []}
    request = ReviewRequest.model_validate_json(
        json.dumps({"expected_sha256": "0" * 64, "proposal": proposal})
    )
    admitted = request.proposal
    if admitted.kind == "draft":
        restored = admitted.draft.base_document
    else:
        assert admitted.kind == "document"
        restored = admitted.document
    assert restored == parse_workflow_source(source)


def test_source_less_document_review_preserves_browser_rounded_literals(tmp_path):
    """Legacy proposals need disk-source comparison; no transport anchor is supplied."""
    source = literal_source()
    editor = editor_for(tmp_path, source)
    base = editor.read()
    document = browser_document(source)
    document["definition"]["task"]["manifest"] = "changed.yaml"
    request = ReviewRequest.model_validate_json(
        json.dumps(
            {
                "expected_sha256": base.sha256,
                "proposal": {"kind": "document", "document": document},
            }
        )
    )
    review = editor.review(request)
    assert review.source == source.replace('"task.yaml"', "'changed.yaml'")
    editor.save(
        SaveRequest(
            source=review.source, proposal_sha256=review.sha256, expected_sha256=base.sha256
        )
    )
    assert editor.project.source_file.read_bytes() == review.source.encode()


@pytest.mark.parametrize("anchor", [True, False])
def test_intentional_browser_edit_preserves_authored_float_type(tmp_path, anchor):
    """Review and saved bytes must retain float type after a changed integer input."""
    source = literal_source()
    editor = editor_for(tmp_path, source)
    base = editor.read()
    document = browser_document(source)
    document["training_settings"]["launch"]["trial_time_budget_minutes"] = 3
    proposal = {"kind": "document", "document": document}
    if anchor:
        proposal["source"] = source
    review = editor.review(
        ReviewRequest.model_validate_json(
            json.dumps(
                {
                    "expected_sha256": base.sha256,
                    "proposal": proposal,
                }
            )
        )
    )
    expected = source.replace(
        '"trial_time_budget_minutes": 2.0', '"trial_time_budget_minutes": 3.0'
    )
    assert review.source == expected
    editor.save(
        SaveRequest(
            source=review.source, proposal_sha256=review.sha256, expected_sha256=base.sha256
        )
    )
    assert editor.project.source_file.read_bytes() == expected.encode()
