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

import importlib
import json
import os
from unittest.mock import MagicMock, call, patch

import pytest

from agent.schemas.hyperparam_tuning import (
    ExpertAdvice,
    GateExhaustionInfo,
    HyperparamTuningInput,
    HyperparamTuningOutput,
)
from agent.schemas.implementor import ImplementorOutput
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.proposal import ProposalOutput
from agent.schemas.validator import ValidatorOutput
from execute_tools.metric_order import MetricOrder
from tests.helpers.metric_fixtures import shipped_spec

#: Step 09a C3 — the migrated ordering consumers take the run's MetricOrder as
#: a REQUIRED keyword. The shipped TIDMAD spec is `higher`, so every expectation
#: in this file is unchanged; the direction is now stated instead of assumed.
_STEP09A_ORDER = MetricOrder(shipped_spec())
from workflows.model_exploration import (
    _CONSTRUCTION_RSS_THRESHOLD_GB,
    _add_plugin_to_registries,
    _register_plugin,
    _validate_construction_memory,
    load_tuning_outputs,
    load_tuning_outputs_from_paths,
    run_workflow,
    tuning_outputs_to_summaries,
)
from workflows.run_config import WorkflowLaunchConfig, launch_config_field_names

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
        # Default: same score as best — i.e. simulates an iter where at least
        # one formal round completed. Tests that need to simulate a
        # trial-only iter (all formal gated) must override this explicitly
        # to None — see test_trial_only_iter_does_not_poison_formal_anchor.
        best_formal_denoising_score=score,
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
        # Step 09a C2 — a real tuner stamps its already-resolved MetricSpec on
        # every output, and the workflow reconciles those stamps into the
        # interpreter's input. Without it here the interpreter would (correctly)
        # refuse this score-bearing fixture.
        metric_spec=shipped_spec(),
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
        model_knowledge_cache={
            "punet": {
                "key_findings": ["Finding 1"],
                "bottlenecks": ["Bottleneck 1"],
                "_stats": {"best_denoising_score": 1.5, "completed_rounds": 3},
            }
        },
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
        summaries = tuning_outputs_to_summaries([_make_tuning_output()], order=_STEP09A_ORDER)
        assert len(summaries) == 1
        assert summaries[0].model_type == "punet"

    def test_converts_multiple_outputs(self):
        summaries = tuning_outputs_to_summaries(
            [
                _make_tuning_output(model_type="punet"),
                _make_tuning_output(model_type="wavenet", score=1.2),
            ],
            order=_STEP09A_ORDER,
        )
        assert len(summaries) == 2

    def test_preserves_best_score(self):
        summaries = tuning_outputs_to_summaries([_make_tuning_output()], order=_STEP09A_ORDER)
        assert summaries[0].best_denoising_score == 1.5

    def test_extracts_round_scores(self):
        summaries = tuning_outputs_to_summaries([_make_tuning_output()], order=_STEP09A_ORDER)
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

    with (
        patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp,
        patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose,
        patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
        patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
        patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
    ):
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
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        assert len(results) == 1
        assert isinstance(results[0], HyperparamTuningOutput)

    def test_accepts_source_paths(self, workflow_env, tmp_path):
        """New API: pass explicit source_paths instead of data_dir+model_types+source_run_name."""
        path = str(tmp_path / "data" / "punet" / "v1" / "agent" / "run_output_v1_agent.json")
        results = run_workflow(
            launch=WorkflowLaunchConfig(
                source_paths=[path],
            ),
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
            launch=WorkflowLaunchConfig(
                source_paths=[seed_path],
            ),
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
            launch=WorkflowLaunchConfig(
                source_paths=[seed_path, iter_1_output_path],
            ),
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
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        workflow_env["interp"].return_value.run.assert_called_once()
        workflow_env["propose"].return_value.run.assert_called_once()
        workflow_env["impl"].return_value.run.assert_called_once()
        workflow_env["valid"].return_value.run.assert_called_once()
        workflow_env["tune"].return_value.run.assert_called_once()

    def test_correct_input_types(self, workflow_env):
        from agent.schemas.implementor import ImplementorInput
        from agent.schemas.interpretation import InterpretationInput
        from agent.schemas.proposal import ProposalInput
        from agent.schemas.validator import ValidatorInput

        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        assert isinstance(
            workflow_env["interp"].return_value.run.call_args[0][0], InterpretationInput
        )
        assert isinstance(workflow_env["propose"].return_value.run.call_args[0][0], ProposalInput)
        assert isinstance(workflow_env["impl"].return_value.run.call_args[0][0], ImplementorInput)
        assert isinstance(workflow_env["valid"].return_value.run.call_args[0][0], ValidatorInput)
        assert isinstance(
            workflow_env["tune"].return_value.run.call_args[0][0], HyperparamTuningInput
        )

    def test_fan_in_expert_advice(self, workflow_env):
        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        tune_arg = workflow_env["tune"].return_value.run.call_args[0][0]
        assert isinstance(tune_arg.expert_advice, ExpertAdvice)
        assert "receptive field" in tune_arg.expert_advice.focus_areas

    def test_workflow_summary_saved(self, workflow_env):
        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
            ),
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
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
            ),
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
        workflow_env["propose"].return_value.run.side_effect = lambda inp: _make_proposal_output(
            next(names)
        )
        workflow_env["tune"].return_value.run.side_effect = lambda inp: _make_tune_output(
            model_type=inp.model_type, score=1.6
        )

        results = run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                max_iterations=3,
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        assert len(results) == 3

    def test_knowledge_cache_grows_across_iterations(self, workflow_env):
        """Iteration 1 passes all seeds as summaries (cache empty).
        Iteration 2 passes only the new model as summaries; seeds are in the cache."""
        names = iter(["model_a", "model_b"])
        workflow_env["propose"].return_value.run.side_effect = lambda inp: _make_proposal_output(
            next(names)
        )
        workflow_env["tune"].return_value.run.side_effect = lambda inp: _make_tune_output(
            model_type=inp.model_type, score=1.6
        )

        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                max_iterations=2,
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        interp_calls = workflow_env["interp"].return_value.run.call_args_list
        iter1_inp = interp_calls[0][0][0]
        iter2_inp = interp_calls[1][0][0]

        # Iter 1: seeds in summaries, cache empty
        assert len(iter1_inp.summaries) == 1  # seed punet
        assert iter1_inp.model_knowledge_cache == {}  # no prior cache

        # Iter 2: only new model in summaries, seeds in cache
        assert len(iter2_inp.summaries) == 1  # new model only
        assert "punet" in iter2_inp.model_knowledge_cache  # seed carried forward

    def test_prediction_memory_carries_from_one_iteration_to_the_next(self, workflow_env):
        """Step 09a C5 — the loop carry, through the REAL workflow.

        Before Step 09a nothing carried this state: every iteration's
        interpreter received the schema defaults, so every production digest's
        pool held exactly one outcome and the proposer's track record always
        read N=1. This asserts iteration 2 receives what iteration 1's digest
        actually wrote — the reachability half of the claim (the restore half
        is `tests/unit/core/test_step09a_c5_prediction_transport.py`).
        """
        digest = _make_interpretation_output()
        digest.prediction_outcomes_history = {"confirmed": 1, "partial": 0, "refuted": 1}
        digest.prediction_outcomes_by_semantics = {
            "metric_order_signsafe_v2": {"confirmed": 2, "partial": 1, "refuted": 0}
        }
        digest.cumulative_information_gain = 0.30
        digest.cumulative_information_gain_by_semantics = {"metric_order_signsafe_v2": 0.45}
        workflow_env["interp"].return_value.run.return_value = digest

        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                max_iterations=2,
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        interp_calls = workflow_env["interp"].return_value.run.call_args_list
        iter1_inp, iter2_inp = interp_calls[0][0][0], interp_calls[1][0][0]

        # Iteration 1 starts from nothing — the schema defaults.
        assert iter1_inp.prediction_outcomes_by_semantics == {}
        assert iter1_inp.cumulative_information_gain == 0.0

        # Iteration 2 receives iteration 1's digest, all four fields, with the
        # v1/v2 separation intact across the hop.
        assert iter2_inp.prediction_outcomes_history == {
            "confirmed": 1,
            "partial": 0,
            "refuted": 1,
        }
        assert iter2_inp.prediction_outcomes_by_semantics == {
            "metric_order_signsafe_v2": {"confirmed": 2, "partial": 1, "refuted": 0}
        }
        assert iter2_inp.cumulative_information_gain == 0.30
        assert iter2_inp.cumulative_information_gain_by_semantics == {
            "metric_order_signsafe_v2": 0.45
        }

    def test_restored_prediction_memory_seeds_the_first_iteration(self, workflow_env):
        """The chain-subprocess half: what `core.resume` restored must reach
        the FIRST iteration of the next subprocess, or the carry stops at the
        process boundary."""
        from agent.schemas.interpretation import PredictionMemory

        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                max_iterations=1,
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
            restored_prediction_memory=PredictionMemory(
                prediction_outcomes_history={"confirmed": 4, "partial": 0, "refuted": 1},
                prediction_outcomes_by_semantics={
                    "metric_order_signsafe_v2": {"confirmed": 3, "partial": 0, "refuted": 0}
                },
                cumulative_information_gain=1.25,
                cumulative_information_gain_by_semantics={"metric_order_signsafe_v2": 0.9},
            ),
        )
        inp = workflow_env["interp"].return_value.run.call_args_list[0][0][0]
        assert inp.prediction_outcomes_history == {"confirmed": 4, "partial": 0, "refuted": 1}
        assert inp.prediction_outcomes_by_semantics == {
            "metric_order_signsafe_v2": {"confirmed": 3, "partial": 0, "refuted": 0}
        }
        assert inp.cumulative_information_gain == 1.25
        assert inp.cumulative_information_gain_by_semantics == {"metric_order_signsafe_v2": 0.9}

    def test_restored_model_knowledge_cache_seeds_first_iter(self, workflow_env):
        """Commit 6.1.a — chain runner forwards prior iter's cache via the
        new ``restored_model_knowledge_cache`` kwarg. The first iter of this
        subprocess must see those entries already present in
        ``InterpretationInput.model_knowledge_cache``, exactly as the
        in-process iter-2 case (covered by the test above) does.

        Without this wiring, the cache-hit branch at
        ``nodes/result_interpretation_agent.py:687-693`` is unreachable in
        chain mode and the Stability Filter (Commit 6.1) is dead code.
        """
        prior_cache = {
            "punet": {
                "key_findings": ["frozen finding from prior iter"],
                "best_config_analysis": "noted",
                "_stats": {"best_denoising_score": 1.42},
            },
        }
        workflow_env["propose"].return_value.run.return_value = _make_proposal_output("model_a")
        workflow_env["tune"].return_value.run.side_effect = lambda inp: _make_tune_output(
            model_type=inp.model_type,
            score=1.6,
        )

        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                max_iterations=1,
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
            restored_model_knowledge_cache=prior_cache,
        )
        iter1_inp = workflow_env["interp"].return_value.run.call_args_list[0][0][0]
        # Cache must be seeded before per_model loop; verbatim round-trip.
        assert "punet" in iter1_inp.model_knowledge_cache
        assert iter1_inp.model_knowledge_cache["punet"]["_stats"]["best_denoising_score"] == 1.42

    def test_restored_model_knowledge_cache_defensive_copy(self, workflow_env):
        """The workflow mutates its in-iter cache (writes new entries on
        cache miss); mutation must not bleed back into the caller's dict."""
        caller_cache = {
            "punet": {
                "key_findings": ["original"],
                "_stats": {"best_denoising_score": 1.0},
            },
        }
        workflow_env["propose"].return_value.run.return_value = _make_proposal_output("model_a")
        workflow_env["tune"].return_value.run.side_effect = lambda inp: _make_tune_output(
            model_type=inp.model_type,
            score=1.6,
        )

        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                max_iterations=1,
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
            restored_model_knowledge_cache=caller_cache,
        )
        # Caller's dict must still have exactly the one entry it started with —
        # the workflow's cache-miss path may have written model_a, but only
        # to its own copy.
        assert list(caller_cache.keys()) == ["punet"]

    def test_no_restored_cache_preserves_legacy_empty_init(self, workflow_env):
        """Default-None kwarg keeps the in-process / first-iter behaviour:
        the iter starts with an empty cache. Regression guard against
        breaking pseudo-mode tests that don't pass the new kwarg."""
        workflow_env["propose"].return_value.run.return_value = _make_proposal_output("model_a")
        workflow_env["tune"].return_value.run.side_effect = lambda inp: _make_tune_output(
            model_type=inp.model_type,
            score=1.6,
        )
        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                max_iterations=1,
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        iter1_inp = workflow_env["interp"].return_value.run.call_args_list[0][0][0]
        assert iter1_inp.model_knowledge_cache == {}

    def test_stops_on_target_score(self, workflow_env):
        names = iter(["model_a", "model_b", "model_c"])
        workflow_env["propose"].return_value.run.side_effect = lambda inp: _make_proposal_output(
            next(names)
        )
        workflow_env["tune"].return_value.run.side_effect = lambda inp: _make_tune_output(
            model_type=inp.model_type, score=2.5
        )

        results = run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                max_iterations=5,
                target_score=2.0,
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        # Should stop after first iteration since score 2.5 >= 2.0
        assert len(results) == 1

    def test_trial_only_iter_does_not_poison_formal_anchor(self, workflow_env):
        """Regression: ``best_score_overall`` (= next iter's
        ``current_run_best_formal_score``) MUST track formal scores only.

        Failure mode this guards: an iter where every formal attempt is
        gated (time-risk, OOM, schema rejection) reports a non-None
        ``best_denoising_score`` (the best trial round) but a None
        ``best_formal_denoising_score``. If the workflow updated from
        ``best_denoising_score``, the noisy trial would poison the formal
        anchor for every subsequent iter, making ``skip_formal_min_delta``
        and ``bypass_formal_time_budget_min_delta`` too strict (v15
        mamba_multirate_fuser / dualpath_spectral_router pattern).

        V19 PR 1 (P1-C1): the schema default is now ``None`` ("no
        incumbent"). iter_2's tune_input.current_run_best_formal_score
        must remain ``None`` — a trial-only iter provides no formal
        incumbent. The INTENT of the original regression (trial scores
        must never become the formal anchor) is preserved; the full
        Invariant II three-iteration coverage lands with P1-C3.
        """
        # iter_1: simulates "all formal attempts gated, only trial scored".
        iter1_tune = _make_tune_output(model_type="model_a", score=7.7)
        iter1_tune.best_formal_denoising_score = None  # no formal completed
        # iter_2: normal output (only here for the second tune_input to inspect).
        iter2_tune = _make_tune_output(model_type="model_b", score=5.6)

        names = iter(["model_a", "model_b"])
        workflow_env["propose"].return_value.run.side_effect = lambda inp: _make_proposal_output(
            next(names)
        )
        workflow_env["tune"].return_value.run.side_effect = [iter1_tune, iter2_tune]

        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                max_iterations=2,
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        iter2_tune_input = workflow_env["tune"].return_value.run.call_args_list[1][0][0]
        # Schema default = None (V19 PR 1: no incumbent). Must NOT be the
        # iter_1 trial score (7.7) — that would mean the bug is back.
        assert iter2_tune_input.current_run_best_formal_score is None


