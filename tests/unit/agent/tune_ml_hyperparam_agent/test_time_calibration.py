"""
Tests for agent/skills/evaluate_time_skill/calibration.py (Phase F).

Covers:
  - calibration_dir env-var override and default ~/.siderius
  - gpu_slug deterministic, fs-safe slugification
  - load_table / save_table round-trip with atomic write semantics
  - load_table defensive against missing file and corrupt JSON
  - lookup_k fallback chain: (gpu, model) → (gpu, *) → 1.0
  - update_k asymmetric EMA (α_up > α_down) and clipping
  - make_entry computes ratio, estimate_violated, ISO timestamp
  - detect_drift triggers only on N consecutive violations
"""
from __future__ import annotations

import json
import os

import pytest

from agent.skills.evaluate_time_skill import calibration as cal


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def test_calibration_dir_default(monkeypatch):
    monkeypatch.delenv(cal._ENV_VAR, raising=False)
    expected = os.path.join(os.path.expanduser("~"), cal._DEFAULT_SUBDIR)
    assert cal.calibration_dir() == expected


def test_calibration_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv(cal._ENV_VAR, str(tmp_path))
    assert cal.calibration_dir() == str(tmp_path)


def test_gpu_slug_lowercase_and_safe():
    assert cal.gpu_slug("NVIDIA GeForce RTX 5090") == "nvidia_geforce_rtx_5090"
    assert cal.gpu_slug("  Tesla  V100-SXM2-32GB  ") == "tesla_v100_sxm2_32gb"
    # Empty / pathological → fallback token, never blank
    assert cal.gpu_slug("???") == "unknown_gpu"
    assert cal.gpu_slug("") == "unknown_gpu"


def test_gpu_slug_is_deterministic():
    name = "NVIDIA A100-SXM4-80GB"
    assert cal.gpu_slug(name) == cal.gpu_slug(name)


def test_calibration_path_uses_slugged_filename(monkeypatch, tmp_path):
    monkeypatch.setenv(cal._ENV_VAR, str(tmp_path))
    p = cal.calibration_path("NVIDIA RTX 5090")
    assert p.startswith(str(tmp_path))
    assert p.endswith("time_calibration_nvidia_rtx_5090.json")


# ---------------------------------------------------------------------------
# load_table / save_table
# ---------------------------------------------------------------------------


def test_load_table_returns_empty_when_missing(monkeypatch, tmp_path):
    monkeypatch.setenv(cal._ENV_VAR, str(tmp_path))
    table = cal.load_table("RTX 5090")
    assert table == {"gpu_name": "RTX 5090", "k_values": {}, "history": []}


def test_load_table_defensive_against_corrupt_json(monkeypatch, tmp_path):
    monkeypatch.setenv(cal._ENV_VAR, str(tmp_path))
    path = cal.calibration_path("RTX 5090")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("{not: valid json")
    table = cal.load_table("RTX 5090")
    # Falls back to empty default rather than raising.
    assert table["k_values"] == {}
    assert table["history"] == []


def test_load_table_fills_missing_keys(monkeypatch, tmp_path):
    monkeypatch.setenv(cal._ENV_VAR, str(tmp_path))
    path = cal.calibration_path("RTX 5090")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"gpu_name": "RTX 5090"}, f)  # missing k_values, history
    table = cal.load_table("RTX 5090")
    assert table["k_values"] == {}
    assert table["history"] == []


def test_save_then_load_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv(cal._ENV_VAR, str(tmp_path))
    table = {
        "gpu_name": "RTX 5090",
        "k_values": {"wavenet": 1.42, "*": 1.10},
        "history": [{"foo": "bar"}],
    }
    cal.save_table("RTX 5090", table)
    loaded = cal.load_table("RTX 5090")
    assert loaded["k_values"] == {"wavenet": 1.42, "*": 1.10}
    assert loaded["history"] == [{"foo": "bar"}]


