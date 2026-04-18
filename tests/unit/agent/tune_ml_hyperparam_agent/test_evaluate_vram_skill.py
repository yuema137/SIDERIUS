"""
Tests for agent/skills/evaluate_vram_skill/wrapper.py

Covers:
  - Error: no GPU available (CUDA not present)
  - Error: GPU present but free VRAM < 4 GB
  - Success feasible: config fits within 80% of free VRAM
  - Success infeasible: config exceeds 80% of free VRAM (OOM risk)
  - CPU device: skips VRAM check, always feasible
  - Focal loss: one_hot term correctly increases estimated memory
  - Suggestion present when infeasible
"""

import pytest
from unittest.mock import patch

from agent.skills.evaluate_vram_skill.wrapper import run_skill

# ---------------------------------------------------------------------------
# Shared fixtures / constants
# ---------------------------------------------------------------------------

_GB = 1024 ** 3
_4GB  = 4  * _GB
_8GB  = 8  * _GB
_16GB = 16 * _GB
_3GB  = 3  * _GB   # below the 4 GB floor → should error


class FakeSandbox:
    """Minimal stand-in; evaluate_vram_skill never calls sandbox methods."""
    pass


# Tiny RNN that instantiates quickly on CPU
SMALL_RNN_CFG = {
    "model_type": "rnn",
    "segmentation_size": 1000,
    "embedding_dim": 8,
    "hidden_dim": 8,
    "num_layers": 1,
}
CUDA_TRAIN_CFG = {"lr": 1e-4, "epochs": 1, "batch_size": 2, "device": "cuda"}
CPU_TRAIN_CFG  = {"lr": 1e-4, "epochs": 1, "batch_size": 2, "device": "cpu"}
CE_LOSS_CFG    = {"loss_type": "ce"}
FOCAL_LOSS_CFG = {"loss_type": "focal"}

# ---------------------------------------------------------------------------
# Error conditions
# ---------------------------------------------------------------------------

class TestErrorConditions:

    def test_no_cuda_available_returns_error(self):
        """If device='cuda' but torch says CUDA is unavailable → error."""
        with patch("torch.cuda.is_available", return_value=False):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
            )
        assert result["status"] == "error"
        assert "no GPU" in result["message"].lower() or "cuda" in result["message"].lower()

    def test_free_vram_below_4gb_returns_error(self):
        """If free VRAM < 4 GB → error regardless of config size."""
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_3GB, _16GB)):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
            )
        assert result["status"] == "error"
        assert "4 GB" in result["message"]

    def test_free_vram_exactly_4gb_does_not_error(self):
        """Free VRAM == 4 GB is the floor; should proceed to feasibility check."""
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_4GB, _16GB)):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
            )
        assert result["status"] == "success"   # not an error

# ---------------------------------------------------------------------------
# Feasibility verdicts
# ---------------------------------------------------------------------------

class TestFeasibilityVerdicts:

    def test_small_config_is_feasible(self):
        """A tiny RNN config should comfortably fit in 16 GB."""
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_16GB, _16GB)):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
            )
        assert result["status"] == "success"
        assert result["feasible"] is True

    def test_large_config_is_infeasible(self):
        """A large batch+seg RNN with focal loss should exceed 80% of 4 GB."""
        big_rnn_cfg = {
            "model_type": "rnn",
            "segmentation_size": 50000,
            "embedding_dim": 64,
            "hidden_dim": 64,
            "num_layers": 2,
        }
        big_train = {"lr": 1e-4, "epochs": 1, "batch_size": 512, "device": "cuda"}
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_4GB, _16GB)):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=big_rnn_cfg,
                train_config=big_train,
                loss_config=FOCAL_LOSS_CFG,
            )
        assert result["status"] == "success"
        assert result["feasible"] is False

    def test_infeasible_result_has_suggestion(self):
        """An infeasible config must return a non-empty suggestion string."""
        big_rnn_cfg = {
            "model_type": "rnn",
            "segmentation_size": 50000,
            "embedding_dim": 64,
            "hidden_dim": 64,
            "num_layers": 2,
        }
        big_train = {"lr": 1e-4, "epochs": 1, "batch_size": 512, "device": "cuda"}
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_4GB, _16GB)):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=big_rnn_cfg,
                train_config=big_train,
                loss_config=FOCAL_LOSS_CFG,
            )
        assert result.get("suggestion", "") != ""

# ---------------------------------------------------------------------------
# CPU device
# ---------------------------------------------------------------------------

class TestCpuDevice:

    def test_cpu_device_always_feasible(self):
        """device='cpu' skips VRAM check entirely — always success + feasible."""
        # No torch.cuda mock needed: the skill short-circuits before touching cuda
        result = run_skill(
            FakeSandbox(),
            model_type="rnn",
            model_config=SMALL_RNN_CFG,
            train_config=CPU_TRAIN_CFG,
            loss_config=CE_LOSS_CFG,
        )
        assert result["status"] == "success"
        assert result["feasible"] is True

    def test_cpu_device_no_vram_fields(self):
        """CPU result must NOT include vram_free_gb (no GPU queried)."""
        result = run_skill(
            FakeSandbox(),
            model_type="rnn",
            model_config=SMALL_RNN_CFG,
            train_config=CPU_TRAIN_CFG,
            loss_config=CE_LOSS_CFG,
        )
        assert "vram_free_gb" not in result

# ---------------------------------------------------------------------------
# Memory breakdown correctness
# ---------------------------------------------------------------------------

class TestMemoryBreakdown:

    def test_focal_loss_increases_estimate(self):
        """Focal loss (one_hot int64) should produce a higher estimate than CE."""
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_16GB, _16GB)):
            result_ce = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
            )
            result_focal = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=FOCAL_LOSS_CFG,
            )
        assert result_focal["estimated_gb"] > result_ce["estimated_gb"]

    def test_result_contains_num_params(self):
        """Result must include the exact parameter count from model instantiation."""
        with patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.mem_get_info", return_value=(_16GB, _16GB)):
            result = run_skill(
                FakeSandbox(),
                model_type="rnn",
                model_config=SMALL_RNN_CFG,
                train_config=CUDA_TRAIN_CFG,
                loss_config=CE_LOSS_CFG,
            )
        assert "num_params" in result
        assert result["num_params"] > 0
