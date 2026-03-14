"""
Tests for workflows/model_exploration.py

All node calls are mocked — these tests validate:

  load_tuning_outputs:
    - Loads valid JSON files from the expected directory structure
    - Skips invalid JSON files with a warning
    - Raises FileNotFoundError when no outputs are found
    - Loads from multiple model types

  tuning_outputs_to_summary_groups:
    - Converts HyperparamTuningOutput to SummaryGroup
    - Preserves model_type, run_name, and records
    - Handles multiple outputs

  run_workflow:
    - Calls all 5 nodes in sequence
    - Protocols wire correct outputs between nodes
    - Fan-in: proposal passed to validate→tune protocol
    - Stops on validation failure (sys.exit)
    - Saves workflow summary JSON on success
    - Saves workflow summary JSON on validation failure
    - Returns HyperparamTuningOutput on success
"""
import json
import os
import pytest
from unittest.mock import MagicMock, patch, ANY

from agent.schemas.hyperparam_tuning import (
    HyperparamTuningInput,
    HyperparamTuningOutput,
    ExpertAdvice,
)
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.proposal import ProposalOutput
from agent.schemas.implementor import ImplementorOutput
from agent.schemas.validator import ValidatorOutput
from agent.schemas.storage import StorageConfig, LocalStorageConfig

from workflows.model_exploration import (
    load_tuning_outputs,
    tuning_outputs_to_summary_groups,
    run_workflow,
)


# ---------------------------------------------------------------------------
# Fixtures — synthetic data
# ---------------------------------------------------------------------------

def _make_tuning_output(model_type="punet", run_name="v1", score=1.5):
    return HyperparamTuningOutput(
        run_name=run_name,
        model_type=model_type,
        file_index=6,
        status="completed",
        completed_rounds=3,
        total_attempts=3,
        best_exp_id=f"{model_type}_{run_name}_001",
        best_denoising_score=score,
        best_config={"model_config": {}, "train_config": {}, "loss_config": {}},
        all_records=[
            {
                "exp_id": f"{model_type}_{run_name}_001",
                "status": "success",
                "model_type": model_type,
                "timestamp": "2026-01-01 00:00:00",
                "file_index": 6,
                "params": {"model_config": {}, "train_config": {}, "loss_config": {}},
                "results": {"denoising_score": score},
                "denoising_score": score,
            },
        ],
        started_at="2026-01-01 00:00:00",
        finished_at="2026-01-01 01:00:00",
    )


def _make_interpretation_output():
    return InterpretationOutput(
        model_types=["punet"],
        model_descriptions={"punet": "A positional U-Net."},
        total_experiments=3,
        per_model_best={"punet": 1.5},
        per_model_worst={"punet": 1.2},
        best_denoising_score=1.5,
        worst_denoising_score=1.2,
        best_config={"model_config": {}},
        key_findings=["Finding 1"],
        bottlenecks=["Bottleneck 1"],
        take_home_message="Need a new architecture.",
    )


def _make_proposal_output():
    return ProposalOutput(
        model_name="gated_tcn",
        model_description="A gated TCN for signal denoising.",
        mathematical_definition="Dilated causal convolutions with gating.",
        motivation="Address limited receptive field.",
        expert_advice=ExpertAdvice(
            focus_areas=["receptive field"],
            constraints=["VRAM < 8 GB"],
        ),
        baseline_config={
            "model_config": {"n_layers": 4},
            "train_config": {"epochs": 10},
            "loss_config": {"loss_type": "focal"},
        },
    )


def _make_implementor_output():
    return ImplementorOutput(
        model_type="gated_tcn",
        model_file_path="/tmp/agent_generated/models/gated_tcn.py",
        test_file_path="/tmp/agent_generated/tests/test_gated_tcn.py",
        description_file_path="/tmp/agent_generated/models/gated_tcn/description.md",
        config_fields={"n_layers": 4, "hidden_dim": 64},
        model_description="A gated TCN for signal denoising.",
        mathematical_definition="Dilated causal convolutions with gating.",
    )


