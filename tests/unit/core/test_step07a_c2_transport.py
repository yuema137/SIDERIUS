"""Step 07a C2 — the eval-SampleSet transport (design §3.4, §3.4a half 1,
§3.10 signature parity) and rung B-07a-2 (validation-scope axis, L2, real
trainer component).

Each family names the defect only it catches:

  * the ONE declared argv delta — `--eval_sample_set_json <path>` emitted
    iff streaming AND an eval set is given, immediately after the
    `--sample_set_json` pair; the LEGACY argv (05c golden) unchanged;
  * the written eval-set file has the SAME compact byte form as the train
    set's and is `validate_sample_set`-clean;
  * an eval set violating DataScope → the executor's existing scope
    refusal (never launched);
  * the wrapper FORWARDS `eval_sample_set` (reachability through the
    tuner's `_run_skill`), and the delete-the-hop mutation (a wrapper that
    drops it) is observable at the executor as `None` — half 1 of §3.4a
    (half 2, `error_training` at the tuner, is C3's);
  * StubSandbox signature parity + scope validation of the eval set;
  * B-07a-2: the REAL trainer subprocess through the production
    `execute_training` (launch primitive un-mocked, CPU) on the synthetic
    3-file two-family contrast profile emits R2 + R3, R3 observed on the
    VALIDATION family — honestly labelled a contrast-profile rung, NOT
    Track B/C.
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
import torch
from torch.utils.data import DataLoader

import agent.skills.training_skill.wrapper as training_wrapper
import core.sandbox_executor as sandbox_module
import execute_tools.train_engine_sandbox as tes
from core.sandbox_executor import StubSandbox, TidmadSandbox
from execute_tools.dataset_config import DataScope, bind_dataset_profile
from execute_tools.scoring_utils import validate_sample_set
from execute_tools.training_history import TrainingHistory, interpret_training_results
from ml_models.loss_models_sandbox import get_criterion
from ml_models.models_format_sandbox import LossConfig
from ml_models.models_sandbox import MODEL_REGISTRY
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import _run_skill
from tests.helpers.recording_sandbox import RecordingSandbox
from tests.helpers.two_family_profile import write_two_family_fixture

EXP_ID = "c2exp"
RUN_NAME = "c2run"
MODEL_TYPE = "fcnet"
MODEL_CFG = {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [100, 10]}
TRAIN_CFG = {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"}
LOSS_CFG = {"loss_type": "ce"}
TRAIN_SS = {0: [0, 1], 1: [2]}
EVAL_SS = {0: [3], 1: [4, 5]}

PYTHON = "<PYTHON>"
WORKSPACE = "<WS>"


def _normalize(cmd: list[str], workspace: str) -> list[str]:
    root = os.path.abspath(workspace)
    return [PYTHON if tok == sys.executable else tok.replace(root, WORKSPACE) for tok in cmd]


def _mock_result(returncode: int = 0):
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = "done\n"
    mock.stderr = ""
    return mock


@pytest.fixture
def sandbox(tmp_path):
    return TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path), progress_bar=False)


def _launch_ok(sandbox):
    def _side_effect(*_args, **_kwargs):
        os.makedirs(sandbox.dirs["models"], exist_ok=True)
        with open(os.path.join(sandbox.dirs["models"], f"_OK_{EXP_ID}"), "wb"):
            pass
        return _mock_result(), None

    return _side_effect


# ---------------------------------------------------------------------------
# The ONE declared argv delta
# ---------------------------------------------------------------------------


class TestArgvDelta:
    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_streaming_argv_with_an_eval_set_is_the_pre_c2_list_plus_exactly_the_declared_pair(
        self, mock_run, sandbox, tmp_path
    ):
        """The COMPLETE ordered streaming argv (05c-style golden). The delta
        versus the pre-07a list is exactly `--eval_sample_set_json <path>`
        immediately after the `--sample_set_json` pair (design §3.4,
        Q-07a-7). Any other inserted, moved or dropped flag shows here."""
        mock_run.side_effect = _launch_ok(sandbox)
        sandbox.execute_training(
            EXP_ID,
            RUN_NAME,
            MODEL_TYPE,
            MODEL_CFG,
            TRAIN_CFG,
            LOSS_CFG,
            sample_set=TRAIN_SS,
            eval_sample_set=EVAL_SS,
            train_portion=0.5,
            train_base_seed=11,
        )
        (cmd,), _ = mock_run.call_args
        assert _normalize(cmd, str(tmp_path)) == [
            "<PYTHON>",
            "execute_tools/train_engine_sandbox.py",
            "--model_cfg",
            "<WS>/configs/c2run/model_config_c2exp.json",
            "--train_cfg",
            "<WS>/configs/c2run/train_config_c2exp.json",
            "--loss_cfg",
            "<WS>/configs/c2run/loss_config_c2exp.json",
            "--dataset_profile_json",
            "<WS>/configs/c2run/dataset_profile_c2exp.json",
            "--exp_id",
            "c2exp",
            "--run_name",
            "c2run",
            "--sandbox_dir",
            "<WS>",
            "--file_index",
            "6",
            "--model_io_json",
            "<WS>/configs/c2run/model_io_c2exp.json",
            "--sample_set_json",
            "<WS>/configs/c2run/train_sample_set_c2exp.json",
            "--eval_sample_set_json",
            "<WS>/configs/c2run/eval_sample_set_c2exp.json",  # THE delta
            "--train_portion",
            "0.5",
            "--train_base_seed",
            "11",
            "--runtime_observation_out",
            "<WS>/configs/c2run/runtime_verification_c2exp.json",
        ]

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_streaming_without_an_eval_set_emits_no_flag(self, mock_run, sandbox):
        """A caller predating the transport (no eval set) launches the exact
        pre-07a streaming argv — the flag is never emitted empty."""
        mock_run.side_effect = _launch_ok(sandbox)
        sandbox.execute_training(
            EXP_ID, RUN_NAME, MODEL_TYPE, MODEL_CFG, TRAIN_CFG, LOSS_CFG, sample_set=TRAIN_SS
        )
        (cmd,), _ = mock_run.call_args
        assert "--eval_sample_set_json" not in cmd

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_legacy_mode_never_emits_the_flag_even_when_an_eval_set_is_given(
        self, mock_run, sandbox
    ):
        """Legacy single-file mode has no validation scope; the 05c legacy
        golden (`test_c0_training_argv_ordered_golden`) stays byte-identical
        and this pins the documented edge: eval set without train set → no flag."""
        mock_run.side_effect = _launch_ok(sandbox)
        sandbox.execute_training(
            EXP_ID, RUN_NAME, MODEL_TYPE, MODEL_CFG, TRAIN_CFG, LOSS_CFG, eval_sample_set=EVAL_SS
        )
        (cmd,), _ = mock_run.call_args
        assert "--eval_sample_set_json" not in cmd and "--sample_set_json" not in cmd

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_the_written_eval_set_has_the_train_sets_byte_form_and_is_scope_clean(
        self, mock_run, sandbox
    ):
        """Byte-parity with the pinned train-set form (compact `json.dump`,
        no indent, no sort_keys) — the child re-ints keys numerically. A
        different serializer here would give the two sibling files two
        formats for one contract."""
        mock_run.side_effect = _launch_ok(sandbox)
        sandbox.execute_training(
            EXP_ID,
            RUN_NAME,
            MODEL_TYPE,
            MODEL_CFG,
            TRAIN_CFG,
            LOSS_CFG,
            sample_set=TRAIN_SS,
            eval_sample_set=EVAL_SS,
        )
        (cmd,), _ = mock_run.call_args
        train_path = cmd[cmd.index("--sample_set_json") + 1]
        eval_path = cmd[cmd.index("--eval_sample_set_json") + 1]
        train_bytes = open(train_path, "rb").read()
        eval_bytes = open(eval_path, "rb").read()
        assert eval_bytes == json.dumps(validate_sample_set(EVAL_SS)).encode()
        assert train_bytes == json.dumps(validate_sample_set(TRAIN_SS)).encode()
        assert eval_bytes != train_bytes  # the eval set is its own set, not a copy of the train set
        assert tes._load_eval_sample_set_arg(eval_path) == json.loads(
            eval_bytes
        )  # child accepts it

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_an_eval_set_outside_the_data_scope_is_refused_before_launch(self, mock_run, tmp_path):
        """The SAME rule as the train set: an eval set naming a file outside
        the run's DataScope is a scope violation — never launched, never
        silently trimmed."""
        scoped = TidmadSandbox(
            run_name=RUN_NAME,
            workspace=str(tmp_path),
            progress_bar=False,
            data_scope=DataScope(file_indices=[0, 1]),
        )
        mock_run.side_effect = _launch_ok(scoped)
        out = scoped.execute_training(
            EXP_ID,
            RUN_NAME,
            MODEL_TYPE,
            MODEL_CFG,
            TRAIN_CFG,
            LOSS_CFG,
            sample_set=TRAIN_SS,
            eval_sample_set={0: [1], 7: [0]},
        )
        assert out["status"] != "success"
        assert "scope" in json.dumps(out).lower()
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# Wrapper reachability + delete-the-hop mutation (half 1 of §3.4a)
# ---------------------------------------------------------------------------


class TestWrapperForwardsTheEvalSet:
    def _params(self):
        return {
            "exp_id": "e1",
            "run_name": "r1",
            "model_type": "wavenet",
            "model_config": {"model_type": "wavenet"},
            "train_config": {},
            "loss_config": {},
            "sample_set": {"0": [0]},
            "eval_sample_set": {"0": [1, 2]},
        }

    def test_the_production_wrapper_delivers_the_eval_set_to_the_executor(self, tmp_path):
        """Reachability through the tuner's own loader (`_run_skill`): the
        value the tuner puts on `active_params["eval_sample_set"]` arrives at
        `execute_training(eval_sample_set=...)`. Before 07a the wrapper
        enumerated its kwargs and DROPPED it (OD-S7-1)."""
        sb = RecordingSandbox(
            base_dir=str(tmp_path),
            canned={"execute_training": {"status": "success", "results": {"final_loss": 1.0}}},
        )
        _run_skill("training_skill", sb, **self._params())
        assert sb.training_kwargs[0]["eval_sample_set"] == {"0": [1, 2]}
        assert sb.training_kwargs[0]["sample_set"] == {"0": [0]}

    def test_delete_the_hop_a_wrapper_that_drops_the_kwarg_is_observable_as_none(
        self, tmp_path, monkeypatch
    ):
        """MUTATION half 1: re-introduce the pre-07a wrapper (kwarg not
        forwarded). The executor sees `eval_sample_set=None` — a training
        result WITHOUT R3 follows. Half 2 (C3): the tuner, which EXPECTED
        validation, records `error_training` rather than a quiet success."""

        def pre_07a_run_skill(sandbox, **kwargs):
            return sandbox.execute_training(
                exp_id=kwargs["exp_id"],
                run_name=kwargs["run_name"],
                model_type=kwargs["model_type"],
                m_cfg=kwargs["model_config"],
                t_cfg=kwargs["train_config"],
                l_cfg=kwargs["loss_config"],
                sample_set=kwargs.get("sample_set"),
            )

        monkeypatch.setattr(training_wrapper, "run_skill", pre_07a_run_skill)
        sb = RecordingSandbox(
            base_dir=str(tmp_path),
            canned={"execute_training": {"status": "success", "results": {"final_loss": 1.0}}},
        )
        _run_skill("training_skill", sb, **self._params())
        assert sb.training_kwargs[0].get("eval_sample_set") is None
        # ...and the boundary that EXPECTS validation refuses that result (C1 contract):
        with pytest.raises(Exception, match="EXPECTED"):
            interpret_training_results({"final_loss": 1.0}, expected_validation=True)


# ---------------------------------------------------------------------------
# StubSandbox parity
# ---------------------------------------------------------------------------


class TestStubSandboxParity:
    def test_the_stub_accepts_and_scope_validates_the_eval_set(self, tmp_path):
        stub = StubSandbox(
            run_name="s", workspace=str(tmp_path), data_scope=DataScope(file_indices=[0, 1])
        )
        ok = stub.execute_training(
            "e", "s", "wavenet", {}, {}, {}, sample_set={0: [0]}, eval_sample_set={1: [0]}
        )
        assert ok["status"] == "success"
        bad = stub.execute_training(
            "e", "s", "wavenet", {}, {}, {}, sample_set={0: [0]}, eval_sample_set={5: [0]}
        )
        assert bad["status"] != "success" and "scope" in json.dumps(bad).lower()


# ---------------------------------------------------------------------------
# Rung B-07a-2 — validation-scope axis (L2, real trainer component)
# ---------------------------------------------------------------------------


def _wavenet_cfg(seg_size: int) -> dict:
    return {
        "model_type": "wavenet",
        "segmentation_size": seg_size,
        "input_channels": 4,
        "residual_channels": 8,
        "gate_channels": 8,
        "skip_channels": 8,
        "kernel_size": 2,
        "num_blocks": 1,
    }


@pytest.mark.allow_real_subprocess
class TestRungB07a2ValidationScopeAxis:
    """Contrast-profile rung (NOT Track B/C): the REAL `train_engine_sandbox.py`
    subprocess, launched by the production `execute_training` (argv assembled
    by the executor; launch primitive un-mocked; CPU; seconds), reads the eval
    SampleSet from the VALIDATION family and emits R2 + R3.

    The only test seam: `--data_dir <fixture>` is appended to the executor's
    argv (a REAL child flag) because the child otherwise resolves the
    machine's TIDMAD directory — the fixture lives in `tmp_path`.
    """

    def test_real_trainer_emits_r2_and_r3_over_the_validation_family(self, tmp_path, monkeypatch):
        (tmp_path / "data").mkdir()
        fx = write_two_family_fixture(tmp_path / "data")
        real_launch = sandbox_module._run_observed_subprocess
        launched: list[list[str]] = []

        def launch_with_data_dir(cmd, **kwargs):
            cmd = [*cmd, "--data_dir", fx.data_dir]
            launched.append(cmd)
            return real_launch(cmd, **kwargs)

        monkeypatch.setattr(sandbox_module, "_run_observed_subprocess", launch_with_data_dir)
        train_ss = {0: [0, 1, 2, 3], 1: [0, 1, 2, 3], 2: [0, 1, 2, 3]}
        eval_ss = {0: [0, 1], 2: [1, 3]}  # a DISTINCT validation scope: 4 PSD × 2 = 8 rows
        with bind_dataset_profile(fx.profile):
            sb = TidmadSandbox(run_name="rung", workspace=str(tmp_path / "ws"), progress_bar=False)
            out = sb.execute_training(
                "b07a2",
                "rung",
                "wavenet",
                _wavenet_cfg(fx.seg_size),
                {
                    "lr": 1e-3,
                    "epochs": 2,
                    "batch_size": 2,
                    "optimizer_type": "adam",
                    "device": "cpu",
                },
                {"loss_type": "focal"},
                sample_set=train_ss,
                eval_sample_set=eval_ss,
                train_base_seed=5,
            )
        assert out["status"] == "success", out.get("message")
        assert launched and "--eval_sample_set_json" in launched[0]

        results = out["results"]
        res = interpret_training_results(results, expected_validation=True)
        h = res.history
        assert h is not None and h.validation_objective is not None
        assert len(h.train_objective) == len(h.validation_objective) == 2
        assert h.validation_requested_samples == h.validation_samples == 8
        assert h.comparability == "established"

        # R3 was observed on the VALIDATION family: recompute the last epoch's
        # R3 on the saved model over the validation family (== to 1e-9) and
        # over the training family with the same indices (≠).
        state = torch.load(os.path.join(sb.dirs["models"], "model_wavenet_b07a2_agent.pth"))
        model = MODEL_REGISTRY["wavenet"](
            tes.get_config_class("wavenet")(**_wavenet_cfg(fx.seg_size))
        )
        model.load_state_dict(state)
        model.eval()
        criterion = get_criterion(LossConfig(loss_type="focal"), None)

        def _mean_over(family: str) -> float:
            with bind_dataset_profile(fx.profile):
                ds = tes.TIDMADEpochDataset(
                    fx.data_dir,
                    {str(k): v for k, v in eval_ss.items()},
                    fx.seg_size,
                    train_portion=None,
                    profile=fx.profile,
                    file_family=family,  # type: ignore[arg-type]
                )
            vals = []
            with torch.no_grad():
                for x, y in DataLoader(ds, batch_size=1, shuffle=False):
                    vals.append(criterion(model(x.to(torch.long)), y.to(torch.long)).item())
            return sum(vals) / len(vals)

        val_ref, train_ref = _mean_over("validation"), _mean_over("training")
        print(
            f"[B-07a-2] r3={h.validation_objective[-1]!r} val_ref={val_ref!r} train_ref={train_ref!r}"
        )
        # Cross-process float32 accumulation (batch 2 in the child vs batch 1
        # here) leaves ~1e-7; the two FAMILIES differ by orders of magnitude more.
        assert h.validation_objective[-1] == pytest.approx(val_ref, abs=1e-5)
        assert abs(h.validation_objective[-1] - train_ref) > 1e-4
