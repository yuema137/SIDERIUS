"""
Tests for core/sandbox_executor.py

Verifies that the progress_bar flag correctly controls stdout routing
in execute_training, execute_inference, and execute_scoring.

Uses unittest.mock to intercept subprocess.run — no GPU, no real data needed.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from core.sandbox_executor import TidmadSandbox, get_plugin_dir
from execute_tools.data_paths import bind_physical_data_root
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

QUICKSTART = Path(__file__).resolve().parents[3] / "configs/task_composition/quickstart.yaml"

# ==========================================
# Fixtures
# ==========================================


@pytest.fixture(autouse=True)
def _bind_data_root(tmp_path):
    with bind_physical_data_root(str(tmp_path)):
        yield


@pytest.fixture
def sandbox(tmp_path):
    composition = compose_run_task_bindings(str(QUICKSTART))
    with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
        yield TidmadSandbox(
            run_name="test_run",
            workspace=str(tmp_path),
            progress_bar=False,
        )


@pytest.fixture
def sandbox_progress(tmp_path):
    composition = compose_run_task_bindings(str(QUICKSTART))
    with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
        yield TidmadSandbox(
            run_name="test_run",
            workspace=str(tmp_path),
            progress_bar=True,
        )


# Minimal valid configs that pass Pydantic validation
MODEL_CFG = {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [100, 10]}
TRAIN_CFG = {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"}
LOSS_CFG = {"loss_type": "ce"}
EXP_ID = "test_exp_001"
RUN_NAME = "test_run"


def _make_mock_result(returncode=0, stdout="done\n", stderr=""):
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = stdout
    mock.stderr = stderr
    return mock


def _make_train_success_side_effect(sandbox, exp_id, stdout="done\n", stderr=""):
    """Build a ``subprocess.run`` side_effect that mirrors a successful
    trainer: writes the ``_OK_<exp_id>`` sentinel to ``sandbox.dirs['models']``
    before returning success. Required for any ``execute_training`` test
    after Phase 6.7 Commit 4 — without the sentinel, the executor's
    silent-crash check rejects the run as ``error_training``."""

    def _side_effect(*args, **kwargs):
        os.makedirs(sandbox.dirs["models"], exist_ok=True)
        sentinel = os.path.join(sandbox.dirs["models"], f"_OK_{exp_id}")
        with open(sentinel, "wb"):
            pass
        return _make_mock_result(returncode=0, stdout=stdout, stderr=stderr), None

    return _side_effect


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
    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_progress_bar_false_captures_stdout(self, mock_run, sandbox):
        mock_run.side_effect = _make_train_success_side_effect(sandbox, EXP_ID)
        sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        _, kwargs = mock_run.call_args
        assert kwargs["capture_stdout"] is True

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_progress_bar_true_streams_stdout(self, mock_run, sandbox_progress):
        mock_run.side_effect = _make_train_success_side_effect(sandbox_progress, EXP_ID)
        sandbox_progress.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        _, kwargs = mock_run.call_args
        assert kwargs["capture_stdout"] is False

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_training_stderr_reaches_the_caller(self, mock_run, sandbox):
        """B-C2a2: `stderr=PIPE` moved below the seam, so asserting the
        kwarg here would assert nothing. What the test existed to protect
        is that a failed child's stderr reaches the caller — asserted
        behaviourally, which survives any future launch change."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ["x"], output="", stderr="DIAGNOSTIC-STDERR"
        )
        result = sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        assert "DIAGNOSTIC-STDERR" in result["message"]

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_training_stderr_reaches_the_caller_with_progress(self, mock_run, sandbox_progress):
        """Same, with the progress bar on — the branch that leaves stdout
        uncaptured must still capture stderr."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ["x"], output="", stderr="DIAGNOSTIC-STDERR"
        )
        result = sandbox_progress.execute_training(
            EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG
        )
        assert "DIAGNOSTIC-STDERR" in result["message"]


# ==========================================
# execute_inference
# ==========================================


class TestExecuteInferenceStdout:
    def _run(self, sandbox, mock_run):
        # Pre-write config files so the method doesn't fail on missing paths
        import json
        import os

        cfg_dir = sandbox.dirs["configs"]
        os.makedirs(cfg_dir, exist_ok=True)
        for name in [f"model_config_{EXP_ID}.json", f"loss_config_{EXP_ID}.json"]:
            with open(os.path.join(cfg_dir, name), "w") as f:
                json.dump({}, f)
        # Also create a dummy model file
        model_path = os.path.join(sandbox.dirs["models"], f"model_fcnet_{EXP_ID}_agent.pth")
        open(model_path, "w").close()
        mock_run.return_value = (_make_mock_result(), None)
        return sandbox.execute_inference(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, LOSS_CFG)

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_progress_bar_false_captures_stdout(self, mock_run, sandbox):
        self._run(sandbox, mock_run)
        _, kwargs = mock_run.call_args
        assert kwargs["capture_stdout"] is True

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_progress_bar_true_streams_stdout(self, mock_run, sandbox_progress):
        self._run(sandbox_progress, mock_run)
        _, kwargs = mock_run.call_args
        assert kwargs["capture_stdout"] is False

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_inference_stderr_reaches_the_caller(self, mock_run, sandbox):
        """See the training equivalent: behaviour, not the kwarg."""
        model_path = os.path.join(sandbox.dirs["models"], f"model_fcnet_{EXP_ID}_agent.pth")
        open(model_path, "w").close()
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ["x"], output="", stderr="DIAGNOSTIC-STDERR"
        )
        result = sandbox.execute_inference(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, LOSS_CFG)
        assert "DIAGNOSTIC-STDERR" in result["message"]


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
        import json
        import os

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

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_explicit_inference_batch_is_used(self, mock_run, sandbox):
        """When the caller passes ``inference_batch=8``, the CLI must carry
        ``--inference_batch_size 8`` — not whatever the registry says for
        ``fcnet`` (which defaults to 25)."""
        self._seed_files(sandbox)
        mock_run.return_value = (_make_mock_result(), None)
        sandbox.execute_inference(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            LOSS_CFG,
            inference_batch=8,
        )
        (cmd,), _ = mock_run.call_args
        assert self._cli_token_after(cmd, "--inference_batch_size") == "8"

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_none_falls_back_to_registry(self, mock_run, sandbox):
        """Back-compat: callers not yet wired through the tuner (A.6-A.11
        landing window) pass no batch. The executor falls through to
        ``inference_batch_for('fcnet')`` which is 25."""
        self._seed_files(sandbox)
        mock_run.return_value = (_make_mock_result(), None)
        sandbox.execute_inference(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            LOSS_CFG,
            inference_batch=None,
        )
        (cmd,), _ = mock_run.call_args
        assert self._cli_token_after(cmd, "--inference_batch_size") == "25"

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_omitted_kwarg_falls_back_to_registry(self, mock_run, sandbox):
        """Positional call without the kwarg must match the ``None`` path
        (default value is ``None``) — pins the default so a future refactor
        can't silently swap it."""
        self._seed_files(sandbox)
        mock_run.return_value = (_make_mock_result(), None)
        sandbox.execute_inference(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, LOSS_CFG)
        (cmd,), _ = mock_run.call_args
        assert self._cli_token_after(cmd, "--inference_batch_size") == "25"

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_explicit_beats_registry_on_known_type(self, mock_run, sandbox):
        """Even when the model_type HAS a registry entry, the explicit value
        must still win — this is the whole point of A.10. Registry is no
        longer the source of truth once the tuner is wired (A.11)."""
        self._seed_files(sandbox)
        mock_run.return_value = (_make_mock_result(), None)
        # transformer's registry entry is 1; force-pass 4 instead.
        import json
        import os

        cfg_dir = sandbox.dirs["configs"]
        for name in [
            f"model_config_{EXP_ID}.json",
            f"loss_config_{EXP_ID}.json",
        ]:
            with open(os.path.join(cfg_dir, name), "w") as f:
                json.dump({}, f)
        model_path = os.path.join(
            sandbox.dirs["models"],
            f"model_fcnet_{EXP_ID}_agent.pth",
        )
        open(model_path, "w").close()
        sandbox.execute_inference(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            LOSS_CFG,
            inference_batch=4,
        )
        (cmd,), _ = mock_run.call_args
        assert self._cli_token_after(cmd, "--inference_batch_size") == "4"


