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
from pathlib import Path
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
from execute_tools.data_paths import bind_physical_data_root
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

# ==========================================
# Fixtures
# ==========================================

MODEL_CFG = {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [100, 10]}
TRAIN_CFG = {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"}
LOSS_CFG = {"loss_type": "ce"}
EXP_ID = "oom_test_001"
RUN_NAME = "test_run"
QUICKSTART = Path(__file__).resolve().parents[3] / "configs/task_composition/quickstart.yaml"


@pytest.fixture
def sandbox(tmp_path):
    composition = compose_run_task_bindings(str(QUICKSTART))
    with bind_physical_data_root(str(tmp_path), purpose="sandbox ceiling test"), bind_run_task_composition(
        composition,
        physical_data_root=str(tmp_path),
    ):
        yield TidmadSandbox(
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
        return _ok_result(stdout=stdout, stderr=stderr), None

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
    @pytest.mark.parametrize(
        "role,expected_gb",
        [
            pytest.param("scoring", 24, id="scoring_default_24gib"),
            pytest.param("training", 40, id="training_default_40gib"),
            pytest.param("inference", 60, id="inference_default_60gib"),
        ],
    )
    def test_role_default_ceiling(self, role, expected_gb, monkeypatch):
        """Per-role default RSS ceiling, no env override.

        Scoring (CPU-only) keeps the original 24 GiB — this is the codepath the
        2026-04-20 incident hit, so we don't loosen it. Training remains capped
        at 40 GiB, while inference gets 60 GiB for full-scope baseline inference.
        See the VA-vs-RSS calibration note in sandbox_executor.py.
        """
        monkeypatch.delenv("SIDERIUS_SUBPROCESS_RSS_GB", raising=False)
        assert _subprocess_rss_gb(role) == expected_gb
        assert _ROLE_DEFAULT_RSS_GB[role] == expected_gb

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

    # UPGRADED by Step 11 C3 (R-11-5). These two used to assert that a
    # malformed override falls back to the role default SILENTLY. That is
    # the behaviour the ruling changes: an operator who sets the variable
    # has stated an intention, and resolving it to a different number
    # without saying so produces a run whose configuration nobody can
    # reconstruct afterwards — `RSS_GB=4O` (letter O) reported nothing
    # wrong. Their functional intent — "what happens on a malformed
    # override" — is preserved; the expected answer is now a refusal.

    @pytest.mark.parametrize("bad", ["not_a_number", "12.5", "", "40 GiB"])
    def test_env_non_numeric_refuses_loudly(self, monkeypatch, bad):
        from core.execution_calibration import MalformedCeilingOverride

        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", bad)
        for role in ("training", "inference", "scoring"):
            with pytest.raises(MalformedCeilingOverride, match="not an integer"):
                _subprocess_rss_gb(role)

    def test_env_negative_refuses_loudly(self, monkeypatch):
        from core.execution_calibration import MalformedCeilingOverride

        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "-5")
        for role in ("training", "inference", "scoring"):
            with pytest.raises(MalformedCeilingOverride, match="negative"):
                _subprocess_rss_gb(role)

    def test_the_refusal_does_not_swallow_the_disable_escape_hatch(self, monkeypatch):
        """`0` must stay a legal, meaningful value. An operator diagnosing
        an allocator problem needs a way to take the cap off, and a
        stricter parser that refused `0` would remove it.
        """
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "0")
        assert _subprocess_rss_gb("training") == 0


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
    @pytest.mark.parametrize(
        "returncode,stderr,expected",
        [
            pytest.param(-9, "", True, id="sigkill_returncode"),
            pytest.param(
                1,
                "Traceback (most recent call last):\n  ...\nMemoryError\n",
                True,
                id="memory_error_in_stderr",
            ),
            pytest.param(1, "ValueError: bad config", False, id="generic_exit_1"),
            pytest.param(-11, "", False, id="sigsegv"),
            pytest.param(2, "", False, id="empty_error"),
            pytest.param(
                1,
                (
                    "Traceback (most recent call last):\n"
                    '  File "train.py", line 465, in run_experiment_streaming\n'
                    "    loss = criterion(output, target_seq)\n"
                    "torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 314.00 MiB.\n"
                ),
                False,
                id="torch_out_of_memory_error",
            ),
            pytest.param(
                1,
                "OutOfMemoryError: GPU allocation failed\n",
                False,
                id="bare_out_of_memory_error",
            ),
            pytest.param(
                1,
                "builtins.MemoryError: Unable to allocate\n",
                True,
                id="qualified_memory_error_still_oom",
            ),
            pytest.param(
                1,
                "MemoryError: Unable to allocate 1.5 GiB for an array with shape (...)\n",
                True,
                id="memory_error_with_message",
            ),
        ],
    )
    def test_is_oom_failure_truth_table(self, returncode, stderr, expected):
        """OOM-class detection on subprocess.CalledProcessError.

        ``torch.OutOfMemoryError`` and bare ``OutOfMemoryError`` are CUDA-
        allocator failures, not host-RAM exhaustion. A substring match on
        "MemoryError" would false-positive because "OutOfMemoryError" contains
        "MemoryError" — the word-boundary regex must not match those cases.
        Tagging a CUDA OOM as oom_host_ram would hide a VA-cap misconfiguration
        under a generic "host RAM" label and send the orchestrator down the
        wrong recovery path. A fully-qualified ``builtins.MemoryError`` still
        registers because ``.`` is a non-word character so the regex matches
        ``.MemoryError``. Real-world MemoryError lines include a message after
        the colon.
        """
        e = _called_process_error(returncode=returncode, stderr=stderr)
        assert _is_oom_failure(e) is expected


