"""
Tests for dashboard/data_sources/local_json.py

Uses synthetic in-memory fixtures written to a temp directory — no real
TIDMAD data required. Tests cover discovery, record retrieval, aggregates,
leaderboard, and edge cases (missing files, empty dirs, OOM records).
"""

import json
import os
import pytest

from dashboard.data_sources.local_json import LocalJsonDataSource


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_record(exp_id, status="success", score=None, loss_type="ce", epochs=10, model_type="punet"):
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
    """
    Builds a minimal synthetic data directory:

    tmp_path/
      punet/
        baseline/summary_baseline_punet.json   ← 1 baseline record
        v1/agent/summary_v1_agent.json          ← seeded baseline + 3 agent records
      wavenet/
        baseline/summary_baseline_wavenet.json  ← 1 baseline record
        (no agent runs)
    """
    root = str(tmp_path)

    # punet baseline
    _write_json(
        os.path.join(root, "punet", "baseline", "summary_baseline_punet.json"),
        [_make_record("baseline_punet_001", score=-2.1)],
    )

    # punet v1 agent (position 0 = seeded baseline, then 3 real agent records)
    _write_json(
        os.path.join(root, "punet", "v1", "agent", "summary_v1_agent.json"),
        [
            _make_record("baseline_punet_001", score=-2.1),           # seeded, must be excluded
            _make_record("punet_v1_agent_001", score=-2.0, loss_type="ce"),
            _make_record("punet_v1_agent_002", score=-1.8, loss_type="focal"),
            _make_record("punet_v1_agent_003", status="skipped_oom_risk", score=None),
        ],
    )

    # wavenet baseline only (no agent run)
    _write_json(
        os.path.join(root, "wavenet", "baseline", "summary_baseline_wavenet.json"),
        [_make_record("baseline_wavenet_001", score=-5.0, model_type="wavenet")],
    )

    return root


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

class TestDiscovery:
    def test_list_models_auto_discovers(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        assert set(ds.list_models()) == {"punet", "wavenet"}

    def test_list_models_respects_explicit_list(self, data_dir):
        ds = LocalJsonDataSource(data_dir, models=["punet"])
        assert ds.list_models() == ["punet"]

    def test_list_models_filters_missing_dirs(self, data_dir):
        ds = LocalJsonDataSource(data_dir, models=["punet", "transformer"])
        assert ds.list_models() == ["punet"]   # transformer dir doesn't exist

    def test_list_runs_includes_baseline(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        runs = ds.list_runs("punet")
        assert "baseline" in runs

    def test_list_runs_includes_agent_run(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        runs = ds.list_runs("punet")
        assert "v1" in runs

    def test_list_runs_no_agent_run(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        runs = ds.list_runs("wavenet")
        assert runs == ["baseline"]

    def test_list_runs_unknown_model_raises(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        with pytest.raises(KeyError):
            ds.list_runs("transformer")


# ---------------------------------------------------------------------------
# Record retrieval
# ---------------------------------------------------------------------------

class TestGetRunRecords:
    def test_baseline_returns_one_record(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        records, total = ds.get_run_records("punet", "baseline")
        assert total == 1
        assert records[0]["exp_id"] == "baseline_punet_001"

    def test_agent_run_excludes_seeded_baseline(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        records, total = ds.get_run_records("punet", "v1")
        exp_ids = [r["exp_id"] for r in records]
        assert "baseline_punet_001" not in exp_ids

    def test_agent_run_total_count(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        _, total = ds.get_run_records("punet", "v1")
        assert total == 3   # 2 success + 1 skipped_oom_risk

    def test_status_filter_success_only(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        records, total = ds.get_run_records("punet", "v1", status_filter="success")
        assert total == 2
        assert all(r["status"] == "success" for r in records)

    def test_status_filter_oom(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        records, total = ds.get_run_records("punet", "v1", status_filter="skipped_oom_risk")
        assert total == 1

    def test_pagination_limit(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        records, total = ds.get_run_records("punet", "v1", limit=2, offset=0)
        assert len(records) == 2
        assert total == 3

    def test_pagination_offset(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        records, total = ds.get_run_records("punet", "v1", limit=10, offset=2)
        assert len(records) == 1
        assert total == 3

    def test_unknown_run_raises(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        with pytest.raises(KeyError):
            ds.get_run_records("punet", "v99")


class TestGetExperiment:
    def test_returns_correct_record(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        rec = ds.get_experiment("punet", "v1", "punet_v1_agent_001")
        assert rec["exp_id"] == "punet_v1_agent_001"

    def test_unknown_exp_id_raises(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        with pytest.raises(KeyError):
            ds.get_experiment("punet", "v1", "does_not_exist")


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------

class TestModelOverview:
    def test_baseline_score(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        ov = ds.get_model_overview("punet")
        assert ov["baseline_score"] == pytest.approx(-2.1)

    def test_best_agent_score(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        ov = ds.get_model_overview("punet")
        assert ov["best_agent_score"] == pytest.approx(-1.8)

    def test_best_run_name(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        ov = ds.get_model_overview("punet")
        assert ov["best_run_name"] == "v1"

    def test_total_experiments_excludes_seeded_baseline(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        ov = ds.get_model_overview("punet")
        assert ov["total_experiments"] == 3   # 2 success + 1 skipped

    def test_status_counts(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        ov = ds.get_model_overview("punet")
        assert ov["status_counts"]["success"] == 2
        assert ov["status_counts"]["skipped_oom_risk"] == 1

    def test_runs_list(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        ov = ds.get_model_overview("punet")
        assert set(ov["runs"]) == {"baseline", "v1"}

    def test_no_agent_run_best_score_is_none(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        ov = ds.get_model_overview("wavenet")
        assert ov["best_agent_score"] is None

    def test_unknown_model_raises(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        with pytest.raises(KeyError):
            ds.get_model_overview("transformer")


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

class TestLeaderboard:
    def test_returns_ranked_entries(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        entries = ds.get_leaderboard("punet", top_n=10)
        scores = [e["denoising_score"] for e in entries]
        assert scores == sorted(scores, reverse=True)

    def test_rank_starts_at_one(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        entries = ds.get_leaderboard("punet")
        assert entries[0]["rank"] == 1

    def test_top_n_respected(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        entries = ds.get_leaderboard("punet", top_n=1)
        assert len(entries) == 1

    def test_skipped_oom_excluded_by_default(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        entries = ds.get_leaderboard("punet", status_filter="success")
        assert all(e["denoising_score"] is not None for e in entries)
        assert len(entries) == 2

    def test_entry_has_required_fields(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        entry = ds.get_leaderboard("punet")[0]
        for field in ("rank", "exp_id", "run_name", "denoising_score", "loss_type", "epochs"):
            assert field in entry

    def test_unknown_model_raises(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        with pytest.raises(KeyError):
            ds.get_leaderboard("transformer")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_existing_dir_is_healthy(self, data_dir):
        ds = LocalJsonDataSource(data_dir)
        assert ds.health_check() is True

    def test_missing_dir_is_unhealthy(self, tmp_path):
        ds = LocalJsonDataSource(str(tmp_path / "nonexistent"))
        assert ds.health_check() is False
