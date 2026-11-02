"""Persisted record statuses must remain readable through the real HTTP app."""

import json
from pathlib import Path
from typing import get_args

import pytest
from fastapi.testclient import TestClient

from agent.schemas.hyperparam_tuning import ExperimentRecord as StoredRecord
from core.recorders import LocalRecorder
from dashboard.main import create_app
from dashboard.settings import DashboardSettings


def _reject_nonfinite(token: str) -> None:
    raise AssertionError(f"Non-JSON numeric token in HTTP response: {token}")


def _write_records(directory: Path, summary_name: str, status: str) -> None:
    recorder = LocalRecorder(str(directory), str(directory / summary_name), "records")
    for index, score in enumerate((0.5, float("nan"), float("inf"), float("-inf"))):
        recorder.save_record(
            {
                "exp_id": f"record_{index}",
                "model_type": "fixture",
                "status": status,
                "denoising_score": score,
                "final_loss": score,
                "file_vector": [score, None],
                "metric_result": {"metric_id": "fixture_score", "direction": "higher"},
            }
        )


@pytest.mark.parametrize("status", get_args(StoredRecord.model_fields["status"].annotation))
def test_current_record_statuses_cross_http_as_strict_json(tmp_path: Path, status: str) -> None:
    """A stale dashboard vocabulary or untyped response breaks these HTTP reads."""
    _write_records(tmp_path / "fixture" / "run" / "agent", "summary_run_agent.json", status)
    _write_records(
        tmp_path / "exploration" / "run" / "iteration_001" / "fixture",
        "summary_run.json",
        status,
    )
    settings = DashboardSettings.model_validate(
        {"data_source": {"type": "local", "local": {"root_data_dir": str(tmp_path)}}}
    )
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        schema = client.get("/api/openapi.json").json()
        status_schema = schema["components"]["schemas"]["ExperimentRecord"]["properties"]["status"]
        assert status in status_schema["enum"]
        for route in (
            "/api/models/fixture/runs/run",
            f"/api/models/fixture/runs/run?status={status}",
            f"/api/exploration/runs/run/models/fixture?status={status}",
        ):
            response = client.get(route)
            assert response.status_code == 200, (route, response.text)
            body = json.loads(response.text, parse_constant=_reject_nonfinite)
            assert body["total_count"] == 4
            assert [row["status"] for row in body["records"]] == [status] * 4
            assert [row["denoising_score"] for row in body["records"]] == [0.5, None, None, None]
        for index in range(4):
            response = client.get(f"/api/models/fixture/runs/run/experiments/record_{index}")
            assert response.status_code == 200, response.text
            body = json.loads(response.text, parse_constant=_reject_nonfinite)
            assert body["status"] == status
            expected = 0.5 if index == 0 else None
            assert body["denoising_score"] == expected
            assert body["final_loss"] == expected
            assert body["file_vector"] == [expected, None]
        overview = client.get("/api/models/fixture")
        assert overview.status_code == 200, overview.text
        body = json.loads(overview.text, parse_constant=_reject_nonfinite)
        assert body["status_counts"][status] == 4
        assert body["best_agent_score"] == 0.5
        leaderboard = client.get(f"/api/models/fixture/leaderboard?status={status}")
        assert leaderboard.status_code == 200, leaderboard.text
        body = json.loads(leaderboard.text, parse_constant=_reject_nonfinite)
        assert [row["exp_id"] for row in body["entries"]] == ["record_0"]
