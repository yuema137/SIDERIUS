"""
V21 PR G G2 — the time gate prices inference at the batch that will
actually run (§0.R.10/§0.R.10a), and the tuner→wrapper transport of the
probed batch is pinned.

Two test families:

1. **Two-directional deterministic verdict flips** on the
   ``training_warmup_x2.7_fallback`` branch (the one order-of-magnitude
   batch-sensitive forecast path). With a fixed workload and a time
   budget chosen STRICTLY BETWEEN the old (table/fallback 25) and new
   (probed B) ceil-based forecasts:

   * **B > 25** (probed 64): the old forecast over-prices → old REJECTS,
     the corrected forecast accepts (a false ``skipped_time_risk``
     rejection is removed);
   * **B < 25** (probed 4): the old forecast under-prices → old ACCEPTS,
     the corrected forecast rejects (a false admission is removed).

   Fixed arithmetic (hardcoded, independent of the code under test):
   seg 16000 → ml_per_psd = 625; 400 PSDs → total_ml = 250_000;
   warmup 10 ms/step × 2.7 = 27 ms/step;
   steps(25)=10_000 → 270 s; steps(64)=3_907 → 105.489 s;
   steps(4)=62_500 → 1_687.5 s; training stub 600 s + scoring stub 60 s.

2. **Transport pins** on ``_run_time_preflight`` (the tuner seam): the
   probed batch present in ``active_params`` reaches the time-skill
   kwargs (delete-the-hop fails this), and a hint-less ``active_params``
   delivers no batch (0.R.4 — the dict is rebuilt per attempt at :4452,
   so a stale hint cannot survive; the wrapper then resolves the
   registry default exactly as pre-G1).

Source finding recorded in the PR G ledger: the tuner has ALWAYS
splatted ``**active_params`` into the skill kwargs
(``_run_time_preflight`` :1171), so no tuner code change exists in G2 —
these tests pin the pre-existing transport plus the wrapper/estimator
consumption added in G1.
"""

from __future__ import annotations

import pytest

# The package __init__ rebinds sys.modules so this resolves to the inner
# implementation module — the same object _run_time_preflight lives in.
import nodes.ml_hyperparameter_tune_agent as tuner_mod
from agent.skills.evaluate_time_skill import wrapper as ts
from execute_tools.dataset_config import TIDMAD_PROFILE


class FakeSandbox:
    base_dir = "/tmp/g2_fake_sandbox"


def _base_kwargs(**overrides) -> dict:
    kw = {
        # Unregistered → the OLD forecast batch is the runtime fallback 25,
        # exactly the generated-model population G2 corrects.
        "model_type": "g2_generated_model_no_entry",
        "model_config": {"segmentation_size": 16000},
        "train_config": {"batch_size": 1, "epochs": 1, "device": "cpu"},
        "loss_config": {"loss_type": "focal"},
        "sample_set": {str(i): list(range(20)) for i in range(20)},
        "train_portion": 1.0,
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
            "ms_per_step": 10.0,
            "safety_multiplier": 2.0,
            # Warmup-measured provenance — blocking-capable per §7.4, so
            # an over-budget projection really REJECTS (unlike static).
            "ms_source": "real_dataset_warmup",
            "formal_execution_eligible": False,
            "gpu_name": "test_gpu",
        },
    }


def _patch_for_x27_branch(monkeypatch) -> None:
    """Force the ``training_warmup_x2.7_fallback`` branch with a measured
    10 ms/step warmup; training/scoring stubbed to fixed seconds; the
    REAL inference estimator prices the steps."""
    monkeypatch.setattr(
        ts._training_est,
        "estimate_wall_time_seconds",
        lambda *a, **kw: _stub_phase("training", 600.0),
    )
    monkeypatch.setattr(
        ts._scoring_est,
        "estimate_wall_time_seconds",
        lambda *a, **kw: _stub_phase("scoring", 60.0),
    )
    monkeypatch.setattr(ts, "_count_params", lambda mt, mc, lt: 100_000)
    monkeypatch.setattr(
        ts,
        "_measure_ms_per_step",
        lambda **kw: (
            10.0,
            {
                "n_warmup_batches": 1,
                "n_timed_batches": 4,
                "timings_ms": [10.0] * 4,
                "aggregator": "median",
            },
        ),
    )


def _run(monkeypatch, *, budget_min: float, inference_batch: int | None):
    _patch_for_x27_branch(monkeypatch)
    kwargs = _base_kwargs(time_budget_minutes=budget_min, data_dir="/fake/warmup/dir")
    if inference_batch is not None:
        kwargs["inference_batch"] = inference_batch
    result = ts.run_skill(FakeSandbox(), **kwargs)
    assert result["status"] == "success"
    assert result["breakdown"]["inference_ms_source"] == "training_warmup_x2.7_fallback"
    return result


