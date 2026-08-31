"""
CLI tests for ``nodes/ml_hyperparameter_tune_agent.main()``.

The CLI now accepts plugin model_types when paired with
``--seed_plugin_path`` (docs/run_scoped_plugins.md, Phase 3/4). These tests
exercise three branches of the preflight check that lives in ``main()``:

  - Built-in model_type, no seed plugin → CLI proceeds.
  - Plugin model_type without seed plugin → CLI bails out with a clear
    actionable message before any sandbox setup.
  - Plugin model_type WITH seed plugin → CLI proceeds, and the seed path
    is threaded into ``HyperparamTuningInput.seed_plugin_path`` so the
    tuner's ``run()`` can stage it into the run-scoped plugin dir.

We patch ``HyperparamTuningAgent`` so no real run happens — these tests
are about argparse + preflight wiring, nothing more.
"""

import pathlib
import sys
import textwrap
from unittest.mock import MagicMock, patch

import pytest

from nodes.ml_hyperparameter_tune_agent import main

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]

_VALID_PLUGIN_BODY = '''
    """Minimal valid plugin fixture for the CLI test."""
    from pydantic import BaseModel

    PLUGIN_MODEL_TYPE = "attn_fcnet"

    class PLUGIN_CONFIG_CLASS(BaseModel):
        segmentation_size: int = 10000

    class PLUGIN_MODEL_CLASS:
        pass
'''


def _write_seed(tmp_path):
    path = tmp_path / "attn_fcnet_seed.py"
    path.write_text(textwrap.dedent(_VALID_PLUGIN_BODY))
    return str(path)