# ==========================================
# execute_inference — Commit B: trial-mode timing sidecar
# ==========================================


class TestExecuteInferenceTimingSidecar:
    """Commit B contract: in trial mode, the parent appends ``--timing_out_json``
    to the subprocess cmd, then reads the sidecar back and returns a dict
    enriched with ``per_file_timings_ms``, ``subprocess_wall_ms``, and
    ``process_startup_ms = max(0, wall - sum)``. Outside trial mode (no
    ``sample_set``), the flag is omitted so baseline runs are unaffected."""

    def _seed_files(self, sandbox):
        cfg_dir = sandbox.dirs["configs"]
        os.makedirs(cfg_dir, exist_ok=True)
        for name in [f"model_config_{EXP_ID}.json", f"loss_config_{EXP_ID}.json"]:
            with open(os.path.join(cfg_dir, name), "w") as f:
                json.dump({}, f)
        model_path = os.path.join(sandbox.dirs["models"], f"model_fcnet_{EXP_ID}_agent.pth")
        open(model_path, "w").close()

    def _expected_timing_path(self, sandbox):
        return os.path.abspath(
            os.path.join(sandbox.dirs["configs"], f"inference_timing_{EXP_ID}.json")
        )

    def _make_subprocess_writes_sidecar(self, sandbox, payload):
        """Build a side_effect that writes ``payload`` to the timing sidecar
        path before returning success — mirrors what the real subprocess does."""
        timing_path = self._expected_timing_path(sandbox)

        def _side_effect(*args, **kwargs):
            with open(timing_path, "w") as f:
                json.dump(payload, f)
            return _make_mock_result(), None

        return _side_effect

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_trial_mode_appends_timing_flag(self, mock_run, sandbox):
        """When ``sample_set`` is provided, ``--timing_out_json {path}`` must
        appear in the cmd so the subprocess knows where to write the
        sidecar."""
        self._seed_files(sandbox)
        sample_set = {"0": [0, 1], "1": [0]}
        mock_run.return_value = (_make_mock_result(), None)
        sandbox.execute_inference(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            LOSS_CFG,
            sample_set=sample_set,
        )
        (cmd,), _ = mock_run.call_args
        assert "--timing_out_json" in cmd, f"--timing_out_json missing from cmd: {cmd}"
        idx = cmd.index("--timing_out_json")
        assert cmd[idx + 1] == self._expected_timing_path(sandbox)

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_normal_mode_omits_timing_flag(self, mock_run, sandbox):
        """Baseline / single-file mode (no sample_set) must not include the
        flag — the subprocess ignores it there anyway, but keeping the cmd
        clean prevents accidental sidecar writes from polluting the configs
        dir during baseline runs."""
        self._seed_files(sandbox)
        mock_run.return_value = (_make_mock_result(), None)
        sandbox.execute_inference(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, LOSS_CFG)
        (cmd,), _ = mock_run.call_args
        assert "--timing_out_json" not in cmd

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_success_returns_per_file_timings_and_decomposed_wall(self, mock_run, sandbox):
        """On successful trial-mode inference, the return dict must carry
        the parsed sidecar plus the parent-measured wall time, with
        ``process_startup_ms`` = wall − sum(per-file). This is the
        decomposition Commit C's aggregator + Commit D's gate consume."""
        self._seed_files(sandbox)
        sample_set = {"0": [0, 1, 2], "1": [0]}
        # Two files with known elapsed_ms; the parent sums these and
        # subtracts from its own wall measurement.
        payload = [
            {"file_index": 0, "n_psd_segs": 3, "elapsed_ms": 100.0},
            {"file_index": 1, "n_psd_segs": 1, "elapsed_ms": 50.0},
        ]
        mock_run.side_effect = self._make_subprocess_writes_sidecar(sandbox, payload)
        result = sandbox.execute_inference(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            LOSS_CFG,
            sample_set=sample_set,
        )
        assert result["status"] == "success"
        assert result["per_file_timings_ms"] == payload
        assert isinstance(result["subprocess_wall_ms"], float)
        assert result["subprocess_wall_ms"] >= 0.0
        assert result["process_startup_ms"] is not None
        # Parent wall always >= sum of per-file (by definition of
        # subprocess wall time) — but the mock makes the work
        # instantaneous, so wall ≪ 150ms and the max(0, ...) clamp kicks
        # in. Pin only that the clamp prevented a negative value.
        assert result["process_startup_ms"] >= 0.0

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_success_with_missing_sidecar_returns_empty_timings(self, mock_run, sandbox):
        """If the subprocess succeeded but no sidecar was written (e.g. the
        subprocess crashed silently between the loop and the write — or the
        feature flag was unset by an external invoker), the parent must not
        crash. Empty list + None startup is the documented fallback shape;
        the aggregator (Commit C) returns None in this case which routes
        the gate to the constant-ratio fallback."""
        self._seed_files(sandbox)
        sample_set = {"0": [0]}
        # Standard mock — does NOT write the sidecar.
        mock_run.return_value = (_make_mock_result(), None)
        result = sandbox.execute_inference(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            LOSS_CFG,
            sample_set=sample_set,
        )
        assert result["status"] == "success"
        assert result["per_file_timings_ms"] == []
        assert result["process_startup_ms"] is None
        assert isinstance(result["subprocess_wall_ms"], float)

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_failure_path_returns_uniform_keys(self, mock_run, sandbox):
        """``CalledProcessError`` must still return the new keys (with
        empty/None values) so callers can read the dict uniformly without
        a ``KeyError`` when the trial OOMs."""
        self._seed_files(sandbox)
        sample_set = {"0": [0]}
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["dummy"],
            stderr="boom",
        )
        result = sandbox.execute_inference(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            LOSS_CFG,
            sample_set=sample_set,
        )
        assert result["status"] in {"error", "oom_host_ram"}
        assert result["per_file_timings_ms"] == []
        assert result["process_startup_ms"] is None
        assert result["subprocess_wall_ms"] is None


