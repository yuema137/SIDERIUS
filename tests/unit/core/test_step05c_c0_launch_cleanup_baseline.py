"""Step 05c — Checkpoint 0: launch-argv and cleanup-filesystem baselines.

Design: ``docs/design/generic_framework_upgrade/
step_05c_tuner_execution_contracts.md`` §4, §4.2, C0.

**Two captures, two distinct failure classes.**

1. **Ordered argv goldens** (§4.2). The re-audit at ``226d4e9f`` found that
   what exists today is only *token-level*: ``test_sandbox_executor.py``
   asserts individual flags via ``_cli_token_after(cmd, "--flag")`` at
   ``:230``, ``:248``, ``:259`` and ``:293``. Those pass unchanged if a token
   is **inserted, removed or reordered** elsewhere in the list, which is
   exactly failure class 4. §3.2a freezes that 05c adds **no new argv** — it
   consumes the Step-02 ``--dataset_profile_json`` and Step-03
   ``--model_io_json`` transports rather than adding a third — so the whole
   ordered list is the honest oracle for that claim.

   The criterion is **exact ordered argv-list equality after explicitly
   documented normalization**, never "byte-identical argv": two tokens are
   genuinely ephemeral and are normalized here, each documented at the
   assertion. No machine-specific temp directory is baked into a golden.

2. **Cleanup filesystem sets**. The two cleanup consumers use
   **deliberately different** glob shapes, and both must be preserved
   exactly — the tuner's is exp-keyed and model/run-agnostic, the sandbox's
   is fully qualified. Both the DELETED set and the SURVIVING set are
   captured: a later widened glob that deletes too much is a data-loss
   defect, and only the surviving-set assertion catches it.
"""

from __future__ import annotations

import glob
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from core.sandbox_executor import TidmadSandbox

# ---------------------------------------------------------------------------
# Fixture identifiers — deliberately distinguishable so an ordering or
# substitution defect is visible in the golden (§4.2). "fcnet" and the two
# ids below share no substring with any flag name.
# ---------------------------------------------------------------------------
EXP_ID = "c0exp"
RUN_NAME = "c0run"
MODEL_TYPE = "fcnet"
MODEL_CFG = {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [100, 10]}
TRAIN_CFG = {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"}
LOSS_CFG = {"loss_type": "ce"}

# The two normalizations, applied by ``_normalize`` below. Each is genuinely
# ephemeral: the interpreter path is machine-specific, and the workspace root
# is a pytest tmp_path that differs on every run and every checkout.
PYTHON = "<PYTHON>"
WORKSPACE = "<WS>"


@pytest.fixture
def sandbox(tmp_path):
    return TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path), progress_bar=False)


def _normalize(cmd: list[str], workspace: str) -> list[str]:
    """Replace ONLY the two documented ephemeral values.

    * ``sys.executable`` -> ``<PYTHON>`` — the venv interpreter path.
    * the pytest ``tmp_path`` workspace root -> ``<WS>`` — every config,
      model and sidecar path is composed under it.

    Everything else, including the relative script path, every flag, every
    identifier and the full ORDER, is compared verbatim.
    """
    root = os.path.abspath(workspace)
    # Step 11 C7 (F-11-7): the three child scripts are now named by ABSOLUTE
    # path, anchored at the repository root rather than at the caller's cwd —
    # the launch used to work only because every launcher happened to chdir
    # to the repository first. The path is normalized back to its
    # repo-relative form here, for two reasons:
    #
    #   * a golden must never embed a machine-specific absolute path
    #     (the repository-portability rule), and
    #   * this comparison exists to pin the ARGUMENT LIST — its flags, its
    #     values and its ORDER — not the anchoring mechanism, which
    #     `tests/unit/core/test_step11_c7_spawn_hygiene.py` owns and proves
    #     absolute, existing and cwd-independent.
    #
    # Nothing else about these goldens moved.
    from core.sandbox_executor import SIDERIUS_ROOT

    siderius_root = os.path.abspath(SIDERIUS_ROOT) + os.sep
    normalized = []
    for tok in cmd:
        if tok == sys.executable:
            normalized.append(PYTHON)
            continue
        if tok.startswith(siderius_root) and tok.endswith(".py"):
            normalized.append(tok[len(siderius_root) :])
            continue
        normalized.append(tok.replace(root, WORKSPACE))
    return normalized


