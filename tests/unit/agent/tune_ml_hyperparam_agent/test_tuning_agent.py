"""
Tests for nodes/ml_hyperparameter_tune_agent.py

LLM calls and skills are mocked — these tests validate:

  _serialize_expert_advice:
    - String passthrough
    - Empty string passthrough
    - ExpertAdvice with all fields populated
    - ExpertAdvice with only some fields populated
    - ExpertAdvice with no fields populated (empty object)

  HyperparamTuningAgent.run():
    - Returns valid HyperparamTuningOutput
    - Output validates against schema
    - Output file written to correct path
    - Completed status when all rounds finish
    - Partial status when OOM skips exhaust attempts
    - Best score extracted correctly
    - All records included (success + OOM)
    - Expert advice (string) passed to brain.plan()
    - Expert advice (ExpertAdvice) serialized and passed to brain.plan()
    - Run config file written at startup
"""
import json
import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch, call

from agent.schemas.hyperparam_tuning import (
    HyperparamTuningInput,
    HyperparamTuningOutput,
    ExpertAdvice,
)
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from nodes.ml_hyperparameter_tune_agent import (
    HyperparamTuningAgent,
    _serialize_expert_advice,
)


# ---------------------------------------------------------------------------
# _serialize_expert_advice tests
# ---------------------------------------------------------------------------

class TestSerializeExpertAdvice:

    def test_string_passthrough(self):
        assert _serialize_expert_advice("try deeper models") == "try deeper models"

    def test_empty_string_passthrough(self):
        assert _serialize_expert_advice("") == ""

    def test_full_expert_advice(self):
        advice = ExpertAdvice(
            focus_areas=["depth", "width"],
            constraints=["VRAM < 8 GB"],
            known_failures=["batch_size > 8 OOMs"],
            suggested_directions=["try focal loss"],
            rationale="Current model is too shallow.",
        )
        result = _serialize_expert_advice(advice)
        assert "Focus areas: depth; width" in result
        assert "Constraints: VRAM < 8 GB" in result
        assert "Known failures: batch_size > 8 OOMs" in result
        assert "Suggested directions: try focal loss" in result
        assert "Rationale: Current model is too shallow." in result

    def test_partial_expert_advice(self):
        advice = ExpertAdvice(
            focus_areas=["learning rate"],
            constraints=[],
            known_failures=[],
            suggested_directions=[],
            rationale="",
        )
        result = _serialize_expert_advice(advice)
        assert "Focus areas: learning rate" in result
        assert "Constraints" not in result
        assert "Known failures" not in result

    def test_empty_expert_advice(self):
        advice = ExpertAdvice()
        result = _serialize_expert_advice(advice)
        assert result == ""


# ---------------------------------------------------------------------------
# HyperparamTuningAgent.run() tests — fixtures
# ---------------------------------------------------------------------------

FAKE_PLAN_RESPONSE = {
    "model_type": "punet",
    "hypothesis": "Deeper architecture with focal loss should improve score.",
    "reasoning": "Previous runs show depth correlates with score.",
    "model_config": {"depth": 4, "segmentation_size": 40000, "batch_size": 1},
    "train_config": {"epochs": 5, "lr": 1e-4},
    "loss_config": {"loss_type": "focal", "gamma": 2.0},
}

FAKE_REFLECT_RESPONSE = {
    "conclusion": "Score improved with depth=4.",
    "key_factor": "Increased depth.",
    "discovery": "Focal loss gamma=2 works well for this architecture.",
    "memory_update": "Depth 4 is promising, try depth 5 next.",
}

FAKE_CONFIG_MANUAL = {
    "status": "success",
    "data": {"punet": {"fields": ["depth", "segmentation_size"]}},
}

FAKE_RESOURCE_CHECK_OK = {"status": "success", "feasible": True}

FAKE_RESOURCE_CHECK_OOM = {
    "status": "success",
    "feasible": False,
    "estimated_gb": 12.0,
    "limit_gb": 8.0,
    "verdict": "Estimated 12 GB exceeds 8 GB limit.",
    "suggestion": "Reduce batch_size.",
}