# ==========================================
# execute_scoring
# ==========================================


class TestExecuteScoringStdout:
    def _run(self, sandbox, mock_run):
        mock_run.return_value = (_make_mock_result(), None)
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
        """Scoring is CPU-only and keeps its direct `subprocess.run`, so
        this kwarg assertion remains meaningful here (B-C2a2 class F)."""
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

    def test_plugin_dir_does_not_restore_ambient_pythonpath(self, monkeypatch, tmp_path):
        """Generated plugins use their own channel, never framework PYTHONPATH."""
        monkeypatch.setenv("PYTHONPATH", "/foreign/source")
        env = _subprocess_env(plugin_dir=str(tmp_path))
        assert "PYTHONPATH" not in env
        assert env["SIDERIUS_PLUGIN_DIRS"] == str(tmp_path)

    def test_neutral_child_imports_framework_from_the_exact_environment(self, tmp_path):
        """A child outside the checkout must not need a source-path injection."""
        env = _subprocess_env()
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import core.sandbox_executor as module; print(module.__file__)",
            ],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        source = Path(completed.stdout.strip()).resolve()
        assert source.is_relative_to(Path(__file__).resolve().parents[3])


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

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_training_subprocess_receives_plugin_dir_in_env(self, mock_run, sandbox):
        """End-to-end wiring check: execute_training must pass the sandbox's
        plugin_dir to the training subprocess via SIDERIUS_PLUGIN_DIRS. If
        this regresses, the subprocess falls back to scanning the legacy
        global dir — the exact pollution Phase 2 is designed to eliminate."""
        mock_run.side_effect = _make_train_success_side_effect(sandbox, EXP_ID)
        sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        _, kwargs = mock_run.call_args
        assert "env" in kwargs
        assert kwargs["env"]["SIDERIUS_PLUGIN_DIRS"].split(os.pathsep)[0] == sandbox.plugin_dir


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


