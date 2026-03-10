"""
Tests for core/sandbox_executor.py

Verifies that the progress_bar flag correctly controls stdout routing
in execute_training, execute_inference, and execute_scoring.

Uses unittest.mock to intercept subprocess.run — no GPU, no real data needed.
"""
import json
import subprocess
import pytest
from unittest.mock import patch, MagicMock, mock_open
from core.sandbox_executor import TidmadSandbox


# ==========================================
# Fixtures
# ==========================================

@pytest.fixture
def sandbox(tmp_path):
    return TidmadSandbox(
        run_name="test_run",
        workspace=str(tmp_path),
        progress_bar=False,
    )

@pytest.fixture
def sandbox_progress(tmp_path):
    return TidmadSandbox(
        run_name="test_run",
        workspace=str(tmp_path),
        progress_bar=True,
    )

# Minimal valid configs that pass Pydantic validation
MODEL_CFG  = {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [100, 10]}
TRAIN_CFG  = {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"}
LOSS_CFG   = {"loss_type": "ce"}
EXP_ID     = "test_exp_001"
RUN_NAME   = "test_run"


def _make_mock_result(returncode=0, stdout="done\n", stderr=""):
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = stdout
    mock.stderr = stderr
    return mock


# ==========================================
# TidmadSandbox initialisation
# ==========================================

class TestProgressBarFlag:

    def test_default_is_false(self, tmp_path):
        sb = TidmadSandbox(run_name="r", workspace=str(tmp_path))
        assert sb.progress_bar is False

    def test_set_true(self, sandbox_progress):
        assert sandbox_progress.progress_bar is True

    def test_set_false(self, sandbox):
        assert sandbox.progress_bar is False


# ==========================================
# execute_training
# ==========================================

class TestExecuteTrainingStdout:

    @patch("core.sandbox_executor.subprocess.run")
    def test_progress_bar_false_captures_stdout(self, mock_run, sandbox):
        mock_run.return_value = _make_mock_result()
        sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        _, kwargs = mock_run.call_args
        assert kwargs["stdout"] == subprocess.PIPE

    @patch("core.sandbox_executor.subprocess.run")
    def test_progress_bar_true_streams_stdout(self, mock_run, sandbox_progress):
        mock_run.return_value = _make_mock_result()
        sandbox_progress.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        _, kwargs = mock_run.call_args
        assert kwargs["stdout"] is None

    @patch("core.sandbox_executor.subprocess.run")
    def test_stderr_always_captured(self, mock_run, sandbox):
        mock_run.return_value = _make_mock_result()
        sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        _, kwargs = mock_run.call_args
        assert kwargs["stderr"] == subprocess.PIPE

    @patch("core.sandbox_executor.subprocess.run")
    def test_stderr_always_captured_with_progress(self, mock_run, sandbox_progress):
        mock_run.return_value = _make_mock_result()
        sandbox_progress.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        _, kwargs = mock_run.call_args
        assert kwargs["stderr"] == subprocess.PIPE


# ==========================================
# execute_inference
# ==========================================

class TestExecuteInferenceStdout:

    def _run(self, sandbox, mock_run):
        # Pre-write config files so the method doesn't fail on missing paths
        import os, json
        cfg_dir = sandbox.dirs["configs"]
        os.makedirs(cfg_dir, exist_ok=True)
        for name in [f"model_config_{EXP_ID}.json", f"loss_config_{EXP_ID}.json"]:
            with open(os.path.join(cfg_dir, name), "w") as f:
                json.dump({}, f)
        # Also create a dummy model file
        model_path = os.path.join(sandbox.dirs["models"], f"model_fcnet_{EXP_ID}_agent.pth")
        open(model_path, "w").close()
        mock_run.return_value = _make_mock_result()
        return sandbox.execute_inference(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, LOSS_CFG)

    @patch("core.sandbox_executor.subprocess.run")
    def test_progress_bar_false_captures_stdout(self, mock_run, sandbox):
        self._run(sandbox, mock_run)
        _, kwargs = mock_run.call_args
        assert kwargs["stdout"] == subprocess.PIPE

    @patch("core.sandbox_executor.subprocess.run")
    def test_progress_bar_true_streams_stdout(self, mock_run, sandbox_progress):
        self._run(sandbox_progress, mock_run)
        _, kwargs = mock_run.call_args
        assert kwargs["stdout"] is None

    @patch("core.sandbox_executor.subprocess.run")
    def test_stderr_always_captured(self, mock_run, sandbox):
        self._run(sandbox, mock_run)
        _, kwargs = mock_run.call_args
        assert kwargs["stderr"] == subprocess.PIPE


# ==========================================
# execute_scoring
# ==========================================

class TestExecuteScoringStdout:

    def _run(self, sandbox, mock_run):
        mock_run.return_value = _make_mock_result()
        # Patch open so score_results JSON reads back as valid dict
        score_data = json.dumps({"denoising_score": 0.9})
        with patch("builtins.open", mock_open(read_data=score_data)):
            with patch("os.path.exists", return_value=True):
                with patch("os.remove"):
                    return sandbox.execute_scoring(
                        EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG
                    )

    @patch("core.sandbox_executor.subprocess.run")
    def test_progress_bar_false_captures_stdout(self, mock_run, sandbox):
        self._run(sandbox, mock_run)
        _, kwargs = mock_run.call_args
        assert kwargs["stdout"] == subprocess.PIPE

    @patch("core.sandbox_executor.subprocess.run")
    def test_progress_bar_true_streams_stdout(self, mock_run, sandbox_progress):
        self._run(sandbox_progress, mock_run)
        _, kwargs = mock_run.call_args
        assert kwargs["stdout"] is None

    @patch("core.sandbox_executor.subprocess.run")
    def test_stderr_always_captured(self, mock_run, sandbox):
        self._run(sandbox, mock_run)
        _, kwargs = mock_run.call_args
        assert kwargs["stderr"] == subprocess.PIPE
