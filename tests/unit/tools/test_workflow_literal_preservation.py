"""Issue 961: unrelated browser edits must not rewrite Professional source values."""

import json
import subprocess
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


def browser_document(source: str) -> dict:
    """Use actual JS serialization, including binary64 integer rounding."""
    return json.loads(
        subprocess.run(
            [
                "node",
                "-e",
                "let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s))))",
            ],
            input=parse_workflow_source(source).model_dump_json(),
            text=True,
            capture_output=True,
            check=True,
        ).stdout
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
            '"formal_time_budget_minutes": 5.0', '"formal_time_budget_minutes": 7'
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
        assert '"formal_time_budget_minutes": 7' in review.source
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
