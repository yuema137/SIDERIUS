"""
Tests for agent/skills/evaluate_time_skill/wrapper.py (Phase B).

Covers:
  - _total_train_steps math over (seg_size, batch_size, train_portion, epochs)
  - _static_ms_per_step formula sanity
  - _suggest_lever routing (3 branches)
  - run_skill feasible / infeasible branches (with _count_params monkeypatched)
  - run_skill error path on malformed model_config
  - run_skill preserves the output contract shape
"""

from __future__ import annotations

import pytest

from agent.skills.evaluate_time_skill import wrapper as ts


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PSD_LEN = ts.PSD_SEGMENT_LENGTH  # 10_000_000 in current config


class FakeSandbox:
    """TimeEval skill does not call sandbox methods."""


def _patch_count_params(monkeypatch, n_params: int) -> None:
    """Replace _count_params with a stub so tests run without torch / model code."""
    monkeypatch.setattr(ts, "_count_params", lambda mt, mc, lt: n_params)


# ---------------------------------------------------------------------------
# _total_train_steps — pure arithmetic, six table-driven cases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "seg_size, batch_size, train_portion, epochs, n_psd, expected",
    [
        # explore_novel_v1 shape: 400 PSDs × (1e7/1250) = 3_200_000
        (1250,  1, 1.0, 1, 400, 3_200_000),
        # exploit_cnn_v1 shape:  400 PSDs × (1e7/16000) = 250_000
        (16000, 1, 1.0, 1, 400,   250_000),
        # large seg_size: 400 × (1e7/50000) = 80_000
        (50000, 1, 1.0, 1, 400,    80_000),
        # batch_size 4 quarters the step count
        (16000, 4, 1.0, 1, 400,    62_500),
        # train_portion 0.1 cuts step count 10× (with ceil)
        (16000, 1, 0.1, 1, 400,    25_000),
        # epochs multiplies
        (16000, 1, 1.0, 3, 400,   750_000),
    ],
)
def test_total_train_steps(seg_size, batch_size, train_portion, epochs, n_psd, expected):
    sample_set = {str(i): list(range(n_psd // 20)) for i in range(20)}
    assert sum(len(v) for v in sample_set.values()) == n_psd
    got = ts._total_train_steps(sample_set, seg_size, batch_size, train_portion, epochs)
    assert got == expected, (
        f"seg={seg_size} bs={batch_size} tp={train_portion} ep={epochs}: "
        f"got {got}, expected {expected}"
    )


def test_total_train_steps_uses_ceil_on_fractional_batches():
    # 1 PSD × 10 ml/PSD × 0.25 portion = 2.5 → ceil = 3 steps
    sample_set = {"0": [0]}
    ml_per_psd = PSD_LEN // 1_000_000  # 10
    assert ml_per_psd == 10
    got = ts._total_train_steps(sample_set, 1_000_000, 1, 0.25, 1)
    assert got == 3


# ---------------------------------------------------------------------------
# _static_ms_per_step — sanity only (formula is coarse by design)
# ---------------------------------------------------------------------------

def test_static_ms_per_step_scales_linearly_with_params():
    a = ts._static_ms_per_step(1_000_000, 1000, 1)
    b = ts._static_ms_per_step(2_000_000, 1000, 1)
    assert b == pytest.approx(2 * a)


def test_static_ms_per_step_scales_linearly_with_seg_size():
    a = ts._static_ms_per_step(1_000_000, 1000, 1)
    b = ts._static_ms_per_step(1_000_000, 4000, 1)
    assert b == pytest.approx(4 * a)


def test_static_ms_per_step_scales_linearly_with_batch_size():
    a = ts._static_ms_per_step(1_000_000, 1000, 1)
    b = ts._static_ms_per_step(1_000_000, 1000, 8)
    assert b == pytest.approx(8 * a)


# ---------------------------------------------------------------------------
# _suggest_lever — three branches
# ---------------------------------------------------------------------------

def test_suggest_lever_high_ms_per_step_recommends_shrinking_model():
    assert "model depth/width" in ts._suggest_lever(ms_per_step=80.0, seg_size=1000, batch_size=1)


def test_suggest_lever_small_seg_bs1_recommends_raising_batch():
    assert "batch_size" in ts._suggest_lever(ms_per_step=2.0, seg_size=1000, batch_size=1)


def test_suggest_lever_otherwise_recommends_raising_seg_size():
    # ms below 50 and (seg >= 10_000 or batch > 1) → seg_size branch
    msg = ts._suggest_lever(ms_per_step=10.0, seg_size=16000, batch_size=1)
    assert "segmentation_size" in msg


# ---------------------------------------------------------------------------
# run_skill — feasible / infeasible / error contract
# ---------------------------------------------------------------------------

_EXPECTED_KEYS = {
    "status", "feasible", "verdict", "suggestion",
    "estimated_minutes", "limit_minutes", "breakdown",
}


def _base_kwargs(**overrides) -> dict:
    kw = {
        "model_type": "tinynet",
        "model_config": {"segmentation_size": 16000},
        "train_config": {"batch_size": 1, "epochs": 1, "device": "cpu"},
        "loss_config": {"loss_type": "focal"},
        "sample_set": {str(i): list(range(20)) for i in range(20)},  # 400 PSDs
        "train_portion": 1.0,
        "time_budget_minutes": 60.0,
    }
    kw.update(overrides)
    return kw


def test_run_skill_returns_contract_shape(monkeypatch):
    _patch_count_params(monkeypatch, 100_000)
    result = ts.run_skill(FakeSandbox(), **_base_kwargs())
    assert set(result.keys()) == _EXPECTED_KEYS
    assert result["status"] == "success"
    assert set(result["breakdown"].keys()) >= {
        "total_train_steps", "ms_per_step_warmup", "k_correction",
        "safety_multiplier", "train_minutes", "source",
    }


def test_run_skill_feasible_tiny_model(monkeypatch):
    # 100k params × 16000 seg × 6e-10 = 0.96 ms/step, 250k steps → ~4 min → fits 60 min.
    _patch_count_params(monkeypatch, 100_000)
    result = ts.run_skill(FakeSandbox(), **_base_kwargs(time_budget_minutes=60.0))
    assert result["feasible"] is True
    assert "FITS" in result["verdict"]
    assert result["suggestion"] == ""
    assert result["estimated_minutes"] < 60.0


def test_run_skill_infeasible_large_model(monkeypatch):
    # 50M params × 16000 seg × 6e-10 = 480 ms/step, 250k steps × 1.1 safety → ~2200 min.
    _patch_count_params(monkeypatch, 50_000_000)
    result = ts.run_skill(FakeSandbox(), **_base_kwargs(time_budget_minutes=60.0))
    assert result["feasible"] is False
    assert "OVER BUDGET" in result["verdict"]
    assert result["suggestion"]  # non-empty
    assert result["estimated_minutes"] > 60.0


def test_run_skill_error_on_malformed_model_config(monkeypatch):
    # Don't patch _count_params — let it actually try to load a bogus model.
    result = ts.run_skill(FakeSandbox(), **_base_kwargs(model_type="nonexistent_model"))
    assert result["status"] == "error"
    assert "message" in result


def test_run_skill_infeasible_suggestion_reflects_lever(monkeypatch):
    # High-ms/step path → model-shrink suggestion.
    _patch_count_params(monkeypatch, 100_000_000)  # 100M → ~960 ms/step at seg=16000
    result = ts.run_skill(FakeSandbox(), **_base_kwargs(time_budget_minutes=60.0))
    assert "model depth/width" in result["suggestion"]


def test_run_skill_respects_safety_multiplier(monkeypatch):
    # Confirm 1.1× shows up in the breakdown and in the estimate.
    _patch_count_params(monkeypatch, 1_000_000)
    result = ts.run_skill(FakeSandbox(), **_base_kwargs(time_budget_minutes=60.0))
    assert result["breakdown"]["safety_multiplier"] == ts.SAFETY_MULTIPLIER
    raw = (
        result["breakdown"]["total_train_steps"]
        * result["breakdown"]["ms_per_step_warmup"]
        / 60_000.0
    )
    # estimated_minutes == raw × safety × k (k=1.0 in phase B)
    assert result["estimated_minutes"] == pytest.approx(
        raw * ts.SAFETY_MULTIPLIER, rel=1e-3
    )