class TestVerdictFlipsBothDirections:
    def test_b_above_25_old_rejects_corrected_accepts(self, monkeypatch):
        """Budget 14 min sits strictly between the corrected forecast
        (600+105.489+60 = 765.489 s ≈ 12.76 min at probed B=64) and the
        old fallback-25 forecast (600+270+60 = 930 s = 15.5 min)."""
        old = _run(monkeypatch, budget_min=14.0, inference_batch=None)
        assert old["phase_breakdown"]["inference"]["breakdown"]["inference_batch"] == 25
        assert old["breakdown"]["over_effective_budget"] is True
        assert old["feasible"] is False, (
            "Pre-G2 pricing at the fallback batch 25 must over-price this "
            "workload and reject it — the §0.R.10 false skipped_time_risk."
        )

        new = _run(monkeypatch, budget_min=14.0, inference_batch=64)
        assert new["phase_breakdown"]["inference"]["breakdown"]["inference_batch"] == 64
        assert new["breakdown"]["over_effective_budget"] is False
        assert new["feasible"] is True, (
            "Priced at the probed batch 64 the same workload fits the same "
            "budget — the wrongful rejection is removed."
        )

    def test_b_below_25_old_accepts_corrected_rejects(self, monkeypatch):
        """Budget 20 min sits strictly between the old forecast (930 s =
        15.5 min at fallback 25) and the corrected forecast
        (600+1687.5+60 = 2347.5 s ≈ 39.1 min at probed B=4)."""
        old = _run(monkeypatch, budget_min=20.0, inference_batch=None)
        assert old["phase_breakdown"]["inference"]["breakdown"]["inference_batch"] == 25
        assert old["breakdown"]["over_effective_budget"] is False
        assert old["feasible"] is True, (
            "Pre-G2 pricing at the fallback batch 25 under-prices this "
            "workload and wrongly admits it — the §0.R.10a false admission."
        )

        new = _run(monkeypatch, budget_min=20.0, inference_batch=4)
        assert new["phase_breakdown"]["inference"]["breakdown"]["inference_batch"] == 4
        assert new["breakdown"]["over_effective_budget"] is True
        assert new["feasible"] is False, (
            "Priced at the probed batch 4 the same workload exceeds the same "
            "budget — the false admission is removed."
        )


class TestTunerTransport:
    """The tuner→wrapper hop: ``_run_time_preflight`` splats
    ``**active_params`` (:1171), so the current attempt's probed batch —
    set at :4696 before the gate fires — reaches the wrapper's
    ``inference_batch`` kwarg."""

    def _capture_preflight_kwargs(self, monkeypatch, active_params: dict) -> dict:
        captured: dict = {}

        def _fake_run_skill(skill_folder, sandbox, **params):
            captured["skill"] = skill_folder
            captured["params"] = params
            return {"status": "success", "feasible": True}

        monkeypatch.setattr(tuner_mod, "_run_skill", _fake_run_skill)
        tuner_mod._run_time_preflight(
            sandbox=FakeSandbox(),
            active_params=active_params,
            time_budget_minutes=20.0,
            data_dir=None,
            memory_history=[],
            is_trial=True,
            dataset_profile=TIDMAD_PROFILE,
        )
        assert captured["skill"] == "evaluate_time_skill"
        return captured["params"]

    def test_probed_batch_reaches_time_skill_kwargs(self, monkeypatch):
        """DELETE-THE-HOP pin: if the tuner stopped forwarding
        ``active_params`` wholesale (or stripped the key), the time gate
        would silently reprice at the registry default — this fails."""
        params = self._capture_preflight_kwargs(
            monkeypatch,
            {"model_type": "g2_generated_model_no_entry", "inference_batch": 64},
        )
        assert params["inference_batch"] == 64

    def test_hintless_active_params_delivers_no_batch(self, monkeypatch):
        """0.R.4 negative construction pin: ``active_params`` is rebuilt
        per attempt WITHOUT an ``inference_batch`` key (:4452); an attempt
        that produced no probe therefore delivers nothing, and the wrapper
        resolves the registry default exactly as pre-G1. A stale hint from
        a previous attempt cannot survive the rebuild."""
        params = self._capture_preflight_kwargs(
            monkeypatch,
            {"model_type": "g2_generated_model_no_entry"},
        )
        assert "inference_batch" not in params
