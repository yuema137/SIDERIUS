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
  * **K.2.5-8**: unregistered model_type uses runtime fallback batch
    (25) and surfaces ``inference_batch_uncalibrated: True`` instead
    of crashing the gate.
  * registered model_type → ``inference_batch_uncalibrated: False``.

- ``estimate_wall_time_seconds``:
  * shape ``{"phase", "seconds", "breakdown"}``.
  * monotone in segments (more data → more time).
  * monotone in ``inference_batch`` at fixed ms/step (larger batch →
    fewer steps → less time).
  * static fallback invokes ``_count_params`` (monkeypatched).
  * **K.2.5-8**: unregistered model_type uses runtime fallback batch
    and flags the breakdown.
"""

from __future__ import annotations

import pytest

from agent.skills.inference_skill import estimator as est
from agent.skills.training_skill import estimator as train_est
from tests.helpers.two_family_profile import make_two_family_profile

_PROFILE = make_two_family_profile(
    num_files=20,
    psd_segment_length=1_600_000,
    segments_per_file=20,
)


def _sample_set(n_psd: int = 400) -> dict:
    """Mirror the fixture from test_evaluate_time_skill (20 keys)."""
    return {str(i): list(range(n_psd // 20)) for i in range(20)}


# ---------------------------------------------------------------------------
# estimate_peak_bytes
# ---------------------------------------------------------------------------


class TestEstimatePeakBytes:
    def test_return_shape(self):
        out = est.estimate_peak_bytes(
            "rnn",
            {"segmentation_size": 16000},
            num_params=100_000,
        )
        assert set(out.keys()) == {"phase", "total_bytes", "breakdown"}
        assert out["phase"] == "inference"
        assert out["total_bytes"] > 0
        assert "inference_batch" in out["breakdown"]

    def test_weights_use_4x_factor_not_16x(self):
        """Inference has no grads or Adam states → 4 B/param, not 16 B."""
        out = est.estimate_peak_bytes(
            "rnn",
            {"segmentation_size": 16000},
            num_params=100_000,
        )
        assert out["breakdown"]["weights_bytes"] == 100_000 * 4

    def test_no_focal_onehot_key(self):
        """Inference does not compute loss — no focal one_hot term should
        appear in the breakdown regardless of training loss choice."""
        out = est.estimate_peak_bytes(
            "rnn",
            {"segmentation_size": 16000},
            num_params=100_000,
        )
        assert "focal_onehot_bytes" not in out["breakdown"]

    def test_rnn_has_no_transformer_attn(self):
        out = est.estimate_peak_bytes(
            "rnn",
            {"segmentation_size": 16000},
            num_params=100_000,
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
        assert (
            large["breakdown"]["transformer_attn_bytes"]
            == 2 * small["breakdown"]["transformer_attn_bytes"]
        )

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
            "rnn",
            mc,
            {"batch_size": 1},
            {"loss_type": "ce"},
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
            "rnn",
            mc,
            {"batch_size": 1},
            {"loss_type": "ce"},
            num_params=1_000_000,
        )
        monkeypatch.setattr(est, "inference_batch_for", lambda mt: 10_000)
        inference = est.estimate_peak_bytes("rnn", mc, num_params=1_000_000)
        assert inference["total_bytes"] > training["total_bytes"]

    def test_unregistered_model_type_uses_runtime_fallback(self):
        """K.2.5-8: post-fallback, unregistered model_types no longer
        crash the gate. The estimator substitutes the runtime default
        (25) and marks the breakdown so callers can warn + audit.

        Pre-K.2.5-8 this raised ``ValueError``; that path crashed every
        gate the proposer triggered on a model_type it invented (e.g.
        ``pe_wavenet_delta`` in the K.8.1 smoke), bypassing K.7's
        gate-exhaustion feedback. See §10.14 K.2.5-8."""
        out = est.estimate_peak_bytes(
            "unregistered_plugin",
            {"segmentation_size": 16000},
            num_params=100_000,
        )
        assert out["breakdown"]["inference_batch"] == 25
        assert out["breakdown"]["inference_batch_uncalibrated"] is True

    def test_registered_model_type_is_not_uncalibrated(self):
        """K.2.5-8: known seed model_types must not get flagged."""
        out = est.estimate_peak_bytes(
            "wavenet",
            {"segmentation_size": 16000},
            num_params=100_000,
        )
        assert out["breakdown"]["inference_batch_uncalibrated"] is False


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
            dataset_profile=_PROFILE,
        )
        assert set(out.keys()) == {"phase", "seconds", "breakdown"}
        assert out["phase"] == "inference"
        assert out["seconds"] > 0
        assert set(out["breakdown"].keys()) >= {
            "total_inference_steps",
            "inference_batch",
            "ms_per_step",
            "ms_source",
        }

    def test_monotone_in_segments(self):
        small = est.estimate_wall_time_seconds(
            "rnn",
            {"segmentation_size": 16000},
            _sample_set(100),
            inference_ms_per_step=1.0,
            dataset_profile=_PROFILE,
        )
        big = est.estimate_wall_time_seconds(
            "rnn",
            {"segmentation_size": 16000},
            _sample_set(400),
            inference_ms_per_step=1.0,
            dataset_profile=_PROFILE,
        )
        assert big["seconds"] > small["seconds"]

    def test_monotone_in_inference_batch_at_fixed_ms(self, monkeypatch):
        """At fixed ms/step, larger inf_batch → fewer steps → less time.

        (The static formula scales ms/step linearly with inf_batch too, so
        without the fixed ms/step it would be batch-invariant; that's the
        correct FLOP-count arithmetic and isn't what this test targets.)"""
        monkeypatch.setattr(est, "inference_batch_for", lambda mt: 5)
        small_bs = est.estimate_wall_time_seconds(
            "rnn",
            {"segmentation_size": 16000},
            _sample_set(),
            inference_ms_per_step=1.0,
            dataset_profile=_PROFILE,
        )
        monkeypatch.setattr(est, "inference_batch_for", lambda mt: 50)
        large_bs = est.estimate_wall_time_seconds(
            "rnn",
            {"segmentation_size": 16000},
            _sample_set(),
            inference_ms_per_step=1.0,
            dataset_profile=_PROFILE,
        )
        assert large_bs["seconds"] < small_bs["seconds"]

    def test_ms_source_labels_warmup_path(self):
        out = est.estimate_wall_time_seconds(
            "rnn",
            {"segmentation_size": 16000},
            _sample_set(),
            inference_ms_per_step=3.0,
            dataset_profile=_PROFILE,
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
            "rnn",
            {"segmentation_size": 16000},
            _sample_set(),
            dataset_profile=_PROFILE,
        )
        assert calls == ["rnn"]
        assert out["breakdown"]["ms_source"] == "static_formula"

    def test_unregistered_model_type_uses_runtime_fallback(self):
        """K.2.5-8 wall-time mirror: unregistered model_types use the
        runtime fallback batch and flag the breakdown."""
        out = est.estimate_wall_time_seconds(
            "unregistered_plugin",
            {"segmentation_size": 16000},
            _sample_set(),
            inference_ms_per_step=1.0,
            dataset_profile=_PROFILE,
        )
        assert out["breakdown"]["inference_batch"] == 25
        assert out["breakdown"]["inference_batch_uncalibrated"] is True


# ---------------------------------------------------------------------------
# V21 PR G G1 — explicit-batch forecast seam
# ---------------------------------------------------------------------------


class TestResolveForecastBatch:
    """``resolve_forecast_batch`` — the G1 override resolver."""

    def test_none_returns_registry_value(self):
        assert est.resolve_forecast_batch(None, "rnn") == 10
        assert est.resolve_forecast_batch(None, "unregistered_plugin") == 25

    def test_explicit_overrides_table_precedence(self):
        """NAMED MUTATION PIN (G1 acceptance): reversing the explicit-vs-
        table precedence (returning the registry value when an explicit
        batch is supplied) fails BOTH asserts — the explicit values differ
        from the table entries (rnn: 10, fallback: 25) by construction."""
        assert est.resolve_forecast_batch(64, "rnn") == 64
        assert est.resolve_forecast_batch(7, "unregistered_plugin") == 7

    @pytest.mark.parametrize("bad", [0, -3, True, False, 25.0, "25"])
    def test_invalid_explicit_rejected_loudly(self, bad):
        """Fail-closed: no silent clamp, no fallback. ``bool`` is rejected
        despite being an ``int`` subclass — a True/False batch is a caller
        bug, not batch 1/0."""
        with pytest.raises(ValueError, match="inference_batch override"):
            est.resolve_forecast_batch(bad, "rnn")


class TestG1ExplicitBatchSeam:
    """G1 acceptance: default-path parity (deep-equal, hardcoded
    expectations), explicit value used verbatim, and
    ``inference_batch_uncalibrated`` unchanged by supplying a hint."""

    # Fixture algebra (hardcoded, independent of the code under test):
    # SEGMENT_LENGTH = 1_600_000, seg 16000 → ml_per_psd = 100;
    # _sample_set() = 400 physical segments → total_ml = 40_000.

    def test_default_parity_registered_deep_equal(self):
        """Absent hint → byte-identical pre-G1 output. Full-dict pin, not
        just the batch field: rnn table batch 10 → 4_000 steps × 2 ms."""
        out = est.estimate_wall_time_seconds(
            "rnn",
            {"segmentation_size": 16000},
            _sample_set(),
            inference_ms_per_step=2.0,
            dataset_profile=_PROFILE,
        )
        assert out == {
            "phase": "inference",
            "seconds": 8.0,
            "breakdown": {
                "total_inference_steps": 4_000,
                "inference_batch": 10,
                "ms_per_step": 2.0,
                "ms_source": "derived_from_training_warmup",
                "inference_batch_uncalibrated": False,
            },
        }

    def test_default_parity_unregistered_deep_equal(self):
        """Absent hint, unregistered model → fallback batch 25 →
        1_600 steps × 2 ms; flag True. Full-dict pin."""
        out = est.estimate_wall_time_seconds(
            "unregistered_plugin",
            {"segmentation_size": 16000},
            _sample_set(),
            inference_ms_per_step=2.0,
            dataset_profile=_PROFILE,
        )
        assert out == {
            "phase": "inference",
            "seconds": 3.2,
            "breakdown": {
                "total_inference_steps": 1_600,
                "inference_batch": 25,
                "ms_per_step": 2.0,
                "ms_source": "derived_from_training_warmup",
                "inference_batch_uncalibrated": True,
            },
        }

    def test_explicit_none_identical_to_absent(self):
        """``inference_batch=None`` is the declared no-op form of the seam."""
        absent = est.estimate_wall_time_seconds(
            "rnn",
            {"segmentation_size": 16000},
            _sample_set(),
            inference_ms_per_step=2.0,
            dataset_profile=_PROFILE,
        )
        explicit_none = est.estimate_wall_time_seconds(
            "rnn",
            {"segmentation_size": 16000},
            _sample_set(),
            inference_ms_per_step=2.0,
            inference_batch=None,
            dataset_profile=_PROFILE,
        )
        assert absent == explicit_none

    def test_explicit_value_used_verbatim_with_ceil_algebra(self):
        """Explicit 64 on rnn (table 10): the breakdown reports 64 in the
        EXISTING key (no new key on any path — 0.R.1) and the step count
        follows ceil(40_000 / 64) = 625."""
        out = est.estimate_wall_time_seconds(
            "rnn",
            {"segmentation_size": 16000},
            _sample_set(),
            inference_ms_per_step=2.0,
            inference_batch=64,
            dataset_profile=_PROFILE,
        )
        assert out["breakdown"]["inference_batch"] == 64
        assert out["breakdown"]["total_inference_steps"] == 625
        assert out["seconds"] == pytest.approx(625 * 2.0 / 1000.0)
        assert set(out["breakdown"].keys()) == {
            "total_inference_steps",
            "inference_batch",
            "ms_per_step",
            "ms_source",
            "inference_batch_uncalibrated",
        }

    def test_uncalibrated_flag_unchanged_by_explicit_batch(self):
        """The flag keeps its registration meaning ("is this model_type in
        the table"), NOT "was a batch supplied": registered stays False,
        unregistered stays True, hint or no hint."""
        registered = est.estimate_wall_time_seconds(
            "rnn",
            {"segmentation_size": 16000},
            _sample_set(),
            inference_ms_per_step=2.0,
            inference_batch=64,
            dataset_profile=_PROFILE,
        )
        unregistered = est.estimate_wall_time_seconds(
            "unregistered_plugin",
            {"segmentation_size": 16000},
            _sample_set(),
            inference_ms_per_step=2.0,
            inference_batch=64,
            dataset_profile=_PROFILE,
        )
        assert registered["breakdown"]["inference_batch_uncalibrated"] is False
        assert unregistered["breakdown"]["inference_batch_uncalibrated"] is True

    def test_explicit_equal_to_table_value_is_deep_equal_to_default(self):
        """Supplying the table's own value must be indistinguishable from
        not supplying one (Q-G-5 no-hint parity in its boundary case)."""
        default = est.estimate_wall_time_seconds(
            "rnn",
            {"segmentation_size": 16000},
            _sample_set(),
            inference_ms_per_step=2.0,
            dataset_profile=_PROFILE,
        )
        explicit = est.estimate_wall_time_seconds(
            "rnn",
            {"segmentation_size": 16000},
            _sample_set(),
            inference_ms_per_step=2.0,
            inference_batch=10,
            dataset_profile=_PROFILE,
        )
        assert default == explicit

    def test_invalid_explicit_raises_through_entry_point(self):
        with pytest.raises(ValueError, match="inference_batch override"):
            est.estimate_wall_time_seconds(
                "rnn",
                {"segmentation_size": 16000},
                _sample_set(),
                inference_ms_per_step=2.0,
                inference_batch=0,
                dataset_profile=_PROFILE,
            )