def _make_validator_output(passed=True):
    return ValidatorOutput(
        passed=passed,
        model_type="gated_tcn",
        plugin_registered=True,
        tests_passed=passed,
        description_valid=True,
        config_fields_valid=True,
        instantiation_passed=passed,
        gradient_check_passed=passed,
        llm_review_passed=passed,
        error_message=None if passed else "pytest failed: shape mismatch",
    )


def _make_tune_output():
    return _make_tuning_output(model_type="gated_tcn", run_name="explore_v1", score=1.8)


# ---------------------------------------------------------------------------
# load_tuning_outputs tests
# ---------------------------------------------------------------------------

class TestLoadTuningOutputs:

    def test_loads_valid_json(self, tmp_path):
        # Create expected directory structure
        agent_dir = tmp_path / "punet" / "v1" / "agent"
        agent_dir.mkdir(parents=True)
        output = _make_tuning_output()
        (agent_dir / "run_output_v1.json").write_text(output.model_dump_json(indent=2))

        results = load_tuning_outputs(str(tmp_path), ["punet"])
        assert len(results) == 1
        assert results[0].model_type == "punet"
        assert results[0].best_denoising_score == 1.5

    def test_skips_invalid_json(self, tmp_path):
        agent_dir = tmp_path / "punet" / "v1" / "agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "run_output_v1.json").write_text("not valid json {{{")

        with pytest.raises(FileNotFoundError):
            load_tuning_outputs(str(tmp_path), ["punet"])

    def test_raises_when_no_outputs_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="No HyperparamTuningOutput"):
            load_tuning_outputs(str(tmp_path), ["punet"])

    def test_loads_multiple_model_types(self, tmp_path):
        for model in ["punet", "wavenet"]:
            agent_dir = tmp_path / model / "v1" / "agent"
            agent_dir.mkdir(parents=True)
            output = _make_tuning_output(model_type=model)
            (agent_dir / "run_output_v1.json").write_text(output.model_dump_json(indent=2))

        results = load_tuning_outputs(str(tmp_path), ["punet", "wavenet"])
        assert len(results) == 2
        types = {r.model_type for r in results}
        assert types == {"punet", "wavenet"}

    def test_loads_multiple_runs_per_model(self, tmp_path):
        for run in ["v1", "v2"]:
            agent_dir = tmp_path / "punet" / run / "agent"
            agent_dir.mkdir(parents=True)
            output = _make_tuning_output(run_name=run)
            (agent_dir / f"run_output_{run}.json").write_text(output.model_dump_json(indent=2))

        results = load_tuning_outputs(str(tmp_path), ["punet"])
        assert len(results) == 2


# ---------------------------------------------------------------------------
# tuning_outputs_to_summary_groups tests
# ---------------------------------------------------------------------------

class TestTuningOutputsToSummaryGroups:

    def test_converts_single_output(self):
        output = _make_tuning_output()
        groups = tuning_outputs_to_summary_groups([output])
        assert len(groups) == 1
        assert groups[0].model_type == "punet"
        assert groups[0].run_name == "v1"
        assert len(groups[0].records) == 1

    def test_converts_multiple_outputs(self):
        outputs = [
            _make_tuning_output(model_type="punet"),
            _make_tuning_output(model_type="wavenet", score=1.2),
        ]
        groups = tuning_outputs_to_summary_groups(outputs)
        assert len(groups) == 2
        types = {g.model_type for g in groups}
        assert types == {"punet", "wavenet"}

    def test_preserves_records(self):
        output = _make_tuning_output()
        groups = tuning_outputs_to_summary_groups([output])
        record = groups[0].records[0]
        assert record["denoising_score"] == 1.5
        assert record["model_type"] == "punet"


# ---------------------------------------------------------------------------
# run_workflow tests
# ---------------------------------------------------------------------------

class TestRunWorkflow:

    @pytest.fixture
    def workflow_mocks(self, tmp_path):
        """Set up mocked nodes and fake data directory."""
        # Create fake tuning output on disk
        agent_dir = tmp_path / "data" / "punet" / "v1" / "agent"
        agent_dir.mkdir(parents=True)
        output = _make_tuning_output()
        (agent_dir / "run_output_v1.json").write_text(output.model_dump_json(indent=2))

        workspace = str(tmp_path / "workflow_output")

        with patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp, \
             patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose, \
             patch("workflows.model_exploration.MLModelImplementor") as MockImpl, \
             patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid, \
             patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune:

            MockInterp.return_value.run.return_value = _make_interpretation_output()
            MockPropose.return_value.run.return_value = _make_proposal_output()
            MockImpl.return_value.run.return_value = _make_implementor_output()
            MockValid.return_value.run.return_value = _make_validator_output(passed=True)
            MockTune.return_value.run.return_value = _make_tune_output()

            yield {
                "data_dir": str(tmp_path / "data"),
                "workspace": workspace,
                "interp": MockInterp,
                "propose": MockPropose,
                "impl": MockImpl,
                "valid": MockValid,
                "tune": MockTune,
            }

    def test_returns_tuning_output(self, workflow_mocks):
        result = run_workflow(
            data_dir=workflow_mocks["data_dir"],
            model_types=["punet"],
            workspace=workflow_mocks["workspace"],
            run_name="test_run",
            max_rounds=5,
        )
        assert isinstance(result, HyperparamTuningOutput)
        assert result.best_denoising_score == 1.8

    def test_all_five_nodes_called(self, workflow_mocks):
        run_workflow(
            data_dir=workflow_mocks["data_dir"],
            model_types=["punet"],
            workspace=workflow_mocks["workspace"],
            run_name="test_run",
        )
        workflow_mocks["interp"].return_value.run.assert_called_once()
        workflow_mocks["propose"].return_value.run.assert_called_once()
        workflow_mocks["impl"].return_value.run.assert_called_once()
        workflow_mocks["valid"].return_value.run.assert_called_once()
        workflow_mocks["tune"].return_value.run.assert_called_once()

    def test_nodes_receive_correct_input_types(self, workflow_mocks):
        run_workflow(
            data_dir=workflow_mocks["data_dir"],
            model_types=["punet"],
            workspace=workflow_mocks["workspace"],
            run_name="test_run",
        )
        from agent.schemas.interpretation import InterpretationInput
        from agent.schemas.proposal import ProposalInput
        from agent.schemas.implementor import ImplementorInput
        from agent.schemas.validator import ValidatorInput

        interp_arg = workflow_mocks["interp"].return_value.run.call_args[0][0]
        assert isinstance(interp_arg, InterpretationInput)

        propose_arg = workflow_mocks["propose"].return_value.run.call_args[0][0]
        assert isinstance(propose_arg, ProposalInput)

        impl_arg = workflow_mocks["impl"].return_value.run.call_args[0][0]
        assert isinstance(impl_arg, ImplementorInput)

        valid_arg = workflow_mocks["valid"].return_value.run.call_args[0][0]
        assert isinstance(valid_arg, ValidatorInput)

        tune_arg = workflow_mocks["tune"].return_value.run.call_args[0][0]
        assert isinstance(tune_arg, HyperparamTuningInput)

    def test_tune_receives_expert_advice_from_proposal(self, workflow_mocks):
        run_workflow(
            data_dir=workflow_mocks["data_dir"],
            model_types=["punet"],
            workspace=workflow_mocks["workspace"],
            run_name="test_run",
        )
        tune_arg = workflow_mocks["tune"].return_value.run.call_args[0][0]
        assert isinstance(tune_arg.expert_advice, ExpertAdvice)
        assert "receptive field" in tune_arg.expert_advice.focus_areas

    def test_workflow_summary_saved_on_success(self, workflow_mocks):
        run_workflow(
            data_dir=workflow_mocks["data_dir"],
            model_types=["punet"],
            workspace=workflow_mocks["workspace"],
            run_name="test_run",
        )
        summary_path = os.path.join(workflow_mocks["workspace"], "workflow_test_run.json")
        assert os.path.exists(summary_path)
        with open(summary_path) as f:
            summary = json.load(f)
        assert summary["status"] == "completed"
        assert summary["proposed_model"] == "gated_tcn"
        assert summary["best_score"] == 1.8

    def test_llm_provider_passed_to_nodes(self, workflow_mocks):
        run_workflow(
            data_dir=workflow_mocks["data_dir"],
            model_types=["punet"],
            workspace=workflow_mocks["workspace"],
            run_name="test_run",
            llm_provider="openai",
            llm_model_id="gpt-4o",
        )
        # Check that nodes were constructed with the right provider
        workflow_mocks["interp"].assert_called_with(provider="openai", model_id="gpt-4o")
        workflow_mocks["propose"].assert_called_with(provider="openai", model_id="gpt-4o")
        workflow_mocks["impl"].assert_called_with(provider="openai", model_id="gpt-4o")
        workflow_mocks["valid"].assert_called_with(provider="openai", model_id="gpt-4o")


class TestRunWorkflowValidationFailure:

    @pytest.fixture
    def workflow_fail_mocks(self, tmp_path):
        """Set up mocked nodes where validation fails."""
        agent_dir = tmp_path / "data" / "punet" / "v1" / "agent"
        agent_dir.mkdir(parents=True)
        output = _make_tuning_output()
        (agent_dir / "run_output_v1.json").write_text(output.model_dump_json(indent=2))

        workspace = str(tmp_path / "workflow_output")

        with patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp, \
             patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose, \
             patch("workflows.model_exploration.MLModelImplementor") as MockImpl, \
             patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid, \
             patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune:

            MockInterp.return_value.run.return_value = _make_interpretation_output()
            MockPropose.return_value.run.return_value = _make_proposal_output()
            MockImpl.return_value.run.return_value = _make_implementor_output()
            MockValid.return_value.run.return_value = _make_validator_output(passed=False)
            MockTune.return_value.run.return_value = _make_tune_output()

            yield {
                "data_dir": str(tmp_path / "data"),
                "workspace": workspace,
                "tune": MockTune,
            }

    def test_exits_on_validation_failure(self, workflow_fail_mocks):
        with pytest.raises(SystemExit):
            run_workflow(
                data_dir=workflow_fail_mocks["data_dir"],
                model_types=["punet"],
                workspace=workflow_fail_mocks["workspace"],
                run_name="test_fail",
            )

    def test_tune_not_called_on_validation_failure(self, workflow_fail_mocks):
        with pytest.raises(SystemExit):
            run_workflow(
                data_dir=workflow_fail_mocks["data_dir"],
                model_types=["punet"],
                workspace=workflow_fail_mocks["workspace"],
                run_name="test_fail",
            )
        workflow_fail_mocks["tune"].return_value.run.assert_not_called()

    def test_workflow_summary_saved_on_failure(self, workflow_fail_mocks):
        with pytest.raises(SystemExit):
            run_workflow(
                data_dir=workflow_fail_mocks["data_dir"],
                model_types=["punet"],
                workspace=workflow_fail_mocks["workspace"],
                run_name="test_fail",
            )
        summary_path = os.path.join(
            workflow_fail_mocks["workspace"], "workflow_test_fail.json"
        )
        assert os.path.exists(summary_path)
        with open(summary_path) as f:
            summary = json.load(f)
        assert summary["status"] == "failed_validation"
        assert summary["validation_passed"] is False
