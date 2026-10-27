"""Read-only typed graph-result HTTP projection."""

import json
from pathlib import Path
from uuid import uuid4

import pytest

from execute_tools.run_report import RunHeadline
from tools.candidate_console.models import (
    GraphBodyResult,
    GraphResultsView,
    GraphRunSummary,
)


def test_graph_results_route_is_typed_and_get_only(console_config, monkeypatch):
    from tests.unit.tools.candidate_console.test_http import client
    from tools.candidate_console.service import CandidateConsole

    operation_id = uuid4()
    projection = GraphResultsView(
        operation_id=operation_id,
        available=True,
        bodies=(
            GraphBodyResult(
                iteration=1,
                tuning_state="succeeded",
                result=GraphRunSummary(
                    run_name="fixture",
                    model_type="test-model",
                    status="completed",
                    termination_reason="completed",
                    started_at="2026-01-01T00:00:00Z",
                    finished_at="2026-01-01T00:00:01Z",
                    completed_rounds=1,
                    total_attempts=1,
                    metric=None,
                    metric_source="unavailable",
                    ranking_refusal="Metric unavailable.",
                    secondary_metrics=(),
                    headline=RunHeadline(
                        best_exp_id=None,
                        best_score=None,
                        best_formal_score=None,
                        best_valid_exp_id=None,
                        best_valid_score=None,
                        best_valid_formal_score=None,
                    ),
                    status_counts={"success": 1},
                ),
            ),
        ),
    )
    monkeypatch.setattr(CandidateConsole, "graph_results", lambda _self, _id: projection)

    with client(console_config) as api:
        response = api.get(f"/api/operations/{operation_id}/graph-results")
        assert response.status_code == 200
        assert response.json()["bodies"][0]["result"]["run_name"] == "fixture"

        # Verify that POST to the GET-only route is refused
        response = api.post(f"/api/operations/{operation_id}/graph-results", json={})
        assert response.status_code == 405


def test_graph_results_schema_invalid_record_yields_integrity_refusal(monkeypatch, tmp_path):
    """A digest-valid tuning record whose JSON schema is invalid yields 409 integrity."""
    import hashlib

    from tools.candidate_console.graph_results import _body_result
    from tools.candidate_operations.models import OperationFailure
    from tools.candidate_worker.graph_models import GraphNodeEvidence

    # Create a minimal valid JSON that doesn't match HyperparamTuningOutput schema
    schema_invalid_json = b'{"run_name": "test", "model_type": "test"}'
    digest = hashlib.sha256(schema_invalid_json).hexdigest()

    record_path = tmp_path / "tuning_output.json"
    record_path.write_bytes(schema_invalid_json)

    # Create a tuning node pointing to the schema-invalid record
    tuning = GraphNodeEvidence(
        node_id="tuning",
        capability="tuning",
        predecessors=(),
        storage=str(tmp_path),
        state="succeeded",
        record_path=str(record_path),
        record_sha256=digest,
    )

    # The schema-invalid record should be rejected with integrity error
    with pytest.raises(OperationFailure, match="unavailable") as refused:
        _body_result(iteration=1, tuning=tuning)
    assert refused.value.detail.code == "integrity"
    assert str(record_path) not in refused.value.detail.message
