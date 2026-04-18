"""
Tests for agent/skills/evaluate_time_skill/wrapper.py (K.2.5 Commit 6 —
sum aggregator over 3 phases).

Covers:
  - _suggest_lever routing (3 branches) — still lives in the wrapper.
  - run_skill feasible / infeasible branches (with _count_params
    monkeypatched so tests run without torch / model code).
  - run_skill error path on malformed model_config.
  - run_skill preserves the output contract shape (including new
    dominant_phase + phase_breakdown fields).
  - Sum semantics: estimated_minutes == Σ phase seconds / 60.
  - Warmup -> source routing: warmup ms/step propagates to
    breakdown.source; fallback lands as "static_formula".

Pure step-count and static-ms/step coverage is now in
tests/unit/agent/training_skill/test_estimator.py (the helpers moved
to the training estimator). This file focuses on the wrapper's
aggregation + contract behaviour.
"""

from __future__ import annotations

import pytest

from agent.skills.evaluate_time_skill import wrapper as ts


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeSandbox:
    """TimeEval skill does not call sandbox methods."""


def _patch_count_params(monkeypatch, n_params: int) -> None:
    """Replace the wrapper's _count_params + the training estimator's internal
    _count_params so tests run without torch / model code. The inference
    estimator accepts num_params via kwarg, so no patch is needed there once
    the wrapper supplies it."""
    monkeypatch.setattr(ts, "_count_params", lambda mt, mc, lt: n_params)


def _base_kwargs(**overrides) -> dict:
    """Default kwargs for run_skill. Uses "rnn" as the model type because
    that's a registered inference-batch plugin — the inference estimator
    calls assert_inference_batch_registered at the top of its wall-time
    function, so an unregistered type would raise before anything runs."""
    kw = {
        "model_type": "rnn",
        "model_config": {"segmentation_size": 16000},
        "train_config": {"batch_size": 1, "epochs": 1, "device": "cpu"},
        "loss_config": {"loss_type": "focal"},
        "sample_set": {str(i): list(range(20)) for i in range(20)},  # 400 PSDs
        "train_portion": 1.0,
        "time_budget_minutes": 60.0,
    }
    kw.update(overrides)
    return kw


# ---------------------------------------------------------------------------
# _suggest_lever — three branches
# ---------------------------------------------------------------------------


def test_suggest_lever_high_ms_per_step_recommends_shrinking_model():
    assert "model depth/width" in ts._suggest_lever(
        ms_per_step=80.0, seg_size=1000, batch_size=1
    )


def test_suggest_lever_small_seg_bs1_recommends_raising_batch():
    assert "batch_size" in ts._suggest_lever(
        ms_per_step=2.0, seg_size=1000, batch_size=1
    )


def test_suggest_lever_otherwise_recommends_raising_seg_size():
    # ms below 50 and (seg >= 10_000 or batch > 1) → seg_size branch
    msg = ts._suggest_lever(ms_per_step=10.0, seg_size=16000, batch_size=1)
    assert "segmentation_size" in msg


# ---------------------------------------------------------------------------
# run_skill — contract shape + success path
# ---------------------------------------------------------------------------


_EXPECTED_KEYS = {
    "status", "feasible", "verdict", "suggestion",
    "estimated_minutes", "limit_minutes", "breakdown",
    "dominant_phase", "phase_breakdown",
}


def test_run_skill_returns_contract_shape(monkeypatch):
    _patch_count_params(monkeypatch, 100_000)
    result = ts.run_skill(FakeSandbox(), **_base_kwargs())
    assert set(result.keys()) == _EXPECTED_KEYS
    assert result["status"] == "success"
    # Flat breakdown preserves the pre-K.2.5 keys used by
    # nodes/ml_hyperparameter_tune_agent.py (source + gpu_name for Phase F).
    assert set(result["breakdown"].keys()) >= {
        "total_train_steps", "ms_per_step_warmup", "k_correction",
        "safety_multiplier", "train_minutes", "num_params",
        "source", "gpu_name",
    }


def test_run_skill_phase_breakdown_contains_all_three_phases(monkeypatch):
    _patch_count_params(monkeypatch, 100_000)
    result = ts.run_skill(FakeSandbox(), **_base_kwargs())
    assert set(result["phase_breakdown"].keys()) == {"training", "inference", "scoring"}
    for phase, pb in result["phase_breakdown"].items():
        assert pb["phase"] == phase
        assert pb["seconds"] >= 0.0
        assert "breakdown" in pb


def test_run_skill_estimated_minutes_is_sum_of_phase_seconds(monkeypatch):
    _patch_count_params(monkeypatch, 100_000)
    result = ts.run_skill(FakeSandbox(), **_base_kwargs())
    total_sec = sum(p["seconds"] for p in result["phase_breakdown"].values())
    assert result["estimated_minutes"] == pytest.approx(total_sec / 60.0, rel=1e-3)


def test_run_skill_dominant_phase_is_training_for_typical_config(monkeypatch):
    # 100k params × 16000 seg × 400 PSDs is firmly training-dominated for the
    # static formula: per-step cost × 250k steps overwhelms the forward-only
    # inference pass + the FFT-bound scoring phase.
    _patch_count_params(monkeypatch, 100_000)
    result = ts.run_skill(FakeSandbox(), **_base_kwargs())
    assert result["dominant_phase"] == "training"


# ---------------------------------------------------------------------------
# Feasibility gate — keyed on the SUM of phase seconds
# ---------------------------------------------------------------------------