# ==========================================
# _format_subprocess_error — oom_host_ram tag
# ==========================================


class TestFormatSubprocessErrorOomTag:
    @pytest.mark.parametrize(
        "returncode,stderr,phase_label,expect_oom_tag,extra_substring",
        [
            pytest.param(
                1,
                "MemoryError\n",
                "Train",
                True,
                "MemoryError",
                id="memory_error_stderr_gets_tag",
            ),
            pytest.param(-9, "", "Scoring", True, "SIGKILL", id="sigkill_gets_tag"),
            pytest.param(
                1,
                "ValueError: bad",
                "Inference",
                False,
                None,
                id="non_oom_failure_no_tag",
            ),
            pytest.param(
                1,
                "torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 314 MiB.\n",
                "Train",
                False,
                "OutOfMemoryError",
                id="torch_cuda_oom_no_tag",
            ),
        ],
    )
    def test_oom_tag_polarity(
        self, returncode, stderr, phase_label, expect_oom_tag, extra_substring
    ):
        """Regression: a CUDA allocator failure must not be tagged as
        oom_host_ram. Before the word-boundary fix, a substring match on
        "MemoryError" inside "torch.OutOfMemoryError" produced a false
        positive — the sandbox status bubbled up as oom_host_ram when the
        real failure was a GPU-side allocation (or a VA-cap misconfiguration
        on the CUDA subprocess). The underlying error class should still be
        visible in the formatted message regardless of tagging.
        """
        e = _called_process_error(returncode=returncode, stderr=stderr)
        msg = _format_subprocess_error(e, phase_label)
        assert ("[oom_host_ram]" in msg) is expect_oom_tag
        if extra_substring is not None:
            assert extra_substring in msg


# ==========================================
# TidmadSandbox — preexec_fn threaded through subprocess.run
# ==========================================


class TestSandboxPreexecWiring:
    """Every subprocess.run in the sandbox must receive preexec_fn, and the
    role passed to ``_subprocess_rss_gb`` must match the subprocess being
    launched. The role-wiring assertions patch ``_subprocess_rss_gb`` to
    capture the role string rather than inspect the opaque preexec closure."""

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_training_passes_preexec_fn(self, mock_run, sandbox, monkeypatch):
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "16")
        mock_run.side_effect = _train_success_side_effect(sandbox)
        sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        _, kwargs = mock_run.call_args
        assert "preexec_fn" in kwargs
        assert callable(kwargs["preexec_fn"])

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_inference_passes_preexec_fn(self, mock_run, sandbox, monkeypatch):
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "16")
        mock_run.return_value = (_ok_result(), None)
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

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_env_zero_disables_preexec(self, mock_run, sandbox, monkeypatch):
        """SIDERIUS_SUBPROCESS_RSS_GB=0 → preexec_fn is None."""
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "0")
        mock_run.side_effect = _train_success_side_effect(sandbox)
        sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        _, kwargs = mock_run.call_args
        assert kwargs["preexec_fn"] is None

    @patch("core.sandbox_executor._subprocess_rss_gb")
    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_training_uses_training_role(self, mock_run, mock_rss, sandbox):
        """Training subprocess resolves ceiling via role='training'."""
        mock_run.side_effect = _train_success_side_effect(sandbox)
        mock_rss.return_value = 40
        sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        mock_rss.assert_called_with("training")

    @patch("core.sandbox_executor._subprocess_rss_gb")
    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_inference_uses_inference_role(self, mock_run, mock_rss, sandbox):
        mock_run.return_value = (_ok_result(), None)
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
    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_training_memory_error_returns_oom_status(self, mock_run, sandbox):
        mock_run.side_effect = _called_process_error(
            returncode=1,
            stderr="Traceback ...\nMemoryError\n",
        )
        out = sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        assert out["status"] == "oom_host_ram"
        assert "[oom_host_ram]" in out["message"]

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_training_sigkill_returns_oom_status(self, mock_run, sandbox):
        mock_run.side_effect = _called_process_error(returncode=-9)
        out = sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        assert out["status"] == "oom_host_ram"

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_training_non_oom_still_error(self, mock_run, sandbox):
        mock_run.side_effect = _called_process_error(returncode=1, stderr="ValueError: bad")
        out = sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        assert out["status"] == "error"
        assert "[oom_host_ram]" not in out["message"]

    @patch("core.sandbox_executor._run_observed_subprocess")
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