FAKE_TRAIN_RESULT = {
    "status": "success",
    "results": {"final_loss": 0.5, "model_params": 100000},
}

FAKE_INFERENCE_RESULT = {"status": "success", "results": {}}

FAKE_SCORE_RESULT = {
    "status": "success",
    "results": {"denoising_score": 1.75, "final_loss": 0.5, "model_params": 100000},
}


def _make_input(tmp_path, max_rounds=1, expert_advice="", model_type="punet"):
    return HyperparamTuningInput(
        model_type=model_type,
        file_index=6,
        max_rounds=max_rounds,
        expert_advice=expert_advice,
        llm_provider="gemini",
        llm_model_id="test-model",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="test_run"),
        ),
        progress_bar=False,
    )


def _mock_run_skill(skill_folder, sandbox, **params):
    """Dispatch fake skill results based on skill_folder."""
    skill_results = {
        "check_config_format_skill": FAKE_CONFIG_MANUAL,
        "evaluate_resource_skill": FAKE_RESOURCE_CHECK_OK,
        "training_skill": FAKE_TRAIN_RESULT,
        "inference_skill": FAKE_INFERENCE_RESULT,
        "denoising_score_skill": FAKE_SCORE_RESULT,
    }
    return skill_results.get(skill_folder, {"status": "error", "message": "unknown skill"})


# ---------------------------------------------------------------------------
# HyperparamTuningAgent.run() tests
# ---------------------------------------------------------------------------

class TestHyperparamTuningAgentRun:

    @pytest.fixture
    def agent_and_mocks(self):
        with patch("nodes.ml_hyperparameter_tune_agent.LLMBridge") as MockBridge, \
             patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox") as MockSandbox, \
             patch("nodes.ml_hyperparameter_tune_agent._run_skill", side_effect=_mock_run_skill), \
             tempfile.TemporaryDirectory() as configs_dir:

            mock_brain = MockBridge.return_value
            mock_brain.plan.return_value = FAKE_PLAN_RESPONSE
            mock_brain.reflect.return_value = FAKE_REFLECT_RESPONSE

            # Track saved records so get_summary returns them
            saved_records = []
            mock_sandbox = MockSandbox.return_value
            mock_sandbox.get_summary.side_effect = lambda: list(saved_records)
            mock_sandbox.save_record.side_effect = lambda r: saved_records.append(r)
            mock_sandbox.dirs = {"configs": configs_dir}

            agent = HyperparamTuningAgent()
            yield agent, mock_brain, mock_sandbox

    def test_returns_valid_output(self, agent_and_mocks, tmp_path):
        agent, _, _ = agent_and_mocks
        output = agent.run(_make_input(tmp_path))
        assert isinstance(output, HyperparamTuningOutput)

    def test_output_validates_against_schema(self, agent_and_mocks, tmp_path):
        agent, _, _ = agent_and_mocks
        output = agent.run(_make_input(tmp_path))
        # Re-validate to confirm schema compliance
        HyperparamTuningOutput.model_validate(output.model_dump())

    def test_completed_status(self, agent_and_mocks, tmp_path):
        agent, _, _ = agent_and_mocks
        output = agent.run(_make_input(tmp_path, max_rounds=1))
        assert output.status == "completed"
        assert output.completed_rounds == 1

    def test_best_score_extracted(self, agent_and_mocks, tmp_path):
        agent, _, _ = agent_and_mocks
        output = agent.run(_make_input(tmp_path))
        assert output.best_denoising_score == 1.75

    def test_best_config_present(self, agent_and_mocks, tmp_path):
        agent, _, _ = agent_and_mocks
        output = agent.run(_make_input(tmp_path))
        assert output.best_config is not None
        assert output.best_config["model_type"] == "punet"

    def test_all_records_included(self, agent_and_mocks, tmp_path):
        agent, _, _ = agent_and_mocks
        output = agent.run(_make_input(tmp_path, max_rounds=2))
        assert output.completed_rounds == 2
        assert len(output.all_records) == 2

    def test_output_file_written(self, agent_and_mocks, tmp_path):
        agent, _, _ = agent_and_mocks
        agent.run(_make_input(tmp_path))
        output_path = tmp_path / "run_output_test_run.json"
        assert output_path.exists()
        data = json.loads(output_path.read_text())
        assert data["status"] == "completed"

    def test_run_config_file_written(self, agent_and_mocks, tmp_path):
        agent, _, _ = agent_and_mocks
        agent.run(_make_input(tmp_path))
        config_path = tmp_path / "run_config_test_run.json"
        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert data["force_model"] == "punet"
        assert data["max_rounds"] == 1

    def test_string_expert_advice_passed_to_plan(self, agent_and_mocks, tmp_path):
        agent, mock_brain, _ = agent_and_mocks
        agent.run(_make_input(tmp_path, expert_advice="focus on depth"))
        mock_brain.plan.assert_called_once()
        _, kwargs = mock_brain.plan.call_args
        assert kwargs["expert_advice"] == "focus on depth"

    def test_structured_expert_advice_serialized(self, agent_and_mocks, tmp_path):
        agent, mock_brain, _ = agent_and_mocks
        advice = ExpertAdvice(
            focus_areas=["depth"],
            constraints=["VRAM < 8 GB"],
        )
        agent.run(_make_input(tmp_path, expert_advice=advice))
        mock_brain.plan.assert_called_once()
        _, kwargs = mock_brain.plan.call_args
        assert "Focus areas: depth" in kwargs["expert_advice"]
        assert "Constraints: VRAM < 8 GB" in kwargs["expert_advice"]

    def test_model_type_in_output(self, agent_and_mocks, tmp_path):
        agent, _, _ = agent_and_mocks
        output = agent.run(_make_input(tmp_path, model_type="fcnet"))
        assert output.model_type == "fcnet"

    def test_timing_fields_present(self, agent_and_mocks, tmp_path):
        agent, _, _ = agent_and_mocks
        output = agent.run(_make_input(tmp_path))
        assert output.started_at
        assert output.finished_at

    def test_run_name_in_output(self, agent_and_mocks, tmp_path):
        agent, _, _ = agent_and_mocks
        output = agent.run(_make_input(tmp_path))
        assert output.run_name == "test_run"


