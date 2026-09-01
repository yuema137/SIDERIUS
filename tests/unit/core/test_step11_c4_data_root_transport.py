"""Step 11 C4 — the physical data root becomes a transported run binding.

The gap, from the frozen design's §3.1 table: of the values a composed run
resolves, the **physical data root never crossed the argv boundary**. The
training and inference argv carried no ``--data_dir`` and the scoring argv
carried no ``--raw_data_dir``, so all three children fell back to the
module-level ``TIDMAD_DATA_DIR`` resolved AT IMPORT. A composed run read
TIDMAD's data whatever it had declared, and looked entirely normal doing
it — which is why the whole spawn surface has only ever been executed by
TIDMAD.

Three properties are owned here.

**R-11-1 — legacy argv is byte-identical.** The transport follows the
``--task_data_path_id`` precedent: emitted ONLY when a root is bound. An
un-composed run's command line is unchanged, which the C0 baseline
asserts independently.

**R-11-7 — the root is provenance, never semantics.** It is a host path.
It is deliberately not on ``RunTaskComposition`` and cannot reach the
semantic fingerprint, because two checkouts of the same task package at
different paths are the same scientific run.

**R-11-8 — a composed run fails closed.** Missing, empty, placeholder or
not-a-directory refuses at the BINDING edge, before an LLM call or a GPU
minute. The import-time fallback is NOT removed (removing it breaks CI
collection repo-wide); what changes is that the composed path no longer
DEPENDS on it.
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, mock_open, patch

import pytest

from core.sandbox_executor import TidmadSandbox
from execute_tools.data_paths import (
    DatasetDirectoryUnavailable,
    active_physical_data_root,
    bind_physical_data_root,
    resolve_physical_data_root,
)
from execute_tools.dataset_config import bind_dataset_profile
from tests.helpers.two_family_profile import make_two_family_profile

MODEL_CFG = {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [100, 10]}
TRAIN_CFG = {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"}
LOSS_CFG = {"loss_type": "ce"}
EXP_ID = "c4_exp"
RUN_NAME = "c4_run"
PROFILE = make_two_family_profile(
    num_files=1,
    psd_segment_length=10_000,
    segments_per_file=2,
)


def _flag_value(cmd: list[str], flag: str) -> str | None:
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


# ----------------------------------------------------------------------
# The binding itself
# ----------------------------------------------------------------------


class TestTheRunScopedBinding:
    def test_unbound_refuses_instead_of_selecting_a_task(self):
        assert active_physical_data_root() is None
        with pytest.raises(DatasetDirectoryUnavailable):
            resolve_physical_data_root()

    def test_binding_makes_the_root_active(self, tmp_path):
        root = tmp_path / "data"
        root.mkdir()
        with bind_physical_data_root(str(root)) as bound:
            assert bound == str(root)
            assert active_physical_data_root() == str(root)
            assert resolve_physical_data_root() == str(root)

    def test_the_binding_is_reset_on_exit(self, tmp_path):
        root = tmp_path / "data"
        root.mkdir()
        with bind_physical_data_root(str(root)):
            pass
        assert active_physical_data_root() is None

    def test_the_binding_is_reset_on_an_exception(self, tmp_path):
        """Nested and sequential runs in one process must never observe
        each other's root — the same leak invariant the composition
        bindings carry.
        """
        root = tmp_path / "data"
        root.mkdir()
        with pytest.raises(RuntimeError), bind_physical_data_root(str(root)):
            raise RuntimeError("boom")
        assert active_physical_data_root() is None

    @pytest.mark.parametrize("bad", ["", "/nonexistent/step11/c4"])
    def test_an_unusable_root_refuses_at_the_binding_edge(self, bad):
        with pytest.raises(DatasetDirectoryUnavailable):
            with bind_physical_data_root(bad, purpose="a c4 test"):
                pass

    def test_a_file_is_not_a_directory(self, tmp_path):
        f = tmp_path / "not_a_dir"
        f.write_text("x")
        with pytest.raises(DatasetDirectoryUnavailable):
            with bind_physical_data_root(str(f)):
                pass

    def test_a_refused_binding_leaves_nothing_bound(self, tmp_path):
        """Fail-closed must not leave a half-bound run behind."""
        with pytest.raises(DatasetDirectoryUnavailable):
            with bind_physical_data_root("/nonexistent/step11/c4"):
                pass
        assert active_physical_data_root() is None


# ----------------------------------------------------------------------
# Argv transport
# ----------------------------------------------------------------------


@pytest.fixture
def sandbox(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    with bind_physical_data_root(str(root)):
        return TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path / "ws"), progress_bar=False)


@pytest.fixture(autouse=True)
def _bind_synthetic_task_config():
    from workflows.task_config import bind_task_config

    values = {
        "task_description": "Synthetic transport fixture.",
        "forward_contract": {},
    }
    with bind_task_config(values), bind_dataset_profile(PROFILE):
        yield


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


def _run_inference(sandbox, mock_run):
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
    return mock_run.call_args[0][0]


def _run_scoring(sandbox, mock_run):
    result = MagicMock()
    result.returncode = 0
    result.stdout = "done\n"
    result.stderr = ""
    mock_run.return_value = result
    with patch("builtins.open", mock_open(read_data=json.dumps({"denoising_score": 0.9}))):
        with patch("os.path.exists", return_value=True):
            with patch("os.remove"):
                sandbox.execute_scoring(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
    return mock_run.call_args[0][0]


class TestTheRootReachesEveryChild:
    """The transport, asserted at the real argv the parent hands the seam."""

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_training_carries_the_bound_root(self, mock_run, tmp_path):
        root = tmp_path / "declared"
        root.mkdir()
        with bind_physical_data_root(str(root)):
            sb = TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path / "ws"))
            mock_run.side_effect = _train_success(sb, EXP_ID)
            sb.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        assert _flag_value(mock_run.call_args[0][0], "--data_dir") == str(root)

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_inference_carries_the_bound_root(self, mock_run, tmp_path):
        root = tmp_path / "declared"
        root.mkdir()
        with bind_physical_data_root(str(root)):
            sb = TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path / "ws"))
            cmd = _run_inference(sb, mock_run)
        assert _flag_value(cmd, "--data_dir") == str(root)

    @patch("core.sandbox_executor.subprocess.run")
    def test_scoring_carries_the_root_as_raw_data_dir(self, mock_run, tmp_path):
        """The load-bearing distinction. The scoring child's `--data_dir` is
        the DELIVERABLE directory — the parent passes `self.base_dir` there —
        so its dataset root is `--raw_data_dir`. Conflating them would point
        the scorer's raw-baseline read at the sandbox.
        """
        root = tmp_path / "declared"
        root.mkdir()
        with bind_physical_data_root(str(root)):
            sb = TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path / "ws"))
            cmd = _run_scoring(sb, mock_run)
        assert _flag_value(cmd, "--raw_data_dir") == str(root)
        assert _flag_value(cmd, "--data_dir") == sb.base_dir
        assert _flag_value(cmd, "--data_dir") != str(root)

    def test_the_sandbox_data_dir_follows_the_binding(self, tmp_path):
        root = tmp_path / "declared"
        root.mkdir()
        with bind_physical_data_root(str(root)):
            sb = TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path / "ws"))
            assert sb.dirs["data"] == str(root)

    def test_the_sandbox_refuses_when_no_root_is_bound(self, tmp_path):
        with pytest.raises(DatasetDirectoryUnavailable):
            TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path / "ws"))


# ----------------------------------------------------------------------
# R-11-8 — a composed run may not lean on the legacy fallback
# ----------------------------------------------------------------------


class TestAComposedRunMustDeclareItsRoot:
    def test_binding_a_composition_without_a_root_refuses(self):
        from workflows.task_composition import (
            CompositionDataRootMissing,
            bind_run_task_composition,
        )

        composition = MagicMock()
        with pytest.raises(CompositionDataRootMissing):
            with bind_run_task_composition(composition):
                pass

    def test_an_uncomposed_run_is_refused(self):
        """A supported run cannot select a scientific task by omission."""
        from workflows.task_composition import TaskCompositionError, bind_run_task_composition

        with pytest.raises(TaskCompositionError, match="task composition is required"):
            with bind_run_task_composition(None):
                pass

    def test_the_refusal_names_the_operator_flag(self):
        from workflows.task_composition import (
            CompositionDataRootMissing,
            bind_run_task_composition,
        )

        with pytest.raises(CompositionDataRootMissing) as exc:
            with bind_run_task_composition(MagicMock(), physical_data_root=""):
                pass
        assert "--data_dir" in str(exc.value)

    def test_both_production_edges_pass_the_root(self):
        """Reachability. The parameter existing proves nothing if the two
        composition edges do not supply it — and there are exactly two.
        """
        import pathlib

        repo = pathlib.Path(__file__).resolve().parents[3]
        for rel in (
            "sdsc_submission_scripts/run_one_iteration.py",
            "workflows/model_exploration.py",
        ):
            src = (repo / rel).read_text(encoding="utf-8")
            assert "bind_run_task_composition(run_composition, physical_data_root=" in src, (
                f"{rel} binds a composition without declaring its data root"
            )


class TestTheRootIsProvenanceNotSemantics:
    """R-11-7: a host path must never reach the semantic fingerprint."""

    def test_the_composition_carries_no_data_root_field(self):
        from dataclasses import fields

        from workflows.task_composition import RunTaskComposition

        names = {f.name for f in fields(RunTaskComposition)}
        assert "physical_data_root" not in names
        assert "data_dir" not in names

    def test_the_fingerprint_helper_takes_no_root(self):
        """The fingerprint is computed from an explicit parameter list, so
        this asserts the root was not added to it.
        """
        import inspect

        from workflows import task_composition

        sig = inspect.signature(task_composition.compute_semantic_fingerprint)
        assert "physical_data_root" not in sig.parameters
        assert "data_dir" not in sig.parameters


class TestTheTunerReadsOneAuthority:
    """R-11-7's reconciliation of `HyperparamTuningInput.data_dir`."""

    def test_the_bound_root_wins_over_the_input_field(self):
        import pathlib

        repo = pathlib.Path(__file__).resolve().parents[3]
        src = (
            repo / "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py"
        ).read_text(encoding="utf-8")
        assert "_bound_data_root = active_physical_data_root()" in src
        assert (
            "time_data_dir = _bound_data_root if _bound_data_root is not None "
            "else agent_input.data_dir" in src
        )