class TestSeedPluginPathCLI:
    def _argv_for(self, force_model: str, workspace, *extra: str):
        """Build a minimal sys.argv for the tuner CLI. ``--max_rounds 1`` and
        ``--workspace=tmp_path`` keep the run footprint trivial; the agent
        is patched anyway so these only matter for parser validation."""
        return [
            "ml_hyperparameter_tune_agent.py",
            "--force_model",
            force_model,
            "--max_rounds",
            "1",
            "--workspace",
            str(workspace),
            "--run_name",
            "cli_test",
            "--task_composition",
            str(REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml"),
            "--data_dir",
            str(workspace),
            *extra,
        ]

    @patch("nodes.ml_hyperparameter_tune_agent.HyperparamTuningAgent")
    def test_builtin_model_no_seed_proceeds(self, mock_agent_cls, tmp_path):
        """Built-in model_type (e.g. 'fcnet') needs no seed plugin —
        unchanged behavior."""
        mock_agent = MagicMock()
        mock_agent_cls.return_value = mock_agent

        with patch.object(sys, "argv", self._argv_for("fcnet", tmp_path)):
            main()

        mock_agent.run.assert_called_once()
        agent_input = mock_agent.run.call_args[0][0]
        assert agent_input.model_type == "fcnet"
        assert agent_input.seed_plugin_path is None

    @patch("nodes.ml_hyperparameter_tune_agent.HyperparamTuningAgent")
    def test_plugin_model_without_seed_errors(self, mock_agent_cls, tmp_path, capsys):
        """Plugin model_type without --seed_plugin_path must bail out at
        argparse time with a helpful message — NOT crash later in the
        planner with an obscure get_config_class error."""
        with patch.object(sys, "argv", self._argv_for("attn_fcnet", tmp_path)):
            with pytest.raises(SystemExit):
                main()

        err = capsys.readouterr().err
        assert "--force_model='attn_fcnet'" in err
        assert "--seed_plugin_path" in err
        # Agent must not have been constructed — preflight ran first.
        mock_agent_cls.assert_not_called()

    @patch("nodes.ml_hyperparameter_tune_agent.HyperparamTuningAgent")
    def test_plugin_model_with_seed_proceeds(self, mock_agent_cls, tmp_path):
        """Plugin model_type with a matching --seed_plugin_path must pass
        preflight AND the schema validator, and the seed path must reach
        the agent input verbatim so ``run()`` can stage it."""
        mock_agent = MagicMock()
        mock_agent_cls.return_value = mock_agent
        seed_path = _write_seed(tmp_path)

        argv = self._argv_for("attn_fcnet", tmp_path, "--seed_plugin_path", seed_path)
        with patch.object(sys, "argv", argv):
            main()

        mock_agent.run.assert_called_once()
        agent_input = mock_agent.run.call_args[0][0]
        assert agent_input.model_type == "attn_fcnet"
        assert agent_input.seed_plugin_path == seed_path

    @patch("nodes.ml_hyperparameter_tune_agent.HyperparamTuningAgent")
    def test_plugin_model_with_mismatched_seed_errors(self, mock_agent_cls, tmp_path):
        """Schema validator catches the case where the seed file declares
        a different PLUGIN_MODEL_TYPE — the CLI surfaces the Pydantic error
        rather than silently registering the seed under the wrong key."""
        # Seed says "attn_fcnet" but we pass --force_model some_other_type.
        # Preflight will pass (some_other_type is unknown but seed is set);
        # the schema validator catches the model_type/PLUGIN_MODEL_TYPE
        # mismatch.
        seed_path = _write_seed(tmp_path)
        argv = self._argv_for("some_other_type", tmp_path, "--seed_plugin_path", seed_path)
        with patch.object(sys, "argv", argv):
            with pytest.raises(Exception, match="PLUGIN_MODEL_TYPE"):
                main()
        mock_agent_cls.assert_not_called()


class TestTaskCompositionCLI:
    """``--task_composition`` — Step 12 / PR-12d D8a.

    Found and closed while writing D8a's readiness packet: the tuner's own
    standalone CLI (what ``--force_model`` runs through, deterministically —
    no LLM-chosen architecture) had no way to bind a task composition at
    all, so a G-12d Pets/DAVIS track could not launch composed AND
    reference-model-locked in one command. `run_chain.sh` already supports
    `--task_composition`; this mirrors the SAME pattern one launcher over.
    """

    def _argv_for(self, force_model: str, workspace, *extra: str):
        return [
            "ml_hyperparameter_tune_agent.py",
            "--force_model",
            force_model,
            "--max_rounds",
            "1",
            "--workspace",
            str(workspace),
            "--run_name",
            "cli_test",
            "--task_composition",
            str(REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml"),
            "--data_dir",
            str(workspace),
            *extra,
        ]

    @patch("nodes.ml_hyperparameter_tune_agent.HyperparamTuningAgent")
    def test_required_manifest_populates_the_ref(
        self, mock_agent_cls, tmp_path
    ):
        """The shared helper supplies the required Quickstart declaration."""
        mock_agent = MagicMock()
        mock_agent_cls.return_value = mock_agent

        with patch.object(sys, "argv", self._argv_for("fcnet", tmp_path)):
            main()

        agent_input = mock_agent.run.call_args[0][0]
        assert agent_input.task_composition_ref.task_data_path_id == "quickstart_tabular"

    @patch("nodes.ml_hyperparameter_tune_agent.HyperparamTuningAgent")
    def test_a_composed_launch_populates_the_ref(self, mock_agent_cls, tmp_path):
        mock_agent = MagicMock()
        mock_agent_cls.return_value = mock_agent
        manifest = str(REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml")

        argv = self._argv_for(
            "quickstart_reference_mlp",
            tmp_path,
            "--seed_plugin_path",
            str(REPO_ROOT / "examples" / "quickstart" / "plugins" / "quickstart_reference_mlp.py"),
            "--task_composition",
            manifest,
            "--data_dir",
            str(tmp_path),
        )
        with patch.object(sys, "argv", argv):
            main()

        agent_input = mock_agent.run.call_args[0][0]
        assert agent_input.task_composition_ref is not None
        assert agent_input.task_composition_ref.task_data_path_id == "quickstart_tabular"

    @patch("nodes.ml_hyperparameter_tune_agent.HyperparamTuningAgent")
    def test_the_binding_is_ACTIVE_during_run_and_unwinds_after(self, mock_agent_cls, tmp_path):
        """Reachability, not just presence: the CONTEXT is live exactly
        around `.run()`, not merely constructed and discarded."""
        from execute_tools.task_data_path import active_task_data_path

        seen = {}

        def _capture(_input):
            seen["during"] = active_task_data_path()
            return MagicMock(status="completed", completed_rounds=1)

        mock_agent = MagicMock()
        mock_agent.run.side_effect = _capture
        mock_agent_cls.return_value = mock_agent
        manifest = str(REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml")

        argv = self._argv_for(
            "quickstart_reference_mlp",
            tmp_path,
            "--seed_plugin_path",
            str(REPO_ROOT / "examples" / "quickstart" / "plugins" / "quickstart_reference_mlp.py"),
            "--task_composition",
            manifest,
            "--data_dir",
            str(tmp_path),
        )
        with patch.object(sys, "argv", argv):
            main()

        assert seen["during"] is not None
        assert seen["during"].task_data_path_id == "quickstart_tabular"
        assert active_task_data_path() is None, "the binding must unwind after main() returns"

    @patch("nodes.ml_hyperparameter_tune_agent.HyperparamTuningAgent")
    def test_an_unresolvable_manifest_fails_BEFORE_agent_construction(
        self, mock_agent_cls, tmp_path
    ):
        """CLI MISUSE, same posture as the seed-plugin preflight: fail
        loudly before any sandbox setup rather than mid-run."""
        from workflows.task_composition import TaskCompositionError

        argv = self._argv_for(
            "fcnet", tmp_path, "--task_composition", str(tmp_path / "no_such_manifest.yaml")
        )
        with patch.object(sys, "argv", argv):
            with pytest.raises(TaskCompositionError):
                main()
        mock_agent_cls.assert_not_called()

    @patch("nodes.ml_hyperparameter_tune_agent.HyperparamTuningAgent")
    def test_required_composition_enters_the_binding(self, mock_agent_cls, tmp_path):
        """The required declaration is active during the agent call."""
        from execute_tools.task_data_path import active_task_data_path

        seen = {}

        def _capture(_input):
            seen["during"] = active_task_data_path()
            return MagicMock(status="completed", completed_rounds=1)

        mock_agent = MagicMock()
        mock_agent.run.side_effect = _capture
        mock_agent_cls.return_value = mock_agent

        with patch.object(sys, "argv", self._argv_for("fcnet", tmp_path)):
            main()

        assert seen["during"].task_data_path_id == "quickstart_tabular"
