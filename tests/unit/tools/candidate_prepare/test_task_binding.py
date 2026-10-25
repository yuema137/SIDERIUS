"""Bound declarations refuse before external reads or run admission effects."""

import hashlib
from pathlib import Path

import pytest

from tests.unit.tools.candidate_prepare.test_reusable_preparation import reusable as reusable
from tools.candidate_prepare import (
    inspect_reusable_source,
    preflight_reusable_candidate,
    reusable_admission,
)
from workflows.definition import TaskBinding, parse_workflow_source, render_workflow_source


def test_bound_preparation_refuses_before_task_reads_and_envelope(reusable, monkeypatch):
    """Dropping the A1 source guard reaches forbidden manifest/config read or resolution."""
    source = Path(reusable.source_path)
    document = parse_workflow_source(source.read_text()).model_copy(
        update={
            "task_binding": TaskBinding(
                package_id="synthetic",
                revision="one",
                task_data_path_id="synthetic_path",
                semantic_fingerprint="a" * 64,
            )
        }
    )
    source.write_text(render_workflow_source(document))
    request = reusable.model_copy(
        update={"expected_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    )
    monkeypatch.setattr(
        reusable_admission,
        "reusable_locations",
        lambda *args: pytest.fail("bound source reached native resolution"),
    )
    before = tuple(Path(request.runs_root).iterdir())
    for action in (inspect_reusable_source, preflight_reusable_candidate):
        with pytest.raises(ValueError, match="bound workflow preparation is unsupported"):
            action(request)
    assert tuple(Path(request.runs_root).iterdir()) == before
