"""
V21 PR G G1 — the wrapper side of the explicit-batch forecast seam
(`agent/skills/evaluate_time_skill/wrapper.py`).

Pins the G1 contract on `run_skill`'s optional ``inference_batch`` kwarg:

  * absent → byte-identical pre-G1 behaviour: the hint scaling at the
    Commit-D branch prices at the registry batch, and the inference
    estimator receives ``inference_batch=None``;
  * present → BOTH forecast sides receive the SAME value (0.R.3): the
    ``inference_ms`` hint scaling uses it AND the estimator call carries
    it — a one-sided mutation on either side fails these tests;
  * invalid → the wrapper's structured ``status: "error"`` return (the
    fail-closed ``resolve_forecast_batch`` raises inside the ``try``),
    never a silent clamp;
  * ``inference_batch_uncalibrated`` keeps its registration meaning,
    unchanged by supplying a hint.

Deleting the wrapper→estimator hop (dropping the ``inference_batch=``
argument at the estimator call) fails ``test_explicit_batch_reaches_
both_sides_with_same_value`` and ``test_explicit_batch_reaches_real_
estimator_breakdown`` — the G1 half of the transport-contract evidence
(G2 adds the tuner→wrapper hop and its own delete-the-hop test).

Fixtures mirror ``test_inference_hint_path.py`` (phase stubs; rnn is
registered with table batch 10; SEGMENT_LENGTH=10_000_000 and seg 16000
give ml_per_psd = 625).
"""

from __future__ import annotations

import pytest

from agent.skills.evaluate_time_skill import wrapper as ts
from execute_tools.dataset_config import TIDMAD_PROFILE


class FakeSandbox:
    """run_skill ignores the sandbox argument."""


def _base_kwargs(**overrides) -> dict:
    kw = {
        "model_type": "rnn",  # registered in inference_batch_for (table: 10)
        "model_config": {"segmentation_size": 16000},
        "train_config": {"batch_size": 1, "epochs": 1, "device": "cpu"},
        "loss_config": {"loss_type": "focal"},
        "sample_set": {str(i): list(range(20)) for i in range(20)},
        "train_portion": 1.0,
        "time_budget_minutes": 60.0,
        # Step 05b: the run-bound topology is a REQUIRED kwarg — the skill
        # no longer resolves one of its own.
        "dataset_profile": TIDMAD_PROFILE,
    }
    kw.update(overrides)
    return kw


def _stub_phase(phase_name: str, seconds: float) -> dict:
    return {
        "phase": phase_name,
        "seconds": seconds,
        "breakdown": {
            "total_train_steps": 100,
            "ms_per_step": 1.0,
            "safety_multiplier": 2.0,
            "ms_source": "static_uncalibrated",
            "formal_execution_eligible": False,
            "gpu_name": "test_gpu",
            "total_inference_steps": 100,
            "inference_batch": 10,
            "inference_batch_uncalibrated": False,
        },
    }


def _patch_phases(
    monkeypatch, *, capture: dict | None = None, real_inference: bool = False
) -> None:
    """Stub the phase estimators. With ``capture``, the inference stub
    records the kwargs the wrapper passed (``inference_ms_per_step`` and
    ``inference_batch``). With ``real_inference=True`` the real inference
    estimator runs (training/scoring still stubbed; ``_count_params``
    patched so no model is instantiated)."""
    monkeypatch.setattr(
        ts._training_est,
        "estimate_wall_time_seconds",
        lambda *a, **kw: _stub_phase("training", 600.0),
    )
    if not real_inference:

        def _inf_stub(*a, **kw):
            if capture is not None:
                capture["inference_ms_per_step"] = kw.get("inference_ms_per_step")
                capture["inference_batch"] = kw.get("inference_batch")
            return _stub_phase("inference", 120.0)

        monkeypatch.setattr(ts._inference_est, "estimate_wall_time_seconds", _inf_stub)
    monkeypatch.setattr(
        ts._scoring_est,
        "estimate_wall_time_seconds",
        lambda *a, **kw: _stub_phase("scoring", 60.0),
    )
    monkeypatch.setattr(ts, "_count_params", lambda mt, mc, lt: 100_000)


ML_PER_PSD = 625  # 10_000_000 // 16000, hardcoded independently


