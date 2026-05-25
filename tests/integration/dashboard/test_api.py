"""
Integration tests for the dashboard REST API (dashboard/api/router.py).

Uses FastAPI's TestClient with a real LocalJsonDataSource pointed at a
synthetic temp directory — no real TIDMAD data required, no network calls.
"""

import json
import os

import pytest
from fastapi.testclient import TestClient

from dashboard.api import router as router_module
from dashboard.api.models import FrontendConfig
from dashboard.data_sources.local_json import LocalJsonDataSource
from dashboard.main import create_app
from dashboard.settings import DashboardSettings, load_settings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_record(
    exp_id, status="success", score=None, loss_type="ce", epochs=10, model_type="punet"
):
    return {
        "exp_id": exp_id,
        "status": status,
        "model_type": model_type,
        "timestamp": "2026-01-01 00:00:00",
        "denoising_score": score,
        "params": {
            "model_config": {},
            "train_config": {"lr": 0.001, "epochs": epochs, "batch_size": 4, "device": "cpu"},
            "loss_config": {"loss_type": loss_type},
        },
        "results": {"final_loss": 0.5, "model_params": 1000},
        "memory": {"hypothesis": "test", "conclusion": "ok"},
    }


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


@pytest.fixture
def data_dir(tmp_path):
    root = str(tmp_path)
    _write_json(
        os.path.join(root, "punet", "baseline", "summary_baseline_punet.json"),
        [_make_record("baseline_punet_001", score=-2.1)],
    )
    _write_json(
        os.path.join(root, "punet", "v1", "agent", "summary_v1_agent.json"),
        [
            _make_record("baseline_punet_001", score=-2.1),  # seeded
            _make_record("punet_v1_agent_001", score=-2.0, loss_type="ce"),
            _make_record("punet_v1_agent_002", score=-1.8, loss_type="focal"),
            _make_record("punet_v1_agent_003", status="skipped_oom_risk", score=None),
        ],
    )
    _write_json(
        os.path.join(root, "wavenet", "baseline", "summary_baseline_wavenet.json"),
        [_make_record("baseline_wavenet_001", score=-5.0, model_type="wavenet")],
    )
    return root


@pytest.fixture
def client(data_dir):
    """TestClient wired to a real LocalJsonDataSource over synthetic data."""
    import tempfile
    import textwrap

    import yaml as _yaml

    cfg_path = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    _yaml.dump(
        {
            "data_source": {"type": "local", "local": {"root_data_dir": data_dir, "models": []}},
            "server": {"host": "127.0.0.1", "port": 8000},
            "dashboard": {"refresh_interval_seconds": 30, "default_run_name": "v1"},
        },
        cfg_path,
    )
    cfg_path.close()

    from dashboard.settings import load_settings

    settings = load_settings(cfg_path.name)
    app = create_app(settings)
    os.unlink(cfg_path.name)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_ok_status(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.json()["readable"] is True

    def test_data_source_type(self, client):
        r = client.get("/api/health")
        assert r.json()["data_source_type"] == "local"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestConfig:
    def test_returns_refresh_interval(self, client):
        r = client.get("/api/config")
        assert r.status_code == 200
        assert r.json()["refresh_interval_seconds"] == 30

    def test_returns_models(self, client):
        r = client.get("/api/config")
        assert set(r.json()["models"]) == {"punet", "wavenet"}

    def test_default_run_name(self, client):
        r = client.get("/api/config")
        assert r.json()["default_run_name"] == "v1"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_list_models(self, client):
        r = client.get("/api/models")
        assert r.status_code == 200
        assert set(r.json()["models"]) == {"punet", "wavenet"}

    def test_model_overview(self, client):
        r = client.get("/api/models/punet")
        assert r.status_code == 200
        body = r.json()
        assert body["model"] == "punet"
        assert body["baseline_score"] == pytest.approx(-2.1)
        assert body["best_agent_score"] == pytest.approx(-1.8)
        assert body["total_experiments"] == 3

    def test_model_not_found(self, client):
        r = client.get("/api/models/transformer")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


class TestRuns:
    def test_list_runs(self, client):
        r = client.get("/api/models/punet/runs")
        assert r.status_code == 200
        assert set(r.json()["runs"]) == {"baseline", "v1"}

    def test_get_run_records(self, client):
        r = client.get("/api/models/punet/runs/v1")
        assert r.status_code == 200
        body = r.json()
        assert body["total_count"] == 3
        assert len(body["records"]) == 3

    def test_seeded_baseline_excluded(self, client):
        r = client.get("/api/models/punet/runs/v1")
        exp_ids = [rec["exp_id"] for rec in r.json()["records"]]
        assert "baseline_punet_001" not in exp_ids

    def test_status_filter(self, client):
        r = client.get("/api/models/punet/runs/v1?status=success")
        body = r.json()
        assert body["total_count"] == 2
        assert all(rec["status"] == "success" for rec in body["records"])

    def test_pagination_limit(self, client):
        r = client.get("/api/models/punet/runs/v1?limit=1")
        assert len(r.json()["records"]) == 1
        assert r.json()["total_count"] == 3

    def test_run_not_found(self, client):
        r = client.get("/api/models/punet/runs/v99")
        assert r.status_code == 404

    def test_baseline_run(self, client):
        r = client.get("/api/models/punet/runs/baseline")
        assert r.status_code == 200
        assert r.json()["total_count"] == 1


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------


class TestExperiments:
    def test_get_experiment(self, client):
        r = client.get("/api/models/punet/runs/v1/experiments/punet_v1_agent_001")
        assert r.status_code == 200
        assert r.json()["exp_id"] == "punet_v1_agent_001"

    def test_experiment_not_found(self, client):
        r = client.get("/api/models/punet/runs/v1/experiments/does_not_exist")
        assert r.status_code == 404

    def test_internal_run_name_not_in_response(self, client):
        r = client.get("/api/models/punet/runs/v1/experiments/punet_v1_agent_001")
        assert "_run_name" not in r.json()


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------


class TestLeaderboard:
    def test_ranked_by_score(self, client):
        r = client.get("/api/models/punet/leaderboard")
        assert r.status_code == 200
        entries = r.json()["entries"]
        scores = [e["denoising_score"] for e in entries]
        assert scores == sorted(scores, reverse=True)

    def test_top_n_param(self, client):
        r = client.get("/api/models/punet/leaderboard?top_n=1")
        assert len(r.json()["entries"]) == 1

    def test_rank_field(self, client):
        r = client.get("/api/models/punet/leaderboard")
        assert r.json()["entries"][0]["rank"] == 1

    def test_model_not_found(self, client):
        r = client.get("/api/models/transformer/leaderboard")
        assert r.status_code == 404
