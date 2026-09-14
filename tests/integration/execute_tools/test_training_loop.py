"""
Integration tests for execute_tools/train_engine_sandbox.py

Tests one full training run for every valid model/loss combination.
Calls run_experiment() directly (bypassing subprocess) so the test is
self-contained.

Data source: a module-owned one-segment synthetic HDF5 input. Real scientific
data and task qualification belong to the external task repository.

Valid combinations:
  - punet      : ce, focal, focal_cw
  - fcnet      : ce, focal, focal_cw, smooth_l1
  - transformer: ce, focal, focal_cw
  - wavenet    : ce, focal, focal_cw
  - rnn        : ce, focal, focal_cw

Model configs — two variants per model:
  Config A (minimal — used in these tests, fast on CPU):
    punet      : depth=2, multi=16, kernel_size=7
    fcnet      : latent_dims=[200, 20]
    transformer: embedding_dim=32, nhead=4, num_layers=2
    wavenet    : input_channels=8, residual_channels=16, num_blocks=3
    rnn        : embedding_dim=16, hidden_dim=32, num_layers=1

  Config B (larger — closer to real baseline, slower):
    punet      : depth=4, multi=40, kernel_size=9
    fcnet      : latent_dims=[512, 128, 32]
    transformer: embedding_dim=64, nhead=8, num_layers=4
    wavenet    : input_channels=16, residual_channels=32, num_blocks=6
    rnn        : embedding_dim=128, hidden_dim=256, num_layers=2
"""

import os

import numpy as np
import pytest
import torch
from torch.utils.data import DataLoader

from execute_tools.dataset_config import tidmad_topology
from execute_tools.train_engine_sandbox import TIDMADDataset, run_experiment
from ml_models.models_format_sandbox import (
    AEConfig,
    LossConfig,
    PUNetConfig,
    RNNSeq2SeqConfig,
    TrainConfig,
    TransformerConfig,
    WaveNetConfig,
)
from tests.helpers.two_family_profile import write_bound_timeseries

# Segmentation size used for all synthetic tests — small enough to be fast,
# large enough to satisfy the minimum constraint in model configs (ge=1000).
# Does NOT need to match real data (40000). We only test that the loop works.
SYNTH_SEG_SIZE = 1000


@pytest.fixture
def h5_source(tmp_path, synthetic_dataset_profile):
    """Return a local synthetic input factory under an explicit test profile."""

    def _make(seg_size: int):
        topology = tidmad_topology(synthetic_dataset_profile)
        filename = topology.dataset.training_file_name(0)
        rng = np.random.default_rng(42)
        values = rng.integers(-128, 127, size=seg_size, dtype=np.int16)
        write_bound_timeseries(tmp_path / filename, values, values.copy())
        return str(tmp_path), filename

    return _make


# ==========================================
# Helpers
# ==========================================


def make_train_cfg():
    return TrainConfig(lr=1e-3, epochs=1, batch_size=1, device="cpu")


def make_model_cfg(model_type, variant="A"):
    """Return model config for the given model type.

    segmentation_size is fixed to SYNTH_SEG_SIZE for this synthetic test.

    variant="A"  — minimal architecture, fast on CPU.
    variant="B"  — larger architecture, tests model flexibility.
    """
    seg_size = SYNTH_SEG_SIZE  # overridden by make_loader for real data
    if variant == "A":
        if model_type == "punet":
            return PUNetConfig(segmentation_size=seg_size, depth=2, multi=16, kernel_size=7)
        elif model_type == "fcnet":
            return AEConfig(segmentation_size=seg_size, latent_dims=[200, 20])
        elif model_type == "transformer":
            return TransformerConfig(
                segmentation_size=seg_size, embedding_dim=32, nhead=4, num_layers=2
            )
        elif model_type == "wavenet":
            return WaveNetConfig(
                segmentation_size=seg_size,
                input_channels=8,
                residual_channels=16,
                gate_channels=16,
                skip_channels=16,
                num_blocks=3,
            )
        elif model_type == "rnn":
            return RNNSeq2SeqConfig(
                segmentation_size=seg_size, embedding_dim=16, hidden_dim=32, num_layers=1
            )
    elif variant == "B":
        if model_type == "punet":
            return PUNetConfig(segmentation_size=seg_size, depth=4, multi=40, kernel_size=9)
        elif model_type == "fcnet":
            return AEConfig(segmentation_size=seg_size, latent_dims=[512, 128, 32])
        elif model_type == "transformer":
            return TransformerConfig(
                segmentation_size=seg_size, embedding_dim=64, nhead=8, num_layers=4
            )
        elif model_type == "wavenet":
            return WaveNetConfig(
                segmentation_size=seg_size,
                input_channels=16,
                residual_channels=32,
                gate_channels=32,
                skip_channels=32,
                num_blocks=6,
            )
        elif model_type == "rnn":
            return RNNSeq2SeqConfig(
                segmentation_size=seg_size, embedding_dim=128, hidden_dim=256, num_layers=2
            )


