"""
Integration tests for execute_tools/train_engine_sandbox.py

Tests one full training run for every valid model/loss combination using
synthetic HDF5 data. Calls run_experiment() directly (bypassing subprocess)
so the test is self-contained and fast.

Valid combinations:
  - punet      : ce, focal, focal_cw
  - fcnet      : ce, focal, focal_cw, smooth_l1
  - transformer: ce, focal, focal_cw
"""
import os
import pytest
import torch
from torch.utils.data import DataLoader

from train_engine_sandbox import TIDMADDataset, run_experiment
from models_format_sandbox import PUNetConfig, AEConfig, TransformerConfig, WaveNetConfig, TrainConfig, LossConfig


SEG_SIZE = 1000


# ==========================================
# Helpers
# ==========================================

def make_train_cfg():
    return TrainConfig(lr=1e-3, epochs=1, batch_size=1, device="cpu")


def make_model_cfg(model_type):
    if model_type == "punet":
        return PUNetConfig(segmentation_size=SEG_SIZE, depth=2, multi=16, kernel_size=7)
    elif model_type == "fcnet":
        return AEConfig(segmentation_size=SEG_SIZE, latent_dims=[200, 20])
    elif model_type == "transformer":
        return TransformerConfig(segmentation_size=SEG_SIZE, embedding_dim=32, nhead=4, num_layers=2)
    elif model_type == "wavenet":
        return WaveNetConfig(segmentation_size=SEG_SIZE, input_channels=8, residual_channels=16,
                             gate_channels=16, skip_channels=16, num_blocks=3)


def make_loader(synthetic_h5, model_cfg):
    fpath, fname = synthetic_h5
    dataset = TIDMADDataset(fpath, [fname], model_cfg.segmentation_size, sample_size=20)
    return DataLoader(dataset, batch_size=1, shuffle=False, drop_last=True)


def run_one(model_type, loss_type, synthetic_h5, tmp_path):
    """Run one training experiment and return (results, model_path)."""
    exp_id = f"test_{model_type}_{loss_type}"
    model_dir = tmp_path / "cached_models"
    model_dir.mkdir(exist_ok=True)
    sandbox_dirs = {"models": str(model_dir)}

    model_cfg = make_model_cfg(model_type)
    train_cfg = make_train_cfg()
    loss_cfg = LossConfig(loss_type=loss_type)
    loader = make_loader(synthetic_h5, model_cfg)

    results = run_experiment(model_cfg, train_cfg, loss_cfg, loader, sandbox_dirs, exp_id)
    model_path = os.path.join(str(model_dir), f"model_{model_type}_{exp_id}_agent.pth")
    return results, model_path


# ==========================================
# punet — classification losses only
# ==========================================

class TestPUNetTraining:

    @pytest.mark.parametrize("loss_type", ["ce", "focal", "focal_cw"])
    def test_punet_trains_and_saves_model(self, loss_type, synthetic_h5, tmp_path):
        results, model_path = run_one("punet", loss_type, synthetic_h5, tmp_path)

        assert "final_loss" in results
        assert "loss_history" in results
        assert len(results["loss_history"]) == 1   # 1 epoch
        assert isinstance(results["final_loss"], float)
        assert os.path.exists(model_path), f"Model not saved at {model_path}"

    @pytest.mark.parametrize("loss_type", ["ce", "focal", "focal_cw"])
    def test_punet_model_is_loadable(self, loss_type, synthetic_h5, tmp_path):
        _, model_path = run_one("punet", loss_type, synthetic_h5, tmp_path)
        state = torch.load(model_path, map_location="cpu")
        assert isinstance(state, dict)
        assert len(state) > 0


# ==========================================
# fcnet — classification and regression losses
# ==========================================

class TestFCNetTraining:

    @pytest.mark.parametrize("loss_type", ["ce", "focal", "focal_cw", "smooth_l1"])
    def test_fcnet_trains_and_saves_model(self, loss_type, synthetic_h5, tmp_path):
        results, model_path = run_one("fcnet", loss_type, synthetic_h5, tmp_path)

        assert "final_loss" in results
        assert "loss_history" in results
        assert len(results["loss_history"]) == 1
        assert isinstance(results["final_loss"], float)
        assert os.path.exists(model_path), f"Model not saved at {model_path}"

    @pytest.mark.parametrize("loss_type", ["ce", "focal", "focal_cw", "smooth_l1"])
    def test_fcnet_model_is_loadable(self, loss_type, synthetic_h5, tmp_path):
        _, model_path = run_one("fcnet", loss_type, synthetic_h5, tmp_path)
        state = torch.load(model_path, map_location="cpu")
        assert isinstance(state, dict)
        assert len(state) > 0


# ==========================================
# transformer — classification losses only
# ==========================================

class TestTransformerTraining:

    @pytest.mark.parametrize("loss_type", ["ce", "focal", "focal_cw"])
    def test_transformer_trains_and_saves_model(self, loss_type, synthetic_h5, tmp_path):
        results, model_path = run_one("transformer", loss_type, synthetic_h5, tmp_path)

        assert "final_loss" in results
        assert "loss_history" in results
        assert len(results["loss_history"]) == 1
        assert isinstance(results["final_loss"], float)
        assert os.path.exists(model_path), f"Model not saved at {model_path}"

    @pytest.mark.parametrize("loss_type", ["ce", "focal", "focal_cw"])
    def test_transformer_model_is_loadable(self, loss_type, synthetic_h5, tmp_path):
        _, model_path = run_one("transformer", loss_type, synthetic_h5, tmp_path)
        state = torch.load(model_path, map_location="cpu")
        assert isinstance(state, dict)
        assert len(state) > 0


# ==========================================
# wavenet — classification losses only
# ==========================================

class TestWaveNetTraining:

    @pytest.mark.parametrize("loss_type", ["ce", "focal", "focal_cw"])
    def test_wavenet_trains_and_saves_model(self, loss_type, synthetic_h5, tmp_path):
        results, model_path = run_one("wavenet", loss_type, synthetic_h5, tmp_path)

        assert "final_loss" in results
        assert "loss_history" in results
        assert len(results["loss_history"]) == 1
        assert isinstance(results["final_loss"], float)
        assert os.path.exists(model_path), f"Model not saved at {model_path}"

    @pytest.mark.parametrize("loss_type", ["ce", "focal", "focal_cw"])
    def test_wavenet_model_is_loadable(self, loss_type, synthetic_h5, tmp_path):
        _, model_path = run_one("wavenet", loss_type, synthetic_h5, tmp_path)
        state = torch.load(model_path, map_location="cpu")
        assert isinstance(state, dict)
        assert len(state) > 0