# ==========================================
# execute_training — Phase 6.7 Commit 4 silent-crash detection
# ==========================================


class TestExecuteTrainingSilentCrash:
    """Fix 3, producer side. The trainer-side helper writes ``_OK_<exp_id>``
    only after ``torch.save`` returned successfully. If the subprocess exits
    0 but the sentinel is missing, training crashed somewhere between save
    and process exit (post-save segfault, kernel OOM-kill, GPU watchdog).
    The executor must surface this as ``error_training`` — without the
    check, the consumer-side preflight in ``inference_single`` would raise
    on the missing .pth and the failure would be misclassified as
    ``error_inference``.

    The ``error_training:`` prefix in the message is the contract the
    tuner pattern-matches against in ``ml_hyperparameter_tune_agent`` to
    re-route the inference-side error category. Pinning the prefix here
    keeps producer and consumer in lock-step.
    """

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_returncode_zero_no_sentinel_returns_error_training(
        self,
        mock_run,
        sandbox,
    ):
        """The smoking-gun case from the v3/v4 forensic logs: the subprocess
        exits cleanly but no sentinel was written. Status is ``error`` with
        an ``error_training:``-prefixed message — not the misleading
        ``error_inference`` it used to surface as."""
        mock_run.return_value = (
            _make_mock_result(
                returncode=0,
                stdout="Trainer started\nTrainer finished\n",
                stderr="W0426 12:00:01 cuda_memory_allocator.cc:213] reclaim spike\n",
            ),
            None,
        )

        out = sandbox.execute_training(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            TRAIN_CFG,
            LOSS_CFG,
        )

        assert out["status"] == "error"
        assert out["message"].startswith("error_training:"), (
            f"missing required prefix; got: {out['message'][:120]!r}"
        )
        assert EXP_ID in out["message"]

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_silent_crash_message_includes_stderr_tail(
        self,
        mock_run,
        sandbox,
    ):
        """The 20-line stderr tail is what the operator (and the tuner's
        reflector) reads to triage the crash. Pin that it actually makes
        it into the surfaced message."""
        # 25 stderr lines — only the LAST 20 should appear in the tail.
        stderr_lines = [f"line {i}: noisy warning" for i in range(25)]
        mock_run.return_value = (
            _make_mock_result(
                returncode=0,
                stdout="",
                stderr="\n".join(stderr_lines) + "\n",
            ),
            None,
        )

        out = sandbox.execute_training(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            TRAIN_CFG,
            LOSS_CFG,
        )

        assert "--- stderr tail (last 20 lines) ---" in out["message"]
        # The last line must be present.
        assert "line 24: noisy warning" in out["message"]
        # The 6th-to-last (line 19) must be present (line 19 is included).
        assert "line 19: noisy warning" in out["message"]
        # The 6th line (line 5) must NOT be present — only the last 20
        # (lines 5..24 inclusive would be 20 lines, so line 4 is the
        # first that should be cut).
        assert "line 4: noisy warning" not in out["message"]

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_silent_crash_does_not_read_train_results_json(
        self,
        mock_run,
        sandbox,
    ):
        """When the sentinel is missing, the executor must short-circuit
        BEFORE attempting to read ``experiment_results_*.json`` — that
        file is also not guaranteed to exist after a silent crash, and
        opening it would mask the real cause behind a ``FileNotFoundError``
        / ``JSONDecodeError`` raised inside the executor itself."""
        mock_run.return_value = (
            _make_mock_result(
                returncode=0,
                stdout="",
                stderr="",
            ),
            None,
        )

        # Confirm no result JSON exists at the expected path — proves the
        # short-circuit isn't accidentally papered over by a prior file.
        train_json = os.path.join(
            sandbox.dirs["records"],
            RUN_NAME,
            f"experiment_results_fcnet_{EXP_ID}.json",
        )
        assert not os.path.exists(train_json)

        out = sandbox.execute_training(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            TRAIN_CFG,
            LOSS_CFG,
        )

        # No ``results`` key — that's only on the success path.
        assert out["status"] == "error"
        assert "results" not in out

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_sentinel_present_keeps_success_status(self, mock_run, sandbox):
        """Mirror image of the silent-crash branch: when the sentinel IS
        present, the executor proceeds to the success path. This is the
        regression guard that makes sure the silent-crash check doesn't
        false-positive on healthy runs."""
        mock_run.side_effect = _make_train_success_side_effect(sandbox, EXP_ID)
        out = sandbox.execute_training(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            TRAIN_CFG,
            LOSS_CFG,
        )
        assert out["status"] == "success"
        assert "error_training:" not in out.get("message", "")