def test_save_is_atomic_no_tmp_left_behind(monkeypatch, tmp_path):
    """tmp file from `tempfile.mkstemp` should be renamed away — if the
    rename worked we expect exactly one file in the dir."""
    monkeypatch.setenv(cal._ENV_VAR, str(tmp_path))
    cal.save_table("RTX 5090", cal._empty_table("RTX 5090"))
    files = os.listdir(tmp_path)
    assert files == ["time_calibration_rtx_5090.json"]


# ---------------------------------------------------------------------------
# lookup_k fallback chain
# ---------------------------------------------------------------------------


def test_lookup_k_exact_match_wins():
    table = {"k_values": {"wavenet": 1.5, "*": 1.1}}
    assert cal.lookup_k(table, "wavenet") == 1.5


def test_lookup_k_falls_back_to_wildcard():
    table = {"k_values": {"wavenet": 1.5, "*": 1.1}}
    assert cal.lookup_k(table, "punet") == 1.1


def test_lookup_k_returns_one_when_neither_present():
    table = {"k_values": {}}
    assert cal.lookup_k(table, "anything") == 1.0


def test_lookup_k_handles_missing_k_values_key():
    assert cal.lookup_k({}, "anything") == 1.0


# ---------------------------------------------------------------------------
# make_entry
# ---------------------------------------------------------------------------


def test_make_entry_shape_and_ratio():
    e = cal.make_entry(
        gpu_name="RTX 5090",
        model_type="wavenet",
        seg_size=10000,
        batch_size=2,
        total_steps=1000,
        warmup_ms_per_step=10.0,
        actual_ms_per_step=15.0,
        estimated_minutes=20.0,
        actual_minutes=25.0,
    )
    assert e["ratio"] == pytest.approx(1.5)
    assert e["estimate_violated"] is True
    assert e["model_type"] == "wavenet"
    assert e["gpu_name"] == "RTX 5090"
    # Timestamp shape: ISO-8601 UTC (Z-suffixed)
    assert e["timestamp"].endswith("Z")


def test_make_entry_estimate_not_violated_when_under_budget():
    e = cal.make_entry(
        gpu_name="g", model_type="m", seg_size=1, batch_size=1,
        total_steps=1, warmup_ms_per_step=10.0, actual_ms_per_step=5.0,
        estimated_minutes=20.0, actual_minutes=10.0,
    )
    assert e["estimate_violated"] is False
    assert e["ratio"] == pytest.approx(0.5)


