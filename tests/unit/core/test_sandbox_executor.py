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
from core.sandbox_executor import TidmadSandbox, get_plugin_dir


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
# execute_inference — Phase 6.6 A.10 inference_batch wiring
# ==========================================

class TestExecuteInferenceBatch:
    """A.10: ``execute_inference`` must prefer the explicit ``inference_batch``
    kwarg over the legacy registry. The plumbing is a single CLI argument
    (``--inference_batch_size``) whose value becomes the runtime batch size
    the subprocess uses — so we assert on the exact CLI token the subprocess
    receives, not on internal state."""

    def _seed_files(self, sandbox):
        import os, json
        cfg_dir = sandbox.dirs["configs"]
        os.makedirs(cfg_dir, exist_ok=True)
        for name in [f"model_config_{EXP_ID}.json", f"loss_config_{EXP_ID}.json"]:
            with open(os.path.join(cfg_dir, name), "w") as f:
                json.dump({}, f)
        model_path = os.path.join(sandbox.dirs["models"], f"model_fcnet_{EXP_ID}_agent.pth")
        open(model_path, "w").close()

    def _cli_token_after(self, cmd, flag):
        """Extract the CLI argument value immediately following ``flag`` in
        ``cmd``. Asserting on the full cmd list would over-specify the test —
        this isolates the single token the test cares about."""
        idx = cmd.index(flag)
        return cmd[idx + 1]

    @patch("core.sandbox_executor.subprocess.run")
    def test_explicit_inference_batch_is_used(self, mock_run, sandbox):
        """When the caller passes ``inference_batch=8``, the CLI must carry
        ``--inference_batch_size 8`` — not whatever the registry says for
        ``fcnet`` (which defaults to 25)."""
        self._seed_files(sandbox)
        mock_run.return_value = _make_mock_result()
        sandbox.execute_inference(
            EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, LOSS_CFG,
            inference_batch=8,
        )
        (cmd,), _ = mock_run.call_args
        assert self._cli_token_after(cmd, "--inference_batch_size") == "8"

    @patch("core.sandbox_executor.subprocess.run")
    def test_none_falls_back_to_registry(self, mock_run, sandbox):
        """Back-compat: callers not yet wired through the tuner (A.6–A.11
        landing window) pass no batch. The executor falls through to
        ``inference_batch_for('fcnet')`` which is 25."""
        self._seed_files(sandbox)
        mock_run.return_value = _make_mock_result()
        sandbox.execute_inference(
            EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, LOSS_CFG,
            inference_batch=None,
        )
        (cmd,), _ = mock_run.call_args
        assert self._cli_token_after(cmd, "--inference_batch_size") == "25"

    @patch("core.sandbox_executor.subprocess.run")
    def test_omitted_kwarg_falls_back_to_registry(self, mock_run, sandbox):
        """Positional call without the kwarg must match the ``None`` path
        (default value is ``None``) — pins the default so a future refactor
        can't silently swap it."""
        self._seed_files(sandbox)
        mock_run.return_value = _make_mock_result()
        sandbox.execute_inference(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, LOSS_CFG)
        (cmd,), _ = mock_run.call_args
        assert self._cli_token_after(cmd, "--inference_batch_size") == "25"

    @patch("core.sandbox_executor.subprocess.run")
    def test_explicit_beats_registry_on_known_type(self, mock_run, sandbox):
        """Even when the model_type HAS a registry entry, the explicit value
        must still win — this is the whole point of A.10. Registry is no
        longer the source of truth once the tuner is wired (A.11)."""
        self._seed_files(sandbox)
        mock_run.return_value = _make_mock_result()
        # transformer's registry entry is 1; force-pass 4 instead.
        import os, json
        cfg_dir = sandbox.dirs["configs"]
        for name in [
            f"model_config_{EXP_ID}.json", f"loss_config_{EXP_ID}.json",
        ]:
            with open(os.path.join(cfg_dir, name), "w") as f:
                json.dump({}, f)
        model_path = os.path.join(
            sandbox.dirs["models"], f"model_fcnet_{EXP_ID}_agent.pth",
        )
        open(model_path, "w").close()
        sandbox.execute_inference(
            EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, LOSS_CFG,
            inference_batch=4,
        )
        (cmd,), _ = mock_run.call_args
        assert self._cli_token_after(cmd, "--inference_batch_size") == "4"


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


# ==========================================
# get_plugin_dir helper (Phase 4)
# ==========================================

class TestGetPluginDir:
    """``get_plugin_dir`` is the single source of truth for the workspace-rooted
    plugin layout. The workflow uses it to predict where the tuner's sandbox
    will look, so the two MUST agree on the path. See
    docs/run_scoped_plugins.md (Phase 4)."""

    def test_layout_matches_doc(self, tmp_path):
        """Path is exactly ``<workspace>/plugins/<run_name>/`` (absolutised)."""
        result = get_plugin_dir(str(tmp_path), "run_a")
        expected = _os.path.join(str(tmp_path), "plugins", "run_a")
        assert result == expected

    def test_returns_absolute_path(self, tmp_path, monkeypatch):
        """Workflow may pass a relative workspace; the returned path must be
        absolute so it equals the sandbox's ``self.plugin_dir`` (which is
        always absolute via ``os.path.abspath(workspace)``)."""
        monkeypatch.chdir(tmp_path)
        result = get_plugin_dir("./relative_ws", "run_a")
        assert _os.path.isabs(result)
        assert result.endswith(_os.path.join("relative_ws", "plugins", "run_a"))

    def test_matches_sandbox_plugin_dir(self, tmp_path):
        """Regression guard for the Phase 4 contract: the helper and the
        sandbox MUST resolve to the same string. If they ever drift, the
        workflow's ``_register_plugin`` writes one place and the training
        subprocess scans another — silent breakage."""
        sb = TidmadSandbox(run_name="run_x", workspace=str(tmp_path))
        assert get_plugin_dir(str(tmp_path), "run_x") == sb.plugin_dir

    def test_distinct_run_names_distinct_dirs(self, tmp_path):
        a = get_plugin_dir(str(tmp_path), "run_a")
        b = get_plugin_dir(str(tmp_path), "run_b")
        assert a != b
