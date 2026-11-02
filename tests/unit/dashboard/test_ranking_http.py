"""Ranking decisions and diagnostics must survive the real dashboard HTTP boundary."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.recorders import LocalRecorder
from dashboard.main import create_app
from dashboard.settings import DashboardSettings

_UNAVAILABLE = "metric direction unavailable / metric_spec absent"


def _record(exp_id: str, score: float, metric: dict[str, str] | None) -> dict[str, object]:
    record: dict[str, object] = {
        "exp_id": exp_id,
        "model_type": "fixture",
        "status": "success",
        "denoising_score": score,
    }
    if metric is not None:
        record["metric_result"] = metric
    return record


def _client(tmp_path: Path, records: list[dict[str, object]]) -> TestClient:
    directory = tmp_path / "fixture" / "run" / "agent"
    recorder = LocalRecorder(str(directory), str(directory / "summary_run_agent.json"), "records")
    for record in records:
        recorder.save_record(record)
    settings = DashboardSettings.model_validate(
        {"data_source": {"type": "local", "local": {"root_data_dir": str(tmp_path)}}}
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


@pytest.mark.parametrize("direction,best", [("higher", 2.0), ("lower", 1.0)])
def test_legacy_row_does_not_poison_declared_ranking(
    tmp_path: Path, direction: str, best: float
) -> None:
    """An identity-free extreme score stays visible but cannot win on either axis."""
    metric = {"metric_id": "fixture_score", "direction": direction}
    records = [
        _record("legacy", 100.0, None),
        _record("one", 1.0, metric),
        _record("two", 2.0, metric),
    ]
    with _client(tmp_path, records) as client:
        response = client.get("/api/models/fixture/leaderboard")
        assert response.status_code == 200, response.text
        entries = response.json()["entries"]
        assert [entry["rank"] for entry in entries] == [1, 2, None]
        assert entries[0]["denoising_score"] == best
        assert entries[0]["metric_ranking"] is None
        assert entries[-1]["exp_id"] == "legacy"
        assert entries[-1]["denoising_score"] == 100.0
        assert entries[-1]["metric_ranking"] == _UNAVAILABLE
        response = client.get("/api/models/fixture")
        assert response.status_code == 200, response.text
        overview = response.json()
        assert overview["best_agent_score"] == best
        assert overview["best_run_name"] == "run"
        assert overview["metric_identity_unavailable_rows"] == 1
        assert overview["metric_ranking_unavailable"] is None


@pytest.mark.parametrize("conflicting", [False, True], ids=["legacy-only", "conflicting-metrics"])
def test_unrankable_corpus_exposes_reason_without_inventing_best(
    tmp_path: Path, conflicting: bool
) -> None:
    """Both missing and conflicting identities must be readable, never ranked."""
    first = {"metric_id": "metric_a", "direction": "higher"} if conflicting else None
    second = {"metric_id": "metric_b", "direction": "lower"} if conflicting else None
    with _client(tmp_path, [_record("one", 1.0, first), _record("two", 2.0, second)]) as client:
        response = client.get("/api/models/fixture/leaderboard")
        assert response.status_code == 200, response.text
        entries = response.json()["entries"]
        assert [entry["rank"] for entry in entries] == [None, None]
        assert [entry["denoising_score"] for entry in entries] == [1.0, 2.0]
        reason = entries[0]["metric_ranking"]
        assert _UNAVAILABLE in reason
        assert entries[1]["metric_ranking"] == reason
        if conflicting:
            assert "metric_a" in reason and "metric_b" in reason
            assert "incomparable" in reason
        response = client.get("/api/models/fixture")
        assert response.status_code == 200, response.text
        overview = response.json()
        assert overview["best_agent_score"] is None
        assert overview["best_run_name"] is None
        assert overview["total_experiments"] == 2
        assert overview["metric_identity_unavailable_rows"] == (0 if conflicting else 2)
        assert overview["metric_ranking_unavailable"] == reason
