"""
Tests for ml_models/models_format_sandbox.py

Verifies that all Pydantic config classes correctly accept valid inputs
and reject invalid inputs with meaningful errors.
"""

import pytest
from pydantic import ValidationError

from ml_models.models_format_sandbox import (
    AEConfig,
    ExperimentConfig,
    GatedFNOConfig,
    LossConfig,
    PUNetConfig,
    TransformerConfig,
    WaveNetConfig,
)

# ==========================================
# PUNetConfig
# ==========================================


class TestPUNetConfig:
    def test_valid_custom(self):
        cfg = PUNetConfig(segmentation_size=10000, depth=3, multi=32, kernel_size=7)
        assert cfg.depth == 3
        assert cfg.kernel_size == 7

    def test_even_kernel_size_raises(self):
        with pytest.raises(ValidationError, match="odd"):
            PUNetConfig(kernel_size=8)

    def test_segmentation_size_too_small_for_depth_raises(self):
        # depth=4 requires segmentation_size >= 4^4 = 256, but stride makes it 4**4=256
        # Use a clearly too-small value
        with pytest.raises(ValidationError):
            PUNetConfig(segmentation_size=100, depth=4)

    def test_segmentation_size_at_boundary_passes(self):
        # 4^3 = 64, so 1000 is fine for depth=3
        cfg = PUNetConfig(segmentation_size=1000, depth=3)
        assert cfg.segmentation_size == 1000


# ==========================================
# AEConfig
# ==========================================


class TestAEConfig:
    def test_valid_custom_dims(self):
        cfg = AEConfig(latent_dims=[500, 50], segmentation_size=1000)
        assert cfg.latent_dims == [500, 50]

    def test_zero_latent_dim_raises(self):
        with pytest.raises(ValidationError, match="positive"):
            AEConfig(latent_dims=[500, 0, 50])

    def test_negative_latent_dim_raises(self):
        with pytest.raises(ValidationError, match="positive"):
            AEConfig(latent_dims=[-1])


# ==========================================
# TransformerConfig
# ==========================================


class TestTransformerConfig:
    def test_valid_custom(self):
        cfg = TransformerConfig(embedding_dim=64, nhead=4, segmentation_size=5000)
        assert cfg.embedding_dim == 64

    def test_embedding_dim_not_divisible_by_nhead_raises(self):
        with pytest.raises(ValidationError):
            TransformerConfig(embedding_dim=33, nhead=4)

    def test_embedding_dim_divisible_by_nhead_passes(self):
        cfg = TransformerConfig(embedding_dim=32, nhead=4)
        assert cfg.embedding_dim == 32


# ==========================================
# WaveNetConfig
# ==========================================


class TestWaveNetConfig:
    def test_valid_custom(self):
        cfg = WaveNetConfig(num_blocks=4, residual_channels=16, skip_channels=16)
        assert cfg.num_blocks == 4

    def test_odd_gate_channels_raises(self):
        with pytest.raises(ValidationError, match="even"):
            WaveNetConfig(gate_channels=33)

    def test_even_gate_channels_passes(self):
        cfg = WaveNetConfig(gate_channels=32)
        assert cfg.gate_channels == 32


# ==========================================
# RNNSeq2SeqConfig
# ==========================================


# ==========================================
# LossConfig — parameter nullification
# ==========================================


class TestLossConfig:
    def test_focal_nullifies_beta(self):
        cfg = LossConfig(loss_type="focal", alpha=0.25, gamma=2.0, beta=5.0)
        assert cfg.beta is None

    def test_smooth_l1_nullifies_alpha_and_gamma(self):
        cfg = LossConfig(loss_type="smooth_l1", alpha=0.5, gamma=2.0, beta=1.0)
        assert cfg.alpha is None
        assert cfg.gamma is None
        assert cfg.use_class_weights is False

    def test_ce_nullifies_focal_params(self):
        cfg = LossConfig(loss_type="ce")
        assert cfg.alpha is None
        assert cfg.gamma is None
        assert cfg.beta is None


# ==========================================
# ExperimentConfig — cross-validation
# ==========================================


def _make_experiment(model_type: str, loss_type: str) -> dict:
    """Helper to build a minimal valid ExperimentConfig payload."""
    model_configs = {
        "punet": {"model_type": "punet", "segmentation_size": 1000},
        "fcnet": {"model_type": "fcnet", "segmentation_size": 1000, "latent_dims": [100, 10]},
        "transformer": {
            "model_type": "transformer",
            "segmentation_size": 1000,
            "embedding_dim": 32,
            "nhead": 4,
        },
        "wavenet": {"model_type": "wavenet", "segmentation_size": 1000},
        "rnn": {"model_type": "rnn", "segmentation_size": 1000},
    }
    return {
        "exp_id": "test_exp",
        "run_name": "test_run",
        "model_type": model_type,
        "network_config": model_configs[model_type],
        "train_config": {"lr": 1e-4, "epochs": 1, "device": "cpu"},
        "loss_config": {"loss_type": loss_type},
    }


class TestExperimentConfig:
    @pytest.mark.parametrize(
        "model_type,loss_type",
        [
            pytest.param("punet", "focal", id="punet_with_focal"),
            pytest.param("punet", "ce", id="punet_with_ce"),
            pytest.param("fcnet", "smooth_l1", id="fcnet_with_smooth_l1"),
            pytest.param("fcnet", "ce", id="fcnet_with_ce"),
            pytest.param("transformer", "ce", id="transformer_with_ce"),
            pytest.param("wavenet", "ce", id="wavenet_with_ce"),
            pytest.param("rnn", "ce", id="rnn_with_ce"),
        ],
    )
    def test_compatible_model_loss_passes(self, model_type, loss_type):
        cfg = ExperimentConfig(**_make_experiment(model_type, loss_type))
        assert cfg.model_type == model_type

    @pytest.mark.parametrize(
        "model_type",
        [
            pytest.param("punet", id="punet_with_smooth_l1"),
            pytest.param("transformer", id="transformer_with_smooth_l1"),
            pytest.param("wavenet", id="wavenet_with_smooth_l1"),
            pytest.param("rnn", id="rnn_with_smooth_l1"),
        ],
    )
    def test_smooth_l1_with_classification_model_raises(self, model_type):
        with pytest.raises(ValidationError, match="smooth_l1"):
            ExperimentConfig(**_make_experiment(model_type, "smooth_l1"))


# ==========================================
# GatedFNOConfig
# ==========================================


class TestGatedFNOConfig:
    def test_valid_with_static_v(self):
        v = [0.5] * 64
        cfg = GatedFNOConfig(num_gates=64, static_v=v)
        assert cfg.static_v == v
        assert len(cfg.static_v) == 64

    def test_static_v_length_mismatch_raises(self):
        with pytest.raises(ValidationError, match="static_v length"):
            GatedFNOConfig(num_gates=64, static_v=[0.5] * 32)


# ==========================================
# TrainConfig — stable compatibility lr default
# ==========================================


class TestNativeRecoveryGuidance:
    def test_native_recovery_does_not_prescribe_the_schema_default(self):
        """A serialization default must not become a native search strategy.

        Historical recovery wording is covered by the exp-owned provider's
        offline parity checks; the framework tests its explicit native path.
        """
        from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge
        from tests.helpers.tuner_prompt_fixtures import planner_kwargs

        bridge = BoundaryRecorderBridge()
        bridge.plan(**planner_kwargs())
        assert len(bridge.captures) == 1
        assert "`lr=5e-4`" not in bridge.captures[0][2]
        assert "A failure does not by itself prescribe an optimizer" in bridge.captures[0][2]
