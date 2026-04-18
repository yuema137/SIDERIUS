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
    _copy_seed_plugin,
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

FAKE_RESOURCE_CHECK_OK = {
    "status": "success",
    "feasible": True,
    "estimated_gb": 2.5,
    "limit_gb": 6.0,
    "vram_budget_gb": 8.0,
    "verdict": "FITS",
    "suggestion": "",
}

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
    "results": {"denoising_score": 1.75},
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
        "evaluate_vram_skill": FAKE_RESOURCE_CHECK_OK,
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
            mock_sandbox.score_vector.return_value = FAKE_SCORE_VECTOR_RESULT

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

    def test_formal_round_builds_two_sample_sets(self, agent_and_mocks, tmp_path):
        """Formal round: two build_sample_set calls — one for train, one for eval.
        Eval has portion=1.0, train has trial_portion (default 0.02)."""
        agent, _, _, _ = agent_and_mocks
        skill_calls = []
        original_mock = _mock_run_skill

        def tracking_mock(skill_folder, sandbox, **params):
            skill_calls.append((skill_folder, params))
            return original_mock(skill_folder, sandbox, **params)

        with patch("nodes.ml_hyperparameter_tune_agent._run_skill", side_effect=tracking_mock), \
             patch("nodes.ml_hyperparameter_tune_agent.build_sample_set") as mock_build:
            mock_build.return_value = {0: [0, 1], 6: [0, 1]}

            agent.run(_make_trial_input(tmp_path, max_rounds=1, is_trial=True))

            # Final round (max_rounds=1) → formal mode → two build_sample_set calls:
            # one for training scope, one for eval scope (portion=1.0)
            build_calls = mock_build.call_args_list
            assert len(build_calls) == 2, f"Expected 2 build_sample_set calls for formal, got {len(build_calls)}"
            # One call should have portion=1.0 (eval)
            portions = [c.kwargs.get("trial_portion") for c in build_calls]
            assert 1.0 in portions, f"Expected eval portion=1.0, got {portions}"

            # Training skill receives train_portion
            train_calls = [(f, p) for f, p in skill_calls if f == "training_skill"]
            assert len(train_calls) >= 1
            assert train_calls[0][1].get("train_portion") == 0.1


# ---------------------------------------------------------------------------
# [Step 0.5/3] Time-budget gate (Phase E1)
#
# evaluate_time_skill is called after the VRAM check. Mirrors the VRAM gate's
# error/feasible/infeasible structure exactly:
#   - status="error"   → RuntimeError, kills the round.
#   - feasible=True    → training proceeds.
#   - feasible=False   → emit skipped_time_risk record, continue (no round consumed).
#   - budget=None      → skill not called at all (one-time warning at startup).
# See docs/resource_estimator_implement.md §2.7 / E1.
# ---------------------------------------------------------------------------

FAKE_TIME_CHECK_OK = {
    "status": "success",
    "feasible": True,
    "estimated_minutes": 12.0,
    "limit_minutes": 30.0,
    "verdict": "FITS",
    "suggestion": "",
}

FAKE_TIME_CHECK_OVER = {
    "status": "success",
    "feasible": False,
    "estimated_minutes": 90.0,
    "limit_minutes": 30.0,
    "verdict": "OVER BUDGET — Est 90.0 min vs budget 30.0 min.",
    "suggestion": "Reduce model depth/width.",
}


def _make_input_with_budget(
    tmp_path,
    *,
    max_rounds=1,
    trial_budget=None,
    formal_budget=None,
    trial_vram_budget=None,
    formal_vram_budget=None,
    data_dir=None,
    is_trial=False,
):
    """Phase I/K: helper takes both time budgets and both VRAM budgets
    independently.

    The default ``FAKE_PLAN_RESPONSE`` has no ``is_trial`` key so the LLM-side
    plan defaults to formal mode → tests passing only ``formal_budget`` will
    exercise the gate. To exercise the trial branch, set ``is_trial=True``
    here AND override ``mock_brain.plan.return_value`` to include
    ``"is_trial": True``."""
    return HyperparamTuningInput(
        model_type="punet",
        file_index=6,
        max_rounds=max_rounds,
        expert_advice="",
        llm_provider="gemini",
        llm_model_id="test-model",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="test_run"),
        ),
        progress_bar=False,
        trial_time_budget_minutes=trial_budget,
        formal_time_budget_minutes=formal_budget,
        trial_vram_budget_gb=trial_vram_budget,
        formal_vram_budget_gb=formal_vram_budget,
        data_dir=data_dir,
        is_trial=is_trial,
    )


