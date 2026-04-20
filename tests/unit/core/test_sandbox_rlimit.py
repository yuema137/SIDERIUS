"""
Unit tests for subprocess host-RAM hardening (Fix 1).

Covers the helpers introduced in ``core/sandbox_executor.py`` for
docs/optimize_inference_and_scoring.md §3 Fix 1:

  * ``_subprocess_rss_gb()`` — env-var resolution with default 24 GiB.
  * ``_limited_preexec(gb)`` — returns a callable that caps RLIMIT_AS
    in the child; returns ``None`` when disabled.
  * ``_is_oom_failure(e)`` — recognises SIGKILL and Python ``MemoryError``
    as host-RAM exhaustion.
  * ``_format_subprocess_error`` — tags OOM-class failures with the
    ``[oom_host_ram]`` marker.
  * ``TidmadSandbox.execute_{training,inference,scoring}`` — pass
    ``preexec_fn`` to ``subprocess.run`` and surface ``oom_host_ram``
    status on OOM-class CalledProcessError.

All tests mock ``subprocess.run`` — no GPU, no real process spawning.
"""
import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from core.sandbox_executor import (
    TidmadSandbox,
    _DEFAULT_SUBPROCESS_RSS_GB,
    _format_subprocess_error,
    _is_oom_failure,
    _limited_preexec,
    _subprocess_rss_gb,
)


# ==========================================
# Fixtures
# ==========================================

MODEL_CFG = {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [100, 10]}
TRAIN_CFG = {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"}
LOSS_CFG = {"loss_type": "ce"}
EXP_ID = "oom_test_001"
RUN_NAME = "test_run"


@pytest.fixture
def sandbox(tmp_path):
    return TidmadSandbox(
        run_name=RUN_NAME,
        workspace=str(tmp_path),
        progress_bar=False,
    )


def _ok_result(stdout="done\n", stderr=""):
    m = MagicMock()
    m.returncode = 0
    m.stdout = stdout
    m.stderr = stderr
    return m


def _called_process_error(returncode: int, stderr: str = "", stdout: str = "") -> subprocess.CalledProcessError:
    e = subprocess.CalledProcessError(returncode, ["dummy"])
    e.stderr = stderr
    e.stdout = stdout
    return e


# ==========================================
# _subprocess_rss_gb — env-var resolution
# ==========================================

class TestSubprocessRssGb:

    def test_default_is_24(self, monkeypatch):
        monkeypatch.delenv("SIDERIUS_SUBPROCESS_RSS_GB", raising=False)
        assert _subprocess_rss_gb() == 24
        assert _DEFAULT_SUBPROCESS_RSS_GB == 24

    def test_env_override_positive(self, monkeypatch):
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "12")
        assert _subprocess_rss_gb() == 12

    def test_env_zero_disables(self, monkeypatch):
        """Zero is an explicit opt-out — callers get None from _limited_preexec."""
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "0")
        assert _subprocess_rss_gb() == 0

    def test_env_non_numeric_falls_back(self, monkeypatch):
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "not_a_number")
        assert _subprocess_rss_gb() == _DEFAULT_SUBPROCESS_RSS_GB

    def test_env_negative_falls_back(self, monkeypatch):
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "-5")
        assert _subprocess_rss_gb() == _DEFAULT_SUBPROCESS_RSS_GB


# ==========================================
# _limited_preexec — callable returned, limit applied
# ==========================================

class TestLimitedPreexec:

    def test_returns_callable_for_positive_gb(self):
        fn = _limited_preexec(8)
        assert callable(fn)

    def test_returns_none_for_zero(self):
        assert _limited_preexec(0) is None

    def test_returns_none_for_negative(self):
        assert _limited_preexec(-1) is None

    def test_callable_applies_setrlimit(self):
        """The returned closure must call setrlimit(RLIMIT_AS, (bytes, bytes)).

        We can't invoke it directly in-process without actually capping the
        test runner, so we patch ``resource`` and check the call args.
        """
        import resource as _resource_mod
        gb = 7
        expected_bytes = gb * (1024 ** 3)

        with patch.object(_resource_mod, "setrlimit") as mock_setrlimit:
            fn = _limited_preexec(gb)
            assert fn is not None
            fn()
            mock_setrlimit.assert_called_once_with(
                _resource_mod.RLIMIT_AS,
                (expected_bytes, expected_bytes),
            )


# ==========================================
# _is_oom_failure — signatures we recognise
# ==========================================

class TestIsOomFailure:

    def test_sigkill_returncode_is_oom(self):
        e = _called_process_error(returncode=-9)
        assert _is_oom_failure(e) is True

    def test_memory_error_in_stderr_is_oom(self):
        e = _called_process_error(
            returncode=1,
            stderr="Traceback (most recent call last):\n  ...\nMemoryError\n",
        )
        assert _is_oom_failure(e) is True

    def test_generic_exit_1_not_oom(self):
        e = _called_process_error(returncode=1, stderr="ValueError: bad config")
        assert _is_oom_failure(e) is False

    def test_sigsegv_not_oom(self):
        e = _called_process_error(returncode=-11)
        assert _is_oom_failure(e) is False

    def test_empty_error_not_oom(self):
        e = _called_process_error(returncode=2)
        assert _is_oom_failure(e) is False