class TestChainIncumbentThreading:
    """V19 PR 1 (P1-C3) — two-state variable design (design doc §3.4,
    Invariant II): the restored chain incumbent initializes
    ``chain_formal_incumbent_reference`` ONLY (reaching the tuner input
    as a named protocol parameter); ``best_score_overall`` remains
    derived solely from the current workflow execution's own formal
    results."""

    def test_restored_incumbent_initializes_reference_only(self, workflow_env):
        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                enable_chain_incumbent_formal_gates=True,
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
            restored_chain_incumbent_score=5.0,
        )
        tune_input = workflow_env["tune"].return_value.run.call_args_list[0][0][0]
        assert tune_input.current_run_best_formal_score == 5.0
        assert tune_input.enable_chain_incumbent_formal_gates is True
        # Non-contamination: best_score_overall derives solely from this
        # execution's own RAW formal (mock output: 1.8) — never from the
        # restored chain state (5.0).
        summary_path = os.path.join(workflow_env["workspace"], "test_run", "workflow_test_run.json")
        with open(summary_path) as f:
            summary = json.load(f)
        assert summary["best_score_overall"] == 1.8

    def test_valid_formal_advances_reference_across_iterations(self, workflow_env):
        """In-process equivalence half: iter 1's committed VALID formal
        becomes iter 2's reference (the on-disk half of the equivalence
        claim lives in tests/unit/sdsc_submission_scripts/, via
        write_manifest + restore_prior_state)."""
        iter1 = _make_tune_output("model_a", 1.8)
        iter1.best_valid_formal_denoising_score = 1.0
        iter1.best_valid_formal_exp_id = "model_a_explore_v1_001"
        iter2 = _make_tune_output("model_b", 1.8)

        names = iter(["model_a", "model_b"])
        workflow_env["propose"].return_value.run.side_effect = lambda inp: _make_proposal_output(
            next(names)
        )
        workflow_env["tune"].return_value.run.side_effect = [iter1, iter2]

        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                max_iterations=2,
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        iter2_input = workflow_env["tune"].return_value.run.call_args_list[1][0][0]
        # The VALUE always travels (reconstruction is unconditional)…
        assert iter2_input.current_run_best_formal_score == 1.0
        # …while CONSUMPTION stays off by default (rollback semantics).
        assert iter2_input.enable_chain_incumbent_formal_gates is False

    def test_raw_formal_never_advances_reference(self, workflow_env):
        """A raw formal (valid None) must not become the next iteration's
        reference — valid-only rule, §3.3."""
        iter1 = _make_tune_output("model_a", 7.7)  # raw formal 7.7, valid None
        iter2 = _make_tune_output("model_b", 1.8)

        names = iter(["model_a", "model_b"])
        workflow_env["propose"].return_value.run.side_effect = lambda inp: _make_proposal_output(
            next(names)
        )
        workflow_env["tune"].return_value.run.side_effect = [iter1, iter2]

        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                max_iterations=2,
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        iter2_input = workflow_env["tune"].return_value.run.call_args_list[1][0][0]
        assert iter2_input.current_run_best_formal_score is None


# ---------------------------------------------------------------------------
# run_workflow — start_iteration plumbing (Phase 8 P3)
# ---------------------------------------------------------------------------


