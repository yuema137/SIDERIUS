"""
Tests for ml_models/models_sandbox.py

Verifies that each model's forward pass produces the correct output shape
on CPU with synthetic inputs. Uses small segmentation_size for speed.
"""
import pytest
import torch

from ml_models.models_sandbox import PositionalUNet, AE, TransformerModel, SimpleWaveNet, RNNSeq2Seq, MODEL_REGISTRY
from ml_models.models_format_sandbox import PUNetConfig, AEConfig, TransformerConfig, WaveNetConfig, RNNSeq2SeqConfig


BATCH = 2
SEG_SIZE = 1000  # small for speed


# ==========================================
# MODEL_REGISTRY
# ==========================================

class TestModelRegistry:

    def test_registry_contains_all_builtin_models(self):
        expected = {"punet", "fcnet", "transformer", "wavenet", "rnn"}
        assert expected.issubset(set(MODEL_REGISTRY.keys()))

    def test_registry_maps_to_correct_classes(self):
        assert MODEL_REGISTRY["punet"] is PositionalUNet
        assert MODEL_REGISTRY["fcnet"] is AE
        assert MODEL_REGISTRY["transformer"] is TransformerModel
        assert MODEL_REGISTRY["wavenet"] is SimpleWaveNet
        assert MODEL_REGISTRY["rnn"] is RNNSeq2Seq


# ==========================================
# PositionalUNet
# ==========================================

class TestPositionalUNet:

    @pytest.fixture
    def input_tensor(self):
        """[Batch, SeqLen] integer tensor simulating ADC values (0-255)."""
        return torch.randint(0, 256, (BATCH, SEG_SIZE))

    def _make_model(self, **kwargs):
        cfg = PUNetConfig(segmentation_size=SEG_SIZE, **kwargs)
        return PositionalUNet(cfg)

    def test_output_shape(self, input_tensor):
        model = self._make_model()
        out = model(input_tensor)
        assert out.shape == (BATCH, 256, SEG_SIZE)

    def test_output_shape_depth_2(self, input_tensor):
        model = self._make_model(depth=2)
        out = model(input_tensor)
        assert out.shape == (BATCH, 256, SEG_SIZE)

    def test_output_shape_depth_3(self, input_tensor):
        model = self._make_model(depth=3)
        out = model(input_tensor)
        assert out.shape == (BATCH, 256, SEG_SIZE)

    def test_output_is_float(self, input_tensor):
        model = self._make_model()
        out = model(input_tensor)
        assert out.dtype == torch.float32

    def test_no_nan_in_output(self, input_tensor):
        model = self._make_model()
        out = model(input_tensor)
        assert not torch.isnan(out).any()


# ==========================================
# AE (fcnet)
# ==========================================

class TestAE:

    @pytest.fixture
    def input_tensor(self):
        """[Batch, SeqLen] float tensor."""
        return torch.randn(BATCH, SEG_SIZE)

    def _make_model(self, loss_type="ce"):
        cfg = AEConfig(segmentation_size=SEG_SIZE, latent_dims=[200, 20])
        return AE(cfg, loss_type=loss_type)

    def test_output_shape_classification(self, input_tensor):
        """CE/focal mode: output should be [Batch, 256, SeqLen]."""
        model = self._make_model(loss_type="ce")
        out = model(input_tensor)
        assert out.shape == (BATCH, 256, SEG_SIZE)

    def test_output_shape_regression(self, input_tensor):
        """smooth_l1 mode: output should be [Batch, SeqLen]."""
        model = self._make_model(loss_type="smooth_l1")
        out = model(input_tensor)
        assert out.shape == (BATCH, SEG_SIZE)

    def test_output_is_float(self, input_tensor):
        model = self._make_model()
        out = model(input_tensor)
        assert out.dtype == torch.float32

    def test_no_nan_in_output(self, input_tensor):
        model = self._make_model()
        out = model(input_tensor)
        assert not torch.isnan(out).any()

    def test_custom_latent_dims(self, input_tensor):
        cfg = AEConfig(segmentation_size=SEG_SIZE, latent_dims=[500, 100, 10])
        model = AE(cfg, loss_type="ce")
        out = model(input_tensor)
        assert out.shape == (BATCH, 256, SEG_SIZE)


