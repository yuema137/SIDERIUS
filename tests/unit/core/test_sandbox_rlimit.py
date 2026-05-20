"""
Unit tests for subprocess host-RAM hardening (Fix 1).

Covers the helpers introduced in ``core/sandbox_executor.py`` for
docs/optimize_inference_and_scoring.md §3 Fix 1:

  * ``_subprocess_rss_gb(role)`` — role-aware defaults (scoring=24 GiB,
    training/inference=48 GiB) + env-var override.
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
    _ROLE_DEFAULT_RSS_GB,
    TidmadSandbox,
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


def _train_success_side_effect(sandbox, exp_id=EXP_ID, stdout="done\n", stderr=""):
    """Build a ``subprocess.run`` side_effect that mirrors a successful
    training run (Phase 6.7 Commit 4): writes the ``_OK_<exp_id>`` sentinel
    to ``sandbox.dirs['models']`` before returning. Without this, the
    executor's silent-crash check rejects the run as ``error_training``
    even though the mocked subprocess returncode is 0."""

    def _side_effect(*args, **kwargs):
        os.makedirs(sandbox.dirs["models"], exist_ok=True)
        sentinel = os.path.join(sandbox.dirs["models"], f"_OK_{exp_id}")
        with open(sentinel, "wb"):
            pass
        return _ok_result(stdout=stdout, stderr=stderr)

    return _side_effect


def _called_process_error(
    returncode: int, stderr: str = "", stdout: str = ""
) -> subprocess.CalledProcessError:
    e = subprocess.CalledProcessError(returncode, ["dummy"])
    e.stderr = stderr
    e.stdout = stdout
    return e


# ==========================================
# _subprocess_rss_gb — role-aware defaults + env-var resolution
# ==========================================


class TestSubprocessRssGb:
    def test_scoring_default_is_24(self, monkeypatch):
        """Scoring (CPU-only) keeps the original 24 GiB ceiling — this is the
        codepath the 2026-04-20 incident hit, so we don't loosen it."""
        monkeypatch.delenv("SIDERIUS_SUBPROCESS_RSS_GB", raising=False)
        assert _subprocess_rss_gb("scoring") == 24
        assert _ROLE_DEFAULT_RSS_GB["scoring"] == 24

    def test_training_default_is_40(self, monkeypatch):
        """Training (CUDA) ceiling is 20 GiB (static CUDA+torch VA) + 16 GiB
        (working VRAM budget) + 4 GiB (safety margin). Keeps ~21 GiB of host
        RAM free after the cap. See VA-vs-RSS calibration note in
        sandbox_executor.py."""
        monkeypatch.delenv("SIDERIUS_SUBPROCESS_RSS_GB", raising=False)
        assert _subprocess_rss_gb("training") == 40
        assert _ROLE_DEFAULT_RSS_GB["training"] == 40

    def test_inference_default_is_40(self, monkeypatch):
        """Inference is also a CUDA subprocess — same 40 GiB ceiling as training."""
        monkeypatch.delenv("SIDERIUS_SUBPROCESS_RSS_GB", raising=False)
        assert _subprocess_rss_gb("inference") == 40
        assert _ROLE_DEFAULT_RSS_GB["inference"] == 40

    def test_unknown_role_raises(self):
        with pytest.raises(ValueError, match="unknown role"):
            _subprocess_rss_gb("bogus")

    def test_env_override_wins_for_every_role(self, monkeypatch):
        """Global env var overrides the role default uniformly. This keeps
        the pre-existing SIDERIUS_SUBPROCESS_RSS_GB contract — anyone who had
        it set gets the same value across training/inference/scoring."""
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "12")
        assert _subprocess_rss_gb("training") == 12
        assert _subprocess_rss_gb("inference") == 12
        assert _subprocess_rss_gb("scoring") == 12

    def test_env_zero_disables_for_every_role(self, monkeypatch):
        """Zero is an explicit opt-out — callers get None from _limited_preexec."""
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "0")
        assert _subprocess_rss_gb("training") == 0
        assert _subprocess_rss_gb("inference") == 0
        assert _subprocess_rss_gb("scoring") == 0

    def test_env_non_numeric_falls_back_to_role_default(self, monkeypatch):
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "not_a_number")
        assert _subprocess_rss_gb("training") == _ROLE_DEFAULT_RSS_GB["training"]
        assert _subprocess_rss_gb("scoring") == _ROLE_DEFAULT_RSS_GB["scoring"]

    def test_env_negative_falls_back_to_role_default(self, monkeypatch):
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "-5")
        assert _subprocess_rss_gb("training") == _ROLE_DEFAULT_RSS_GB["training"]
        assert _subprocess_rss_gb("inference") == _ROLE_DEFAULT_RSS_GB["inference"]


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
        expected_bytes = gb * (1024**3)

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

    def test_torch_out_of_memory_error_not_oom(self):
        """``torch.OutOfMemoryError`` is a CUDA-allocator failure, not a
        host-RAM exhaustion. A substring match on "MemoryError" would
        false-positive because "OutOfMemoryError" contains "MemoryError".
        The word-boundary regex must not match this case — tagging a CUDA
        OOM as oom_host_ram would hide a VA-cap misconfiguration under a
        generic "host RAM" label and send the orchestrator down the wrong
        recovery path.
        """
        stderr = (
            "Traceback (most recent call last):\n"
            '  File "train.py", line 465, in run_experiment_streaming\n'
            "    loss = criterion(output, target_seq)\n"
            "torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 314.00 MiB.\n"
        )
        e = _called_process_error(returncode=1, stderr=stderr)
        assert _is_oom_failure(e) is False

    def test_bare_out_of_memory_error_not_oom(self):
        """Same defence without the `torch.` prefix — some stack frames show
        the class name unqualified."""
        e = _called_process_error(returncode=1, stderr="OutOfMemoryError: GPU allocation failed\n")
        assert _is_oom_failure(e) is False

    def test_qualified_memory_error_still_oom(self):
        """A fully-qualified ``builtins.MemoryError`` (rare, but possible in
        some tracebacks) should still register as a host-RAM OOM — the
        word-boundary regex must match ``.MemoryError`` since ``.`` is a
        non-word character."""
        e = _called_process_error(returncode=1, stderr="builtins.MemoryError: Unable to allocate\n")
        assert _is_oom_failure(e) is True

    def test_memory_error_with_message_is_oom(self):
        """Real-world MemoryError lines include a message after the colon."""
        e = _called_process_error(
            returncode=1,
            stderr="MemoryError: Unable to allocate 1.5 GiB for an array with shape (...)\n",
        )
        assert _is_oom_failure(e) is True


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

    def test_torch_oom_not_tagged_host_ram(self):
        """Regression: a CUDA allocator failure must not be tagged as
        oom_host_ram. Before the word-boundary fix, a substring match on
        "MemoryError" inside "torch.OutOfMemoryError" produced a false
        positive — the sandbox status bubbled up as oom_host_ram when the
        real failure was a GPU-side allocation (or a VA-cap misconfiguration
        on the CUDA subprocess)."""
        e = _called_process_error(
            returncode=1,
            stderr="torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 314 MiB.\n",
        )
        msg = _format_subprocess_error(e, "Train")
        assert "[oom_host_ram]" not in msg
        assert "OutOfMemoryError" in msg  # the underlying error should still be visible