# ==========================================
# _format_subprocess_error — oom_host_ram tag
# ==========================================

class TestFormatSubprocessErrorOomTag:

    def test_memory_error_stderr_gets_oom_tag(self):
        e = _called_process_error(returncode=1, stderr="MemoryError\n")
        msg = _format_subprocess_error(e, "Train")
        assert "[oom_host_ram]" in msg
        assert "MemoryError" in msg

    def test_sigkill_gets_oom_tag(self):
        e = _called_process_error(returncode=-9)
        msg = _format_subprocess_error(e, "Scoring")
        assert "[oom_host_ram]" in msg
        assert "SIGKILL" in msg

    def test_non_oom_failure_has_no_oom_tag(self):
        e = _called_process_error(returncode=1, stderr="ValueError: bad")
        msg = _format_subprocess_error(e, "Inference")
        assert "[oom_host_ram]" not in msg


# ==========================================
# TidmadSandbox — preexec_fn threaded through subprocess.run
# ==========================================

class TestSandboxPreexecWiring:
    """Every subprocess.run in the sandbox must receive preexec_fn."""

    @patch("core.sandbox_executor.subprocess.run")
    def test_training_passes_preexec_fn(self, mock_run, sandbox, monkeypatch):
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "16")
        mock_run.return_value = _ok_result()
        sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        _, kwargs = mock_run.call_args
        assert "preexec_fn" in kwargs
        assert callable(kwargs["preexec_fn"])

    @patch("core.sandbox_executor.subprocess.run")
    def test_inference_passes_preexec_fn(self, mock_run, sandbox, monkeypatch):
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "16")
        mock_run.return_value = _ok_result()
        sandbox.execute_inference(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, LOSS_CFG)
        _, kwargs = mock_run.call_args
        assert "preexec_fn" in kwargs
        assert callable(kwargs["preexec_fn"])

    @patch("core.sandbox_executor.subprocess.run")
    def test_scoring_passes_preexec_fn(self, mock_run, sandbox, monkeypatch):
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "16")
        mock_run.return_value = _ok_result()
        # execute_scoring pre-creates a score JSON it then reads back — seed it
        # so the success path completes cleanly with mocked subprocess.run.
        result_dir = os.path.join(sandbox.dirs["records"], RUN_NAME)
        os.makedirs(result_dir, exist_ok=True)
        sandbox.execute_scoring(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        _, kwargs = mock_run.call_args
        assert "preexec_fn" in kwargs
        assert callable(kwargs["preexec_fn"])

    @patch("core.sandbox_executor.subprocess.run")
    def test_env_zero_disables_preexec(self, mock_run, sandbox, monkeypatch):
        """SIDERIUS_SUBPROCESS_RSS_GB=0 → preexec_fn is None."""
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "0")
        mock_run.return_value = _ok_result()
        sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        _, kwargs = mock_run.call_args
        assert kwargs["preexec_fn"] is None


# ==========================================
# TidmadSandbox — OOM-class failures surface status="oom_host_ram"
# ==========================================

class TestSandboxOomStatus:

    @patch("core.sandbox_executor.subprocess.run")
    def test_training_memory_error_returns_oom_status(self, mock_run, sandbox):
        mock_run.side_effect = _called_process_error(
            returncode=1,
            stderr="Traceback ...\nMemoryError\n",
        )
        out = sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        assert out["status"] == "oom_host_ram"
        assert "[oom_host_ram]" in out["message"]

    @patch("core.sandbox_executor.subprocess.run")
    def test_training_sigkill_returns_oom_status(self, mock_run, sandbox):
        mock_run.side_effect = _called_process_error(returncode=-9)
        out = sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        assert out["status"] == "oom_host_ram"

    @patch("core.sandbox_executor.subprocess.run")
    def test_training_non_oom_still_error(self, mock_run, sandbox):
        mock_run.side_effect = _called_process_error(returncode=1, stderr="ValueError: bad")
        out = sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        assert out["status"] == "error"
        assert "[oom_host_ram]" not in out["message"]

    @patch("core.sandbox_executor.subprocess.run")
    def test_inference_memory_error_returns_oom_status(self, mock_run, sandbox):
        mock_run.side_effect = _called_process_error(
            returncode=1,
            stderr="MemoryError\n",
        )
        out = sandbox.execute_inference(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, LOSS_CFG)
        assert out["status"] == "oom_host_ram"

    @patch("core.sandbox_executor.subprocess.run")
    def test_scoring_memory_error_returns_oom_status(self, mock_run, sandbox):
        mock_run.side_effect = _called_process_error(
            returncode=1,
            stderr="MemoryError\n",
        )
        out = sandbox.execute_scoring(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        assert out["status"] == "oom_host_ram"