def make_loader(h5_source_fn, model_cfg):
    """Build a DataLoader from h5_source (a callable) and the model config.

    Calls h5_source_fn(seg_size) so the module-owned synthetic fixture generates
    exactly enough data for this model's segmentation_size.

    sample_size=1 : one segment per group — sufficient for testing the loop.
    max_segments=1: cap at one training segment so the matrix stays bounded.
    """
    data_dir, fname = h5_source_fn(model_cfg.segmentation_size)
    dataset = TIDMADDataset(
        data_dir, [fname], model_cfg.segmentation_size, sample_size=1, max_segments=1
    )
    return DataLoader(dataset, batch_size=1, shuffle=False, drop_last=True)


def run_one(model_type, loss_type, h5_source, tmp_path, variant="A"):
    """Run one training experiment and return (results, model_path).

    variant="A"  — minimal architecture, fast on CPU.
    variant="B"  — larger architecture, tests model flexibility.
    Both variants are parametrized in every test. To run a single variant:
        uv run pytest -k "A"   or   uv run pytest -k "B"
    This module has no real-data mode.
    """
    exp_id = f"test_{model_type}_{loss_type}_cfg{variant}"
    model_dir = tmp_path / "cached_models"
    model_dir.mkdir(exist_ok=True)
    sandbox_dirs = {"models": str(model_dir)}

    model_cfg = make_model_cfg(model_type, variant=variant)
    train_cfg = make_train_cfg()
    loss_cfg = LossConfig(loss_type=loss_type)
    loader = make_loader(h5_source, model_cfg)

    results = run_experiment(model_cfg, train_cfg, loss_cfg, loader, sandbox_dirs, exp_id)
    model_path = os.path.join(str(model_dir), f"model_{model_type}_{exp_id}_agent.pth")
    return results, model_path


# ==========================================
# punet — classification losses only
# ==========================================


class TestPUNetTraining:
    @pytest.mark.parametrize("variant", ["A", "B"])
    @pytest.mark.parametrize("loss_type", ["ce", "focal", "focal_cw"])
    def test_punet_trains_and_saves_model(self, loss_type, variant, h5_source, tmp_path):
        results, model_path = run_one("punet", loss_type, h5_source, tmp_path, variant=variant)

        assert "final_loss" in results
        assert "loss_history" in results
        assert len(results["loss_history"]) == 1  # 1 epoch
        assert isinstance(results["final_loss"], float)
        assert os.path.exists(model_path), f"Model not saved at {model_path}"

    @pytest.mark.parametrize("variant", ["A", "B"])
    @pytest.mark.parametrize("loss_type", ["ce", "focal", "focal_cw"])
    def test_punet_model_is_loadable(self, loss_type, variant, h5_source, tmp_path):
        _, model_path = run_one("punet", loss_type, h5_source, tmp_path, variant=variant)
        state = torch.load(model_path, map_location="cpu")
        assert isinstance(state, dict)
        assert len(state) > 0


# ==========================================
# fcnet — classification and regression losses
# ==========================================


