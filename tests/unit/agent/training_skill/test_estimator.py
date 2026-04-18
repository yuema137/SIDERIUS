"""
Tests for agent/skills/training_skill/estimator.py

K.2.5 Commit 2 covers:

- ``estimate_peak_bytes``:
  * output shape ``{"phase", "total_bytes", "breakdown"}``
  * CE vs focal (one_hot term), RNN vs transformer (attention term)
  * fcnet activations use the 1× factor
  * scales linearly in num_params, batch_size, seg_size (for output logits);
    quadratically in seg_size for transformer attention

- ``estimate_wall_time_seconds``:
  * output shape ``{"phase", "seconds", "breakdown"}``
  * **Regression**: same inputs as evaluate_time_skill's
    ``test_run_skill_feasible_tiny_model`` case produce the same seconds
    (locks the K.2.5 "lift-only" invariant).
  * ms_per_step passthrough: caller-supplied ms, no gpu → k=1.0; with gpu →
    calibration.lookup_k is consulted.
  * static fallback: ms_per_step=None + num_params=None → internal
    ``_count_params`` is invoked (monkeypatched).
  * epochs + train_portion linear scaling.
"""

from __future__ import annotations

import pytest

from agent.skills.training_skill import estimator as est


# ---------------------------------------------------------------------------
# estimate_peak_bytes
# ---------------------------------------------------------------------------

class TestEstimatePeakBytes:
    """VRAM estimator — worst-case float32 training memory breakdown."""

    @staticmethod
    def _mc(**over):
        cfg = {"segmentation_size": 16000}
        cfg.update(over)
        return cfg

    @staticmethod
    def _tc(**over):
        cfg = {"batch_size": 1}
        cfg.update(over)
        return cfg

    def test_return_shape(self):
        out = est.estimate_peak_bytes(
            "rnn", self._mc(), self._tc(), {"loss_type": "ce"}, num_params=100_000,
        )
        assert set(out.keys()) == {"phase", "total_bytes", "breakdown"}
        assert out["phase"] == "training"
        assert out["total_bytes"] > 0
        assert set(out["breakdown"].keys()) == {
            "model_overhead_bytes", "output_logits_bytes", "activations_bytes",
            "focal_onehot_bytes",   "transformer_attn_bytes",
        }

    def test_focal_loss_adds_onehot_bytes(self):
        """Focal's one_hot tensor is the only term that differs CE → focal."""
        base = dict(
            model_type="rnn", model_config=self._mc(),
            train_config=self._tc(), num_params=100_000,
        )
        ce    = est.estimate_peak_bytes(**base, loss_config={"loss_type": "ce"})
        focal = est.estimate_peak_bytes(**base, loss_config={"loss_type": "focal"})

        assert focal["total_bytes"] > ce["total_bytes"]
        assert ce["breakdown"]["focal_onehot_bytes"] == 0
        assert focal["breakdown"]["focal_onehot_bytes"] > 0
        for k in ("model_overhead_bytes", "output_logits_bytes",
                  "activations_bytes", "transformer_attn_bytes"):
            assert ce["breakdown"][k] == focal["breakdown"][k]

    def test_rnn_has_no_transformer_attn(self):
        out = est.estimate_peak_bytes(
            "rnn", self._mc(), self._tc(), {"loss_type": "ce"}, num_params=100_000,
        )
        assert out["breakdown"]["transformer_attn_bytes"] == 0

    def test_transformer_has_attn_term(self):
        out = est.estimate_peak_bytes(
            "transformer",
            self._mc(nhead=4, num_layers=2),
            self._tc(),
            {"loss_type": "ce"},
            num_params=100_000,
        )
        assert out["breakdown"]["transformer_attn_bytes"] > 0

    def test_fcnet_activations_use_1x_factor(self):
        """fcnet (linear) backward activations ≈ 1× output; other types ≈ 2×."""
        mc, tc, lc = self._mc(), self._tc(), {"loss_type": "ce"}
        fc  = est.estimate_peak_bytes("fcnet", mc, tc, lc, num_params=1)
        rnn = est.estimate_peak_bytes("rnn",   mc, tc, lc, num_params=1)
        assert fc["breakdown"]["activations_bytes"] * 2 == rnn["breakdown"]["activations_bytes"]

    def test_num_params_scales_model_overhead_linearly(self):
        mc, tc, lc = self._mc(), self._tc(), {"loss_type": "ce"}
        a = est.estimate_peak_bytes("rnn", mc, tc, lc, num_params=100_000)
        b = est.estimate_peak_bytes("rnn", mc, tc, lc, num_params=200_000)
        assert b["breakdown"]["model_overhead_bytes"] == 2 * a["breakdown"]["model_overhead_bytes"]

    def test_batch_size_scales_output_logits_linearly(self):
        mc, lc = self._mc(), {"loss_type": "ce"}
        a = est.estimate_peak_bytes("rnn", mc, self._tc(batch_size=1), lc, num_params=1)
        b = est.estimate_peak_bytes("rnn", mc, self._tc(batch_size=4), lc, num_params=1)
        assert b["breakdown"]["output_logits_bytes"] == 4 * a["breakdown"]["output_logits_bytes"]

    def test_seg_size_scales_output_logits_linearly(self):
        tc, lc = self._tc(), {"loss_type": "ce"}
        a = est.estimate_peak_bytes("rnn", self._mc(segmentation_size=1000), tc, lc, num_params=1)
        b = est.estimate_peak_bytes("rnn", self._mc(segmentation_size=4000), tc, lc, num_params=1)
        assert b["breakdown"]["output_logits_bytes"] == 4 * a["breakdown"]["output_logits_bytes"]

    def test_seg_size_scales_transformer_attn_quadratically(self):
        tc, lc = self._tc(), {"loss_type": "ce"}
        a = est.estimate_peak_bytes(
            "transformer",
            self._mc(segmentation_size=1000, nhead=2, num_layers=2),
            tc, lc, num_params=1,
        )
        b = est.estimate_peak_bytes(
            "transformer",
            self._mc(segmentation_size=2000, nhead=2, num_layers=2),
            tc, lc, num_params=1,
        )
        # (2000/1000)^2 = 4
        assert b["breakdown"]["transformer_attn_bytes"] == 4 * a["breakdown"]["transformer_attn_bytes"]