class TestTimeBudgetGate:
    """Phase E1 — tuner round-gate behaviour."""

    def _make_agent(self, time_check_result, *, enable_trial_mode=False):
        """Patch context with controllable time-check return value.

        When ``enable_trial_mode=True``, also patches the anchor-map loader
        and ``os.path.exists`` (and adds ``data`` to ``mock_sandbox.dirs``)
        so the agent's pre-loop trial-mode bootstrap (`segment_anchors.json`
        existence check) doesn't crash. Required by Phase I per-mode tests
        where ``HyperparamTuningInput.is_trial=True`` flips ``trial_allowed``."""
        cm_brain = patch("nodes.ml_hyperparameter_tune_agent.LLMBridge")
        cm_sandbox = patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox")
        cm_skill = patch("nodes.ml_hyperparameter_tune_agent._run_skill")
        cm_tmp = tempfile.TemporaryDirectory()
        cm_anchor = (patch("nodes.ml_hyperparameter_tune_agent.load_anchor_map")
                     if enable_trial_mode else None)
        cm_exists = (patch("os.path.exists", return_value=True)
                     if enable_trial_mode else None)

        MockBridge = cm_brain.__enter__()
        MockSandbox = cm_sandbox.__enter__()
        mock_skill = cm_skill.__enter__()
        configs_dir = cm_tmp.__enter__()
        if cm_anchor is not None:
            mock_anchor = cm_anchor.__enter__()
            mock_anchor.return_value = {"anchors": {}, "s_max": 1.0}
        if cm_exists is not None:
            cm_exists.__enter__()

        mock_brain = MockBridge.return_value
        mock_brain.plan.return_value = FAKE_PLAN_RESPONSE
        mock_brain.reflect.return_value = FAKE_REFLECT_RESPONSE

        saved_records = []
        skill_calls = []
        mock_sandbox = MockSandbox.return_value
        mock_sandbox.get_summary.side_effect = lambda: list(saved_records)
        mock_sandbox.save_record.side_effect = lambda r: saved_records.append(r)
        mock_sandbox.dirs = (
            {"configs": configs_dir, "data": configs_dir}
            if enable_trial_mode
            else {"configs": configs_dir}
        )
        if enable_trial_mode:
            # Trial-mode rounds compute a per-file score vector (one entry
            # per anchor file) before scalar reduction; the formal path
            # bypasses this. Mock it to a deterministic 2-tuple so the
            # round completes without the per-file scoring branch crashing.
            mock_sandbox.score_vector.return_value = FAKE_SCORE_VECTOR_RESULT

        def dispatch(skill_folder, sandbox, **params):
            skill_calls.append((skill_folder, params))
            if skill_folder == "check_config_format_skill":
                return FAKE_CONFIG_MANUAL
            if skill_folder == "evaluate_vram_skill":
                return FAKE_RESOURCE_CHECK_OK
            if skill_folder == "evaluate_time_skill":
                return time_check_result
            if skill_folder == "training_skill":
                return FAKE_TRAIN_RESULT
            if skill_folder == "inference_skill":
                return FAKE_INFERENCE_RESULT
            if skill_folder == "denoising_score_skill":
                return FAKE_SCORE_RESULT
            return {"status": "error", "message": f"unknown skill {skill_folder}"}

        mock_skill.side_effect = dispatch

        agent = HyperparamTuningAgent()

        def cleanup():
            if cm_exists is not None:
                cm_exists.__exit__(None, None, None)
            if cm_anchor is not None:
                cm_anchor.__exit__(None, None, None)
            cm_brain.__exit__(None, None, None)
            cm_sandbox.__exit__(None, None, None)
            cm_skill.__exit__(None, None, None)
            cm_tmp.__exit__(None, None, None)

        return agent, mock_brain, mock_sandbox, saved_records, skill_calls, cleanup

    # --- happy path ---------------------------------------------------------

    def test_feasible_proceeds_to_training(self, tmp_path):
        agent, _, _, saved_records, skill_calls, cleanup = self._make_agent(
            FAKE_TIME_CHECK_OK
        )
        try:
            output = agent.run(
                _make_input_with_budget(tmp_path, formal_budget=30.0)
            )
        finally:
            cleanup()
        assert output.status == "completed"
        assert output.completed_rounds == 1
        # Training was called and the saved record is a success
        called_skills = [s for s, _ in skill_calls]
        assert "training_skill" in called_skills
        assert saved_records[0]["status"] == "success"

    def test_skill_receives_budget_and_data_dir(self, tmp_path):
        """Default plan is formal (no is_trial in FAKE_PLAN_RESPONSE) → the
        per-round pick lands on formal_budget; the skill's single
        time_budget_minutes kwarg carries that value."""
        agent, _, _, _, skill_calls, cleanup = self._make_agent(FAKE_TIME_CHECK_OK)
        try:
            agent.run(_make_input_with_budget(
                tmp_path,
                formal_budget=45.0,
                data_dir="/mnt/tidmad",
            ))
        finally:
            cleanup()
        time_calls = [p for s, p in skill_calls if s == "evaluate_time_skill"]
        assert len(time_calls) == 1
        assert time_calls[0]["time_budget_minutes"] == 45.0
        assert time_calls[0]["data_dir"] == "/mnt/tidmad"

    # --- infeasible path ----------------------------------------------------

    def test_infeasible_emits_skipped_record(self, tmp_path):
        agent, _, _, saved_records, skill_calls, cleanup = self._make_agent(
            FAKE_TIME_CHECK_OVER
        )
        try:
            output = agent.run(_make_input_with_budget(
                tmp_path, max_rounds=1, formal_budget=30.0
            ))
        finally:
            cleanup()
        # All 3 attempts hit the time gate → 3 skipped_time_risk records, 0 rounds completed
        assert output.status == "partial"
        assert output.completed_rounds == 0
        assert all(r["status"] == "skipped_time_risk" for r in saved_records)
        # Training was never called
        assert not any(s == "training_skill" for s, _ in skill_calls)

    def test_skipped_record_carries_suggestion(self, tmp_path):
        agent, _, _, saved_records, _, cleanup = self._make_agent(FAKE_TIME_CHECK_OVER)
        try:
            agent.run(_make_input_with_budget(
                tmp_path, max_rounds=1, formal_budget=30.0
            ))
        finally:
            cleanup()
        rec = saved_records[0]
        assert rec["memory"]["memory_update"] == "Reduce model depth/width."
        assert "OVER BUDGET" in rec["memory"]["discovery"]
        # Conclusion mentions both the estimate and the budget
        assert "90.0" in rec["memory"]["conclusion"]
        assert "30.0" in rec["memory"]["conclusion"]

    # --- error path ---------------------------------------------------------

    def test_error_status_does_not_skip_silently(self, tmp_path):
        """status=error from the skill must propagate as a Loop Error (caught
        by the outer try/except) — it must NOT be treated as feasible=True."""
        agent, _, _, saved_records, skill_calls, cleanup = self._make_agent(
            {"status": "error", "message": "instantiation failed"}
        )
        try:
            output = agent.run(_make_input_with_budget(
                tmp_path, max_rounds=1, formal_budget=30.0
            ))
        finally:
            cleanup()
        # The RuntimeError is caught by the loop's try/except → no rounds complete,
        # no records saved (training never reached, no skipped_time_risk emitted
        # because status was error not infeasible).
        assert output.completed_rounds == 0
        assert not any(s == "training_skill" for s, _ in skill_calls)
        assert not saved_records

    # --- gate-disabled path -------------------------------------------------

    def test_none_budget_skips_skill_entirely(self, tmp_path):
        """Both budgets None → evaluate_time_skill is never called and
        training proceeds (one-time warning per mode printed at startup)."""
        agent, _, _, saved_records, skill_calls, cleanup = self._make_agent(
            FAKE_TIME_CHECK_OVER  # would block if invoked
        )
        try:
            output = agent.run(
                _make_input_with_budget(tmp_path)  # both budgets default None
            )
        finally:
            cleanup()
        assert output.status == "completed"
        assert output.completed_rounds == 1
        called_skills = [s for s, _ in skill_calls]
        assert "evaluate_time_skill" not in called_skills
        assert "training_skill" in called_skills

    # --- Phase I: per-mode budget pick at the per-round gate ----------------

    def test_trial_mode_round_picks_trial_budget(self, tmp_path):
        """plan.is_trial=True → the per-round gate calls the skill with the
        trial budget. The formal budget is ignored even when set.

        Note: max_rounds=2 is required because the agent forces the FINAL
        round to formal mode (`max_rounds=1` would always run formal). The
        first round honours the LLM's is_trial=True so the per-mode pick is
        actually exercised."""
        agent, mock_brain, _, _, skill_calls, cleanup = self._make_agent(
            FAKE_TIME_CHECK_OK, enable_trial_mode=True,
        )
        # Override the default plan to return is_trial=True for this round.
        mock_brain.plan.return_value = {**FAKE_PLAN_RESPONSE, "is_trial": True}
        try:
            agent.run(_make_input_with_budget(
                tmp_path,
                max_rounds=2,
                trial_budget=15.0,
                formal_budget=240.0,
                is_trial=True,  # mirrors LLM plan: caller permits trial mode
            ))
        finally:
            cleanup()
        time_calls = [p for s, p in skill_calls if s == "evaluate_time_skill"]
        # First round runs as trial → trial budget. Second (final) round is
        # forced formal → formal budget. We assert specifically on the trial
        # round to keep the per-mode pick check unambiguous.
        assert len(time_calls) == 2
        assert time_calls[0]["time_budget_minutes"] == 15.0

    def test_formal_mode_round_picks_formal_budget(self, tmp_path):
        """plan.is_trial=False (default) → the per-round gate calls the skill
        with the formal budget. The trial budget is ignored even when set."""
        agent, _, _, _, skill_calls, cleanup = self._make_agent(FAKE_TIME_CHECK_OK)
        try:
            agent.run(_make_input_with_budget(
                tmp_path,
                trial_budget=15.0,
                formal_budget=240.0,
            ))
        finally:
            cleanup()
        time_calls = [p for s, p in skill_calls if s == "evaluate_time_skill"]
        assert len(time_calls) == 1
        assert time_calls[0]["time_budget_minutes"] == 240.0

    def test_trial_round_with_only_formal_budget_skips_gate(self, tmp_path):
        """LLM picks trial mode but only formal_budget is set → trial gate
        disabled for the trial round, skill never called for that round.

        max_rounds=1 + is_trial=True forces final-round-formal, so we use
        max_rounds=2 to actually get a trial round. The trial round must
        skip the gate; the final formal round will hit it (formal_budget
        is set), but FAKE_TIME_CHECK_OVER would block it — we assert that
        only ONE evaluate_time_skill call happens (the formal one), not
        two — confirming the trial round bypassed the gate."""
        agent, mock_brain, _, _, skill_calls, cleanup = self._make_agent(
            FAKE_TIME_CHECK_OK,  # final formal round passes
            enable_trial_mode=True,
        )
        mock_brain.plan.return_value = {**FAKE_PLAN_RESPONSE, "is_trial": True}
        try:
            output = agent.run(_make_input_with_budget(
                tmp_path,
                max_rounds=2,
                formal_budget=240.0,  # trial_budget left None
                is_trial=True,
            ))
        finally:
            cleanup()
        assert output.status == "completed"
        time_calls = [p for s, p in skill_calls if s == "evaluate_time_skill"]
        # Only the final (formal) round invokes the skill — the trial round
        # bypassed it because trial_budget was None.
        assert len(time_calls) == 1
        assert time_calls[0]["time_budget_minutes"] == 240.0

    def test_formal_round_with_only_trial_budget_skips_gate(self, tmp_path):
        """LLM defaults to formal but only trial_budget is set → formal gate
        disabled for this round, skill never called, training proceeds."""
        agent, _, _, _, skill_calls, cleanup = self._make_agent(
            FAKE_TIME_CHECK_OVER  # would block if invoked
        )
        try:
            output = agent.run(_make_input_with_budget(
                tmp_path,
                trial_budget=5.0,  # formal_budget left None
            ))
        finally:
            cleanup()
        assert output.status == "completed"
        called_skills = [s for s, _ in skill_calls]
        assert "evaluate_time_skill" not in called_skills
        assert "training_skill" in called_skills

    # --- Phase J: success-record carries time-estimator memory --------------
    #
    # When the gate passes, the success record's memory block must surface the
    # pre-flight estimate, the active budget, and the mode so the next planner
    # round sees them via experiment_history. When the gate is disabled (both
    # budgets None), the keys must be absent — not None — so the reflector
    # doesn't have to filter them. See docs/resource_estimator_implement.md §J.1.

    def test_success_record_memory_carries_time_fields_formal(self, tmp_path):
        """Gate-pass in formal mode → memory carries the three time fields
        sourced from the time_check dict and time_mode='formal'."""
        agent, _, _, saved_records, _, cleanup = self._make_agent(
            FAKE_TIME_CHECK_OK
        )
        try:
            agent.run(_make_input_with_budget(tmp_path, formal_budget=30.0))
        finally:
            cleanup()
        rec = saved_records[0]
        assert rec["status"] == "success"
        mem = rec["memory"]
        assert mem["time_estimate_minutes"] == 12.0   # FAKE_TIME_CHECK_OK
        assert mem["time_budget_minutes"] == 30.0
        assert mem["time_mode"] == "formal"

    def test_success_record_memory_time_mode_trial(self, tmp_path):
        """Gate-pass in trial mode → time_mode='trial' and the carried budget
        matches the trial budget (not the formal one). max_rounds=2 because
        the agent forces the FINAL round to formal — we assert on the first
        (trial) record."""
        agent, mock_brain, _, saved_records, _, cleanup = self._make_agent(
            FAKE_TIME_CHECK_OK, enable_trial_mode=True,
        )
        mock_brain.plan.return_value = {**FAKE_PLAN_RESPONSE, "is_trial": True}
        try:
            agent.run(_make_input_with_budget(
                tmp_path,
                max_rounds=2,
                trial_budget=15.0,
                formal_budget=240.0,
                is_trial=True,
            ))
        finally:
            cleanup()
        # First saved record is the trial round (FAKE_TIME_CHECK_OK reports
        # limit_minutes=30.0 regardless of which budget was actually picked,
        # because it's a fixed fake — what we care about here is time_mode).
        trial_rec = saved_records[0]
        assert trial_rec["status"] == "success"
        assert trial_rec["memory"]["time_mode"] == "trial"
        assert trial_rec["memory"]["time_estimate_minutes"] == 12.0

    def test_success_record_omits_time_fields_when_gate_disabled(self, tmp_path):
        """Both budgets None → gate skipped entirely → the three time keys
        must be ABSENT from the saved record's memory dict (not present with
        None values), so the reflector sees the same shape as pre-Phase-J
        records."""
        agent, _, _, saved_records, _, cleanup = self._make_agent(
            FAKE_TIME_CHECK_OK
        )
        try:
            agent.run(_make_input_with_budget(tmp_path))  # both None
        finally:
            cleanup()
        rec = saved_records[0]
        assert rec["status"] == "success"
        mem = rec["memory"]
        assert "time_estimate_minutes" not in mem
        assert "time_budget_minutes" not in mem
        assert "time_mode" not in mem

    def test_skipped_time_risk_record_carries_time_fields(self, tmp_path):
        """Phase J §J.3 — the skipped_time_risk record must carry the same
        three time fields as the success record, so the planner sees the
        same shape regardless of pass/fail. Default plan is formal."""
        agent, _, _, saved_records, _, cleanup = self._make_agent(
            FAKE_TIME_CHECK_OVER
        )
        try:
            agent.run(_make_input_with_budget(
                tmp_path, max_rounds=1, formal_budget=30.0,
            ))
        finally:
            cleanup()
        rec = saved_records[0]
        assert rec["status"] == "skipped_time_risk"
        mem = rec["memory"]
        # Values come from FAKE_TIME_CHECK_OVER
        assert mem["time_estimate_minutes"] == 90.0
        assert mem["time_budget_minutes"] == 30.0
        assert mem["time_mode"] == "formal"


