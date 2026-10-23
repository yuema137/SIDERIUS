"""Reusable source fixture loaded strictly from the current checkout."""

from pathlib import Path

from workflows.definition import ReusableWorkflowDocument, parse_workflow_source

EXAMPLE = (
    Path(__file__).resolve().parents[3] / "examples/workflow_declarations/reusable_candidate.py"
)


def reusable() -> ReusableWorkflowDocument:
    document = parse_workflow_source(EXAMPLE.read_text())
    assert isinstance(document, ReusableWorkflowDocument)
    return document