# ---------------------------------------------------------------------------
# estimate_wall_time_seconds
# ---------------------------------------------------------------------------

class TestEstimateWallTimeSeconds:

    @staticmethod
    def _sample_set(n_psd: int = 400) -> dict:
        """Mirrors the fixture used in test_evaluate_time_skill (20 keys × n/20 PSDs)."""
        return {str(i): list(range(n_psd // 20)) for i in range(20)}

    def test_return_shape(self):
        out = est.estimate_wall_time_seconds(
            "rnn",
            {"segmentation_size": 16000},
            {"batch_size": 1, "epochs": 1},
            self._sample_set(),
            ms_per_step=1.0,
        )
        assert set(out.keys()) == {"phase", "seconds", "breakdown"}
        assert out["phase"] == "training"
        assert out["seconds"] > 0
        assert set(out["breakdown"].keys()) >= {
            "total_train_steps", "ms_per_step", "ms_source",
            "k_correction",      "safety_multiplier", "gpu_name",
        }

    def test_regression_against_wrapper_static_path(self):
        """**Main K.2.5 invariant** — lifting the body must preserve output.

        Matches ``test_evaluate_time_skill.test_run_skill_feasible_tiny_model``
        exactly: num_params=100_000, seg=16000, bs=1, epochs=1, tp=1.0,
        400 PSDs. The wrapper's ``estimated_minutes`` in that test rounds to
        ~4.4 min → 264 s. We check seconds to the same precision.

        Arithmetic:
          steps        = ceil(400 × (10_000_000 // 16000) × 1.0 / 1) × 1 = 250_000
          ms/step static = 100_000 × 16000 × 1 × 6e-10                 = 0.96
          seconds       = 250_000 × 0.96 × 1.0 × 1.1 / 1000            = 264.0
        """
        out = est.estimate_wall_time_seconds(
            "tinynet",
            {"segmentation_size": 16000},
            {"batch_size": 1, "epochs": 1},
            self._sample_set(400),
            num_params=100_000,
            ms_per_step=None,
        )
        assert out["seconds"] == pytest.approx(264.0, rel=1e-3)
        assert out["breakdown"]["total_train_steps"] == 250_000
        assert out["breakdown"]["ms_source"] == "static_formula_phase_b"
        assert out["breakdown"]["k_correction"] == 1.0

    def test_ms_per_step_passthrough_no_gpu(self):
        """Caller-supplied ms, gpu_name=None → k stays 1.0."""
        out = est.estimate_wall_time_seconds(
            "rnn",
            {"segmentation_size": 16000},
            {"batch_size": 1, "epochs": 1},
            self._sample_set(),
            ms_per_step=5.0,
            gpu_name=None,
        )
        # steps = 250_000; seconds = 250_000 × 5.0 × 1.0 × 1.1 / 1000 = 1375
        assert out["seconds"] == pytest.approx(1375.0, rel=1e-3)
        assert out["breakdown"]["ms_source"] == "real_dataset_warmup"
        assert out["breakdown"]["k_correction"] == 1.0

    def test_ms_per_step_passthrough_applies_gpu_calibration(self, monkeypatch):
        """gpu_name supplied → calibration.lookup_k is consulted."""
        from agent.skills.evaluate_time_skill import calibration
        monkeypatch.setattr(calibration, "load_table", lambda gpu: {"rnn": 2.0})
        monkeypatch.setattr(calibration, "lookup_k", lambda tbl, mt: tbl[mt])

        out = est.estimate_wall_time_seconds(
            "rnn",
            {"segmentation_size": 16000},
            {"batch_size": 1, "epochs": 1},
            self._sample_set(),
            ms_per_step=5.0,
            gpu_name="Test GPU",
        )
        assert out["breakdown"]["k_correction"] == pytest.approx(2.0)
        # seconds = 250_000 × 5.0 × 2.0 × 1.1 / 1000 = 2750
        assert out["seconds"] == pytest.approx(2750.0, rel=1e-3)

    def test_static_fallback_invokes_internal_count_params(self, monkeypatch):
        """ms_per_step=None AND num_params=None → estimator calls _count_params."""
        calls = []

        def _stub_count(model_type, model_config, loss_type):
            calls.append((model_type, loss_type))
            return 50_000

        monkeypatch.setattr(est, "_count_params", _stub_count)
        out = est.estimate_wall_time_seconds(
            "tinynet",
            {"segmentation_size": 16000},
            {"batch_size": 1, "epochs": 1},
            self._sample_set(),
        )
        assert calls == [("tinynet", "ce")]
        # ms/step = 50_000 × 16000 × 1 × 6e-10 = 0.48
        # seconds = 250_000 × 0.48 × 1.0 × 1.1 / 1000 = 132
        assert out["seconds"] == pytest.approx(132.0, rel=1e-3)

    def test_epochs_scales_linearly(self):
        kw = dict(
            model_type="rnn",
            model_config={"segmentation_size": 16000},
            sample_set=self._sample_set(),
            ms_per_step=1.0,
        )
        a = est.estimate_wall_time_seconds(
            train_config={"batch_size": 1, "epochs": 1}, **kw
        )
        b = est.estimate_wall_time_seconds(
            train_config={"batch_size": 1, "epochs": 3}, **kw
        )
        assert b["seconds"] == pytest.approx(3 * a["seconds"], rel=1e-6)

    def test_train_portion_reduces_steps(self):
        kw = dict(
            model_type="rnn",
            model_config={"segmentation_size": 16000},
            train_config={"batch_size": 1, "epochs": 1},
            sample_set=self._sample_set(),
            ms_per_step=1.0,
        )
        full = est.estimate_wall_time_seconds(**kw, train_portion=1.0)
        half = est.estimate_wall_time_seconds(**kw, train_portion=0.5)
        assert half["seconds"] < full["seconds"]
        assert half["seconds"] == pytest.approx(full["seconds"] / 2, rel=1e-3)
