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
    RNNSeq2SeqConfig,
    TrainConfig,
    TransformerConfig,
    WaveNetConfig,
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
# WaveNetConfig
# ==========================================


class TestWaveNetConfig:
    def test_valid_default(self):
        cfg = WaveNetConfig()
        assert cfg.model_type == "wavenet"
        assert cfg.gate_channels == 64
        assert cfg.num_blocks == 10

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


class TestRNNSeq2SeqConfig:
    def test_valid_default(self):
        cfg = RNNSeq2SeqConfig()
        assert cfg.model_type == "rnn"
        assert cfg.hidden_dim == 256
        assert cfg.num_layers == 2

    def test_valid_custom(self):
        cfg = RNNSeq2SeqConfig(embedding_dim=64, hidden_dim=128, num_layers=1)
        assert cfg.hidden_dim == 128
        assert cfg.num_layers == 1

    def test_dropout_ignored_for_single_layer(self):
        # dropout > 0 with num_layers=1 is valid config (LSTM silently ignores it)
        cfg = RNNSeq2SeqConfig(num_layers=1, dropout=0.3)
        assert cfg.dropout == 0.3

    def test_hidden_dim_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            RNNSeq2SeqConfig(hidden_dim=2000)


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
    def test_valid_default(self):
        cfg = GatedFNOConfig()
        assert cfg.model_type == "gated_fno"
        assert cfg.width == 64
        assert cfg.num_layers == 2
        assert cfg.num_gates == 128
        assert cfg.static_v is None

    def test_valid_custom(self):
        cfg = GatedFNOConfig(width=32, num_layers=3, num_gates=64)
        assert cfg.width == 32
        assert cfg.num_layers == 3
        assert cfg.num_gates == 64

    def test_valid_with_static_v(self):
        v = [0.5] * 64
        cfg = GatedFNOConfig(num_gates=64, static_v=v)
        assert cfg.static_v == v
        assert len(cfg.static_v) == 64

    def test_static_v_length_mismatch_raises(self):
        with pytest.raises(ValidationError, match="static_v length"):
            GatedFNOConfig(num_gates=64, static_v=[0.5] * 32)

    @pytest.mark.parametrize(
        "kwargs",
        [
            pytest.param({"width": 8}, id="width_below_min"),
            pytest.param({"num_layers": 0}, id="num_layers_below_min"),
            pytest.param({"num_gates": 4}, id="num_gates_below_min"),
        ],
    )
    def test_field_below_min_raises(self, kwargs):
        with pytest.raises(ValidationError):
            GatedFNOConfig(**kwargs)


# ==========================================
# TrainConfig — stable compatibility lr default
# ==========================================


class TestTrainConfigCompatibilityLrDefault:
    """An omitted LLM ``lr`` key keeps the established resolved value.

    Repository separation moves scientific baseline artifacts without
    silently changing a generic schema default. The expectation is hardcoded
    rather than read back from the schema under test, so drift still fails.
    """

    def test_omitted_lr_resolves_stably_through_the_production_path(self):
        """Defect only this catches: the schema default departing 5e-4.

        The construction below is the exact production validation
        expression for an LLM plan's training config —
        ``TrainConfig(**t_cfg)`` at ``core/sandbox_executor.py`` (parent
        validation) and ``execute_tools/train_engine_sandbox.py`` (trainer
        subprocess) — with ``lr`` absent, as an LLM that omits the key
        produces it. Fails when: the declared default moves off 5e-4.
        """
        t_cfg = {"epochs": 1, "batch_size": 1, "device": "cpu"}  # no "lr" key
        assert TrainConfig(**t_cfg).lr == 5e-4

    def test_collapse_recovery_prompt_names_the_same_compatibility_value(self):
        """Defect only this catches: the planner prompt's known-working
        value drifting from the schema default (two authorities again).

        The collapse-recovery block tells the LLM to "reset to the
        known-working baseline: ... ``lr=5e-4``". That literal and the
        schema default above are pinned to the same hardcoded value,
        so whichever surface moves first fails one of these two tests
        rather than silently disagreeing with the other. Fails when: the
        prompt literal is edited or removed.
        """
        from agent.prompts import PLANNER_PROMPT

        assert "`lr=5e-4`" in PLANNER_PROMPT