class TestRunWorkflowStartIteration:
    """Verify the chain-mode iteration-index plumbing.

    Pre-P3, ``run_workflow`` always looped ``range(1, max_iterations + 1)``,
    so every chain subprocess (which runs ``max_iterations=1``) wrote
    ``iteration=1`` into ``evolution_log.jsonl`` regardless of which chain
    iter it actually was. P3 adds a ``start_iteration`` parameter that
    offsets the loop and therefore the value carried on
    ``InterpretationInput.iteration`` — which is what the evolution-log
    writer in ``nodes.result_interpretation_agent`` reads.
    """

    def test_default_start_iteration_unchanged(self, workflow_env):
        """start_iteration omitted → first iter stamps iteration=1 (legacy)."""
        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        interp_input = workflow_env["interp"].return_value.run.call_args_list[0][0][0]
        assert interp_input.iteration == 1

    def test_start_iteration_offsets_loop(self, workflow_env):
        """start_iteration=5, max_iterations=1 → exactly one iter stamped 5."""
        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                start_iteration=5,
                max_iterations=1,
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        calls = workflow_env["interp"].return_value.run.call_args_list
        assert len(calls) == 1
        assert calls[0][0][0].iteration == 5
        # Directory name reflects the offset too — keeps post-mortem grep
        # alignment with evolution_log.jsonl rows.
        run_dir = os.path.join(workflow_env["workspace"], "test_run")
        assert os.path.isdir(os.path.join(run_dir, "iteration_005"))

    def test_start_iteration_with_multi_iter(self, workflow_env):
        """start_iteration=3, max_iterations=2 → iters stamped 3 and 4."""
        names = iter(["model_a", "model_b"])
        workflow_env["propose"].return_value.run.side_effect = lambda inp: _make_proposal_output(
            next(names)
        )
        workflow_env["tune"].return_value.run.side_effect = lambda inp: _make_tune_output(
            model_type=inp.model_type, score=1.6
        )
        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                start_iteration=3,
                max_iterations=2,
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        calls = workflow_env["interp"].return_value.run.call_args_list
        assert [c[0][0].iteration for c in calls] == [3, 4]


# ---------------------------------------------------------------------------
# run_workflow — validation failure + retry tests
# ---------------------------------------------------------------------------


class TestRunWorkflowValidationRetry:
    """Exercise the *outer* propose→implement→validate retry loop.

    The workflow has two retry layers (see ``run_workflow``):
      - **inner** ``max_impl_attempts``: validator failure re-runs the
        implementor with the validator's error as feedback, keeping the
        same proposal. Default is 3.
      - **outer** ``max_proposal_attempts``: only triggered when all inner
        impl retries are exhausted; generates a brand new proposal.

    These tests are about the OUTER loop, so they pin
    ``max_impl_attempts=1`` to disable the inner one — otherwise the first
    validator failure is absorbed by an impl retry (same proposal) and
    the outer loop never sees it.
    """

    def test_retries_on_validation_failure(self, workflow_env):
        # First validation fails (impl retries are off → bubbles to outer
        # loop), second proposal's validation passes.
        workflow_env["valid"].return_value.run.side_effect = [
            _make_validator_output(passed=False),
            _make_validator_output(passed=True),
        ]
        results = run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                max_impl_attempts=1,
            ),
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
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                max_impl_attempts=1,
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        # Second proposal call should have previous_failures
        second_call_input = workflow_env["propose"].return_value.run.call_args_list[1][0][0]
        assert len(second_call_input.previous_failures) == 1
        assert "shape mismatch" in second_call_input.previous_failures[0]

    def test_stops_after_max_proposal_attempts(self, workflow_env):
        # Default max_impl_attempts=3, so 2 outer attempts × 3 impl retries
        # = 6 validator calls. Only the OUTER count matters here.
        workflow_env["valid"].return_value.run.return_value = _make_validator_output(passed=False)
        results = run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                max_proposal_attempts=2,
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
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
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                max_impl_attempts=1,
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        run_dir = os.path.join(workflow_env["workspace"], "test_run")
        iter_dir = os.path.join(run_dir, "iteration_001")
        assert os.path.isdir(os.path.join(iter_dir, "attempt_001_gated_tcn"))
        assert os.path.isdir(os.path.join(iter_dir, "attempt_002_gated_tcn"))


# ---------------------------------------------------------------------------
# Phase K.7.5 — gate-exhaustion propagation across iterations (§10.13)
# ---------------------------------------------------------------------------


class TestRunWorkflowGateExhaustionPropagation:
    """The workflow must retain the previous iteration's tuner output and
    pass it as ``prior_tune_output=`` to the next iteration's
    ``local_full_context`` call. The protocol then surfaces
    ``gate_exhaustion`` (when present) into the next proposer's
    ``ProposalInput.prior_iteration_gate_exhaustion``.

    Iteration 1 has no prior, so its ProposalInput must carry
    ``prior_iteration_gate_exhaustion=None``. Iteration 2 must receive
    iteration 1's gate_exhaustion verbatim.

    See docs/resource_estimator_implement.md §10.13.
    """

    def _gate_exhaustion(self):
        return GateExhaustionInfo(
            total_attempts=9,
            vram_gated_attempts=9,
            time_gated_attempts=0,
            other_failure_attempts=0,
            active_mode="trial",
            vram_budget_gb=4.0,
            time_budget_minutes=20.0,
            baseline_vram_estimate_gb=6.4,
            baseline_vram_factor=1.6,
            baseline_time_estimate_minutes=8.0,
            baseline_time_factor=0.4,
            worst_vram_factor=2.0,
            worst_time_factor=0.6,
            summary_message="All 9 attempts were rejected by the VRAM gate.",
        )

    def test_iter1_proposal_has_empty_recent_gate_exhaustions(self, workflow_env):
        """First iteration runs with no prior tuner output, so the proposer's
        ``recent_gate_exhaustions`` must be empty — confirms the workflow's
        retained-outputs carrier is initialised empty and the protocol
        produces ``[]`` on iteration 1."""
        names = iter(["model_a", "model_b"])
        workflow_env["propose"].return_value.run.side_effect = lambda inp: _make_proposal_output(
            next(names)
        )
        workflow_env["tune"].return_value.run.side_effect = [
            _make_tune_output(model_type="model_a", score=1.6),
            _make_tune_output(model_type="model_b", score=1.7),
        ]
        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                max_iterations=2,
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        iter1_propose_input = workflow_env["propose"].return_value.run.call_args_list[0][0][0]
        assert iter1_propose_input.recent_gate_exhaustions == []

    def test_iter2_proposal_receives_iter1_gate_exhaustion(self, workflow_env):
        """When iteration 1's tuner output carries a populated gate_exhaustion,
        iteration 2's proposer must see the same payload, surfaced as a
        single-entry ``recent_gate_exhaustions`` list via the protocol."""
        gate = self._gate_exhaustion()

        iter1_tune = _make_tune_output(model_type="model_a", score=1.6)
        iter1_tune.gate_exhaustion = gate
        iter2_tune = _make_tune_output(model_type="model_b", score=1.7)

        names = iter(["model_a", "model_b"])
        workflow_env["propose"].return_value.run.side_effect = lambda inp: _make_proposal_output(
            next(names)
        )
        workflow_env["tune"].return_value.run.side_effect = [iter1_tune, iter2_tune]

        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                max_iterations=2,
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        iter2_propose_input = workflow_env["propose"].return_value.run.call_args_list[1][0][0]
        surfaced = iter2_propose_input.recent_gate_exhaustions
        assert len(surfaced) == 1
        assert isinstance(surfaced[0], GateExhaustionInfo)
        # Round-trip equality — every field crossed the workflow → protocol hop
        assert surfaced[0].model_dump() == gate.model_dump()

    def test_iter2_proposal_no_gate_exhaustion_when_iter1_succeeded(self, workflow_env):
        """When iteration 1's tuner succeeds (gate_exhaustion=None), the next
        proposer must NOT see a stale or fabricated entry — the protocol
        filters None entries out, leaving ``recent_gate_exhaustions`` empty."""
        iter1_tune = _make_tune_output(model_type="model_a", score=1.6)
        iter2_tune = _make_tune_output(model_type="model_b", score=1.7)
        # Default factory produces gate_exhaustion=None; assert that explicitly
        # so this test fails loudly if the factory is ever changed.
        assert iter1_tune.gate_exhaustion is None

        names = iter(["model_a", "model_b"])
        workflow_env["propose"].return_value.run.side_effect = lambda inp: _make_proposal_output(
            next(names)
        )
        workflow_env["tune"].return_value.run.side_effect = [iter1_tune, iter2_tune]

        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                max_iterations=2,
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )
        iter2_propose_input = workflow_env["propose"].return_value.run.call_args_list[1][0][0]
        assert iter2_propose_input.recent_gate_exhaustions == []

    def test_four_iteration_deque_evicts_oldest(self, workflow_env):
        """Phase N (§14.N.4) — 4-iteration mock loop where every iter emits
        a sentinel gate_exhaustion. The workflow's ``recent_tune_outputs``
        is a ``deque(maxlen=3)``, so by the time iteration 4's proposer is
        called, the deque holds iters 1, 2, 3 (oldest-first, iter 1 not yet
        evicted); and then iter 4's tune-end append evicts iter 1, leaving
        iters 2, 3, 4 — which a hypothetical iter 5 would see.

        Assertions follow §14.N.4's "iter N's protocol call receives the
        deque containing iters (N-3, N-2, N-1)" rule, plus the eviction
        claim via a 5th iteration's view."""
        # Distinct sentinel summaries so we can assert identity + order
        gates = [
            GateExhaustionInfo(
                total_attempts=1,
                vram_gated_attempts=1,
                time_gated_attempts=0,
                other_failure_attempts=0,
                active_mode="trial",
                vram_budget_gb=4.0,
                time_budget_minutes=20.0,
                baseline_vram_estimate_gb=6.4,
                baseline_vram_factor=1.6,
                baseline_time_estimate_minutes=8.0,
                baseline_time_factor=0.4,
                worst_vram_factor=2.0,
                worst_time_factor=0.6,
                summary_message=f"SENTINEL-iter{i}",
            )
            for i in range(1, 6)
        ]
        tunes = []
        for i, gate in enumerate(gates, start=1):
            t = _make_tune_output(model_type=f"model_{i}", score=1.5 + 0.1 * i)
            t.gate_exhaustion = gate
            tunes.append(t)

        names = iter(f"model_{i}" for i in range(1, 6))
        workflow_env["propose"].return_value.run.side_effect = lambda inp: _make_proposal_output(
            next(names)
        )
        workflow_env["tune"].return_value.run.side_effect = tunes

        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                max_iterations=5,
            ),
            workspace=workflow_env["workspace"],
            run_name="test_run",
        )

        call_args = workflow_env["propose"].return_value.run.call_args_list

        # Iter 4's proposer sees iters 1, 2, 3 — deque at capacity (3), no
        # eviction yet (that happens after iter 4's own tune-end append).
        iter4 = call_args[3][0][0]
        assert len(iter4.recent_gate_exhaustions) == 3
        summaries4 = [g.summary_message for g in iter4.recent_gate_exhaustions]
        assert summaries4 == ["SENTINEL-iter1", "SENTINEL-iter2", "SENTINEL-iter3"]

        # Iter 5's proposer observes the eviction: iter 1 gone, window slid
        # forward to iters 2, 3, 4. This is the §14.N.4 eviction claim.
        iter5 = call_args[4][0][0]
        assert len(iter5.recent_gate_exhaustions) == 3
        summaries5 = [g.summary_message for g in iter5.recent_gate_exhaustions]
        assert summaries5 == ["SENTINEL-iter2", "SENTINEL-iter3", "SENTINEL-iter4"]
        # Iter 1 must not leak into any propose call after iter 4
        assert "SENTINEL-iter1" not in summaries5