# ==========================================
# TidmadSandbox — preexec_fn threaded through subprocess.run
# ==========================================


class TestSandboxPreexecWiring:
    """Every subprocess.run in the sandbox must receive preexec_fn, and the
    role passed to ``_subprocess_rss_gb`` must match the subprocess being
    launched. The role-wiring assertions patch ``_subprocess_rss_gb`` to
    capture the role string rather than inspect the opaque preexec closure."""

    @patch("core.sandbox_executor.subprocess.run")
    def test_training_passes_preexec_fn(self, mock_run, sandbox, monkeypatch):
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "16")
        mock_run.side_effect = _train_success_side_effect(sandbox)
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
        mock_run.side_effect = _train_success_side_effect(sandbox)
        sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        _, kwargs = mock_run.call_args
        assert kwargs["preexec_fn"] is None

    @patch("core.sandbox_executor._subprocess_rss_gb")
    @patch("core.sandbox_executor.subprocess.run")
    def test_training_uses_training_role(self, mock_run, mock_rss, sandbox):
        """Training subprocess resolves ceiling via role='training'."""
        mock_run.side_effect = _train_success_side_effect(sandbox)
        mock_rss.return_value = 40
        sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        mock_rss.assert_called_with("training")

    @patch("core.sandbox_executor._subprocess_rss_gb")
    @patch("core.sandbox_executor.subprocess.run")
    def test_inference_uses_inference_role(self, mock_run, mock_rss, sandbox):
        mock_run.return_value = _ok_result()
        mock_rss.return_value = 40
        sandbox.execute_inference(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, LOSS_CFG)
        mock_rss.assert_called_with("inference")

    @patch("core.sandbox_executor._subprocess_rss_gb")
    @patch("core.sandbox_executor.subprocess.run")
    def test_scoring_uses_scoring_role(self, mock_run, mock_rss, sandbox):
        mock_run.return_value = _ok_result()
        mock_rss.return_value = 24
        result_dir = os.path.join(sandbox.dirs["records"], RUN_NAME)
        os.makedirs(result_dir, exist_ok=True)
        sandbox.execute_scoring(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        mock_rss.assert_called_with("scoring")


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