# ==========================================
# L1b — SIDERIUS_LOSS_DIRS wiring
# ==========================================
#
# Mirrors the SIDERIUS_PLUGIN_DIRS test block above for the loss-plugin
# surface added by enable_loss_inventory L1b. See
# ``docs/design/enable_loss_inventory.md`` § Commit L1.

from core.sandbox_executor import get_loss_dir


class TestSubprocessEnvLossDir:
    """``_subprocess_env(loss_dir=...)`` extends the same env-builder that
    handles plugin_dir. The two env vars are independent — supplying one
    must not affect the other, and supplying both must populate both."""

    def test_no_loss_dir_leaves_env_var_unset(self):
        env = _subprocess_env()
        assert "SIDERIUS_LOSS_DIRS" not in env

    def test_loss_dir_populates_env_var(self, tmp_path):
        env = _subprocess_env(loss_dir=str(tmp_path))
        assert env["SIDERIUS_LOSS_DIRS"] == str(tmp_path)

    def test_loss_dir_does_not_set_plugin_dir(self, tmp_path):
        """Independence guard: supplying only ``loss_dir`` must leave
        SIDERIUS_PLUGIN_DIRS unset. If this regresses, the two env vars
        are coupled and the L1b separation-of-concerns is violated."""
        env = _subprocess_env(loss_dir=str(tmp_path))
        assert "SIDERIUS_PLUGIN_DIRS" not in env

    def test_plugin_dir_does_not_set_loss_dir(self, tmp_path):
        """Mirror of the above — supplying only ``plugin_dir`` must leave
        SIDERIUS_LOSS_DIRS unset."""
        env = _subprocess_env(plugin_dir=str(tmp_path))
        assert "SIDERIUS_LOSS_DIRS" not in env

    def test_both_dirs_populate_both_env_vars(self, tmp_path):
        plugin = tmp_path / "plugins"
        loss = tmp_path / "losses"
        env = _subprocess_env(plugin_dir=str(plugin), loss_dir=str(loss))
        assert env["SIDERIUS_PLUGIN_DIRS"] == str(plugin)
        assert env["SIDERIUS_LOSS_DIRS"] == str(loss)

    def test_loss_dir_does_not_restore_ambient_pythonpath(self, monkeypatch, tmp_path):
        """Generated losses use their own channel, never framework PYTHONPATH."""
        monkeypatch.setenv("PYTHONPATH", "/foreign/source")
        env = _subprocess_env(loss_dir=str(tmp_path))
        assert "PYTHONPATH" not in env
        assert env["SIDERIUS_LOSS_DIRS"] == str(tmp_path)