class TestFCNetTraining:
    @pytest.mark.parametrize("variant", ["A", "B"])
    @pytest.mark.parametrize("loss_type", ["ce", "focal", "focal_cw", "smooth_l1"])
    def test_fcnet_trains_and_saves_model(self, loss_type, variant, h5_source, tmp_path):
        results, model_path = run_one("fcnet", loss_type, h5_source, tmp_path, variant=variant)

        assert "final_loss" in results
        assert "loss_history" in results
        assert len(results["loss_history"]) == 1
        assert isinstance(results["final_loss"], float)
        assert os.path.exists(model_path), f"Model not saved at {model_path}"

    @pytest.mark.parametrize("variant", ["A", "B"])
    @pytest.mark.parametrize("loss_type", ["ce", "focal", "focal_cw", "smooth_l1"])
    def test_fcnet_model_is_loadable(self, loss_type, variant, h5_source, tmp_path):
        _, model_path = run_one("fcnet", loss_type, h5_source, tmp_path, variant=variant)
        state = torch.load(model_path, map_location="cpu")
        assert isinstance(state, dict)
        assert len(state) > 0


# ==========================================
# transformer — classification losses only
# ==========================================


class TestTransformerTraining:
    @pytest.mark.parametrize("variant", ["A", "B"])
    @pytest.mark.parametrize("loss_type", ["ce", "focal", "focal_cw"])
    def test_transformer_trains_and_saves_model(self, loss_type, variant, h5_source, tmp_path):
        results, model_path = run_one(
            "transformer", loss_type, h5_source, tmp_path, variant=variant
        )

        assert "final_loss" in results
        assert "loss_history" in results
        assert len(results["loss_history"]) == 1
        assert isinstance(results["final_loss"], float)
        assert os.path.exists(model_path), f"Model not saved at {model_path}"

    @pytest.mark.parametrize("variant", ["A", "B"])
    @pytest.mark.parametrize("loss_type", ["ce", "focal", "focal_cw"])
    def test_transformer_model_is_loadable(self, loss_type, variant, h5_source, tmp_path):
        _, model_path = run_one("transformer", loss_type, h5_source, tmp_path, variant=variant)
        state = torch.load(model_path, map_location="cpu")
        assert isinstance(state, dict)
        assert len(state) > 0


# ==========================================
# wavenet — classification losses only
# ==========================================


class TestWaveNetTraining:
    @pytest.mark.parametrize("variant", ["A", "B"])
    @pytest.mark.parametrize("loss_type", ["ce", "focal", "focal_cw"])
    def test_wavenet_trains_and_saves_model(self, loss_type, variant, h5_source, tmp_path):
        results, model_path = run_one("wavenet", loss_type, h5_source, tmp_path, variant=variant)

        assert "final_loss" in results
        assert "loss_history" in results
        assert len(results["loss_history"]) == 1
        assert isinstance(results["final_loss"], float)
        assert os.path.exists(model_path), f"Model not saved at {model_path}"

    @pytest.mark.parametrize("variant", ["A", "B"])
    @pytest.mark.parametrize("loss_type", ["ce", "focal", "focal_cw"])
    def test_wavenet_model_is_loadable(self, loss_type, variant, h5_source, tmp_path):
        _, model_path = run_one("wavenet", loss_type, h5_source, tmp_path, variant=variant)
        state = torch.load(model_path, map_location="cpu")
        assert isinstance(state, dict)
        assert len(state) > 0


# ==========================================
# rnn — classification losses only
# ==========================================


class TestRNNSeq2SeqTraining:
    @pytest.mark.parametrize("variant", ["A", "B"])
    @pytest.mark.parametrize("loss_type", ["ce", "focal", "focal_cw"])
    def test_rnn_trains_and_saves_model(self, loss_type, variant, h5_source, tmp_path):
        results, model_path = run_one("rnn", loss_type, h5_source, tmp_path, variant=variant)

        assert "final_loss" in results
        assert "loss_history" in results
        assert len(results["loss_history"]) == 1
        assert isinstance(results["final_loss"], float)
        assert os.path.exists(model_path), f"Model not saved at {model_path}"

    @pytest.mark.parametrize("variant", ["A", "B"])
    @pytest.mark.parametrize("loss_type", ["ce", "focal", "focal_cw"])
    def test_rnn_model_is_loadable(self, loss_type, variant, h5_source, tmp_path):
        _, model_path = run_one("rnn", loss_type, h5_source, tmp_path, variant=variant)
        state = torch.load(model_path, map_location="cpu")
        assert isinstance(state, dict)
        assert len(state) > 0
