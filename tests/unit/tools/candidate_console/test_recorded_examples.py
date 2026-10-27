"""Historical candidate viewing stays allowlisted, typed, and read-only."""

from pathlib import Path

import pytest

from tools.candidate_console import CandidateConsole, RecordedExampleChoice
from tools.candidate_operations.models import OperationFailure


def test_recorded_example_must_be_strictly_below_candidate_root(console_config):
    root = Path(console_config.operation_store.candidate_roots[0])
    choice = RecordedExampleChoice(
        example_id="root",
        label="Candidate root itself",
        workspace=str(root),
        expected_run_id="a" * 32,
    )
    with pytest.raises(ValueError, match="inside a candidate root"):
        CandidateConsole(console_config.model_copy(update={"recorded_examples": (choice,)}))


def test_recorded_example_refuses_missing_or_unconfigured_records(console_config):
    root = Path(console_config.operation_store.candidate_roots[0])
    workspace = root / "recorded"
    control = workspace / "candidate_run"
    control.mkdir(parents=True)
    choice = RecordedExampleChoice(
        example_id="tess",
        label="TESS recorded candidate",
        workspace=str(workspace),
        expected_run_id="b" * 32,
    )
    service = CandidateConsole(console_config.model_copy(update={"recorded_examples": (choice,)}))

    assert service.recorded_example_choices()[0].model_dump() == {
        "example_id": "tess",
        "label": "TESS recorded candidate",
    }
    with pytest.raises(OperationFailure, match="not configured"):
        service.recorded_example("other")
    with pytest.raises(OperationFailure, match="evidence is incomplete"):
        service.recorded_example("tess")
    assert list(control.iterdir()) == []
    assert list(workspace.iterdir()) == [control]