class TestSandboxLossDir:
    """``TidmadSandbox`` owns per-run loss isolation analogously to
    plugin isolation: it creates ``<workspace>/losses/<run_name>/`` at
    construction and threads that path into every subprocess via
    SIDERIUS_LOSS_DIRS."""

    def test_loss_dir_created_under_workspace(self, tmp_path):
        sb = TidmadSandbox(run_name="run_a", workspace=str(tmp_path))
        expected = _os.path.join(str(tmp_path), "losses", "run_a")
        assert sb.loss_dir == expected
        assert _os.path.isdir(sb.loss_dir)

    def test_two_sandboxes_get_distinct_loss_dirs(self, tmp_path):
        sb1 = TidmadSandbox(run_name="run_a", workspace=str(tmp_path))
        sb2 = TidmadSandbox(run_name="run_b", workspace=str(tmp_path))
        assert sb1.loss_dir != sb2.loss_dir

    def test_sandbox_loss_dir_is_distinct_from_plugin_dir(self, tmp_path):
        """``plugin_dir`` and ``loss_dir`` are siblings under the workspace
        with different names; they must never collide."""
        sb = TidmadSandbox(run_name="run_a", workspace=str(tmp_path))
        assert sb.plugin_dir != sb.loss_dir
        # Both still live under the workspace.
        assert sb.plugin_dir.startswith(str(tmp_path))
        assert sb.loss_dir.startswith(str(tmp_path))

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_training_subprocess_receives_loss_dir_in_env(self, mock_run, sandbox):
        """End-to-end wiring check: ``execute_training`` must pass the
        sandbox's loss_dir to the training subprocess via
        SIDERIUS_LOSS_DIRS. Mirror of the plugin_dir version."""
        mock_run.side_effect = _make_train_success_side_effect(sandbox, EXP_ID)
        sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        _, kwargs = mock_run.call_args
        assert "env" in kwargs
        assert kwargs["env"]["SIDERIUS_LOSS_DIRS"] == sandbox.loss_dir
        # And plugin_dir is still wired — regression guard for the existing path.
        assert kwargs["env"]["SIDERIUS_PLUGIN_DIRS"].split(os.pathsep)[0] == sandbox.plugin_dir


