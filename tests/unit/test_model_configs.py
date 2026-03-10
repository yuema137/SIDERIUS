"""
Tests for model_tools/models_format_sandbox.py

Verifies that all Pydantic config classes correctly accept valid inputs
and reject invalid inputs with meaningful errors.
"""
import pytest
from pydantic import ValidationError

from model_tools.models_format_sandbox import (
    PUNetConfig,
    AEConfig,
    TransformerConfig,
    LossConfig,
    TrainConfig,
    ExperimentConfig,
)


# ==========================================
# PUNetConfig
# ==========================================

class TestPUNetConfig:

    def test_valid_default(self):
        cfg = PUNetConfig()
        assert cfg.model_type == "punet"
        assert cfg.kernel_size == 9
        assert cfg.depth == 4

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

    def test_valid_default(self):
        cfg = AEConfig()
        assert cfg.model_type == "fcnet"
        assert cfg.latent_dims == [4000, 400, 40]

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

    def test_valid_default(self):
        cfg = TransformerConfig()
        assert cfg.model_type == "transformer"
        assert cfg.nhead == 4

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

    def test_focal_cw_valid(self):
        cfg = LossConfig(loss_type="focal_cw", gamma=4.0)
        assert cfg.loss_type == "focal_cw"


# ==========================================
# ExperimentConfig — cross-validation
# ==========================================

def _make_experiment(model_type: str, loss_type: str) -> dict:
    """Helper to build a minimal valid ExperimentConfig payload."""
    model_configs = {
        "punet":       {"model_type": "punet", "segmentation_size": 1000},
        "fcnet":       {"model_type": "fcnet", "segmentation_size": 1000, "latent_dims": [100, 10]},
        "transformer": {"model_type": "transformer", "segmentation_size": 1000, "embedding_dim": 32, "nhead": 4},
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

    def test_punet_with_focal_passes(self):
        cfg = ExperimentConfig(**_make_experiment("punet", "focal"))
        assert cfg.model_type == "punet"

    def test_punet_with_ce_passes(self):
        cfg = ExperimentConfig(**_make_experiment("punet", "ce"))
        assert cfg.model_type == "punet"

    def test_fcnet_with_smooth_l1_passes(self):
        cfg = ExperimentConfig(**_make_experiment("fcnet", "smooth_l1"))
        assert cfg.model_type == "fcnet"

    def test_fcnet_with_ce_passes(self):
        cfg = ExperimentConfig(**_make_experiment("fcnet", "ce"))
        assert cfg.model_type == "fcnet"

    def test_transformer_with_ce_passes(self):
        cfg = ExperimentConfig(**_make_experiment("transformer", "ce"))
        assert cfg.model_type == "transformer"

    def test_punet_with_smooth_l1_raises(self):
        with pytest.raises(ValidationError, match="smooth_l1"):
            ExperimentConfig(**_make_experiment("punet", "smooth_l1"))

    def test_transformer_with_smooth_l1_raises(self):
        with pytest.raises(ValidationError, match="smooth_l1"):
            ExperimentConfig(**_make_experiment("transformer", "smooth_l1"))
