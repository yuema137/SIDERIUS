"""Step 11 — C0 pre-change baselines (R-11-1, R-11-5, R-11-11, C6).

These tests freeze the **pre-change** observable behaviour of the spawn
surface so that every later Step-11 commit has something exact to be
measured against. They are captured at the frozen implementation base
`c1caa609` and must remain green for the LEGACY / un-composed TIDMAD path
for the whole of Step 11.

What each baseline owns
-----------------------

``TestLegacyArgvFlagBaseline``
    R-11-1's legacy contract: for an **un-composed** run the training,
    inference and scoring argv carry EXACTLY these flags. A later commit
    that transports a new value unconditionally — rather than only when a
    composition is bound — turns this RED. This is the whole point of the
    per-mode reconciliation in R-11-1, so the baseline is captured at
    runtime from the production builders, not read off the source text.

``TestRoleCeilingBaseline``
    §9.3 finding 14 / R-11-5: TIDMAD's resolved ceilings are 40/60/24 and
    the ladder has exactly TWO layers. C3 declares these with provenance
    and must resolve to the same numbers.

``TestMalformedOverrideRefusesLoudly`` — **flipped by C3 (R-11-5).**
    Its C0 predecessor asserted that a malformed
    ``SIDERIUS_SUBPROCESS_RSS_GB`` silently falls back to the role default.
    R-11-5 requires a loud refusal, and per R-11-10 the guard was rewritten
    in place rather than twinned.

``TestTidmadCleanupGlobBaseline``
    C6's parity target: the TIDMAD deliverable glob must be byte-identical
    after naming flows from the run binding.
"""

from __future__ import annotations

import json
import os
import subprocess
from unittest.mock import MagicMock, mock_open, patch

import pytest

from core.execution_calibration import MalformedCeilingOverride
from core.sandbox_executor import _ROLE_DEFAULT_RSS_GB, TidmadSandbox, _subprocess_rss_gb
from execute_tools.deliverable_spec import default_deliverable_naming

MODEL_CFG = {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [100, 10]}
TRAIN_CFG = {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"}
LOSS_CFG = {"loss_type": "ce"}
EXP_ID = "step11_c0_exp"
RUN_NAME = "step11_c0_run"


# ----------------------------------------------------------------------
# R-11-1 — legacy / un-composed argv flag baseline
# ----------------------------------------------------------------------

# Captured at the frozen base `c1caa609` by RUNNING the production builders
# with no composition bound and the MINIMAL legacy call signature (no
# sample set, no runtime policy, no file order). Only OPTION tokens are
# frozen: positional values are absolute temp paths and carry no contract.
#
# Scope, stated so the baseline cannot pass for the wrong reason: the
# argument-driven conditional flags (`--sample_set_json`,
# `--eval_sample_set_json`, `--train_portion`, `--train_base_seed`,
# `--order_strategy`, `--file_order_json`, `--runtime_observation_out`,
# `--runtime_policy_json`) are absent here because the CALLER supplied
# nothing, not because they were removed. The property this baseline owns
# is narrower and is exactly the one Step 11 can break: **no new
# UNCONDITIONAL flag appears on the legacy path.** `--task_data_path_id`
# is correctly absent below, which is the R-11-1 precedent working.
LEGACY_TRAINING_FLAGS: tuple[str, ...] = (
    "--model_cfg",
    "--train_cfg",
    "--loss_cfg",
    "--dataset_profile_json",
    "--exp_id",
    "--run_name",
    "--sandbox_dir",
    "--file_index",
    "--model_io_json",
)

LEGACY_INFERENCE_FLAGS: tuple[str, ...] = (
    "--mode",
    "-m",
    "--dataset_profile_json",
    "--model_cfg",
    "--loss_cfg",
    "--model_path",
    "--exp_id",
    "--run_name",
    "--output_dir",
    "--inference_batch_size",
    "--file_index",
    "--model_io_json",
)

LEGACY_SCORING_FLAGS: tuple[str, ...] = (
    "--mode",
    "-m",
    "--dataset_profile_json",
    "--exp_id",
    "--run_name",
    "--output_json",
    "--data_dir",
    "--file_index",
)


def _options(cmd: list[str]) -> tuple[str, ...]:
    """Option tokens of an argv, in order, de-duplicated by first sight.

    A value that merely LOOKS like a flag (a negative number) is excluded by
    requiring a non-digit after the dashes.
    """
    seen: list[str] = []
    for tok in cmd:
        if tok.startswith("-") and not tok.lstrip("-")[:1].isdigit() and tok not in seen:
            seen.append(tok)
    return tuple(seen)


@pytest.fixture
def sandbox(tmp_path):
    return TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path), progress_bar=False)