# ---------------------------------------------------------------------------
# _register_plugin tests (Phase 4 — docs/run_scoped_plugins.md)
# ---------------------------------------------------------------------------


class TestRegisterPlugin:
    """Phase 4 contract: ``_register_plugin`` must copy the validated plugin
    into the *caller-supplied* ``dest_plugin_dir`` (the tuner's run-scoped
    plugin dir). Pre-Phase-4 it copied to the legacy global
    ``<repo>/agent_generated/models/``, which the training subprocess no
    longer scans once SIDERIUS_PLUGIN_DIRS is set."""

    def _make_implementor_output_with_real_files(self, tmp_path, model_type="gated_tcn"):
        """Build an ImplementorOutput whose model_file_path /
        description_file_path point at real files inside tmp_path so
        ``_register_plugin``'s ``shutil.copy2`` calls actually run."""
        src_models = tmp_path / "src" / "models"
        src_models.mkdir(parents=True)
        plugin_src = src_models / f"{model_type}.py"
        plugin_src.write_text(
            f'PLUGIN_MODEL_TYPE = "{model_type}"\n'
            "class PLUGIN_CONFIG_CLASS: ...\n"
            "class PLUGIN_MODEL_CLASS: ...\n"
        )
        desc_src_dir = src_models / model_type
        desc_src_dir.mkdir()
        desc_src = desc_src_dir / "description.md"
        desc_src.write_text("# Test plugin description\n")
        test_src = tmp_path / "src" / "tests" / f"test_{model_type}.py"
        test_src.parent.mkdir(parents=True)
        test_src.write_text("def test_noop(): pass\n")

        return ImplementorOutput(
            model_type=model_type,
            model_file_path=str(plugin_src),
            test_file_path=str(test_src),
            description_file_path=str(desc_src),
            config_fields={"n_layers": 4},
            model_description="A test plugin.",
            mathematical_definition="y = f(x)",
        )

    def test_writes_plugin_into_supplied_dest(self, tmp_path):
        """Plugin file lands at ``<dest_plugin_dir>/<model_name>.py`` —
        nowhere else. This is the core Phase 4 promise."""
        impl = self._make_implementor_output_with_real_files(tmp_path)
        dest = tmp_path / "ws" / "plugins" / "tune_run"
        _register_plugin(impl, "gated_tcn", str(dest))

        assert (dest / "gated_tcn.py").is_file()
        # And the file actually contains the source we wrote.
        assert "PLUGIN_MODEL_TYPE" in (dest / "gated_tcn.py").read_text()

    def test_writes_description_into_supplied_dest(self, tmp_path):
        impl = self._make_implementor_output_with_real_files(tmp_path)
        dest = tmp_path / "ws" / "plugins" / "tune_run"
        _register_plugin(impl, "gated_tcn", str(dest))

        assert (dest / "gated_tcn" / "description.md").is_file()
        assert "Test plugin description" in (dest / "gated_tcn" / "description.md").read_text()

    def test_does_not_touch_legacy_global_dir(self, tmp_path, monkeypatch):
        """Regression guard for the silent-breakage case the previous design
        had: with ``SIDERIUS_PLUGIN_DIRS`` set, anything written to the
        legacy ``<repo>/agent_generated/models/`` is invisible to the
        training subprocess. Phase 4 must NOT write there."""
        # Run from a tmp cwd so any accidental "agent_generated/models/..."
        # write would land here, where we can detect it.
        monkeypatch.chdir(tmp_path)
        impl = self._make_implementor_output_with_real_files(tmp_path)
        dest = tmp_path / "ws" / "plugins" / "tune_run"
        _register_plugin(impl, "gated_tcn", str(dest))

        legacy = tmp_path / "agent_generated" / "models" / "gated_tcn.py"
        assert not legacy.exists(), (
            f"_register_plugin wrote to the legacy global dir at {legacy} — "
            "this regresses Phase 4. The training subprocess no longer scans "
            "that path when SIDERIUS_PLUGIN_DIRS is set."
        )

    def test_creates_dest_dir_if_missing(self, tmp_path):
        """The workflow constructs ``dest_plugin_dir`` via ``get_plugin_dir``
        and may call ``_register_plugin`` before the tuner's sandbox has
        ``_ensure_dir``-ed it. The function must create the dir on its own."""
        impl = self._make_implementor_output_with_real_files(tmp_path)
        dest = tmp_path / "fresh" / "plugins" / "tune_run"
        assert not dest.exists()
        _register_plugin(impl, "gated_tcn", str(dest))
        assert (dest / "gated_tcn.py").is_file()

    def test_skips_when_source_plugin_missing(self, tmp_path, capsys):
        """Defensive: if the implementor output points at a path that
        doesn't exist (e.g. mocked output in a unit test), the function
        warns and returns instead of raising."""
        impl = ImplementorOutput(
            model_type="ghost",
            model_file_path=str(tmp_path / "does_not_exist.py"),
            test_file_path=str(tmp_path / "test_ghost.py"),
            description_file_path=str(tmp_path / "ghost" / "description.md"),
            config_fields={},
            model_description="x",
            mathematical_definition="x",
        )
        dest = tmp_path / "ws" / "plugins" / "tune_run"
        _register_plugin(impl, "ghost", str(dest))  # must not raise

        captured = capsys.readouterr()
        assert "plugin file not found" in captured.out
        assert not (dest / "ghost.py").exists()

    # ----- L6a: loss-plugin propagation -----------------------------------
    #
    # Pre-L6a the implementor wrote the loss plugin to a per-attempt
    # ``{attempt_dir}/losses/{loss_name}.py`` directory that no subsequent
    # code copied anywhere. ``SIDERIUS_LOSS_DIRS`` (set by the sandbox to a
    # workspace-scoped path) pointed at an empty directory, so the training
    # subprocess could never load the custom loss plugin. The four tests
    # below pin the L6a contract: the function now copies the loss file to
    # the caller-supplied ``dest_loss_dirs`` ONLY when the provenance says
    # ``action="generated"``; ``action="reused"`` is a no-op (the chain-
    # canonical copy from the originating iter is expected to still exist).

    def _make_implementor_output_with_loss(self, tmp_path, action="generated"):
        """Build an ImplementorOutput with a real loss plugin file at
        ``{tmp_path}/src/losses/{loss_name}.py`` and a populated
        ``loss_provenance`` whose ``action`` is the parameter."""
        from agent.schemas.implementor import LossProvenance

        loss_name = "expected_value_mse"
        loss_src_dir = tmp_path / "src" / "losses"
        loss_src_dir.mkdir(parents=True)
        loss_src = loss_src_dir / f"{loss_name}.py"
        loss_src.write_text(
            f'PLUGIN_LOSS_TYPE = "{loss_name}"\n'
            "class PLUGIN_LOSS_CONFIG_CLASS: ...\n"
            "class PLUGIN_LOSS_CLASS: ...\n"
        )
        impl = self._make_implementor_output_with_real_files(tmp_path)
        impl.loss_provenance = LossProvenance(
            loss_name=loss_name,
            action=action,
            source_iteration="iter_001",
            loss_file_path=str(loss_src),
            dummy_tensor_validated=True,
        )
        return impl

    def test_l6a_copies_loss_plugin_when_generated(self, tmp_path):
        """Branch C / generated path: loss file lands at
        ``{loss_dest}/{loss_name}.py``."""
        impl = self._make_implementor_output_with_loss(tmp_path, action="generated")
        model_dest = tmp_path / "ws" / "plugins" / "tune_run"
        loss_dest = tmp_path / "ws" / "losses" / "tune_run"
        _register_plugin(
            impl,
            "gated_tcn",
            str(model_dest),
            dest_loss_dirs=str(loss_dest),
        )
        assert (loss_dest / "expected_value_mse.py").is_file()
        assert "PLUGIN_LOSS_TYPE" in (loss_dest / "expected_value_mse.py").read_text()

    def test_l6a_copies_loss_plugin_to_multiple_dests(self, tmp_path):
        """Mirror of the model-plugin dual-dest pattern: tuner-scoped +
        chain-canonical destinations both receive the file."""
        impl = self._make_implementor_output_with_loss(tmp_path, action="generated")
        model_dest = tmp_path / "ws" / "plugins" / "tune_run"
        tuner_loss_dest = tmp_path / "tuning_dir" / "losses" / "tune_run"
        chain_loss_dest = tmp_path / "ws" / "losses" / "tune_run"
        _register_plugin(
            impl,
            "gated_tcn",
            str(model_dest),
            dest_loss_dirs=[str(tuner_loss_dest), str(chain_loss_dest)],
        )
        assert (tuner_loss_dest / "expected_value_mse.py").is_file()
        assert (chain_loss_dest / "expected_value_mse.py").is_file()

    def test_l6a_skips_loss_copy_when_reused(self, tmp_path):
        """Branch B / reused path: the implementor recorded an existing
        plugin path; ``_register_plugin`` MUST NOT copy it. The chain-
        canonical copy from the originating iter is expected to still
        exist."""
        impl = self._make_implementor_output_with_loss(tmp_path, action="reused")
        model_dest = tmp_path / "ws" / "plugins" / "tune_run"
        loss_dest = tmp_path / "ws" / "losses" / "tune_run"
        _register_plugin(
            impl,
            "gated_tcn",
            str(model_dest),
            dest_loss_dirs=str(loss_dest),
        )
        assert not (loss_dest / "expected_value_mse.py").exists()

    def test_l6a_no_op_when_dest_loss_dirs_none(self, tmp_path):
        """Back-compat: existing call sites that pass only the three
        positional args (no ``dest_loss_dirs``) keep working — the function
        does not raise and the model copy still completes."""
        impl = self._make_implementor_output_with_loss(tmp_path, action="generated")
        model_dest = tmp_path / "ws" / "plugins" / "tune_run"
        _register_plugin(impl, "gated_tcn", str(model_dest))  # no dest_loss_dirs
        assert (model_dest / "gated_tcn.py").is_file()  # model still copied

    def test_l6a_warns_when_loss_source_missing(self, tmp_path, capsys):
        """Defensive symmetry with ``test_skips_when_source_plugin_missing``:
        if the loss source file doesn't exist (mock setup error), warn and
        continue rather than raising."""
        from agent.schemas.implementor import LossProvenance

        impl = self._make_implementor_output_with_real_files(tmp_path)
        impl.loss_provenance = LossProvenance(
            loss_name="ghost_loss",
            action="generated",
            source_iteration="iter_001",
            loss_file_path=str(tmp_path / "does_not_exist_loss.py"),
            dummy_tensor_validated=True,
        )
        model_dest = tmp_path / "ws" / "plugins" / "tune_run"
        loss_dest = tmp_path / "ws" / "losses" / "tune_run"
        _register_plugin(
            impl,
            "gated_tcn",
            str(model_dest),
            dest_loss_dirs=str(loss_dest),
        )
        captured = capsys.readouterr()
        assert "loss plugin file not found" in captured.out
        assert not (loss_dest / "ghost_loss.py").exists()

    def test_register_plugin_populates_loss_registry_with_file_not_dir(self, tmp_path):
        """Regression guard for the L6c bug (2026-06-24): _register_plugin
        called register_loss_in_memory with the dest *directory* path
        instead of the dest *file* path. spec_from_file_location silently
        returned None for the directory, leaving LOSS_REGISTRY empty.
        Every in-process pre-flight then fell back to filesystem, found
        nothing (workspace has no SIDERIUS_LOSS_DIRS), and aborted the
        round. Gate 3 hit aborted_fail_rounds; Gate 2 false-passed by the
        tuner reverting to a built-in loss.

        This test would have caught the bug immediately — it asserts that
        after _register_plugin runs with a generated loss, LOSS_REGISTRY[name]
        holds an actual class object, not None.
        """
        from ml_models.loss_models_sandbox import (
            LOSS_CONFIG_REGISTRY,
            LOSS_REGISTRY,
        )

        impl = self._make_implementor_output_with_loss(tmp_path, action="generated")
        model_dest = tmp_path / "ws" / "plugins" / "tune_run"
        loss_dest = tmp_path / "ws" / "losses" / "tune_run"
        # Clear registry to ensure post-call state is from THIS call only.
        LOSS_REGISTRY.pop("expected_value_mse", None)
        LOSS_CONFIG_REGISTRY.pop("expected_value_mse", None)
        _register_plugin(
            impl,
            "gated_tcn",
            str(model_dest),
            dest_loss_dirs=str(loss_dest),
        )
        # The loss file MUST have been copied to disk under loss_dest.
        assert (loss_dest / "expected_value_mse.py").is_file()
        # AND LOSS_REGISTRY must contain the loss class (not None, not missing).
        assert "expected_value_mse" in LOSS_REGISTRY, (
            f"register_loss_in_memory failed silently — LOSS_REGISTRY keys "
            f"after _register_plugin: {sorted(LOSS_REGISTRY)}"
        )
        assert LOSS_REGISTRY["expected_value_mse"] is not None
        assert "expected_value_mse" in LOSS_CONFIG_REGISTRY
        assert LOSS_CONFIG_REGISTRY["expected_value_mse"] is not None
        # Cleanup
        LOSS_REGISTRY.pop("expected_value_mse", None)
        LOSS_CONFIG_REGISTRY.pop("expected_value_mse", None)