def _seed_inference_inputs(sandbox: TidmadSandbox) -> None:
    """The checkpoint and configs ``execute_inference`` requires on disk."""
    cfg_dir = sandbox.dirs["configs"]
    os.makedirs(cfg_dir, exist_ok=True)
    for name in (f"model_config_{EXP_ID}.json", f"loss_config_{EXP_ID}.json"):
        with open(os.path.join(cfg_dir, name), "w") as handle:
            json.dump({}, handle)
    os.makedirs(sandbox.dirs["models"], exist_ok=True)
    open(
        os.path.join(sandbox.dirs["models"], f"model_{MODEL_TYPE}_{EXP_ID}_agent.pth"), "w"
    ).close()


def _mock_result(returncode: int = 0):
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = "done\n"
    mock.stderr = ""
    return mock


# ---------------------------------------------------------------------------
# 1. Ordered argv goldens (§4.2)
# ---------------------------------------------------------------------------


@patch("core.sandbox_executor._run_observed_subprocess")
def test_c0_inference_argv_ordered_golden(mock_run, sandbox, tmp_path):
    """The COMPLETE ordered inference argv list, no sample_set.

    Guards ``sandbox_executor.execute_inference`` ``:1660-1692``. C3 migrates
    the producer names inside the child this list launches; §3.2a's frozen
    acceptance is that the child **reconstructs** the spec from
    ``--dataset_profile_json`` and ``--model_io_json``, which already cross —
    so this list must come out unchanged. If a new argument ever proves
    unavoidable, §3.2a requires the Stage-A claim be downgraded in writing,
    not quietly restated; this golden is what forces that conversation.
    """
    _seed_inference_inputs(sandbox)
    mock_run.return_value = (_mock_result(), None)

    sandbox.execute_inference(EXP_ID, RUN_NAME, MODEL_TYPE, MODEL_CFG, LOSS_CFG)

    (cmd,), _ = mock_run.call_args
    assert _normalize(cmd, str(tmp_path)) == [
        "<PYTHON>",
        "execute_tools/inference_single.py",
        "--mode",
        "agent",
        "-m",
        "fcnet",
        "--dataset_profile_json",
        "<WS>/configs/c0run/dataset_profile_c0exp.json",
        "--model_cfg",
        "<WS>/configs/c0run/model_config_c0exp.json",
        "--loss_cfg",
        "<WS>/configs/c0run/loss_config_c0exp.json",
        "--model_path",
        "<WS>/cached_models/model_fcnet_c0exp_agent.pth",
        "--exp_id",
        "c0exp",
        "--run_name",
        "c0run",
        "--output_dir",
        "<WS>",
        "--inference_batch_size",
        "25",
        "--file_index",
        "6",
        "--model_io_json",
        "<WS>/configs/c0run/model_io_c0exp.json",
    ]


@patch("core.sandbox_executor._run_observed_subprocess")
def test_c0_inference_argv_ordered_golden_with_sample_set(mock_run, sandbox, tmp_path):
    """The trial-mode ordered argv: the four conditional tails appended by the
    ``sample_set is not None`` branch (``:1706-1729``).

    Captured separately because the conditional tail is where an inserted flag
    is easiest to hide — the no-sample_set golden above would never see it.
    """
    _seed_inference_inputs(sandbox)
    mock_run.return_value = (_mock_result(), None)

    sandbox.execute_inference(
        EXP_ID,
        RUN_NAME,
        MODEL_TYPE,
        MODEL_CFG,
        LOSS_CFG,
        sample_set={"0": [0, 1]},
    )

    (cmd,), _ = mock_run.call_args
    assert _normalize(cmd, str(tmp_path)) == [
        "<PYTHON>",
        "execute_tools/inference_single.py",
        "--mode",
        "agent",
        "-m",
        "fcnet",
        "--dataset_profile_json",
        "<WS>/configs/c0run/dataset_profile_c0exp.json",
        "--model_cfg",
        "<WS>/configs/c0run/model_config_c0exp.json",
        "--loss_cfg",
        "<WS>/configs/c0run/loss_config_c0exp.json",
        "--model_path",
        "<WS>/cached_models/model_fcnet_c0exp_agent.pth",
        "--exp_id",
        "c0exp",
        "--run_name",
        "c0run",
        "--output_dir",
        "<WS>",
        "--inference_batch_size",
        "25",
        "--file_index",
        "6",
        "--model_io_json",
        "<WS>/configs/c0run/model_io_c0exp.json",
        "--sample_set_json",
        "<WS>/configs/c0run/eval_sample_set_c0exp.json",
        "--timing_out_json",
        "<WS>/configs/c0run/inference_timing_c0exp.json",
        "--runtime_observation_out",
        "<WS>/configs/c0run/runtime_verification_c0exp.json",
    ]