def test_run_skill_feasible_tiny_model(monkeypatch):
    # 100k params is tiny. Even after summing training + inference + scoring
    # the total should sit well under 60 min for 400 PSDs.
    _patch_count_params(monkeypatch, 100_000)
    result = ts.run_skill(FakeSandbox(), **_base_kwargs(time_budget_minutes=60.0))
    assert result["feasible"] is True
    assert "FITS" in result["verdict"]
    assert result["suggestion"] == ""
    assert result["estimated_minutes"] < 60.0


def test_run_skill_infeasible_large_model(monkeypatch):
    # 50M params → ~480 ms/step × 250k steps × 1.1 safety → training alone
    # blows past 60 min, well before inference + scoring are added.
    _patch_count_params(monkeypatch, 50_000_000)
    result = ts.run_skill(FakeSandbox(), **_base_kwargs(time_budget_minutes=60.0))
    assert result["feasible"] is False
    assert "OVER BUDGET" in result["verdict"]
    assert result["suggestion"]  # non-empty
    assert result["estimated_minutes"] > 60.0


def test_run_skill_error_on_malformed_model_config(monkeypatch):
    # Don't patch _count_params — let it actually try to load a bogus model.
    # The error is caught by the wrapper's top-level try/except before any
    # estimator runs (so the unregistered-type assert in the inference
    # estimator is never reached).
    result = ts.run_skill(FakeSandbox(), **_base_kwargs(model_type="nonexistent_model"))
    assert result["status"] == "error"
    assert "message" in result


def test_run_skill_infeasible_suggestion_reflects_lever(monkeypatch):
    # High-ms/step path → model-shrink suggestion.
    _patch_count_params(monkeypatch, 100_000_000)  # 100M → ~960 ms/step at seg=16000
    result = ts.run_skill(FakeSandbox(), **_base_kwargs(time_budget_minutes=60.0))
    assert "model depth/width" in result["suggestion"]


def test_run_skill_safety_multiplier_surfaced_in_breakdown(monkeypatch):
    # The 1.1× safety multiplier is applied inside the training estimator,
    # and surfaces on the flat breakdown for compatibility with pre-K.2.5
    # callers. It also appears on the training-phase's phase_breakdown entry.
    _patch_count_params(monkeypatch, 1_000_000)
    result = ts.run_skill(FakeSandbox(), **_base_kwargs(time_budget_minutes=60.0))
    from agent.skills.training_skill import estimator as te
    assert result["breakdown"]["safety_multiplier"] == te.SAFETY_MULTIPLIER
    train_bd = result["phase_breakdown"]["training"]["breakdown"]
    assert train_bd["safety_multiplier"] == te.SAFETY_MULTIPLIER

    # Training phase seconds == total_steps × ms/step × k × safety / 1000.
    train_minutes = result["phase_breakdown"]["training"]["seconds"] / 60.0
    raw = (
        train_bd["total_train_steps"]
        * train_bd["ms_per_step"]
        / 60_000.0
    )
    assert train_minutes == pytest.approx(
        raw * train_bd["k_correction"] * te.SAFETY_MULTIPLIER, rel=1e-3
    )


# ---------------------------------------------------------------------------
# Warmup vs static-formula source routing
# ---------------------------------------------------------------------------


def test_run_skill_uses_warmup_when_data_dir_and_measurement_available(monkeypatch):
    # When data_dir is passed and _measure_ms_per_step returns a positive
    # value, run_skill must use it and flag the source accordingly.
    _patch_count_params(monkeypatch, 100_000)
    monkeypatch.setattr(ts, "_measure_ms_per_step", lambda **kw: 3.5)
    result = ts.run_skill(
        FakeSandbox(),
        **_base_kwargs(data_dir="/any/path"),
    )
    assert result["breakdown"]["source"] == "real_dataset_warmup"
    assert result["breakdown"]["ms_per_step_warmup"] == pytest.approx(3.5)


def test_run_skill_falls_back_to_static_when_warmup_returns_none(monkeypatch):
    # Warmup returns None (no CUDA, build failure, etc.) → static formula path.
    # Training estimator reports ms_source="static_formula"; wrapper surfaces
    # it as breakdown.source.
    _patch_count_params(monkeypatch, 100_000)
    monkeypatch.setattr(ts, "_measure_ms_per_step", lambda **kw: None)
    result = ts.run_skill(
        FakeSandbox(),
        **_base_kwargs(data_dir="/any/path"),
    )
    assert result["breakdown"]["source"] == "static_formula_phase_b"


def test_run_skill_skips_warmup_without_data_dir(monkeypatch):
    # No data_dir → _measure_ms_per_step must not be invoked at all.
    _patch_count_params(monkeypatch, 100_000)
    calls = []

    def _should_not_be_called(**kw):
        calls.append(kw)
        return 99.0

    monkeypatch.setattr(ts, "_measure_ms_per_step", _should_not_be_called)
    result = ts.run_skill(FakeSandbox(), **_base_kwargs())
    assert calls == []
    assert result["breakdown"]["source"] == "static_formula_phase_b"


# ---------------------------------------------------------------------------
# Warmup propagation to inference phase
# ---------------------------------------------------------------------------


def test_warmup_scales_inference_ms_by_one_third(monkeypatch):
    # When the training warmup reports M ms/step, the wrapper must hand the
    # inference estimator M/3 as its inference_ms_per_step (no backward pass).
    _patch_count_params(monkeypatch, 100_000)
    monkeypatch.setattr(ts, "_measure_ms_per_step", lambda **kw: 9.0)
    result = ts.run_skill(FakeSandbox(), **_base_kwargs(data_dir="/any/path"))
    inf_bd = result["phase_breakdown"]["inference"]["breakdown"]
    assert inf_bd["ms_source"] == "derived_from_training_warmup"
    assert inf_bd["ms_per_step"] == pytest.approx(3.0, rel=1e-6)