# ---------------------------------------------------------------------------
# _add_plugin_to_registries — Phase 6.8 Commit 6
# ---------------------------------------------------------------------------
#
# The pre-Commit-6 _register_plugin only touched MODEL_REGISTRY and the packaged
# PLUGIN_CONFIG_REGISTRY. The two missing surfaces — PLUGIN_OUTPUT_TYPE_REGISTRY
# and the bare-name models_format_sandbox.PLUGIN_CONFIG_REGISTRY mirror — caused
# regressors to be miscategorised as classifiers and the training subprocess to
# fail with `Unknown model_type` when run via bare imports. These tests pin the
# fix.
# ---------------------------------------------------------------------------

import sys as _sys
import textwrap as _textwrap

_REGRESSOR_PLUGIN_SRC = _textwrap.dedent("""\
    import torch
    import torch.nn as nn
    from pydantic import BaseModel, Field

    PLUGIN_MODEL_TYPE = "test_regressor_plugin_c6"
    PLUGIN_OUTPUT_TYPE = "regressor"

    class TestRegressorConfig(BaseModel):
        model_type: str = "test_regressor_plugin_c6"
        segmentation_size: int = Field(default=1000, ge=100)
        batch_size: int = 1

    class TestRegressorModel(nn.Module):
        def __init__(self, config):
            super().__init__()
            # Fixed small projection — doesn't scale with T. The forward
            # pass is illustrative only; register-plugin tests don't run
            # it. A real plugin would map seg_size -> seg_size, but doing
            # so here would (correctly!) trip _validate_construction_memory
            # at representative_T=16000 because nn.Linear(T, T) is O(T²).
            self.proj = nn.Linear(8, 8)

        def forward(self, x):
            return x.float().mean(dim=-1, keepdim=True).expand(-1, x.shape[-1])

    PLUGIN_CONFIG_CLASS = TestRegressorConfig
    PLUGIN_MODEL_CLASS  = TestRegressorModel
""")


_CLASSIFIER_PLUGIN_SRC = _textwrap.dedent("""\
    import torch
    import torch.nn as nn
    from pydantic import BaseModel, Field

    PLUGIN_MODEL_TYPE = "test_classifier_plugin_c6"

    class TestClassifierConfig(BaseModel):
        model_type: str = "test_classifier_plugin_c6"
        segmentation_size: int = Field(default=1000, ge=100)
        batch_size: int = 1

    class TestClassifierModel(nn.Module):
        def __init__(self, config):
            super().__init__()
            # Fixed small projection — see TestRegressorModel rationale.
            self.proj = nn.Linear(8, 8)

        def forward(self, x):
            out = x.float().mean(dim=-1, keepdim=True)
            return out.unsqueeze(1).expand(-1, 256, x.shape[-1])

    PLUGIN_CONFIG_CLASS = TestClassifierConfig
    PLUGIN_MODEL_CLASS  = TestClassifierModel
""")


