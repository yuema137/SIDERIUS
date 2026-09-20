"""Step 07a C2 — the eval-SampleSet transport (design §3.4, §3.4a half 1,
§3.10 signature parity) and rung B-07a-2 (validation-scope axis, L2, real
trainer component).

Each family names the defect only it catches:

  * the ONE declared argv delta — `--eval_sample_set_json <path>` emitted
    iff streaming AND an eval set is given, immediately after the
    `--sample_set_json` pair, with an explicitly bound synthetic profile/root;
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

import contextlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import torch
from torch.utils.data import DataLoader

import agent.skills.training_skill.wrapper as training_wrapper
import core.sandbox_executor as sandbox_module
import execute_tools.train_engine_sandbox as tes
from agent.schemas.custom_loss_contract import (
    EqualShapeApplicability,
    build_custom_loss_contract_snapshot,
)
from agent.schemas.model_io_contract import (
    Dimension,
    DtypeAdmissibility,
    TensorAxis,
    TensorContract,
)
from core.sandbox_executor import StubSandbox, TidmadSandbox
from core.training_execution_bindings import TrainingExecutionBindings
from execute_tools.dataset_config import DataScope, bind_dataset_profile
from execute_tools.scoring_utils import validate_sample_set
from execute_tools.task_data_path import EvalMaterializationParams
from execute_tools.training_history import TrainingHistory, interpret_training_results
from execute_tools.validation_execution import ValidationDeployment, bind_validation_deployment
from ml_models.loss_models_sandbox import get_criterion
from ml_models.models_format_sandbox import LossConfig
from ml_models.models_sandbox import MODEL_REGISTRY
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import _run_skill
from tests.helpers.recording_sandbox import RecordingSandbox
from tests.helpers.trainer_subprocess_binding import attempt_scopes, bound_trainer_task
from tests.helpers.two_family_profile import write_two_family_fixture

EXP_ID = "c2exp"
RUN_NAME = "c2run"
MODEL_TYPE = "fcnet"
MODEL_CFG = {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [100, 10]}
TRAIN_CFG = {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"}
LOSS_CFG = {"loss_type": "ce"}
TRAIN_SS = {0: [0, 1], 1: [2]}
EVAL_SS = {0: [3], 1: [0, 1]}

PYTHON = "<PYTHON>"
WORKSPACE = "<WS>"


def _loss_snapshot():
    tensor = TensorContract(
        axes=(
            TensorAxis(dimension=Dimension(symbolic="B")),
            TensorAxis(dimension=Dimension(fixed=2)),
        ),
        dtype=DtypeAdmissibility(admissible=("float32",)),
    )
    return build_custom_loss_contract_snapshot(
        tensor,
        tensor,
        EqualShapeApplicability(dtype=tensor.dtype, rank=2),
    )


def _normalize(cmd: list[str], workspace: str) -> list[str]:
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


def _mock_result(returncode: int = 0):
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = "done\n"
    mock.stderr = ""
    return mock


@pytest.fixture
def sandbox(tmp_path, synthetic_run_authorities, synthetic_physical_data_root):
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
    def test_custom_loss_contract_is_written_and_reaches_the_child_argv(self, mock_run, sandbox):
        snapshot = _loss_snapshot()
        mock_run.side_effect = _launch_ok(sandbox)
        sandbox.execute_training(
            EXP_ID,
            RUN_NAME,
            MODEL_TYPE,
            MODEL_CFG,
            TRAIN_CFG,
            LOSS_CFG,
            sample_set=TRAIN_SS,
            execution_bindings=TrainingExecutionBindings(expected_custom_loss_snapshot=snapshot),
        )

        (cmd,), _ = mock_run.call_args
        flag_index = cmd.index("--custom_loss_contract_json")
        contract_path = cmd[flag_index + 1]
        assert flag_index < cmd.index("--sample_set_json")
        assert json.loads(Path(contract_path).read_text(encoding="utf-8")) == snapshot.model_dump(
            mode="json"
        )

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_streaming_argv_transports_explicit_root_and_ordered_eval_pair(
        self, mock_run, sandbox, tmp_path
    ):
        """The complete ordered argv under the declared synthetic authorities.

        The 07a invariant remains: the eval pair immediately follows the
        training pair. Physical-root transport is now mandatory, and this
        profile deliberately has no optional ModelIO contract.
        """
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
            "--data_dir",
            sandbox.dirs["data"],
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
        """An omitted eval set must not become an empty child flag."""
        mock_run.side_effect = _launch_ok(sandbox)
        sandbox.execute_training(
            EXP_ID, RUN_NAME, MODEL_TYPE, MODEL_CFG, TRAIN_CFG, LOSS_CFG, sample_set=TRAIN_SS
        )
        (cmd,), _ = mock_run.call_args
        assert "--eval_sample_set_json" not in cmd

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_opaque_scope_transports_per_epoch_sampling_and_ordering(self, mock_run, tmp_path):
        """Opaque task scopes must not erase generic execution controls.

        This is the production failure shape: deleting any transport hop makes
        the captured child argv omit the requested portion, deterministic seed,
        or sequential file order even though the parent resolved all four.
        """
        data_root = tmp_path / "opaque_data"
        data_root.mkdir()
        fixture = write_two_family_fixture(data_root)
        with bound_trainer_task(tmp_path / "binding", fixture) as adapter:
            opaque_scope = {0: [0, 1], 1: [0, 1], 2: [0, 1]}
            scoped_sandbox = TidmadSandbox(
                run_name=RUN_NAME,
                workspace=str(tmp_path / "opaque_workspace"),
                progress_bar=False,
            )
            mock_run.side_effect = _launch_ok(scoped_sandbox)
            scoped_sandbox.execute_training(
                EXP_ID,
                RUN_NAME,
                MODEL_TYPE,
                MODEL_CFG,
                TRAIN_CFG,
                LOSS_CFG,
                train_portion=0.1,
                train_base_seed=73,
                order_strategy="sequential",
                file_order=[2, 0, 1],
                execution_bindings=TrainingExecutionBindings(
                    task_scopes=attempt_scopes(adapter, opaque_scope)
                ),
            )

        (cmd,), _ = mock_run.call_args
        assert "--sample_set_json" not in cmd
        assert cmd[cmd.index("--train_portion") + 1] == "0.1"
        assert cmd[cmd.index("--train_base_seed") + 1] == "73"
        assert cmd[cmd.index("--order_strategy") + 1] == "sequential"
        order_path = Path(cmd[cmd.index("--file_order_json") + 1])
        assert json.loads(order_path.read_text(encoding="utf-8")) == [2, 0, 1]

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_legacy_mode_never_emits_the_flag_even_when_an_eval_set_is_given(
        self, mock_run, sandbox
    ):
        """The legacy SampleSet emitter still requires the training leg.

        This argv-only witness does not claim the uncomposed child can run;
        the real child witness below supplies explicit task-owned scopes.
        """
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
    def test_an_eval_set_outside_the_data_scope_is_refused_before_launch(
        self, mock_run, tmp_path, synthetic_run_authorities, synthetic_physical_data_root
    ):
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
            "task_scopes": "resolved-task-scopes",
            "expected_custom_loss_snapshot": _loss_snapshot(),
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
        bindings = sb.training_kwargs[0]["execution_bindings"]
        assert bindings.task_scopes == "resolved-task-scopes"
        assert bindings.expected_custom_loss_snapshot == _loss_snapshot()

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
    def test_the_stub_accepts_and_scope_validates_the_eval_set(
        self, tmp_path, synthetic_run_authorities, synthetic_physical_data_root
    ):
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

    The parent binds an importable synthetic task manifest and physical root.
    Both scopes cross through production serialization; the subprocess argv
    is observed but never patched to add a missing input.
    """

    def test_real_opaque_trainer_materializes_requested_train_portion(self, tmp_path):
        """The child consumes, rather than merely receives, the transported portion."""
        (tmp_path / "data").mkdir()
        fixture = write_two_family_fixture(tmp_path / "data")
        training_scope = {0: [0, 1, 2, 3], 1: [0, 1, 2, 3], 2: [0, 1, 2, 3]}
        with bound_trainer_task(tmp_path, fixture) as adapter:
            scoped_sandbox = TidmadSandbox(
                run_name="opaque_portion",
                workspace=str(tmp_path / "ws"),
                progress_bar=False,
            )
            outcome = scoped_sandbox.execute_training(
                "opaque_portion",
                "opaque_portion",
                "wavenet",
                _wavenet_cfg(fixture.seg_size),
                {
                    "lr": 1e-3,
                    "epochs": 1,
                    "batch_size": 2,
                    "optimizer_type": "adam",
                    "device": "cpu",
                },
                {"loss_type": "focal"},
                train_portion=0.5,
                train_base_seed=19,
                runtime_policy={},
                execution_bindings=TrainingExecutionBindings(
                    task_scopes=attempt_scopes(adapter, training_scope)
                ),
            )

        assert outcome["status"] == "success", outcome.get("message")
        detail = outcome["runtime_verification"]["components"]["training"]["workload"]["detail"]
        assert detail["train_portion"] == 0.5
        assert detail["epoch0_samples"] == 12

    @pytest.mark.parametrize("deployed,wrapped", [(False, False), (True, False), (True, True)])
    def test_real_trainer_emits_r2_and_r3_over_the_validation_family(
        self, tmp_path, monkeypatch, deployed, wrapped
    ):
        (tmp_path / "data").mkdir()
        fx = write_two_family_fixture(tmp_path / "data")
        real_launch = sandbox_module._run_observed_subprocess
        launched: list[list[str]] = []

        def record_launch(cmd, **kwargs):
            launched.append(cmd)
            return real_launch(cmd, **kwargs)

        monkeypatch.setattr(sandbox_module, "_run_observed_subprocess", record_launch)
        train_ss = {0: [0, 1, 2, 3], 1: [0, 1, 2, 3], 2: [0, 1, 2, 3]}
        eval_ss = {0: [0, 1], 2: [1, 3]}  # a DISTINCT validation scope: 4 PSD × 2 = 8 rows
        marker = tmp_path / "validation-client-pids.txt"
        wrapper_marker = tmp_path / "launcher-pid.txt"
        wrapper = tmp_path / "training-launcher.py"
        wrapper.write_text(
            "import os,sys\n"
            "from pathlib import Path\n"
            f"Path({str(wrapper_marker)!r}).write_text(str(os.getpid()))\n"
            "os.execvpe(sys.argv[1],sys.argv[1:],os.environ)\n"
        )
        with contextlib.ExitStack() as stack:
            adapter = stack.enter_context(bound_trainer_task(tmp_path, fx))
            if deployed:
                stack.enter_context(
                    bind_validation_deployment(
                        ValidationDeployment(
                            factory=f"{type(adapter).__module__}:create_native",
                            settings={"rows": 8, "data_dir": fx.data_dir, "marker": str(marker)},
                            training_launcher=(sys.executable, str(wrapper)) if wrapped else (),
                        )
                    )
                )
            original_materialize = adapter.validation_dataset
            if deployed:

                def forbidden(*args):
                    raise AssertionError("parent read private validation data for row declaration")

                monkeypatch.setattr(adapter, "validation_dataset", forbidden)
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
                execution_bindings=TrainingExecutionBindings(
                    task_scopes=attempt_scopes(adapter, train_ss, eval_ss)
                ),
                train_base_seed=5,
            )
            monkeypatch.setattr(adapter, "validation_dataset", original_materialize)
        assert out["status"] == "success", out.get("message")
        assert launched and "--task_eval_scope_ref" in launched[0]
        assert "--task_manifest" in launched[0]
        assert ("--validation_executor_json" in launched[0]) == deployed
        if deployed:
            pids = marker.read_text().splitlines()
            assert len(pids) == 2 and len(set(pids)) == 1
            assert int(pids[0]) != os.getpid()
            if wrapped:
                assert wrapper_marker.read_text() == pids[0]
                assert launched[0][:2] == [sys.executable, str(wrapper)]
        assert launched[0][launched[0].index("--data_dir") + 1] == fx.data_dir

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
            ds = adapter.validation_dataset(
                adapter.scope(eval_ss, family=family),
                EvalMaterializationParams(data_dir=fx.data_dir),
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
        # here) leaves ~1e-7, so R3 must MATCH the validation family closely.
        r3 = h.validation_objective[-1]
        assert r3 == pytest.approx(val_ref, abs=1e-5)

        # ...and must be nearer the validation family than the training one.
        #
        # Step 12 / PR-12d, F-12d-35. This was `abs(r3 - train_ref) > 1e-4`,
        # justified as "the two FAMILIES differ by orders of magnitude more".
        # On CI they differed by 8.0e-06 and the test failed — while the
        # SEMANTICS were perfectly intact: r3 sat 1.5e-07 from val_ref and
        # 8.0e-06 from train_ref, i.e. R3 was computed over the validation
        # family, exactly as claimed. The absolute threshold was a claim about
        # how different two DATASETS happen to be, which no amount of correct
        # production code controls, and which is not what this test owns.
        #
        # A RELATIVE comparison owns the defect precisely: were R3 computed
        # over the training family, `r3` would coincide with `train_ref` and
        # this fails. It is strictly better targeted, not weaker — the failure
        # it catches is unchanged, and the environmental coupling is gone.
        assert abs(r3 - val_ref) < abs(r3 - train_ref), (
            f"R3 {r3!r} is nearer the TRAINING family {train_ref!r} than the "
            f"validation family {val_ref!r} — the validation pass ran over the "
            f"wrong file family"
        )