# ---------------------------------------------------------------------------
# [Pre-flight 1/2] VRAM-budget gate (Phase K)
#
# evaluate_vram_skill runs BEFORE evaluate_time_skill. Mirrors the time gate's
# shape with one key difference: the VRAM skill ALWAYS runs (it still enforces
# the defensive free×0.8 floor even without a budget); the budget only tightens
# the ceiling. The memory-field guard is keyed on chosen_vram_budget is not
# None — when absent, vram_*_gb fields are omitted from the saved record.
# See docs/resource_estimator_implement.md §10.4 / §10.7 / §10.8.
# ---------------------------------------------------------------------------


FAKE_RESOURCE_CHECK_OVER = {
    "status": "success",
    "feasible": False,
    "estimated_gb": 12.0,
    "limit_gb": 8.0,
    "vram_budget_gb": 8.0,
    "verdict": "OOM RISK — Estimated 12 GB exceeds 8 GB limit.",
    "suggestion": "Reduce batch_size.",
}


class TestVramBudgetGate:
    """Phase K — per-mode VRAM-budget pick + memory propagation."""

    def _make_agent(
        self,
        vram_check_result=FAKE_RESOURCE_CHECK_OK,
        *,
        time_check_result=FAKE_TIME_CHECK_OK,
        enable_trial_mode=False,
    ):
        """Mirror of TestTimeBudgetGate._make_agent with a configurable VRAM
        result. Time gate defaults to FITS so VRAM-focused assertions aren't
        clouded by the time check also blocking."""
        cm_brain = patch("nodes.ml_hyperparameter_tune_agent.LLMBridge")
        cm_sandbox = patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox")
        cm_skill = patch("nodes.ml_hyperparameter_tune_agent._run_skill")
        cm_tmp = tempfile.TemporaryDirectory()
        cm_anchor = (patch("nodes.ml_hyperparameter_tune_agent.load_anchor_map")
                     if enable_trial_mode else None)
        cm_exists = (patch("os.path.exists", return_value=True)
                     if enable_trial_mode else None)

        MockBridge = cm_brain.__enter__()
        MockSandbox = cm_sandbox.__enter__()
        mock_skill = cm_skill.__enter__()
        configs_dir = cm_tmp.__enter__()
        if cm_anchor is not None:
            mock_anchor = cm_anchor.__enter__()
            mock_anchor.return_value = {"anchors": {}, "s_max": 1.0}
        if cm_exists is not None:
            cm_exists.__enter__()

        mock_brain = MockBridge.return_value
        mock_brain.plan.return_value = FAKE_PLAN_RESPONSE
        mock_brain.reflect.return_value = FAKE_REFLECT_RESPONSE

        saved_records = []
        skill_calls = []
        mock_sandbox = MockSandbox.return_value
        mock_sandbox.get_summary.side_effect = lambda: list(saved_records)
        mock_sandbox.save_record.side_effect = lambda r: saved_records.append(r)
        mock_sandbox.dirs = (
            {"configs": configs_dir, "data": configs_dir}
            if enable_trial_mode
            else {"configs": configs_dir}
        )
        if enable_trial_mode:
            mock_sandbox.score_vector.return_value = FAKE_SCORE_VECTOR_RESULT

        def dispatch(skill_folder, sandbox, **params):
            skill_calls.append((skill_folder, params))
            if skill_folder == "check_config_format_skill":
                return FAKE_CONFIG_MANUAL
            if skill_folder == "evaluate_vram_skill":
                return vram_check_result
            if skill_folder == "evaluate_time_skill":
                return time_check_result
            if skill_folder == "training_skill":
                return FAKE_TRAIN_RESULT
            if skill_folder == "inference_skill":
                return FAKE_INFERENCE_RESULT
            if skill_folder == "denoising_score_skill":
                return FAKE_SCORE_RESULT
            return {"status": "error", "message": f"unknown skill {skill_folder}"}

        mock_skill.side_effect = dispatch

        agent = HyperparamTuningAgent()

        def cleanup():
            if cm_exists is not None:
                cm_exists.__exit__(None, None, None)
            if cm_anchor is not None:
                cm_anchor.__exit__(None, None, None)
            cm_brain.__exit__(None, None, None)
            cm_sandbox.__exit__(None, None, None)
            cm_skill.__exit__(None, None, None)
            cm_tmp.__exit__(None, None, None)

        return agent, mock_brain, mock_sandbox, saved_records, skill_calls, cleanup

    # --- per-mode budget pick -----------------------------------------------

    def test_trial_mode_round_picks_trial_vram_budget(self, tmp_path):
        """plan.is_trial=True → evaluate_vram_skill receives the trial VRAM
        budget. max_rounds=2 because the agent forces the FINAL round to
        formal — we assert on the first (trial) call."""
        agent, mock_brain, _, _, skill_calls, cleanup = self._make_agent(
            enable_trial_mode=True,
        )
        mock_brain.plan.return_value = {**FAKE_PLAN_RESPONSE, "is_trial": True}
        try:
            agent.run(_make_input_with_budget(
                tmp_path,
                max_rounds=2,
                trial_vram_budget=6.0,
                formal_vram_budget=24.0,
                is_trial=True,
            ))
        finally:
            cleanup()
        vram_calls = [p for s, p in skill_calls if s == "evaluate_vram_skill"]
        assert len(vram_calls) == 2
        # First round runs as trial → trial vram budget.
        assert vram_calls[0]["vram_budget_gb"] == 6.0

    def test_formal_mode_round_picks_formal_vram_budget(self, tmp_path):
        """plan.is_trial=False (default) → evaluate_vram_skill receives the
        formal VRAM budget. The trial budget is ignored even when set."""
        agent, _, _, _, skill_calls, cleanup = self._make_agent()
        try:
            agent.run(_make_input_with_budget(
                tmp_path,
                trial_vram_budget=6.0,
                formal_vram_budget=24.0,
            ))
        finally:
            cleanup()
        vram_calls = [p for s, p in skill_calls if s == "evaluate_vram_skill"]
        assert len(vram_calls) == 1
        assert vram_calls[0]["vram_budget_gb"] == 24.0

    def test_none_budget_passes_none_to_skill(self, tmp_path):
        """Both VRAM budgets None → skill still runs (defensive free×0.8
        floor is enforced inside the wrapper), but the kwarg value is None
        so the skill knows to use its fallback path."""
        agent, _, _, _, skill_calls, cleanup = self._make_agent()
        try:
            agent.run(_make_input_with_budget(tmp_path))
        finally:
            cleanup()
        vram_calls = [p for s, p in skill_calls if s == "evaluate_vram_skill"]
        assert len(vram_calls) == 1
        assert vram_calls[0]["vram_budget_gb"] is None

    # --- joint short-circuit ------------------------------------------------

    def test_vram_fail_short_circuits_time_check(self, tmp_path):
        """VRAM gate returning feasible=False must `continue` the loop, so
        evaluate_time_skill is never called even when a time budget is set."""
        agent, _, _, saved_records, skill_calls, cleanup = self._make_agent(
            vram_check_result=FAKE_RESOURCE_CHECK_OVER,
        )
        try:
            agent.run(_make_input_with_budget(
                tmp_path,
                formal_budget=30.0,
                formal_vram_budget=8.0,
            ))
        finally:
            cleanup()
        called = [s for s, _ in skill_calls]
        assert "evaluate_vram_skill" in called
        assert "evaluate_time_skill" not in called
        assert "training_skill" not in called
        # The skipped_oom_risk record is what was saved.
        assert saved_records and saved_records[0]["status"] == "skipped_oom_risk"

    # --- success-record memory ---------------------------------------------

    def test_success_record_memory_carries_vram_fields_formal(self, tmp_path):
        """Gate-pass in formal mode with a budget set → memory carries
        vram_estimate_gb and vram_budget_gb sourced from the resource_check
        dict (estimated_gb / limit_gb)."""
        agent, _, _, saved_records, _, cleanup = self._make_agent()
        try:
            agent.run(_make_input_with_budget(
                tmp_path, formal_vram_budget=8.0,
            ))
        finally:
            cleanup()
        rec = saved_records[0]
        assert rec["status"] == "success"
        mem = rec["memory"]
        assert mem["vram_estimate_gb"] == 2.5   # FAKE_RESOURCE_CHECK_OK
        assert mem["vram_budget_gb"] == 6.0     # limit_gb (min of defensive, budget)

    def test_success_record_memory_vram_fields_trial_mode(self, tmp_path):
        """Gate-pass in trial mode → the memory's vram fields carry the
        estimate the gate used; mode is inferable via time_mode when the
        time gate also ran."""
        agent, mock_brain, _, saved_records, _, cleanup = self._make_agent(
            enable_trial_mode=True,
        )
        mock_brain.plan.return_value = {**FAKE_PLAN_RESPONSE, "is_trial": True}
        try:
            agent.run(_make_input_with_budget(
                tmp_path,
                max_rounds=2,
                trial_vram_budget=6.0,
                formal_vram_budget=24.0,
                is_trial=True,
            ))
        finally:
            cleanup()
        trial_rec = saved_records[0]
        assert trial_rec["status"] == "success"
        assert trial_rec["memory"]["vram_estimate_gb"] == 2.5
        assert trial_rec["memory"]["vram_budget_gb"] == 6.0

    def test_success_record_omits_vram_fields_when_gate_disabled(self, tmp_path):
        """Both VRAM budgets None → the two vram_*_gb keys must be ABSENT
        from the saved record's memory dict (not present with None values),
        so the reflector sees the same shape as pre-Phase-K records."""
        agent, _, _, saved_records, _, cleanup = self._make_agent()
        try:
            agent.run(_make_input_with_budget(tmp_path))  # both vram None
        finally:
            cleanup()
        rec = saved_records[0]
        assert rec["status"] == "success"
        mem = rec["memory"]
        assert "vram_estimate_gb" not in mem
        assert "vram_budget_gb" not in mem

    # --- skipped_oom_risk record memory ------------------------------------

    def test_skipped_oom_risk_record_carries_vram_fields(self, tmp_path):
        """Mirror of the time gate's §J.3 — the skipped_oom_risk record must
        carry the same two vram fields as the success record so the planner
        sees the same shape regardless of pass/fail."""
        agent, _, _, saved_records, _, cleanup = self._make_agent(
            vram_check_result=FAKE_RESOURCE_CHECK_OVER,
        )
        try:
            agent.run(_make_input_with_budget(
                tmp_path, formal_vram_budget=8.0,
            ))
        finally:
            cleanup()
        rec = saved_records[0]
        assert rec["status"] == "skipped_oom_risk"
        mem = rec["memory"]
        # Values come from FAKE_RESOURCE_CHECK_OVER
        assert mem["vram_estimate_gb"] == 12.0
        assert mem["vram_budget_gb"] == 8.0

    def test_skipped_oom_risk_record_omits_vram_fields_when_disabled(self, tmp_path):
        """No VRAM budget set but the defensive floor still flags OOM risk →
        the skipped_oom_risk record must omit vram_*_gb keys (gate-disabled
        shape), mirroring the success-record behaviour."""
        agent, _, _, saved_records, _, cleanup = self._make_agent(
            vram_check_result=FAKE_RESOURCE_CHECK_OVER,
        )
        try:
            agent.run(_make_input_with_budget(tmp_path))  # both vram None
        finally:
            cleanup()
        rec = saved_records[0]
        assert rec["status"] == "skipped_oom_risk"
        mem = rec["memory"]
        assert "vram_estimate_gb" not in mem
        assert "vram_budget_gb" not in mem