@pytest.fixture
def regressor_plugin_file(tmp_path):
    p = tmp_path / "test_regressor_plugin_c6.py"
    p.write_text(_REGRESSOR_PLUGIN_SRC)
    return str(p)


@pytest.fixture
def classifier_plugin_file(tmp_path):
    p = tmp_path / "test_classifier_plugin_c6.py"
    p.write_text(_CLASSIFIER_PLUGIN_SRC)
    return str(p)


@pytest.fixture
def clean_registries():
    """Snapshot + restore every registry surface so cross-test pollution
    cannot mask a real bug. Also wipes the test model_types from any
    leaked sys.modules entries from a prior run."""
    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
    from ml_models.models_sandbox import MODEL_REGISTRY
    from ml_models.plugin_loader import PLUGIN_OUTPUT_TYPE_REGISTRY

    keys_to_clear = ("test_regressor_plugin_c6", "test_classifier_plugin_c6")

    snap_model = {k: MODEL_REGISTRY.get(k) for k in keys_to_clear}
    snap_cfg = {k: PLUGIN_CONFIG_REGISTRY.get(k) for k in keys_to_clear}
    snap_out = {k: PLUGIN_OUTPUT_TYPE_REGISTRY.get(k) for k in keys_to_clear}

    for k in keys_to_clear:
        MODEL_REGISTRY.pop(k, None)
        PLUGIN_CONFIG_REGISTRY.pop(k, None)
        PLUGIN_OUTPUT_TYPE_REGISTRY.pop(k, None)

    # Also clear any stale sys.modules entries from prior loads of these stems.
    for stem in keys_to_clear:
        _sys.modules.pop(f"siderius_plugin_{stem}", None)

    yield

    for k, v in snap_model.items():
        if v is None:
            MODEL_REGISTRY.pop(k, None)
        else:
            MODEL_REGISTRY[k] = v
    for k, v in snap_cfg.items():
        if v is None:
            PLUGIN_CONFIG_REGISTRY.pop(k, None)
        else:
            PLUGIN_CONFIG_REGISTRY[k] = v
    for k, v in snap_out.items():
        if v is None:
            PLUGIN_OUTPUT_TYPE_REGISTRY.pop(k, None)
        else:
            PLUGIN_OUTPUT_TYPE_REGISTRY[k] = v


class TestAddPluginToRegistries:
    """Pins the four-surface contract for ``_add_plugin_to_registries``."""

    def test_returns_model_type_on_success(self, regressor_plugin_file, clean_registries):
        result = _add_plugin_to_registries(regressor_plugin_file)
        assert result == "test_regressor_plugin_c6"

    def test_returns_none_on_invalid_plugin(self, tmp_path, clean_registries):
        bad = tmp_path / "broken_plugin.py"
        bad.write_text("# missing required attrs\n")
        assert _add_plugin_to_registries(str(bad)) is None

    def test_updates_model_registry(self, classifier_plugin_file, clean_registries):
        from ml_models.models_sandbox import MODEL_REGISTRY

        _add_plugin_to_registries(classifier_plugin_file)
        assert "test_classifier_plugin_c6" in MODEL_REGISTRY

    def test_updates_packaged_config_registry(self, classifier_plugin_file, clean_registries):
        from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY

        _add_plugin_to_registries(classifier_plugin_file)
        assert "test_classifier_plugin_c6" in PLUGIN_CONFIG_REGISTRY

    def test_regressor_routes_via_get_output_type(self, regressor_plugin_file, clean_registries):
        """The latent-bug regression test: pre-Commit-6, this returned
        'classifier' because PLUGIN_OUTPUT_TYPE_REGISTRY was never updated."""
        from ml_models.plugin_loader import get_output_type

        _add_plugin_to_registries(regressor_plugin_file)
        assert get_output_type("test_regressor_plugin_c6") == "regressor"

    def test_classifier_default_routes_correctly(self, classifier_plugin_file, clean_registries):
        from ml_models.plugin_loader import get_output_type

        _add_plugin_to_registries(classifier_plugin_file)
        assert get_output_type("test_classifier_plugin_c6") == "classifier"

    def test_no_bare_module_identity_after_package_refactor(
        self, classifier_plugin_file, clean_registries
    ):
        """Post-package-refactor invariant: there is no bare
        ``models_format_sandbox`` module identity to mirror to. The editable
        install exposes ``ml_models`` as a proper package, so the legacy
        ``sys.path`` insert that used to surface a duplicate bare module has
        been removed and ``_add_plugin_to_registries`` no longer needs a
        dual-mirror branch."""
        import sys

        assert sys.modules.get("models_format_sandbox") is None, (
            "package refactor invariant violated: a bare "
            "`models_format_sandbox` module identity was found in "
            "sys.modules. The dual-module workaround was removed; only the "
            "fully-qualified `ml_models.models_format_sandbox` should exist."
        )

        pkg = importlib.import_module("ml_models.models_format_sandbox")
        pkg.PLUGIN_CONFIG_REGISTRY.pop("test_classifier_plugin_c6", None)

        _add_plugin_to_registries(classifier_plugin_file)

        assert "test_classifier_plugin_c6" in pkg.PLUGIN_CONFIG_REGISTRY


class TestRegisterPluginUsesHelper:
    """End-to-end: ``_register_plugin`` (the workflow's caller) must drive
    all four registry surfaces via the helper."""

    def test_register_plugin_populates_all_four_surfaces(self, tmp_path, clean_registries):
        impl = ImplementorOutput(
            model_type="test_regressor_plugin_c6",
            model_file_path=str(tmp_path / "src_plugin.py"),
            test_file_path=str(tmp_path / "src_test.py"),
            description_file_path=str(tmp_path / "src_desc.md"),
            config_fields={},
            model_description="x",
            mathematical_definition="y=f(x)",
        )
        # Materialise source files _register_plugin actually copies.
        (tmp_path / "src_plugin.py").write_text(_REGRESSOR_PLUGIN_SRC)
        (tmp_path / "src_test.py").write_text("def test_noop(): pass\n")
        (tmp_path / "src_desc.md").write_text("desc\n")

        dest = tmp_path / "ws" / "plugins" / "run_x"
        _register_plugin(impl, "test_regressor_plugin_c6", str(dest))

        from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
        from ml_models.models_sandbox import MODEL_REGISTRY
        from ml_models.plugin_loader import (
            PLUGIN_OUTPUT_TYPE_REGISTRY,
            get_output_type,
        )

        assert "test_regressor_plugin_c6" in MODEL_REGISTRY
        assert "test_regressor_plugin_c6" in PLUGIN_CONFIG_REGISTRY
        assert PLUGIN_OUTPUT_TYPE_REGISTRY.get("test_regressor_plugin_c6") == "regressor"
        assert get_output_type("test_regressor_plugin_c6") == "regressor"


# ---------------------------------------------------------------------------
# Workflow-surface signature drift regression
#
# Catches the class of bug from commit 02eed58, where run_one_iteration.py
# forwarded ``formal_round_strategy=args.formal_round_strategy`` into
# run_workflow but the workflow's signature was never updated to accept
# the kwarg — every chain run would have crashed with TypeError on
# iteration 1. argparse-parity tests don't catch this because they never
# invoke the workflow.
#
# Two-layer check per orchestration kwarg:
#   1. ``inspect.signature(run_workflow)`` exposes the parameter (cheap,
#      catches the (a)-style TypeError before any test setup).
#   2. The value reaches ``HyperparamTuningInput`` unchanged via the
#      validator->tune protocol (catches a kwarg that's accepted but
#      silently dropped between workflow surface and tuner input).
# ---------------------------------------------------------------------------


def _tune_input_from_workflow(workflow_env, tmp_path, **workflow_kwargs):
    """Run the workflow with a single source path and return the
    HyperparamTuningInput that reached HyperparamTuningAgent.run().

    Step 09.5a C3: the caller's flat kwargs are split by ownership, so every
    test below still reads as ``_tune_input_from_workflow(env, tmp, foo=bar)``.
    """
    path = str(tmp_path / "data" / "punet" / "v1" / "agent" / "run_output_v1_agent.json")
    launch_fields = launch_config_field_names()
    launch_kwargs = {"source_paths": [path]}
    run_kwargs = {"workspace": workflow_env["workspace"], "run_name": "test_run"}
    for key, value in workflow_kwargs.items():
        (launch_kwargs if key in launch_fields else run_kwargs)[key] = value
    run_workflow(launch=WorkflowLaunchConfig(**launch_kwargs), **run_kwargs)
    mock_tune_run = workflow_env["tune"].return_value.run
    assert mock_tune_run.called, "tuning agent was never invoked"
    tune_input = mock_tune_run.call_args[0][0]
    assert isinstance(tune_input, HyperparamTuningInput)
    return tune_input


