"""
Tests for agent/skills/inference_skill/estimator.py

K.2.5 Commit 3 covers:

- ``estimate_peak_bytes``:
  * shape ``{"phase", "total_bytes", "breakdown"}``.
  * weights = num_params × 4 B (no grads/Adam — 16 B would be training).
  * no ``focal_onehot_bytes`` key (loss not computed at inference).
  * transformer attention scales with ``inference_batch``.
  * **training ≥ inference** invariant for a representative RNN config.
  * **inversion**: monkeypatched huge ``inference_batch`` → inference
    VRAM exceeds training VRAM — the exact crossover the aggregator
    (commit 5) must surface to the planner.
  * ``ValueError`` on unregistered model_type (via
    ``assert_inference_batch_registered``).

- ``estimate_wall_time_seconds``:
  * shape ``{"phase", "seconds", "breakdown"}``.
  * monotone in segments (more data → more time).
  * monotone in ``inference_batch`` at fixed ms/step (larger batch →
    fewer steps → less time).
  * static fallback invokes ``_count_params`` (monkeypatched).
  * ``ValueError`` on unregistered model_type.
"""

from __future__ import annotations

import pytest

from agent.skills.inference_skill import estimator as est
from agent.skills.training_skill import estimator as train_est


def _sample_set(n_psd: int = 400) -> dict:
    """Mirror the fixture from test_evaluate_time_skill (20 keys)."""
    return {str(i): list(range(n_psd // 20)) for i in range(20)}


# ---------------------------------------------------------------------------
# estimate_peak_bytes
# ---------------------------------------------------------------------------

class TestEstimatePeakBytes:

    def test_return_shape(self):
        out = est.estimate_peak_bytes(
            "rnn", {"segmentation_size": 16000}, num_params=100_000,
        )
        assert set(out.keys()) == {"phase", "total_bytes", "breakdown"}
        assert out["phase"] == "inference"
        assert out["total_bytes"] > 0
        assert "inference_batch" in out["breakdown"]

    def test_weights_use_4x_factor_not_16x(self):
        """Inference has no grads or Adam states → 4 B/param, not 16 B."""
        out = est.estimate_peak_bytes(
            "rnn", {"segmentation_size": 16000}, num_params=100_000,
        )
        assert out["breakdown"]["weights_bytes"] == 100_000 * 4

    def test_no_focal_onehot_key(self):
        """Inference does not compute loss — no focal one_hot term should
        appear in the breakdown regardless of training loss choice."""
        out = est.estimate_peak_bytes(
            "rnn", {"segmentation_size": 16000}, num_params=100_000,
        )
        assert "focal_onehot_bytes" not in out["breakdown"]

    def test_rnn_has_no_transformer_attn(self):
        out = est.estimate_peak_bytes(
            "rnn", {"segmentation_size": 16000}, num_params=100_000,
        )
        assert out["breakdown"]["transformer_attn_bytes"] == 0

    def test_transformer_attn_scales_linearly_with_inference_batch(self, monkeypatch):
        """Attention term is linear in inf_batch (quadratic in seg_size,
        linear in nhead/num_layers — covered elsewhere)."""
        monkeypatch.setattr(est, "inference_batch_for", lambda mt: 10)
        small = est.estimate_peak_bytes(
            "transformer",
            {"segmentation_size": 1000, "nhead": 2, "num_layers": 2},
            num_params=1,
        )
        monkeypatch.setattr(est, "inference_batch_for", lambda mt: 20)
        large = est.estimate_peak_bytes(
            "transformer",
            {"segmentation_size": 1000, "nhead": 2, "num_layers": 2},
            num_params=1,
        )
        assert large["breakdown"]["transformer_attn_bytes"] == \
            2 * small["breakdown"]["transformer_attn_bytes"]

    def test_training_exceeds_inference_when_params_dominate(self):
        """Sanity: in the params-dominated regime (model_overhead 16×params
        swamps the batch×seg×8 output+activations term), training peak
        exceeds inference peak even though inf_batch > train batch.

        This is *one* regime, not a universal invariant — the "training ≥
        inference" implicit assumption in the pre-K.2.5 single-phase VRAM
        wrapper is fragile, which is exactly what K.2.5 makes observable.
        The inversion test below covers the opposite regime."""
        # 10M params, seg=1000 → model_overhead (160 MB) swamps inference
        # output (10 × 256 × 1000 × 4 = 10.2 MB).
        mc = {"segmentation_size": 1000}
        training = train_est.estimate_peak_bytes(
            "rnn", mc, {"batch_size": 1}, {"loss_type": "ce"},
            num_params=10_000_000,
        )
        inference = est.estimate_peak_bytes("rnn", mc, num_params=10_000_000)
        assert training["total_bytes"] > inference["total_bytes"]

    def test_monkeypatched_huge_inference_batch_inverts_ordering(self, monkeypatch):
        """**Inversion test**: planting a huge ``inference_batch`` via
        monkeypatch makes inference dominate training. This is the exact
        case the 3-phase aggregator (commit 5) must surface; planning
        against training alone would miss the OOM risk."""
        mc = {"segmentation_size": 16000}
        training = train_est.estimate_peak_bytes(
            "rnn", mc, {"batch_size": 1}, {"loss_type": "ce"},
            num_params=1_000_000,
        )
        monkeypatch.setattr(est, "inference_batch_for", lambda mt: 10_000)
        inference = est.estimate_peak_bytes("rnn", mc, num_params=1_000_000)
        assert inference["total_bytes"] > training["total_bytes"]

    def test_raises_on_unregistered_model_type(self):
        """Planning-time estimator must fail loudly for plugins without
        a registered batch — no silent guessing at 25."""
        with pytest.raises(ValueError, match="no registered inference batch"):
            est.estimate_peak_bytes(
                "unregistered_plugin",
                {"segmentation_size": 16000},
                num_params=100_000,
            )


# ---------------------------------------------------------------------------
# estimate_wall_time_seconds
# ---------------------------------------------------------------------------

class TestEstimateWallTimeSeconds:

    def test_return_shape(self):
        out = est.estimate_wall_time_seconds(
            "rnn",
            {"segmentation_size": 16000},
            _sample_set(),
            inference_ms_per_step=1.0,
        )
        assert set(out.keys()) == {"phase", "seconds", "breakdown"}
        assert out["phase"] == "inference"
        assert out["seconds"] > 0
        assert set(out["breakdown"].keys()) >= {
            "total_inference_steps", "inference_batch", "ms_per_step", "ms_source",
        }

    def test_monotone_in_segments(self):
        small = est.estimate_wall_time_seconds(
            "rnn", {"segmentation_size": 16000},
            _sample_set(100), inference_ms_per_step=1.0,
        )
        big = est.estimate_wall_time_seconds(
            "rnn", {"segmentation_size": 16000},
            _sample_set(400), inference_ms_per_step=1.0,
        )
        assert big["seconds"] > small["seconds"]

    def test_monotone_in_inference_batch_at_fixed_ms(self, monkeypatch):
        """At fixed ms/step, larger inf_batch → fewer steps → less time.

        (The static formula scales ms/step linearly with inf_batch too, so
        without the fixed ms/step it would be batch-invariant; that's the
        correct FLOP-count arithmetic and isn't what this test targets.)"""
        monkeypatch.setattr(est, "inference_batch_for", lambda mt: 5)
        small_bs = est.estimate_wall_time_seconds(
            "rnn", {"segmentation_size": 16000},
            _sample_set(), inference_ms_per_step=1.0,
        )
        monkeypatch.setattr(est, "inference_batch_for", lambda mt: 50)
        large_bs = est.estimate_wall_time_seconds(
            "rnn", {"segmentation_size": 16000},
            _sample_set(), inference_ms_per_step=1.0,
        )
        assert large_bs["seconds"] < small_bs["seconds"]

    def test_ms_source_labels_warmup_path(self):
        out = est.estimate_wall_time_seconds(
            "rnn", {"segmentation_size": 16000},
            _sample_set(), inference_ms_per_step=3.0,
        )
        assert out["breakdown"]["ms_source"] == "derived_from_training_warmup"
        assert out["breakdown"]["ms_per_step"] == pytest.approx(3.0)

    def test_static_fallback_invokes_count_params(self, monkeypatch):
        """ms_per_step=None AND num_params=None → ``_count_params`` is invoked."""
        calls = []
        def _stub(model_type, model_config):
            calls.append(model_type)
            return 100_000
        monkeypatch.setattr(est, "_count_params", _stub)
        out = est.estimate_wall_time_seconds(
            "rnn", {"segmentation_size": 16000}, _sample_set(),
        )
        assert calls == ["rnn"]
        assert out["breakdown"]["ms_source"] == "static_formula"

    def test_raises_on_unregistered_model_type(self):
        with pytest.raises(ValueError, match="no registered inference batch"):
            est.estimate_wall_time_seconds(
                "unregistered_plugin",
                {"segmentation_size": 16000},
                _sample_set(),
                inference_ms_per_step=1.0,
            )