# ==========================================
# TransformerModel
# ==========================================

class TestTransformerModel:

    @pytest.fixture
    def input_tensor(self):
        """[Batch, SeqLen] long tensor simulating ADC values (0-255)."""
        return torch.randint(0, 256, (BATCH, SEG_SIZE)).long()

    def _make_model(self, num_layers=2, **kwargs):
        cfg = TransformerConfig(
            segmentation_size=SEG_SIZE,
            embedding_dim=32,
            nhead=4,
            num_layers=num_layers,
            **kwargs
        )
        return TransformerModel(cfg)

    def test_output_shape(self, input_tensor):
        model = self._make_model()
        out = model(input_tensor)
        assert out.shape == (BATCH, 256, SEG_SIZE)

    def test_output_shape_deeper(self, input_tensor):
        model = self._make_model(num_layers=4)
        out = model(input_tensor)
        assert out.shape == (BATCH, 256, SEG_SIZE)

    def test_output_is_float(self, input_tensor):
        model = self._make_model()
        out = model(input_tensor)
        assert out.dtype == torch.float32

    def test_no_nan_in_output(self, input_tensor):
        model = self._make_model()
        out = model(input_tensor)
        assert not torch.isnan(out).any()


# ==========================================
# SimpleWaveNet
# ==========================================

class TestSimpleWaveNet:

    @pytest.fixture
    def input_tensor(self):
        """[Batch, SeqLen] integer tensor simulating ADC values (0-255)."""
        return torch.randint(0, 256, (BATCH, SEG_SIZE))

    def _make_model(self, num_blocks=3, **kwargs):
        cfg = WaveNetConfig(
            segmentation_size=SEG_SIZE,
            input_channels=8,
            residual_channels=16,
            gate_channels=16,
            skip_channels=16,
            num_blocks=num_blocks,
            **kwargs
        )
        return SimpleWaveNet(cfg)

    def test_output_shape(self, input_tensor):
        model = self._make_model()
        out = model(input_tensor)
        assert out.shape == (BATCH, 256, SEG_SIZE)

    def test_output_is_float(self, input_tensor):
        model = self._make_model()
        out = model(input_tensor)
        assert out.dtype == torch.float32

    def test_no_nan_in_output(self, input_tensor):
        model = self._make_model()
        out = model(input_tensor)
        assert not torch.isnan(out).any()

    def test_more_blocks(self, input_tensor):
        model = self._make_model(num_blocks=5)
        out = model(input_tensor)
        assert out.shape == (BATCH, 256, SEG_SIZE)


# ==========================================
# RNNSeq2Seq
# ==========================================

class TestRNNSeq2Seq:

    @pytest.fixture
    def input_tensor(self):
        """[Batch, SeqLen] integer tensor simulating ADC values (0-255)."""
        return torch.randint(0, 256, (BATCH, SEG_SIZE))

    def _make_model(self, num_layers=1, hidden_dim=32, **kwargs):
        cfg = RNNSeq2SeqConfig(
            segmentation_size=SEG_SIZE,
            embedding_dim=16,
            hidden_dim=hidden_dim,
            num_layers=num_layers,
            **kwargs
        )
        return RNNSeq2Seq(cfg)

    def test_output_shape(self, input_tensor):
        model = self._make_model()
        out = model(input_tensor)
        assert out.shape == (BATCH, 256, SEG_SIZE)

    def test_output_is_float(self, input_tensor):
        model = self._make_model()
        out = model(input_tensor)
        assert out.dtype == torch.float32

    def test_no_nan_in_output(self, input_tensor):
        model = self._make_model()
        out = model(input_tensor)
        assert not torch.isnan(out).any()

    def test_deeper_layers(self, input_tensor):
        model = self._make_model(num_layers=2, hidden_dim=32)
        out = model(input_tensor)
        assert out.shape == (BATCH, 256, SEG_SIZE)