class TestOrchestrationParamForwarding:
    def test_signature_accepts_health_checks_config(self):
        import inspect

        sig = inspect.signature(run_workflow)
        assert "health_checks_config" in sig.parameters

    def test_health_checks_config_reaches_tuner(self, workflow_env, tmp_path):
        path = "configs/health_checks_baseline_observe_mode.yaml"
        tune_input = _tune_input_from_workflow(
            workflow_env,
            tmp_path,
            health_checks_config=path,
        )
        assert tune_input.health_checks_config == path

    def test_health_checks_config_defaults_to_none(self, workflow_env, tmp_path):
        tune_input = _tune_input_from_workflow(workflow_env, tmp_path)
        assert tune_input.health_checks_config is None

    def test_signature_accepts_formal_round_strategy(self):
        """Step 09.5a C3: it is transit configuration, so it lives on the
        launch carrier. The invariant — the orchestration surface accepts it —
        is unchanged; only where it is declared moved."""
        import dataclasses

        from workflows.run_config import WorkflowLaunchConfig

        assert "formal_round_strategy" in {f.name for f in dataclasses.fields(WorkflowLaunchConfig)}

    def test_formal_round_strategy_default_full_clone(self, workflow_env, tmp_path):
        """Phase 1 of refactor_formal_round_strategy.md flipped the
        schema default from legacy ``inherit_best_trial`` to canonical
        ``full_clone``. Behavior identical, name normalised."""
        tune_input = _tune_input_from_workflow(workflow_env, tmp_path)
        assert tune_input.formal_round_strategy == "full_clone"

    def test_formal_round_strategy_canonical_independent_reaches_tuning_input(
        self, workflow_env, tmp_path
    ):
        tune_input = _tune_input_from_workflow(
            workflow_env,
            tmp_path,
            formal_round_strategy="independent",
        )
        assert tune_input.formal_round_strategy == "independent"

    def test_formal_round_strategy_canonical_hybrid_params_reaches_tuning_input(
        self, workflow_env, tmp_path
    ):
        """Phase 2 introduced ``hybrid_params`` (loss_cfg + lr only). The
        workflow must accept it and forward it verbatim to the tuner."""
        tune_input = _tune_input_from_workflow(
            workflow_env,
            tmp_path,
            formal_round_strategy="hybrid_params",
        )
        assert tune_input.formal_round_strategy == "hybrid_params"

    def test_formal_round_strategy_legacy_alias_canonicalised(self, workflow_env, tmp_path):
        """A workflow caller passing the legacy literal must see the
        canonicalised name on ``HyperparamTuningInput`` because the
        schema validator runs after the protocol fan-out."""
        tune_input = _tune_input_from_workflow(
            workflow_env,
            tmp_path,
            formal_round_strategy="llm_propose",
        )
        assert tune_input.formal_round_strategy == "independent"

    def test_formal_round_strategy_legacy_inherit_best_trial_canonicalised(
        self, workflow_env, tmp_path
    ):
        """Symmetric to the ``llm_propose`` alias test: the historical
        ``inherit_best_trial`` literal must surface as ``full_clone`` on
        the tuning input."""
        tune_input = _tune_input_from_workflow(
            workflow_env,
            tmp_path,
            formal_round_strategy="inherit_best_trial",
        )
        assert tune_input.formal_round_strategy == "full_clone"

    def test_signature_accepts_degenerate_penalty_score(self):
        """Step 09.5a C3: transit configuration, so it lives on the launch
        carrier with its default unchanged."""
        import dataclasses

        from workflows.run_config import WorkflowLaunchConfig

        field = next(
            f
            for f in dataclasses.fields(WorkflowLaunchConfig)
            if f.name == "degenerate_penalty_score"
        )
        assert field.default is None

    def test_degenerate_penalty_score_default_is_none(self, workflow_env, tmp_path):
        tune_input = _tune_input_from_workflow(workflow_env, tmp_path)
        assert tune_input.degenerate_penalty_score is None

    def test_degenerate_penalty_score_float_reaches_tuning_input(self, workflow_env, tmp_path):
        tune_input = _tune_input_from_workflow(
            workflow_env,
            tmp_path,
            degenerate_penalty_score=-2.5,
        )
        assert tune_input.degenerate_penalty_score == -2.5


# ---------------------------------------------------------------------------
# L6c — _promote_loss_to_global
# ---------------------------------------------------------------------------
#
# Verifies the promotion helper added in L6c: copy from workspace to
# agent_generated/losses/, content-hash dedup, registry file_path update,
# idempotency, and the action="reused" / built-in / missing-source no-op
# paths. The autouse fixture patches LOSSES_DIR to a tmp dir + clears the
# in-memory LOSS_REGISTRY so tests don't pollute the canonical library.


_L6C_PROMO_PLUGIN_SRC_A = """
import torch
import torch.nn as nn
from pydantic import BaseModel


class _PromoCfg(BaseModel):
    pass


class _PromoLoss(nn.Module):
    def __init__(self, config: _PromoCfg) -> None:
        super().__init__()

    def forward(self, inputs: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        return inputs.mean()


PLUGIN_LOSS_TYPE = "promo_loss_a"
PLUGIN_LOSS_CONFIG_CLASS = _PromoCfg
PLUGIN_LOSS_CLASS = _PromoLoss
"""

_L6C_PROMO_PLUGIN_SRC_B_DIFF_NAME_SAME_CONTENT = _L6C_PROMO_PLUGIN_SRC_A.replace(
    "promo_loss_a", "promo_loss_b"
)
# Note: replacing the PLUGIN_LOSS_TYPE string changes file content, so
# byte-identical dedup needs the SAME content under a DIFFERENT FILE NAME.
# We achieve this by NOT changing the PLUGIN_LOSS_TYPE — same content, just
# saved under a different .py file name.


def _make_impl_output_with_loss_provenance(tmp_path, loss_name="promo_loss_a", action="generated"):
    """Build a minimal ImplementorOutput-shaped object with a real loss file
    on disk for _promote_loss_to_global to consume."""
    from agent.schemas.implementor import ImplementorOutput, LossProvenance

    loss_file = tmp_path / f"{loss_name}.py"
    loss_file.write_text(_L6C_PROMO_PLUGIN_SRC_A)
    model_file = tmp_path / "stub_model.py"
    model_file.write_text(
        "PLUGIN_MODEL_TYPE='stub'\nclass PLUGIN_CONFIG_CLASS: ...\nclass PLUGIN_MODEL_CLASS: ...\n"
    )
    test_file = tmp_path / "test_stub.py"
    test_file.write_text("def test_noop(): pass\n")
    desc_dir = tmp_path / "stub"
    desc_dir.mkdir(exist_ok=True)
    desc_file = desc_dir / "description.md"
    desc_file.write_text("# stub\n")

    impl = ImplementorOutput(
        model_type="stub",
        model_file_path=str(model_file),
        test_file_path=str(test_file),
        description_file_path=str(desc_file),
        config_fields={},
        model_description="x",
        mathematical_definition="x",
        loss_provenance=LossProvenance(
            loss_name=loss_name,
            action=action,
            source_iteration="iter_001",
            loss_file_path=str(loss_file),
            dummy_tensor_validated=True,
        ),
    )
    return impl


@pytest.fixture
def l6c_global_losses_dir(tmp_path, monkeypatch):
    """Redirect LOSSES_DIR to tmp_path/global_losses for promotion tests."""
    from agent_generated import _loss_loader

    target = tmp_path / "global_losses"
    target.mkdir()
    monkeypatch.setattr(_loss_loader, "LOSSES_DIR", str(target))
    return target


class TestL6cPromoteLossToGlobal:
    def test_promotes_generated_loss(self, tmp_path, l6c_global_losses_dir):
        """L6c — _promote_loss_to_global copies the loss .py from the
        workspace-scoped path to the global LOSSES_DIR."""
        from workflows.model_exploration import _promote_loss_to_global

        ws = tmp_path / "ws"
        ws.mkdir()
        impl = _make_impl_output_with_loss_provenance(ws)
        _promote_loss_to_global(impl)
        assert (l6c_global_losses_dir / "promo_loss_a.py").is_file()

    def test_skips_reused(self, tmp_path, l6c_global_losses_dir):
        """L6c — action='reused' is a no-op (already promoted by the
        originating iteration)."""
        from workflows.model_exploration import _promote_loss_to_global

        ws = tmp_path / "ws"
        ws.mkdir()
        impl = _make_impl_output_with_loss_provenance(ws, action="reused")
        _promote_loss_to_global(impl)
        # The source file exists in ws but nothing should land in global
        assert not (l6c_global_losses_dir / "promo_loss_a.py").exists()

    def test_skips_when_loss_provenance_none(self, tmp_path, l6c_global_losses_dir):
        """L6c — None provenance (built-in loss path) is a no-op."""
        from workflows.model_exploration import _promote_loss_to_global

        # Build an impl_output with loss_provenance=None
        class _FakeImpl:
            loss_provenance = None

        _promote_loss_to_global(_FakeImpl())  # must not raise
        assert list(l6c_global_losses_dir.iterdir()) == []

    def test_idempotent_when_dest_exists(self, tmp_path, l6c_global_losses_dir, capsys):
        """L6c — calling promote twice for the same loss only writes once
        and the second call logs 'idempotent skip'."""
        from workflows.model_exploration import _promote_loss_to_global

        ws = tmp_path / "ws"
        ws.mkdir()
        impl = _make_impl_output_with_loss_provenance(ws)
        _promote_loss_to_global(impl)
        capsys.readouterr()  # drain
        _promote_loss_to_global(impl)
        captured = capsys.readouterr()
        assert "idempotent skip" in captured.out.lower() or "already at global path" in captured.out

    def test_skips_when_source_missing(self, tmp_path, l6c_global_losses_dir, capsys):
        """L6c — missing source file is a soft warning, not a raise."""
        from workflows.model_exploration import _promote_loss_to_global

        ws = tmp_path / "ws"
        ws.mkdir()
        impl = _make_impl_output_with_loss_provenance(ws)
        # Delete the source after constructing impl
        os.remove(impl.loss_provenance.loss_file_path)
        _promote_loss_to_global(impl)
        captured = capsys.readouterr()
        assert "source file not found" in captured.out.lower()
        assert not (l6c_global_losses_dir / "promo_loss_a.py").exists()

    def test_promote_skips_identical_content(self, tmp_path, l6c_global_losses_dir, capsys):
        """L6c — SHA256 content-hash dedup. If a file with the same content
        already exists under a different name, promotion skips with a
        warning naming the existing duplicate."""
        from workflows.model_exploration import _promote_loss_to_global

        ws = tmp_path / "ws"
        ws.mkdir()
        # Pre-seed the global library with the same content under a different filename
        global_existing = l6c_global_losses_dir / "promo_loss_b.py"
        global_existing.write_text(_L6C_PROMO_PLUGIN_SRC_A)
        # Now try to promote a "new" loss with byte-identical content
        impl = _make_impl_output_with_loss_provenance(ws, loss_name="promo_loss_a")
        _promote_loss_to_global(impl)
        captured = capsys.readouterr()
        assert "identical content already exists" in captured.out.lower()
        assert "promo_loss_b" in captured.out
        # The new-name file MUST NOT have been copied
        assert not (l6c_global_losses_dir / "promo_loss_a.py").exists()
        # The existing-name file is untouched
        assert global_existing.read_text() == _L6C_PROMO_PLUGIN_SRC_A