def _train_success(sandbox, exp_id):
    def _side_effect(*args, **kwargs):
        os.makedirs(sandbox.dirs["models"], exist_ok=True)
        with open(os.path.join(sandbox.dirs["models"], f"_OK_{exp_id}"), "wb"):
            pass
        result = MagicMock()
        result.returncode = 0
        result.stdout = "done\n"
        result.stderr = ""
        return result, None

    return _side_effect


class TestLegacyArgvFlagBaseline:
    """R-11-1: un-composed argv is byte-identical for the whole of Step 11.

    Fails when a Step-11 commit emits a transported binding unconditionally
    instead of only when a composition is bound — the `--task_data_path_id`
    precedent (`sandbox_executor.py:839-862`).
    """

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_training_argv_flags(self, mock_run, sandbox):
        mock_run.side_effect = _train_success(sandbox, EXP_ID)
        sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        cmd = mock_run.call_args[0][0]
        assert _options(cmd) == LEGACY_TRAINING_FLAGS

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_inference_argv_flags(self, mock_run, sandbox):
        cfg_dir = sandbox.dirs["configs"]
        os.makedirs(cfg_dir, exist_ok=True)
        for name in (f"model_config_{EXP_ID}.json", f"loss_config_{EXP_ID}.json"):
            with open(os.path.join(cfg_dir, name), "w") as fh:
                json.dump({}, fh)
        open(os.path.join(sandbox.dirs["models"], f"model_fcnet_{EXP_ID}_agent.pth"), "w").close()
        result = MagicMock()
        result.returncode = 0
        result.stdout = "done\n"
        result.stderr = ""
        mock_run.return_value = (result, None)
        sandbox.execute_inference(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, LOSS_CFG)
        cmd = mock_run.call_args[0][0]
        assert _options(cmd) == LEGACY_INFERENCE_FLAGS

    @patch("core.sandbox_executor.subprocess.run")
    def test_scoring_argv_flags(self, mock_run, sandbox):
        result = MagicMock()
        result.returncode = 0
        result.stdout = "done\n"
        result.stderr = ""
        mock_run.return_value = result
        score_data = json.dumps({"denoising_score": 0.9})
        with patch("builtins.open", mock_open(read_data=score_data)):
            with patch("os.path.exists", return_value=True):
                with patch("os.remove"):
                    sandbox.execute_scoring(
                        EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG
                    )
        cmd = mock_run.call_args[0][0]
        assert _options(cmd) == LEGACY_SCORING_FLAGS

    def test_no_composition_means_no_task_data_path_flag(self, sandbox):
        """The R-11-1 precedent, asserted rather than assumed: the ONE
        existing composed-only flag is absent when nothing is bound.
        """
        assert "--task_data_path_id" not in LEGACY_TRAINING_FLAGS
        assert "--task_data_path_id" not in LEGACY_INFERENCE_FLAGS
        assert "--task_data_path_id" not in LEGACY_SCORING_FLAGS

    def test_no_argv_builder_emits_a_data_root_flag_today(self, sandbox):
        """The §3.1 gap, stated executably: the physical data root does NOT
        cross to training or inference today. C4 changes this for COMPOSED
        runs only, so this assertion is scoped to the flag NAME the child
        would read, and stays true for the legacy path afterwards.
        """
        assert "--data_dir" not in LEGACY_TRAINING_FLAGS
        assert "--data_dir" not in LEGACY_INFERENCE_FLAGS
        # Scoring's existing `--data_dir` is the SANDBOX base dir, not the
        # physical dataset root — a name collision C4 must not conflate.
        assert "--data_dir" in LEGACY_SCORING_FLAGS


# ----------------------------------------------------------------------
# R-11-5 — resource ceiling ladder
# ----------------------------------------------------------------------