class TestDefaultParity:
    def test_absent_kwarg_scales_hint_at_table_batch_and_passes_none(self, monkeypatch):
        """Pre-G1 parity: no ``inference_batch`` kwarg → the Commit-D hint
        scaling uses the registry batch (rnn: 10) and the estimator
        receives ``inference_batch=None``."""
        capture: dict = {}
        _patch_phases(monkeypatch, capture=capture)
        hint = 50.0
        result = ts.run_skill(
            FakeSandbox(),
            **_base_kwargs(),
            inference_per_psd_seg_ms_hint=hint,
        )
        assert result["status"] == "success"
        assert capture["inference_ms_per_step"] == pytest.approx(hint * 10 / ML_PER_PSD)
        assert capture["inference_batch"] is None

    def test_explicit_none_identical_to_absent(self, monkeypatch):
        """``inference_batch=None`` is the declared no-op form."""
        capture: dict = {}
        _patch_phases(monkeypatch, capture=capture)
        result = ts.run_skill(
            FakeSandbox(),
            **_base_kwargs(),
            inference_per_psd_seg_ms_hint=50.0,
            inference_batch=None,
        )
        assert result["status"] == "success"
        assert capture["inference_ms_per_step"] == pytest.approx(50.0 * 10 / ML_PER_PSD)
        assert capture["inference_batch"] is None


class TestExplicitBatchBothSides:
    def test_explicit_batch_reaches_both_sides_with_same_value(self, monkeypatch):
        """0.R.3 both-sides pin: the SAME explicit batch (64 ≠ table 10)
        drives the hint scaling AND reaches the estimator call. A mutation
        using the explicit value on one side only fails one of the two
        asserts; precedence reversal (table despite hint) fails both."""
        capture: dict = {}
        _patch_phases(monkeypatch, capture=capture)
        hint = 50.0
        result = ts.run_skill(
            FakeSandbox(),
            **_base_kwargs(),
            inference_per_psd_seg_ms_hint=hint,
            inference_batch=64,
        )
        assert result["status"] == "success"
        assert capture["inference_ms_per_step"] == pytest.approx(hint * 64 / ML_PER_PSD)
        assert capture["inference_batch"] == 64

    def test_explicit_batch_reaches_real_estimator_breakdown(self, monkeypatch):
        """Wrapper→estimator hop, real estimator: the explicit batch (7)
        lands in the inference phase breakdown's EXISTING key, and the
        registered model's ``inference_batch_uncalibrated`` stays False
        (the flag means registration, not hint presence). Deleting the
        ``inference_batch=`` argument at the estimator call site fails
        this test."""
        _patch_phases(monkeypatch, real_inference=True)
        result = ts.run_skill(
            FakeSandbox(),
            **_base_kwargs(),
            inference_batch=7,
        )
        assert result["status"] == "success"
        inf_breakdown = result["phase_breakdown"]["inference"]["breakdown"]
        assert inf_breakdown["inference_batch"] == 7
        assert inf_breakdown["inference_batch_uncalibrated"] is False
        assert result["inference_batch_uncalibrated"] is False

    def test_absent_kwarg_real_estimator_uses_table_batch(self, monkeypatch):
        """Companion no-hint pin with the real estimator: rnn prices at
        its table batch 10 exactly as pre-G1."""
        _patch_phases(monkeypatch, real_inference=True)
        result = ts.run_skill(FakeSandbox(), **_base_kwargs())
        assert result["status"] == "success"
        inf_breakdown = result["phase_breakdown"]["inference"]["breakdown"]
        assert inf_breakdown["inference_batch"] == 10


class TestInvalidExplicitBatch:
    @pytest.mark.parametrize("bad", [0, -3, True, 25.0])
    def test_invalid_explicit_returns_structured_error(self, monkeypatch, bad):
        """Fail-closed via the wrapper's structured error path — the
        ``ValueError`` from ``resolve_forecast_batch`` is caught by the
        existing ``try`` and surfaced as ``status: "error"``, never a
        silent clamp or fallback."""
        _patch_phases(monkeypatch)
        result = ts.run_skill(
            FakeSandbox(),
            **_base_kwargs(),
            inference_batch=bad,
        )
        assert result["status"] == "error"
        assert "inference_batch override" in result["message"]
