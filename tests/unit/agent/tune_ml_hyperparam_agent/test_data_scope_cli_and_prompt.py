"""
DS5c — tuner CLI flags for DataScope/HealthGate + planner-prompt disclosure.

CLI tests mirror test_tuning_cli.py: patch HyperparamTuningAgent so nothing
runs; assert argparse → HyperparamTuningInput wiring only. Prompt tests
exercise _format_fixed_params_block directly (pure function).
See docs/design/enable_partial_file_list.md (Commit DS5c).
"""

from __future__ import annotations

import sys
from typing import ClassVar
from unittest.mock import MagicMock, patch

import pytest

from agent.prompts import _format_fixed_params_block
from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from execute_tools.dataset_config import DataScope
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent, main


def _argv(workspace, *extra: str):
    return [
        "ml_hyperparameter_tune_agent.py",
        "--force_model",
        "fcnet",
        "--max_rounds",
        "1",
        "--workspace",
        str(workspace),
        "--run_name",
        "ds5c_cli_test",
        *extra,
    ]


class TestDataScopeCLI:
    @patch("nodes.ml_hyperparameter_tune_agent.HyperparamTuningAgent")
    def test_defaults_full_scope_gates_enabled(self, mock_agent_cls, tmp_path):
        mock_agent_cls.return_value = MagicMock()
        with patch.object(sys, "argv", _argv(tmp_path)):
            main()
        inp = mock_agent_cls.return_value.run.call_args[0][0]
        assert inp.data_scope == DataScope.default()
        assert inp.health_gate_enabled is True
        assert inp.health_gate_files is None

    @patch("nodes.ml_hyperparameter_tune_agent.HyperparamTuningAgent")
    def test_range_shorthand_round_trip(self, mock_agent_cls, tmp_path):
        mock_agent_cls.return_value = MagicMock()
        argv = _argv(tmp_path, "--data_scope", "4-9", "--health_gate_files", "4,7,9")
        with patch.object(sys, "argv", argv):
            main()
        inp = mock_agent_cls.return_value.run.call_args[0][0]
        assert inp.data_scope.file_indices == [4, 5, 6, 7, 8, 9]
        assert inp.health_gate_files == [4, 7, 9]

    @patch("nodes.ml_hyperparameter_tune_agent.HyperparamTuningAgent")
    def test_mixed_spec_and_disable_flag(self, mock_agent_cls, tmp_path):
        mock_agent_cls.return_value = MagicMock()
        argv = _argv(tmp_path, "--data_scope", "0-3,7", "--no-health_gate_enabled")
        with patch.object(sys, "argv", argv):
            main()
        inp = mock_agent_cls.return_value.run.call_args[0][0]
        assert inp.data_scope.file_indices == [0, 1, 2, 3, 7]
        assert inp.health_gate_enabled is False
        assert inp.health_gate_files is None

    def test_malformed_scope_spec_fails_before_agent(self, tmp_path):
        with patch.object(sys, "argv", _argv(tmp_path, "--data_scope", "4-x")):
            with pytest.raises(ValueError, match="malformed range"):
                main()


class TestFixedParamsBlockScopeDisclosure:
    SCOPE: ClassVar[list[int]] = [4, 5, 6, 7, 8, 9]

    def test_full_scope_unchanged_empty(self):
        assert _format_fixed_params_block(None, None, None) == ""

    def test_full_scope_with_overrides_has_no_scope_lines(self):
        block = _format_fixed_params_block({"trial_portion": 0.05}, None, None)
        assert "data_scope" not in block
        assert "trial_strategy + target_files" in block  # legacy control surface

    def test_partial_scope_alone_renders_block(self):
        block = _format_fixed_params_block(None, None, self.SCOPE)
        assert "SYSTEM-FIXED PARAMETERS" in block
        assert f"files {self.SCOPE}" in block
        assert "ONLY files this run may access" in block

    def test_partial_scope_forces_snapshot_lines(self):
        block = _format_fixed_params_block(None, None, self.SCOPE)
        assert block.count("forced under a partial data_scope") == 2
        assert "normalized to snapshot" in block

    def test_partial_scope_control_surface_excludes_target(self):
        block = _format_fixed_params_block(None, None, self.SCOPE)
        assert "trial_strategy + target_files" not in block
        assert "target_files is unavailable this run" in block
        assert "train_validation_align" in block

    def test_combined_with_overrides_and_epochs(self):
        block = _format_fixed_params_block({"is_trial": True}, 3, self.SCOPE)
        assert "is_trial" in block
        assert "epochs (cap)" in block
        assert f"files {self.SCOPE}" in block


class TestStartupFailsBeforeRound1:
    """DS5 verification checklist: startup failure paths fail BEFORE round 1
    (no LLM bridge constructed, no plan call)."""

    def _input(self, tmp_path, **kwargs):
        return HyperparamTuningInput(
            model_type="punet",
            max_rounds=1,
            is_trial=True,
            expert_advice="",
            llm_provider="gemini",
            llm_model_id="test-model",
            storage=StorageConfig(
                backend="local",
                local=LocalStorageConfig(workspace=str(tmp_path), run_name="ds5_startup"),
            ),
            progress_bar=False,
            **kwargs,
        )

    @patch("nodes.ml_hyperparameter_tune_agent.LLMBridge")
    def test_partial_scope_without_gate_files(self, mock_bridge_cls, tmp_path):
        inp = self._input(tmp_path, data_scope=DataScope(file_indices=[4, 5, 6]))
        with pytest.raises(ValueError, match="health_gate_files"):
            HyperparamTuningAgent().run(inp)
        mock_bridge_cls.assert_not_called()

    @patch("nodes.ml_hyperparameter_tune_agent.LLMBridge")
    def test_out_of_scope_gate_files(self, mock_bridge_cls, tmp_path):
        inp = self._input(
            tmp_path,
            data_scope=DataScope(file_indices=[4, 5, 6]),
            health_gate_files=[4, 10],
        )
        with pytest.raises(ValueError, match="DataScope"):
            HyperparamTuningAgent().run(inp)
        mock_bridge_cls.assert_not_called()
