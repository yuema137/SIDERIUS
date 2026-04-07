"""
Tests for workflows/model_exploration.py

All node calls are mocked — these tests validate:

  load_tuning_outputs:
    - Loads valid JSON files from the expected directory structure
    - Skips invalid JSON files with a warning
    - Raises FileNotFoundError when no outputs are found
    - Loads from multiple model types
    - Loads multiple runs per model

  tuning_outputs_to_summary_groups:
    - Converts HyperparamTuningOutput to SummaryGroup
    - Preserves model_type, run_name, and records
    - Handles multiple outputs

  run_workflow (single iteration):
    - Calls all 5 nodes in sequence
    - Protocols wire correct input types
    - Fan-in: proposal expert_advice reaches tune agent
    - Saves workflow summary JSON
    - Returns list with one HyperparamTuningOutput

  run_workflow (multi-iteration):
    - Accumulates summary groups across iterations
    - Stops at max_iterations
    - Stops early on target_score

  run_workflow (validation failure + retry):
    - Retries propose→implement→validate on failure
    - Feeds previous_failures to proposal agent
    - Stops workflow if max_proposal_attempts exhausted

  run_workflow (storage layout):
    - Creates iteration_NNN directories
    - Creates attempt_NNN directories within iterations
    - Creates tuning/ directory within iterations
"""
import json
import os
import pytest
from unittest.mock import MagicMock, patch, call

from agent.schemas.hyperparam_tuning import (
    HyperparamTuningInput,
    HyperparamTuningOutput,
    ExpertAdvice,
)
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.proposal import ProposalOutput
from agent.schemas.implementor import ImplementorOutput
from agent.schemas.validator import ValidatorOutput

