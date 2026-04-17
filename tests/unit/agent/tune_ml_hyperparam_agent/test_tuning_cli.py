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
import sys
import textwrap
import pytest
from unittest.mock import patch, MagicMock

from nodes.ml_hyperparameter_tune_agent import main


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
            "--force_model", force_model,
            "--max_rounds", "1",
            "--workspace", str(workspace),
            "--run_name", "cli_test",
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

        argv = self._argv_for(
            "attn_fcnet", tmp_path, "--seed_plugin_path", seed_path
        )
        with patch.object(sys, "argv", argv):
            main()

        mock_agent.run.assert_called_once()
        agent_input = mock_agent.run.call_args[0][0]
        assert agent_input.model_type == "attn_fcnet"
        assert agent_input.seed_plugin_path == seed_path

    @patch("nodes.ml_hyperparameter_tune_agent.HyperparamTuningAgent")
    def test_plugin_model_with_mismatched_seed_errors(
        self, mock_agent_cls, tmp_path
    ):
        """Schema validator catches the case where the seed file declares
        a different PLUGIN_MODEL_TYPE — the CLI surfaces the Pydantic error
        rather than silently registering the seed under the wrong key."""
        # Seed says "attn_fcnet" but we pass --force_model some_other_type.
        # Preflight will pass (some_other_type is unknown but seed is set);
        # the schema validator catches the model_type/PLUGIN_MODEL_TYPE
        # mismatch.
        seed_path = _write_seed(tmp_path)
        argv = self._argv_for(
            "some_other_type", tmp_path, "--seed_plugin_path", seed_path
        )
        with patch.object(sys, "argv", argv):
            with pytest.raises(Exception, match="PLUGIN_MODEL_TYPE"):
                main()
        mock_agent_cls.assert_not_called()