# ---------------------------------------------------------------------------
# _copy_seed_plugin — Phase 3 of docs/run_scoped_plugins.md
# ---------------------------------------------------------------------------

class TestCopySeedPlugin:
    """The helper stages a validated seed plugin in the run's plugin dir so
    the training subprocess finds it via ``SIDERIUS_PLUGIN_DIRS``. Validation
    (file exists, PLUGIN_MODEL_TYPE matches) is the schema's job — this
    helper only performs the file-level side effects, which is what these
    tests cover."""

    def _make_plugin(self, dirpath, name="seed.py", content="PLUGIN_MODEL_TYPE = 'x'\n"):
        path = os.path.join(dirpath, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_copy_places_file_in_dst_dir(self, tmp_path):
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        src_dir.mkdir()
        dst_dir.mkdir()
        src = self._make_plugin(str(src_dir), name="attn_fcnet_plugin.py")

        result = _copy_seed_plugin(src, str(dst_dir))

        assert os.path.isfile(result)
        assert os.path.basename(result) == "attn_fcnet_plugin.py"
        assert os.path.dirname(result) == str(dst_dir)

    def test_copy_preserves_contents(self, tmp_path):
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        src_dir.mkdir()
        dst_dir.mkdir()
        payload = "PLUGIN_MODEL_TYPE = 'xx'\n# marker: 12345\n"
        src = self._make_plugin(str(src_dir), content=payload)

        result = _copy_seed_plugin(src, str(dst_dir))

        with open(result, "r", encoding="utf-8") as f:
            assert f.read() == payload

    def test_copy_same_file_is_noop(self, tmp_path):
        """When src and dst resolve to the same path (re-run with the same
        run_name, no workspace change), shutil.copy2 would raise
        SameFileError — the helper must short-circuit instead."""
        run_dir = tmp_path / "plugins" / "run_a"
        run_dir.mkdir(parents=True)
        src = self._make_plugin(str(run_dir), name="seed.py")

        # dst_dir is the same directory; copy should skip without error
        result = _copy_seed_plugin(src, str(run_dir))

        assert result == os.path.join(str(run_dir), "seed.py")
        assert os.path.isfile(result)

    def test_copy_overwrites_existing_destination(self, tmp_path):
        """Run_name reuse case: the newer caller's seed must win over a stale
        copy from a prior invocation."""
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        src_dir.mkdir()
        dst_dir.mkdir()
        # Pre-existing stale copy in dst
        stale = self._make_plugin(
            str(dst_dir), name="seed.py", content="STALE\n"
        )
        # Fresh src with different content
        src = self._make_plugin(
            str(src_dir), name="seed.py", content="FRESH\n"
        )

        result = _copy_seed_plugin(src, str(dst_dir))

        assert result == stale  # same path
        with open(result, "r", encoding="utf-8") as f:
            assert f.read() == "FRESH\n"