from workflows.model_exploration import (
    load_tuning_outputs,
    load_tuning_outputs_from_paths,
    tuning_outputs_to_summaries,
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


_proposal_counter = 0


def _make_proposal_output(model_name="gated_tcn"):
    return ProposalOutput(
        model_name=model_name,
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


def _make_implementor_output(model_type="gated_tcn"):
    return ImplementorOutput(
        model_type=model_type,
        model_file_path=f"/tmp/agent_generated/models/{model_type}.py",
        test_file_path=f"/tmp/agent_generated/tests/test_{model_type}.py",
        description_file_path=f"/tmp/agent_generated/models/{model_type}/description.md",
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


def _make_tune_output(model_type="gated_tcn", score=1.8):
    return _make_tuning_output(model_type=model_type, run_name="explore_v1", score=score)


def _write_tuning_output(tmp_path, model_type="punet", run="v1", score=1.5):
    """Write a fake tuning output to the expected directory structure."""
    agent_dir = tmp_path / "data" / model_type / run / "agent"
    agent_dir.mkdir(parents=True)
    output = _make_tuning_output(model_type=model_type, run_name=run, score=score)
    (agent_dir / f"run_output_{run}_agent.json").write_text(output.model_dump_json(indent=2))


# ---------------------------------------------------------------------------
# load_tuning_outputs tests
# ---------------------------------------------------------------------------

class TestLoadTuningOutputs:

    def test_loads_valid_json(self, tmp_path):
        _write_tuning_output(tmp_path, "punet")
        results = load_tuning_outputs(str(tmp_path / "data"), ["punet"], "v1")
        assert len(results) == 1
        assert results[0].model_type == "punet"

    def test_raises_on_invalid_json(self, tmp_path):
        agent_dir = tmp_path / "data" / "punet" / "v1" / "agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "run_output_v1_agent.json").write_text("not valid json {{{")
        with pytest.raises(FileNotFoundError):
            load_tuning_outputs(str(tmp_path / "data"), ["punet"], "v1")

    def test_raises_when_no_outputs_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Missing or invalid source files"):
            load_tuning_outputs(str(tmp_path / "data"), ["punet"], "v1")

    def test_loads_multiple_model_types(self, tmp_path):
        _write_tuning_output(tmp_path, "punet")
        _write_tuning_output(tmp_path, "wavenet")
        results = load_tuning_outputs(str(tmp_path / "data"), ["punet", "wavenet"], "v1")
        assert len(results) == 2
        assert {r.model_type for r in results} == {"punet", "wavenet"}

    def test_raises_when_model_missing(self, tmp_path):
        _write_tuning_output(tmp_path, "punet")
        with pytest.raises(FileNotFoundError, match="wavenet"):
            load_tuning_outputs(str(tmp_path / "data"), ["punet", "wavenet"], "v1")


class TestLoadTuningOutputsFromPaths:
    """Tests for the new explicit-path loader (used for per-iteration Slurm runs)."""

    def test_loads_single_path(self, tmp_path):
        _write_tuning_output(tmp_path, "punet")
        path = str(tmp_path / "data" / "punet" / "v1" / "agent" / "run_output_v1_agent.json")
        results = load_tuning_outputs_from_paths([path])
        assert len(results) == 1
        assert results[0].model_type == "punet"

    def test_loads_heterogeneous_paths(self, tmp_path):
        """Mix of seed paths and (simulated) iteration output paths from different dirs."""
        _write_tuning_output(tmp_path, "punet")
        _write_tuning_output(tmp_path, "wavenet")
        # Simulate an iteration output at a non-standard location
        iter_dir = tmp_path / "exploration" / "iter_001" / "model_x"
        iter_dir.mkdir(parents=True)
        # Reuse the punet output as the "iter_001" output
        import shutil
        seed_punet = tmp_path / "data" / "punet" / "v1" / "agent" / "run_output_v1_agent.json"
        iter_output = iter_dir / "run_output_iter_001.json"
        shutil.copy(seed_punet, iter_output)

        paths = [
            str(seed_punet),
            str(tmp_path / "data" / "wavenet" / "v1" / "agent" / "run_output_v1_agent.json"),
            str(iter_output),
        ]
        results = load_tuning_outputs_from_paths(paths)
        assert len(results) == 3

    def test_raises_on_missing_path(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="not found"):
            load_tuning_outputs_from_paths([str(tmp_path / "nonexistent.json")])

    def test_raises_on_invalid_json(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json {{{")
        with pytest.raises(FileNotFoundError, match="invalid"):
            load_tuning_outputs_from_paths([str(bad_file)])

    def test_legacy_api_uses_new_function_internally(self, tmp_path):
        """load_tuning_outputs() should produce identical output to from_paths()."""
        _write_tuning_output(tmp_path, "punet")
        path = str(tmp_path / "data" / "punet" / "v1" / "agent" / "run_output_v1_agent.json")
        legacy_result = load_tuning_outputs(str(tmp_path / "data"), ["punet"], "v1")
        new_result = load_tuning_outputs_from_paths([path])
        assert len(legacy_result) == len(new_result)
        assert legacy_result[0].model_type == new_result[0].model_type


# ---------------------------------------------------------------------------
# tuning_outputs_to_summaries tests
# ---------------------------------------------------------------------------

class TestTuningOutputsToSummaries:

    def test_converts_single_output(self):
        summaries = tuning_outputs_to_summaries([_make_tuning_output()])
        assert len(summaries) == 1
        assert summaries[0].model_type == "punet"

    def test_converts_multiple_outputs(self):
        summaries = tuning_outputs_to_summaries([
            _make_tuning_output(model_type="punet"),
            _make_tuning_output(model_type="wavenet", score=1.2),
        ])
        assert len(summaries) == 2

    def test_preserves_best_score(self):
        summaries = tuning_outputs_to_summaries([_make_tuning_output()])
        assert summaries[0].best_denoising_score == 1.5

    def test_extracts_round_scores(self):
        summaries = tuning_outputs_to_summaries([_make_tuning_output()])
        assert len(summaries[0].round_scores) == 1
        assert summaries[0].round_scores[0] == 1.5


# ---------------------------------------------------------------------------
# run_workflow — shared mock fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def workflow_env(tmp_path):
    """Set up fake data dir and mocked nodes."""
    _write_tuning_output(tmp_path, "punet")
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


# ---------------------------------------------------------------------------
# run_workflow — single iteration tests
# ---------------------------------------------------------------------------

class TestRunWorkflowSingleIteration:

    def test_returns_list_with_one_output(self, workflow_env):
        results = run_workflow(
            data_dir=workflow_env["data_dir"],
            model_types=["punet"],
            source_run_name="v1",
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        assert len(results) == 1
        assert isinstance(results[0], HyperparamTuningOutput)

    def test_accepts_source_paths(self, workflow_env, tmp_path):
        """New API: pass explicit source_paths instead of data_dir+model_types+source_run_name."""
        path = str(tmp_path / "data" / "punet" / "v1" / "agent" / "run_output_v1_agent.json")
        results = run_workflow(
            source_paths=[path],
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        assert len(results) == 1
        assert isinstance(results[0], HyperparamTuningOutput)

    def test_raises_when_no_source_provided(self, workflow_env):
        """Must provide either source_paths OR (data_dir + model_types + source_run_name)."""
        with pytest.raises(ValueError, match="Must provide either source_paths"):
            run_workflow(
                workspace=workflow_env["workspace"],
                run_name="test_run",
            )

    def test_chained_iterations_via_source_paths(self, workflow_env, tmp_path):
        """
        Simulate two sequential Slurm jobs: iteration 1 from seed only,
        iteration 2 from seed + iteration 1's output. Verifies the
        per-iteration chaining logic that the orchestrator script depends on.
        """
        seed_path = str(tmp_path / "data" / "punet" / "v1" / "agent" / "run_output_v1_agent.json")
        workspace = workflow_env["workspace"]

        # --- Iteration 1: just the seed ---
        results_1 = run_workflow(
            source_paths=[seed_path],
            workspace=workspace,
            run_name="iter_001",
        )
        assert len(results_1) == 1
        # The interpretation agent should have received 1 summary (from the seed)
        interp_input_1 = workflow_env["interp"].return_value.run.call_args_list[0][0][0]
        assert len(interp_input_1.summaries) == 1
        assert interp_input_1.summaries[0].model_type == "punet"

        # --- Simulate iteration 1's output being available on disk ---
        # In real Slurm chaining, iteration 1 would write run_output_iter_001.json
        # at {workspace}/iter_001/{model_name}/. We fake that here.
        iter_1_model = results_1[0].model_type
        iter_1_output_dir = os.path.join(workspace, "iter_001", iter_1_model)
        os.makedirs(iter_1_output_dir, exist_ok=True)
        iter_1_output_path = os.path.join(iter_1_output_dir, "run_output_iter_001.json")
        # Write a minimal valid HyperparamTuningOutput JSON
        with open(iter_1_output_path, "w") as f:
            json.dump(results_1[0].model_dump(), f, default=str)

        # --- Iteration 2: seed + iteration 1's output ---
        results_2 = run_workflow(
            source_paths=[seed_path, iter_1_output_path],
            workspace=workspace,
            run_name="iter_002",
        )
        assert len(results_2) == 1
        # The interpretation agent should now have received 2 summaries
        # (call_args_list[1] = the call from iteration 2)
        interp_input_2 = workflow_env["interp"].return_value.run.call_args_list[1][0][0]
        assert len(interp_input_2.summaries) == 2, (
            f"Iteration 2 should see seed + iter_001 output (2 summaries), "
            f"got {len(interp_input_2.summaries)}"
        )

    def test_all_five_nodes_called(self, workflow_env):
        run_workflow(
            data_dir=workflow_env["data_dir"],
            model_types=["punet"],
            source_run_name="v1",
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        workflow_env["interp"].return_value.run.assert_called_once()
        workflow_env["propose"].return_value.run.assert_called_once()
        workflow_env["impl"].return_value.run.assert_called_once()
        workflow_env["valid"].return_value.run.assert_called_once()
        workflow_env["tune"].return_value.run.assert_called_once()

    def test_correct_input_types(self, workflow_env):
        from agent.schemas.interpretation import InterpretationInput
        from agent.schemas.proposal import ProposalInput
        from agent.schemas.implementor import ImplementorInput
        from agent.schemas.validator import ValidatorInput

        run_workflow(
            data_dir=workflow_env["data_dir"],
            model_types=["punet"],
            source_run_name="v1",
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        assert isinstance(
            workflow_env["interp"].return_value.run.call_args[0][0], InterpretationInput)
        assert isinstance(
            workflow_env["propose"].return_value.run.call_args[0][0], ProposalInput)
        assert isinstance(
            workflow_env["impl"].return_value.run.call_args[0][0], ImplementorInput)
        assert isinstance(
            workflow_env["valid"].return_value.run.call_args[0][0], ValidatorInput)
        assert isinstance(
            workflow_env["tune"].return_value.run.call_args[0][0], HyperparamTuningInput)

    def test_fan_in_expert_advice(self, workflow_env):
        run_workflow(
            data_dir=workflow_env["data_dir"],
            model_types=["punet"],
            source_run_name="v1",
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        tune_arg = workflow_env["tune"].return_value.run.call_args[0][0]
        assert isinstance(tune_arg.expert_advice, ExpertAdvice)
        assert "receptive field" in tune_arg.expert_advice.focus_areas

    def test_workflow_summary_saved(self, workflow_env):
        run_workflow(
            data_dir=workflow_env["data_dir"],
            model_types=["punet"],
            source_run_name="v1",
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        run_dir = os.path.join(workflow_env["workspace"], "test_run")
        summary_path = os.path.join(run_dir, "workflow_test_run.json")
        assert os.path.exists(summary_path)
        with open(summary_path) as f:
            summary = json.load(f)
        assert summary["status"] == "completed"
        assert summary["total_iterations"] == 1

    def test_iteration_directory_created(self, workflow_env):
        run_workflow(
            data_dir=workflow_env["data_dir"],
            model_types=["punet"],
            source_run_name="v1",
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        run_dir = os.path.join(workflow_env["workspace"], "test_run")
        iter_dir = os.path.join(run_dir, "iteration_001")
        assert os.path.isdir(iter_dir)
        # Attempt dir includes model name
        assert os.path.isdir(os.path.join(iter_dir, "attempt_001_gated_tcn"))
        # Tuning dir is named by the proposed model
        assert os.path.isdir(os.path.join(iter_dir, "gated_tcn"))


# ---------------------------------------------------------------------------
# run_workflow — multi-iteration tests
# ---------------------------------------------------------------------------

class TestRunWorkflowMultiIteration:

    def test_runs_multiple_iterations(self, workflow_env):
        # Each iteration needs a unique model name
        names = iter(["model_a", "model_b", "model_c"])
        workflow_env["propose"].return_value.run.side_effect = lambda inp: _make_proposal_output(next(names))
        workflow_env["tune"].return_value.run.side_effect = lambda inp: _make_tune_output(
            model_type=inp.model_type, score=1.6)

        results = run_workflow(
            data_dir=workflow_env["data_dir"],
            model_types=["punet"],
            source_run_name="v1",
            workspace=workflow_env["workspace"],
            run_name="test_run",
            max_iterations=3,
        )
        assert len(results) == 3

    def test_accumulates_summary_groups(self, workflow_env):
        names = iter(["model_a", "model_b"])
        workflow_env["propose"].return_value.run.side_effect = lambda inp: _make_proposal_output(next(names))
        workflow_env["tune"].return_value.run.side_effect = lambda inp: _make_tune_output(
            model_type=inp.model_type, score=1.6)

        run_workflow(
            data_dir=workflow_env["data_dir"],
            model_types=["punet"],
            source_run_name="v1",
            workspace=workflow_env["workspace"],
            run_name="test_run",
            max_iterations=2,
        )
        # On iteration 2, the interpretation should see more summaries
        interp_calls = workflow_env["interp"].return_value.run.call_args_list
        iter1_summaries = len(interp_calls[0][0][0].summaries)
        iter2_summaries = len(interp_calls[1][0][0].summaries)
        assert iter2_summaries > iter1_summaries

    def test_stops_on_target_score(self, workflow_env):
        names = iter(["model_a", "model_b", "model_c"])
        workflow_env["propose"].return_value.run.side_effect = lambda inp: _make_proposal_output(next(names))
        workflow_env["tune"].return_value.run.side_effect = lambda inp: _make_tune_output(
            model_type=inp.model_type, score=2.5)

        results = run_workflow(
            data_dir=workflow_env["data_dir"],
            model_types=["punet"],
            source_run_name="v1",
            workspace=workflow_env["workspace"],
            run_name="test_run",
            max_iterations=5,
            target_score=2.0,
        )
        # Should stop after first iteration since score 2.5 >= 2.0
        assert len(results) == 1


# ---------------------------------------------------------------------------
# run_workflow — validation failure + retry tests
# ---------------------------------------------------------------------------

class TestRunWorkflowValidationRetry:

    def test_retries_on_validation_failure(self, workflow_env):
        # First attempt fails, second passes
        workflow_env["valid"].return_value.run.side_effect = [
            _make_validator_output(passed=False),
            _make_validator_output(passed=True),
        ]
        results = run_workflow(
            data_dir=workflow_env["data_dir"],
            model_types=["punet"],
            source_run_name="v1",
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        assert len(results) == 1
        assert workflow_env["propose"].return_value.run.call_count == 2
        assert workflow_env["valid"].return_value.run.call_count == 2

    def test_feeds_previous_failures_to_proposal(self, workflow_env):
        workflow_env["valid"].return_value.run.side_effect = [
            _make_validator_output(passed=False),
            _make_validator_output(passed=True),
        ]
        run_workflow(
            data_dir=workflow_env["data_dir"],
            model_types=["punet"],
            source_run_name="v1",
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        # Second proposal call should have previous_failures
        second_call_input = workflow_env["propose"].return_value.run.call_args_list[1][0][0]
        assert len(second_call_input.previous_failures) == 1
        assert "shape mismatch" in second_call_input.previous_failures[0]

    def test_stops_after_max_proposal_attempts(self, workflow_env):
        workflow_env["valid"].return_value.run.return_value = _make_validator_output(passed=False)
        results = run_workflow(
            data_dir=workflow_env["data_dir"],
            model_types=["punet"],
            source_run_name="v1",
            workspace=workflow_env["workspace"],
            run_name="test_run",
            max_proposal_attempts=2,
        )
        assert len(results) == 0
        assert workflow_env["propose"].return_value.run.call_count == 2
        workflow_env["tune"].return_value.run.assert_not_called()

    def test_creates_multiple_attempt_dirs(self, workflow_env):
        workflow_env["valid"].return_value.run.side_effect = [
            _make_validator_output(passed=False),
            _make_validator_output(passed=True),
        ]
        run_workflow(
            data_dir=workflow_env["data_dir"],
            model_types=["punet"],
            source_run_name="v1",
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        run_dir = os.path.join(workflow_env["workspace"], "test_run")
        iter_dir = os.path.join(run_dir, "iteration_001")
        assert os.path.isdir(os.path.join(iter_dir, "attempt_001_gated_tcn"))
        assert os.path.isdir(os.path.join(iter_dir, "attempt_002_gated_tcn"))
