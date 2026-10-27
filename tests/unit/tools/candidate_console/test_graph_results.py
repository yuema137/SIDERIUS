"""Read-only typed graph-result HTTP projection."""

from uuid import uuid4

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