class TestRoleCeilingBaseline:
    """C3 must resolve to these exact numbers (§9.3 compatibility)."""

    def test_tidmad_resolved_ceilings(self, monkeypatch):
        monkeypatch.delenv("SIDERIUS_SUBPROCESS_RSS_GB", raising=False)
        assert _subprocess_rss_gb("training") == 40
        assert _subprocess_rss_gb("inference") == 60
        assert _subprocess_rss_gb("scoring") == 24

    def test_declared_table_is_exactly_three_roles(self):
        assert _ROLE_DEFAULT_RSS_GB == {"training": 40, "inference": 60, "scoring": 24}

    def test_env_override_wins_for_every_role(self, monkeypatch):
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "7")
        for role in ("training", "inference", "scoring"):
            assert _subprocess_rss_gb(role) == 7

    def test_zero_disables_the_ceiling(self, monkeypatch):
        """`0` is the explicit pre-Fix-1 disable. R-11-5 preserves it."""
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "0")
        assert _subprocess_rss_gb("training") == 0

    def test_unknown_role_raises(self, monkeypatch):
        monkeypatch.delenv("SIDERIUS_SUBPROCESS_RSS_GB", raising=False)
        with pytest.raises(ValueError):
            _subprocess_rss_gb("compilation")


class TestMalformedOverrideRefusesLoudly:
    """R-11-5, landed by C3. **This class REPLACES its own C0 predecessor.**

    Per R-11-10 the pre-fix guard (`TestMalformedOverrideIsSilentToday`,
    which asserted the silent fallback) is not kept beside a post-fix twin
    — it is rewritten in place, so exactly one test states what a malformed
    override does.

    Note what is NOT asserted: nothing here claims a particular ceiling
    value follows a refusal. There is no resolved value after a refusal,
    and that is the point.
    """

    @pytest.mark.parametrize("bad", ["not-a-number", "12.5", "", "40G", " "])
    def test_unparseable_override_refuses(self, monkeypatch, bad):
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", bad)
        with pytest.raises(MalformedCeilingOverride):
            _subprocess_rss_gb("training")

    def test_negative_override_refuses(self, monkeypatch):
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "-1")
        with pytest.raises(MalformedCeilingOverride):
            _subprocess_rss_gb("training")

    def test_the_refusal_names_the_variable_and_the_bad_value(self, monkeypatch):
        """A refusal an operator cannot act on is barely better than a
        silent fallback.
        """
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "4O")
        with pytest.raises(MalformedCeilingOverride) as exc:
            _subprocess_rss_gb("scoring")
        assert "SIDERIUS_SUBPROCESS_RSS_GB" in str(exc.value)
        assert "4O" in str(exc.value)


# ----------------------------------------------------------------------
# C6 — deliverable naming parity target
# ----------------------------------------------------------------------


class TestTidmadCleanupGlobBaseline:
    """C6 parity: the TIDMAD attempt glob must not move.

    Consumed by the watchdog partial-artifact cleanup at
    `core/sandbox_executor.py:1856-1865`.
    """

    def test_attempt_glob_is_byte_identical(self):
        naming = default_deliverable_naming()
        assert (
            naming.attempt_glob(model_type="fcnet", run_name=RUN_NAME, exp_id=EXP_ID)
            == f"abra_validation_denoised_fcnet_{RUN_NAME}_{EXP_ID}_*.h5"
        )

    def test_sandbox_defaults_to_that_authority(self, sandbox):
        assert sandbox.deliverable_naming.attempt_glob(
            model_type="fcnet", run_name=RUN_NAME, exp_id=EXP_ID
        ) == default_deliverable_naming().attempt_glob(
            model_type="fcnet", run_name=RUN_NAME, exp_id=EXP_ID
        )


def test_scoring_launch_semantics_unchanged(sandbox):
    """Guards the §3.5 invariant that scoring keeps its DIRECT
    `subprocess.run` while training/inference go through the observed seam.
    C7 touches spawn hygiene and must not migrate this launch.
    """
    import inspect

    from core import sandbox_executor

    src = inspect.getsource(sandbox_executor.TidmadSandbox.execute_scoring)
    assert "subprocess.run(" in src
    assert "_run_observed_subprocess" not in src
    assert isinstance(subprocess.run, type(subprocess.run))
