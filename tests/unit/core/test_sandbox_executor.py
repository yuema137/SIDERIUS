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


# ==========================================
# _subprocess_env — SIDERIUS_PLUGIN_DIRS wiring (Phase 2)
# ==========================================

import os as _os

from core.sandbox_executor import _subprocess_env


class TestSubprocessEnv:
    """Phase 2 of docs/run_scoped_plugins.md — _subprocess_env opts into the
    run-scoped plugin-dir scan by setting SIDERIUS_PLUGIN_DIRS when a
    plugin_dir is supplied, and leaves it unset otherwise (back-compat for
    any caller outside the tuner sandbox flow)."""

    def test_no_plugin_dir_leaves_env_var_unset(self):
        env = _subprocess_env()
        assert "SIDERIUS_PLUGIN_DIRS" not in env

    def test_plugin_dir_populates_env_var(self, tmp_path):
        env = _subprocess_env(plugin_dir=str(tmp_path))
        assert env["SIDERIUS_PLUGIN_DIRS"] == str(tmp_path)

    def test_plugin_dir_does_not_clobber_pythonpath(self, tmp_path):
        """Regression guard: the plugin_dir wiring must not interfere with
        the PYTHONPATH construction that lets flat imports resolve in the
        training subprocess."""
        env = _subprocess_env(plugin_dir=str(tmp_path))
        assert "PYTHONPATH" in env
        project_root = _os.path.dirname(_os.path.dirname(
            _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        ))
        assert project_root in env["PYTHONPATH"]
        assert _os.path.join(project_root, "ml_models") in env["PYTHONPATH"]
        assert _os.path.join(project_root, "execute_tools") in env["PYTHONPATH"]


# ==========================================
# TidmadSandbox — run-scoped plugin_dir (Phase 2)
# ==========================================

class TestSandboxPluginDir:
    """The sandbox owns per-run plugin isolation. It creates
    ``<workspace>/plugins/<run_name>/`` at construction and threads that
    path through every subprocess it spawns via SIDERIUS_PLUGIN_DIRS."""

    def test_plugin_dir_created_under_workspace(self, tmp_path):
        sb = TidmadSandbox(run_name="run_a", workspace=str(tmp_path))
        expected = _os.path.join(str(tmp_path), "plugins", "run_a")
        assert sb.plugin_dir == expected
        assert _os.path.isdir(sb.plugin_dir)

    def test_two_sandboxes_get_distinct_plugin_dirs(self, tmp_path):
        sb1 = TidmadSandbox(run_name="run_a", workspace=str(tmp_path))
        sb2 = TidmadSandbox(run_name="run_b", workspace=str(tmp_path))
        assert sb1.plugin_dir != sb2.plugin_dir

    @patch("core.sandbox_executor.subprocess.run")
    def test_training_subprocess_receives_plugin_dir_in_env(self, mock_run, sandbox):
        """End-to-end wiring check: execute_training must pass the sandbox's
        plugin_dir to the training subprocess via SIDERIUS_PLUGIN_DIRS. If
        this regresses, the subprocess falls back to scanning the legacy
        global dir — the exact pollution Phase 2 is designed to eliminate."""
        mock_run.return_value = _make_mock_result()
        sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        _, kwargs = mock_run.call_args
        assert "env" in kwargs
        assert kwargs["env"]["SIDERIUS_PLUGIN_DIRS"] == sandbox.plugin_dir