class TestGetLossDir:
    """``get_loss_dir`` is the single source of truth for the workspace-rooted
    loss-plugin layout. Mirror of ``get_plugin_dir`` tests."""

    def test_layout_matches_doc(self, tmp_path):
        """Path is exactly ``<workspace>/losses/<run_name>/`` (absolutised)."""
        result = get_loss_dir(str(tmp_path), "run_a")
        expected = _os.path.join(str(tmp_path), "losses", "run_a")
        assert result == expected

    def test_returns_absolute_path(self, tmp_path, monkeypatch):
        """Workflow may pass a relative workspace; the returned path must be
        absolute so it equals the sandbox's ``self.loss_dir``."""
        monkeypatch.chdir(tmp_path)
        result = get_loss_dir("relative_ws", "run_a")
        assert _os.path.isabs(result)
        assert "relative_ws" in result
        assert result.endswith(_os.path.join("losses", "run_a"))

    def test_distinct_from_plugin_dir(self, tmp_path):
        """``get_loss_dir`` and ``get_plugin_dir`` must produce different
        paths for the same (workspace, run_name) — that's the whole point
        of having separate env vars."""
        plugin = get_plugin_dir(str(tmp_path), "run_a")
        loss = get_loss_dir(str(tmp_path), "run_a")
        assert plugin != loss


class TestBothSandboxesHonourTheDeviceIdentityContract:
    """`sandbox_factory` may return either sandbox, so both must accept the
    SAME contract.

    V20 PR B (#153) added `device_identity` to `TidmadSandbox` and to the
    tuner's factory call, but `StubSandbox` overrides `__init__` and was not
    updated. Pseudo-training through the tuner therefore raised
    `TypeError: StubSandbox.__init__() got an unexpected keyword argument
    'device_identity'` — broken from that merge until V20 PR D's Case A
    needed the path.

    Nothing caught it: the factory seam is untyped, so no static check sees
    the mismatch, and only executing the pseudo branch reveals it.

    The stub must FORWARD the identity rather than swallow it — a pseudo run
    that reports a different device from the one the orchestrator resolved
    would make its telemetry describe the wrong hardware.
    """

    IDENTITY = "GPU-c30b6678-ff2a-f8b4-d378-af9681c6ceef"

    def test_the_stub_accepts_and_exposes_what_the_caller_passed(self, tmp_path):
        """MUTATION TARGET: accepting the argument and dropping it."""
        from core.sandbox_executor import StubSandbox

        sandbox = StubSandbox(run_name="t", workspace=str(tmp_path), device_identity=self.IDENTITY)
        assert sandbox.device_identity == self.IDENTITY

    def test_both_sandboxes_expose_the_same_attribute(self, tmp_path):
        """The contract is shared, so a caller cannot care which it got."""
        from core.sandbox_executor import StubSandbox, TidmadSandbox

        stub = StubSandbox(run_name="t", workspace=str(tmp_path), device_identity=self.IDENTITY)
        real = TidmadSandbox(run_name="t", workspace=str(tmp_path), device_identity=self.IDENTITY)
        assert stub.device_identity == real.device_identity == self.IDENTITY

    def test_absent_identity_stays_none_on_both(self, tmp_path):
        """A gap is not a default device — neither sandbox may invent one."""
        from core.sandbox_executor import StubSandbox, TidmadSandbox

        assert StubSandbox(run_name="t", workspace=str(tmp_path)).device_identity is None
        assert TidmadSandbox(run_name="t", workspace=str(tmp_path)).device_identity is None

    def test_the_tuner_passes_it_to_whatever_the_factory_returns(self):
        """MUTATION TARGET: the tuner resolving an identity and not passing it.

        Checked per AST call node: the orchestrator resolves the identity
        ONCE and hands it to the factory, so the sandbox never discovers a
        device of its own.
        """
        import ast
        from pathlib import Path

        tuner = (
            Path(__file__).resolve().parents[3]
            / "nodes"
            / "ml_hyperparameter_tune_agent"
            / "ml_hyperparameter_tune_agent.py"
        )
        tree = ast.parse(tuner.read_text(encoding="utf-8"))
        passed = [
            n.lineno
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and (getattr(n.func, "attr", None) == "_sandbox_factory")
            and "device_identity" in {kw.arg for kw in n.keywords}
        ]
        assert passed, "the tuner calls _sandbox_factory without device_identity"