class TestHyperparamTuningAgentOOM:
    """Tests for OOM-skip behaviour within run()."""

    @pytest.fixture
    def agent_oom(self):
        with patch("nodes.ml_hyperparameter_tune_agent.LLMBridge") as MockBridge, \
             patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox") as MockSandbox, \
             patch("nodes.ml_hyperparameter_tune_agent._run_skill") as mock_skill, \
             tempfile.TemporaryDirectory() as configs_dir:

            mock_brain = MockBridge.return_value
            mock_brain.plan.return_value = FAKE_PLAN_RESPONSE
            mock_brain.reflect.return_value = FAKE_REFLECT_RESPONSE

            saved_records = []
            mock_sandbox = MockSandbox.return_value
            mock_sandbox.get_summary.side_effect = lambda: list(saved_records)
            mock_sandbox.save_record.side_effect = lambda r: saved_records.append(r)
            mock_sandbox.dirs = {"configs": configs_dir}

            # All resource checks return OOM
            def all_oom(skill_folder, sandbox, **params):
                if skill_folder == "check_config_format_skill":
                    return FAKE_CONFIG_MANUAL
                return FAKE_RESOURCE_CHECK_OOM

            mock_skill.side_effect = all_oom

            agent = HyperparamTuningAgent()
            yield agent, mock_brain, mock_sandbox, saved_records

    def test_partial_status_on_all_oom(self, agent_oom, tmp_path):
        agent, _, _, _ = agent_oom
        output = agent.run(_make_input(tmp_path, max_rounds=2))
        assert output.status == "partial"
        assert output.completed_rounds == 0

    def test_oom_records_saved(self, agent_oom, tmp_path):
        agent, _, _, saved_records = agent_oom
        agent.run(_make_input(tmp_path, max_rounds=1))
        # max_rounds=1 → max_attempts=3, all OOM → 3 records saved
        assert len(saved_records) == 3
        assert all(r["status"] == "skipped_oom_risk" for r in saved_records)

    def test_oom_record_has_expert_advice(self, agent_oom, tmp_path):
        agent, _, _, saved_records = agent_oom
        agent.run(_make_input(tmp_path, max_rounds=1, expert_advice="test advice"))
        assert saved_records[0]["memory"]["expert_advice_followed"] == "test advice"