# ---------------------------------------------------------------------------
# _validate_construction_memory — guard against T-scaling __init__ allocations
# ---------------------------------------------------------------------------
#
# Added 2026-06-24 after the v15 arch chain was OOM-killed at 53 GB RSS
# during the tuner's VRAM pre-flight. The suspected cause: a generated
# SSM plugin that allocated O(T²) host-RAM buffers in ``__init__``. The
# structural VRAM probe could not catch it because the allocation was in
# CPU host memory, not CUDA. This validator runs at registration time —
# before the tuner starts — and rejects any plugin whose ``__init__``
# allocates more than ``_CONSTRUCTION_RSS_THRESHOLD_GB`` GB of RSS.


class TestValidateConstructionMemory:
    def test_threshold_constant_is_500mb(self):
        """The threshold must stay at 0.5 GB. Loosening it silently would
        let the family of bugs this validator exists to catch slip
        through."""
        assert _CONSTRUCTION_RSS_THRESHOLD_GB == 0.5

    def test_small_model_passes(self):
        """A tiny model whose ``__init__`` allocates ~zero RAM passes —
        prints the [MemCheck] line, returns None, raises nothing."""
        import torch.nn as nn
        from pydantic import BaseModel

        class TinyConfig(BaseModel):
            pass

        class TinyModel(nn.Module):
            def __init__(self, cfg):
                super().__init__()
                # A few KB of params, nothing T-scaling.
                self.lin = nn.Linear(8, 8)

            def forward(self, x):
                return self.lin(x)

        # Should not raise.
        _validate_construction_memory(TinyModel, TinyConfig, "tiny_model")

    def test_large_init_fails(self):
        """A model whose ``__init__`` allocates a multi-GB tensor must
        raise ValueError with the diagnostic message that names T-scaling
        buffers as the likely cause. This is the regression test the
        v15 arch OOM would have caught."""
        import torch
        import torch.nn as nn
        from pydantic import BaseModel

        class BigConfig(BaseModel):
            pass

        class BigModel(nn.Module):
            def __init__(self, cfg):
                super().__init__()
                # 16000 × 16000 float32 = 1 GB — the [T, T] attention/SSM
                # matrix shape the validator exists to forbid.
                # torch.randn (not torch.zeros) — Linux backs zero-filled
                # anonymous mmap with the shared zero page until a write
                # commits real RAM; randn writes during init, matching
                # the commit pattern of every realistic faulty plugin
                # (which inits weights / masks / lookup tables).
                self.bad_buffer = torch.randn(16000, 16000)

            def forward(self, x):
                return x

        with pytest.raises(ValueError, match=r"allocated.*GB during.*__init__"):
            _validate_construction_memory(BigModel, BigConfig, "big_model_test")

    def test_error_message_names_t_scaling_diagnostics(self):
        """The diagnostic line in the error message must point the next
        author at the cause (T-scaling buffers in __init__) and the fix
        (move to forward()). Without these, the error is opaque."""
        import torch
        import torch.nn as nn
        from pydantic import BaseModel

        class BigConfig(BaseModel):
            pass

        class BigModel(nn.Module):
            def __init__(self, cfg):
                super().__init__()
                # torch.randn (not torch.zeros) — Linux backs zero-filled
                # anonymous mmap with the shared zero page until a write
                # commits real RAM; randn writes during init, matching
                # the commit pattern of every realistic faulty plugin
                # (which inits weights / masks / lookup tables).
                self.bad_buffer = torch.randn(16000, 16000)

            def forward(self, x):
                return x

        with pytest.raises(ValueError) as exc:
            _validate_construction_memory(BigModel, BigConfig, "diag_test")
        msg = str(exc.value)
        assert "T-dependent" in msg or "scales with T" in msg
        assert "forward()" in msg
        assert "[B, d_state]" in msg

    def test_construction_crash_raises_valueerror(self):
        """A model whose ``__init__`` raises (any exception) is caught
        and re-raised as ValueError so the iteration loop sees a uniform
        failure shape — never a bare KeyError / AttributeError / etc."""
        import torch.nn as nn
        from pydantic import BaseModel

        class BadConfig(BaseModel):
            pass

        class BadModel(nn.Module):
            def __init__(self, cfg):
                super().__init__()
                raise RuntimeError("intentional construction failure")

            def forward(self, x):
                return x

        with pytest.raises(ValueError, match=r"__init__ raised RuntimeError"):
            _validate_construction_memory(BadModel, BadConfig, "bad_model")

    def test_representative_T_injected_when_schema_accepts_segmentation_size(self):
        """When the config schema declares ``segmentation_size``, the
        validator must inject ``representative_T`` into it — otherwise
        a plugin whose default config has a tiny segmentation_size would
        evade the check even though it allocates [T, T] at the operator's
        real T. Verified by a plugin whose ``__init__`` allocation
        scales with segmentation_size."""
        import torch
        import torch.nn as nn
        from pydantic import BaseModel, Field

        class SegConfig(BaseModel):
            # Default is tiny; the validator must override to 16000.
            segmentation_size: int = Field(default=100, gt=0)

        class SegScaledModel(nn.Module):
            def __init__(self, cfg):
                super().__init__()
                # 16000 * 16000 * 4 = 1 GB only if validator overrides
                # segmentation_size. With default=100 the allocation is
                # 100 * 100 * 4 = 40 KB and the check would pass.
                # randn (not zeros) commits real pages — see comment in
                # test_large_init_fails for the Linux mmap rationale.
                self.buffer = torch.randn(cfg.segmentation_size, cfg.segmentation_size)

            def forward(self, x):
                return x

        with pytest.raises(ValueError, match=r"allocated.*GB during.*__init__"):
            _validate_construction_memory(
                SegScaledModel, SegConfig, "seg_scaled", representative_T=16000
            )

    def test_falls_back_to_defaults_when_representative_T_rejected(self):
        """If ``representative_T`` is out of the schema's declared bounds,
        the validator must fall back to the schema's defaults rather than
        skipping the check entirely. (A tiny default may not trip the
        threshold, but at least we get a real run.)"""
        import torch.nn as nn
        from pydantic import BaseModel, Field

        class CappedConfig(BaseModel):
            # Hard cap at 1000 — representative_T=16000 will be rejected.
            segmentation_size: int = Field(default=500, gt=0, le=1000)

        class TinyAtCap(nn.Module):
            def __init__(self, cfg):
                super().__init__()
                # Small allocation regardless of cfg — should pass.
                self.lin = nn.Linear(8, 8)

            def forward(self, x):
                return self.lin(x)

        # Should not raise; falls back to default (500) instead of bailing.
        _validate_construction_memory(TinyAtCap, CappedConfig, "capped_model")

    def test_passes_loss_type_when_constructor_accepts_it(self):
        """fcnet-style models that accept ``loss_type`` in their
        constructor must receive it from the validator (mirroring
        ``_build_model`` in evaluate_vram_skill). Otherwise the
        validator would crash with a TypeError on every hybrid model."""
        import torch.nn as nn
        from pydantic import BaseModel

        class HybridConfig(BaseModel):
            pass

        received_loss_type: list[str] = []

        class HybridModel(nn.Module):
            def __init__(self, cfg, loss_type: str = "ce"):
                super().__init__()
                received_loss_type.append(loss_type)
                self.lin = nn.Linear(8, 8)

            def forward(self, x):
                return self.lin(x)

        _validate_construction_memory(HybridModel, HybridConfig, "hybrid_model")
        assert received_loss_type == ["focal"]