def test_make_entry_handles_zero_warmup_safely():
    e = cal.make_entry(
        gpu_name="g", model_type="m", seg_size=1, batch_size=1,
        total_steps=1, warmup_ms_per_step=0.0, actual_ms_per_step=5.0,
        estimated_minutes=1.0, actual_minutes=1.0,
    )
    # Ratio falls back to 1.0 when warmup is zero (avoids div-by-zero).
    assert e["ratio"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# update_k — asymmetric EMA and clipping
# ---------------------------------------------------------------------------


def _entry(model_type="m", ratio=1.0, violated=False):
    """Minimal entry for update_k tests."""
    return {
        "model_type": model_type,
        "ratio": ratio,
        "estimate_violated": violated,
    }


def test_update_k_uses_alpha_up_when_violated():
    """ratio=2.0, k_old=1.0, violated=True (α_up=0.5):
    k_new = 0.5 * 2.0 + 0.5 * 1.0 = 1.5"""
    table = {"k_values": {"m": 1.0}, "history": []}
    cal.update_k(table, _entry(ratio=2.0, violated=True))
    assert table["k_values"]["m"] == pytest.approx(1.5)


def test_update_k_uses_alpha_down_when_not_violated():
    """ratio=0.5, k_old=1.0, violated=False (α_down=0.1):
    k_new = 0.1 * 0.5 + 0.9 * 1.0 = 0.95"""
    table = {"k_values": {"m": 1.0}, "history": []}
    cal.update_k(table, _entry(ratio=0.5, violated=False))
    assert table["k_values"]["m"] == pytest.approx(0.95)


def test_update_k_starts_from_one_when_no_prior():
    """No prior entry for this model → k_old falls back to lookup_k = 1.0."""
    table = {"k_values": {}, "history": []}
    cal.update_k(table, _entry(ratio=2.0, violated=True))
    assert table["k_values"]["m"] == pytest.approx(1.5)


def test_update_k_falls_back_to_wildcard_when_model_unseen():
    """No (gpu, model) entry but a (gpu, *) wildcard exists → starts from
    the wildcard, then EMA-blends in the new ratio."""
    table = {"k_values": {"*": 1.4}, "history": []}
    cal.update_k(table, _entry(ratio=2.0, violated=True))
    # k_old = 1.4, alpha=0.5 → 0.5*2.0 + 0.5*1.4 = 1.7
    assert table["k_values"]["m"] == pytest.approx(1.7)


def test_update_k_clips_to_kmax():
    """Even with a wildly large ratio, k_new is capped at K_MAX."""
    table = {"k_values": {"m": cal.K_MAX}, "history": []}
    cal.update_k(table, _entry(ratio=100.0, violated=True))
    assert table["k_values"]["m"] == cal.K_MAX


def test_update_k_clips_to_kmin():
    table = {"k_values": {"m": cal.K_MIN}, "history": []}
    # Keep applying optimistic ratios — clipped to K_MIN.
    for _ in range(20):
        cal.update_k(table, _entry(ratio=0.1, violated=False))
    assert table["k_values"]["m"] == cal.K_MIN


def test_update_k_appends_to_history():
    table = {"k_values": {}, "history": []}
    cal.update_k(table, _entry(ratio=1.2, violated=False))
    cal.update_k(table, _entry(ratio=1.3, violated=False))
    assert len(table["history"]) == 2


def test_update_k_asymmetry_corrects_under_prediction_faster():
    """Demonstrates the safety bias: starting from k=1.0, two violations
    move k further than two non-violations of the same magnitude."""
    t_up = {"k_values": {"m": 1.0}, "history": []}
    t_dn = {"k_values": {"m": 1.0}, "history": []}
    cal.update_k(t_up, _entry(ratio=2.0, violated=True))
    cal.update_k(t_up, _entry(ratio=2.0, violated=True))
    cal.update_k(t_dn, _entry(ratio=0.0, violated=False))
    cal.update_k(t_dn, _entry(ratio=0.0, violated=False))
    delta_up = t_up["k_values"]["m"] - 1.0
    delta_dn = 1.0 - t_dn["k_values"]["m"]
    assert delta_up > delta_dn, "α_up must dominate α_down for safety"


# ---------------------------------------------------------------------------
# detect_drift
# ---------------------------------------------------------------------------


def _hist_entry(violated: bool, model_type: str = "m"):
    return {
        "estimate_violated": violated,
        "model_type": model_type,
        "gpu_name": "RTX 5090",
    }


def test_detect_drift_returns_none_when_history_short():
    table = {"history": [_hist_entry(True), _hist_entry(True)], "gpu_name": "g"}
    assert cal.detect_drift(table, last_n=3) is None


def test_detect_drift_returns_none_when_not_all_violated():
    table = {
        "history": [_hist_entry(True), _hist_entry(False), _hist_entry(True)],
        "gpu_name": "g",
    }
    assert cal.detect_drift(table, last_n=3) is None


def test_detect_drift_warns_on_n_consecutive_violations():
    table = {
        "history": [_hist_entry(True), _hist_entry(True), _hist_entry(True)],
        "gpu_name": "RTX 5090",
    }
    msg = cal.detect_drift(table, last_n=3)
    assert msg is not None
    assert "RTX 5090" in msg
    assert "drift" in msg.lower()


def test_detect_drift_only_inspects_last_n_entries():
    """Old violations don't trigger drift if recent entries are clean."""
    table = {
        "history": [
            _hist_entry(True), _hist_entry(True), _hist_entry(True),
            _hist_entry(False),
        ],
        "gpu_name": "g",
    }
    assert cal.detect_drift(table, last_n=3) is None