# ---------------------------------------------------------------------------
# Dynamic trial/formal control tests
# ---------------------------------------------------------------------------

FAKE_PLAN_WITH_TRIAL = {
    **FAKE_PLAN_RESPONSE,
    "is_trial": True,
    "trial_strategy": "snapshot",
    "trial_portion": 0.1,
}


def _make_trial_input(tmp_path, max_rounds=1, is_trial=True):
    return HyperparamTuningInput(
        model_type="punet",
        file_index=6,
        max_rounds=max_rounds,
        is_trial=is_trial,
        expert_advice="",
        llm_provider="gemini",
        llm_model_id="test-model",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="test_run"),
        ),
        progress_bar=False,
    )


FAKE_SCORE_VECTOR_RESULT = ([float("nan")] * 20, 1.5)


class TestDynamicTrialFormal:
    """Tests for per-round trial/formal decision logic."""

    @pytest.fixture
    def agent_and_mocks(self):
        with patch("nodes.ml_hyperparameter_tune_agent.LLMBridge") as MockBridge, \
             patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox") as MockSandbox, \
             patch("nodes.ml_hyperparameter_tune_agent._run_skill", side_effect=_mock_run_skill), \
             patch("nodes.ml_hyperparameter_tune_agent.load_anchor_map") as mock_anchor, \
             patch("nodes.ml_hyperparameter_tune_agent.score_vector", return_value=FAKE_SCORE_VECTOR_RESULT), \
             patch("os.path.exists", return_value=True), \
             tempfile.TemporaryDirectory() as configs_dir:

            mock_brain = MockBridge.return_value
            mock_brain.plan.return_value = FAKE_PLAN_WITH_TRIAL
            mock_brain.reflect.return_value = FAKE_REFLECT_RESPONSE

            mock_anchor.return_value = {"anchors": {}, "s_max": 1.0}

            saved_records = []
            mock_sandbox = MockSandbox.return_value
            mock_sandbox.get_summary.side_effect = lambda: list(saved_records)
            mock_sandbox.save_record.side_effect = lambda r: saved_records.append(r)
            mock_sandbox.dirs = {"configs": configs_dir, "data": configs_dir}

            agent = HyperparamTuningAgent()
            yield agent, mock_brain, mock_sandbox, saved_records

    def test_final_round_always_formal(self, agent_and_mocks, tmp_path):
        """max_rounds=1 + LLM returns is_trial=True → formal mode enforced."""
        agent, mock_brain, _, saved_records = agent_and_mocks
        mock_brain.plan.return_value = FAKE_PLAN_WITH_TRIAL
        output = agent.run(_make_trial_input(tmp_path, max_rounds=1, is_trial=True))
        assert output.status == "completed"
        # Final round forced formal — record should NOT have is_trial=True
        assert saved_records[0].get("is_trial", False) is False

    def test_trial_allowed_false_forces_formal(self, agent_and_mocks, tmp_path):
        """is_trial=False on input → all rounds formal, LLM's is_trial ignored."""
        agent, mock_brain, _, saved_records = agent_and_mocks
        mock_brain.plan.return_value = FAKE_PLAN_WITH_TRIAL
        output = agent.run(_make_trial_input(tmp_path, max_rounds=1, is_trial=False))
        assert output.status == "completed"
        assert saved_records[0].get("is_trial", False) is False

    def test_round_context_passed_to_plan(self, agent_and_mocks, tmp_path):
        """Verify brain.plan() receives current_round and max_rounds kwargs."""
        agent, mock_brain, _, _ = agent_and_mocks
        agent.run(_make_trial_input(tmp_path, max_rounds=1, is_trial=True))
        call_kwargs = mock_brain.plan.call_args
        assert call_kwargs.kwargs.get("current_round") is not None
        assert call_kwargs.kwargs.get("max_rounds") is not None
        assert call_kwargs.kwargs.get("trial_allowed") is True

    def test_invalid_trial_fields_fallback(self, agent_and_mocks, tmp_path):
        """LLM returns trial_portion=5.0 → ExperimentPlan.with_defaults falls back."""
        agent, mock_brain, _, saved_records = agent_and_mocks
        bad_plan = {**FAKE_PLAN_RESPONSE, "trial_portion": 5.0, "is_trial": True}
        mock_brain.plan.return_value = bad_plan
        # max_rounds=1 → final round → formal anyway, but should not crash
        output = agent.run(_make_trial_input(tmp_path, max_rounds=1, is_trial=True))
        assert output.status == "completed"

    def test_trial_config_written(self, agent_and_mocks, tmp_path):
        """Verify trial_config_{exp_id}.json is written with correct fields."""
        agent, mock_brain, mock_sandbox, _ = agent_and_mocks
        configs_dir = mock_sandbox.dirs["configs"]
        agent.run(_make_trial_input(tmp_path, max_rounds=1, is_trial=True))
        # Find the trial_config file
        trial_configs = [f for f in os.listdir(configs_dir) if f.startswith("trial_config_")]
        assert len(trial_configs) >= 1, "trial_config file not written"
        with open(os.path.join(configs_dir, trial_configs[0])) as f:
            tc = json.load(f)
        assert "is_trial" in tc
        assert "mode" in tc
        assert "train_portion" in tc

    def test_inference_receives_eval_sample_set(self, agent_and_mocks, tmp_path):
        """Verify inference skill receives eval_sample_set, not train sample_set."""
        agent, _, _, _ = agent_and_mocks
        skill_calls = []
        original_mock = _mock_run_skill

        def tracking_mock(skill_folder, sandbox, **params):
            skill_calls.append((skill_folder, params))
            return original_mock(skill_folder, sandbox, **params)

        with patch("nodes.ml_hyperparameter_tune_agent._run_skill", side_effect=tracking_mock):
            agent.run(_make_trial_input(tmp_path, max_rounds=1, is_trial=True))

        # Find inference call
        inference_calls = [(f, p) for f, p in skill_calls if f == "inference_skill"]
        assert len(inference_calls) >= 1, "inference_skill not called"
        inf_params = inference_calls[0][1]
        assert "eval_sample_set" in inf_params, "eval_sample_set not passed to inference"

    def test_formal_round_splits_train_eval(self, agent_and_mocks, tmp_path):
        """Formal round: train_sample_set should be sparse, eval_sample_set should be full."""
        agent, _, _, _ = agent_and_mocks
        skill_calls = []
        original_mock = _mock_run_skill

        def tracking_mock(skill_folder, sandbox, **params):
            skill_calls.append((skill_folder, params))
            return original_mock(skill_folder, sandbox, **params)

        with patch("nodes.ml_hyperparameter_tune_agent._run_skill", side_effect=tracking_mock), \
             patch("nodes.ml_hyperparameter_tune_agent.build_sample_set") as mock_build:
            # build_sample_set called with different portions for train vs eval
            call_count = [0]
            def fake_build(**kwargs):
                call_count[0] += 1
                # Return a minimal valid-looking SampleSet
                return {0: [0, 1], 6: [0, 1]}
            mock_build.side_effect = fake_build

            agent.run(_make_trial_input(tmp_path, max_rounds=1, is_trial=True))

            # Final round (max_rounds=1) → formal mode → build_sample_set called twice:
            # once for train (train_portion), once for eval (portion=1.0)
            build_calls = mock_build.call_args_list
            assert len(build_calls) == 2, f"Expected 2 build_sample_set calls for formal, got {len(build_calls)}"
            # First call: train (portion = train_portion default 0.1)
            assert build_calls[0].kwargs.get("trial_portion") == 0.1
            # Second call: eval (portion = 1.0)
            assert build_calls[1].kwargs.get("trial_portion") == 1.0