@patch("core.sandbox_executor._run_observed_subprocess")
def test_c0_training_argv_ordered_golden(mock_run, sandbox, tmp_path):
    """The COMPLETE ordered training argv list.

    Guards ``sandbox_executor.execute_training`` ``:1322-1350``. Training is
    not a deliverable producer, but §4 names its argv as a Stage-A
    compatibility surface: it carries the same ``--dataset_profile_json``
    transport 05c consumes, so a re-plumbing mistake would show here first.
    """

    def _side_effect(*_args, **_kwargs):
        os.makedirs(sandbox.dirs["models"], exist_ok=True)
        with open(os.path.join(sandbox.dirs["models"], f"_OK_{EXP_ID}"), "wb"):
            pass
        return _mock_result(), None

    mock_run.side_effect = _side_effect

    sandbox.execute_training(EXP_ID, RUN_NAME, MODEL_TYPE, MODEL_CFG, TRAIN_CFG, LOSS_CFG)

    (cmd,), _ = mock_run.call_args
    assert _normalize(cmd, str(tmp_path)) == [
        "<PYTHON>",
        "execute_tools/train_engine_sandbox.py",
        "--model_cfg",
        "<WS>/configs/c0run/model_config_c0exp.json",
        "--train_cfg",
        "<WS>/configs/c0run/train_config_c0exp.json",
        "--loss_cfg",
        "<WS>/configs/c0run/loss_config_c0exp.json",
        "--dataset_profile_json",
        "<WS>/configs/c0run/dataset_profile_c0exp.json",
        "--exp_id",
        "c0exp",
        "--run_name",
        "c0run",
        "--sandbox_dir",
        "<WS>",
        "--file_index",
        "6",
        "--model_io_json",
        "<WS>/configs/c0run/model_io_c0exp.json",
    ]


# ---------------------------------------------------------------------------
# 2. Cleanup filesystem sets
# ---------------------------------------------------------------------------

# The tuner's exp-keyed glob — ml_hyperparameter_tune_agent.py:5548.
TUNER_CLEANUP_PATTERN = "abra_validation_denoised_*_{exp_id}_*.h5"
# The sandbox watchdog's fully-qualified glob — sandbox_executor.py:1767.
SANDBOX_CLEANUP_PATTERN = "abra_validation_denoised_{model_type}_{run_name}_{exp_id}_*.h5"

# Seeded workspace. Deliberately mixes this attempt's artifacts, ANOTHER
# attempt's artifacts, a raw validation input, a checkpoint and a non-.h5
# file, because "deletes the right files" and "deletes only those files" are
# different properties.
SEEDED_FILES: tuple[str, ...] = (
    "abra_validation_denoised_fcnet_c0run_c0exp_0000.h5",
    "abra_validation_denoised_fcnet_c0run_c0exp_0007.h5",
    "abra_validation_denoised_wavenet_otherrun_c0exp_0003.h5",
    "abra_validation_denoised_fcnet_c0run_otherexp_0000.h5",
    "abra_validation_0000.h5",
    "model_fcnet_c0exp_agent.pth",
    "abra_validation_denoised_fcnet_c0run_c0exp_0000.txt",
)


@pytest.fixture
def seeded_workspace(tmp_path):
    for name in SEEDED_FILES:
        (tmp_path / name).write_bytes(b"x")
    return tmp_path
