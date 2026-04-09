"""
Tests for agent/schemas/hyperparam_tuning.py

Verifies that the three explicit validation points in ml_hyperparameter_tune_agent.py
correctly accept valid data and reject invalid data with clear Pydantic ValidationErrors.

Validation points:
  1. Entry  — HyperparamTuningInput.model_validate(...)
  2. Per record — ExperimentRecord.model_validate(...)  (both success and OOM-skipped)
  3. Exit   — HyperparamTuningOutput.model_validate(...)
"""
import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import (
    ExpertAdvice,
    ExperimentPlan,
    TrialConfig,
    HyperparamTuningInput,
    HyperparamTuningOutput,
    ExperimentRecord,
    ExperimentMemory,
    ExperimentTiming,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_input_dict():
    return {
        "model_type":    "punet",
        "file_index":    6,
        "max_rounds":    10,
        "expert_advice": "try deeper architectures",
        "llm_provider":  "gemini",
        "llm_model_id":  "gemini-3.1-flash-lite-preview",
        "storage": {
            "backend": "local",
            "local": {"workspace": "./workspace", "run_name": "v1"},
        },
        "progress_bar":  False,
    }


@pytest.fixture
def valid_success_record():
    return {
        "exp_id":     "punet_v1_001",
        "status":     "success",
        "model_type": "punet",
        "timestamp":  "2026-03-11 10:00:00",
        "file_index": 6,
        "params":     {"model_config": {}, "train_config": {}, "loss_config": {}},
        "final_loss":       0.5,
        "loss_history":     [0.8, 0.6, 0.5],
        "model_params":     50000,
        "denoising_score":  1.23,
        "timing": {
            "train_time_s":     120.0,
            "inference_time_s": 30.0,
            "scoring_time_s":   10.0,
        },
        "memory": {
            "expert_advice_followed": "try deeper architectures",
            "hypothesis":    "deeper encoder improves SNR",
            "conclusion":    "score improved by 0.3",
            "discovery":     "depth > 3 helps",
            "memory_update": "try depth=4 next",
        },
    }


@pytest.fixture
def valid_oom_record():
    return {
        "exp_id":          "punet_v1_002",
        "status":          "skipped_oom_risk",
        "model_type":      "punet",
        "timestamp":       "2026-03-11 10:05:00",
        "file_index":      6,
        "params":          {"model_config": {}, "train_config": {}, "loss_config": {}},
        "denoising_score": None,
        "memory": {
            "expert_advice_followed": "try deeper architectures",
            "hypothesis":    "large batch might help",
            "conclusion":    "Skipped: estimated VRAM (28.0 GB) exceeds limit (25.6 GB).",
            "discovery":     "batch_size=512 is too large",
            "memory_update": "Reduce batch_size or segmentation_size.",
        },
    }


@pytest.fixture
def valid_output_dict(valid_success_record):
    return {
        "run_name":             "v1",
        "model_type":           "punet",
        "file_index":           6,
        "status":               "completed",
        "completed_rounds":     10,
        "total_attempts":       12,
        "best_exp_id":          "punet_v1_001",
        "best_denoising_score": 1.23,
        "best_config":          {"model_config": {}, "train_config": {}, "loss_config": {}},
        "all_records":          [valid_success_record],
        "started_at":           "2026-03-11 10:00:00",
        "finished_at":          "2026-03-11 12:00:00",
    }


# ---------------------------------------------------------------------------
# 1. Entry validation — HyperparamTuningInput
# ---------------------------------------------------------------------------

class TestHyperparamTuningInput:

    def test_valid_plain_string_advice(self, valid_input_dict):
        inp = HyperparamTuningInput.model_validate(valid_input_dict)
        assert inp.model_type == "punet"
        assert inp.expert_advice == "try deeper architectures"

    def test_valid_structured_advice(self, valid_input_dict):
        valid_input_dict["expert_advice"] = {
            "focus_areas":           ["increase depth"],
            "constraints":           ["VRAM < 10 GB"],
            "known_failures":        ["latent_dims=[4000,400,40] with focal"],
            "suggested_directions":  ["try focal gamma=3"],
            "rationale":             "architecture plateau detected",
        }
        inp = HyperparamTuningInput.model_validate(valid_input_dict)
        assert isinstance(inp.expert_advice, ExpertAdvice)
        assert inp.expert_advice.focus_areas == ["increase depth"]

    def test_valid_auto_model_type(self, valid_input_dict):
        valid_input_dict["model_type"] = "auto"
        inp = HyperparamTuningInput.model_validate(valid_input_dict)
        assert inp.model_type == "auto"

    def test_invalid_provider_raises(self, valid_input_dict):
        valid_input_dict["llm_provider"] = "anthropic"
        with pytest.raises(ValidationError) as exc:
            HyperparamTuningInput.model_validate(valid_input_dict)
        assert "llm_provider" in str(exc.value)

    def test_zero_max_rounds_raises(self, valid_input_dict):
        valid_input_dict["max_rounds"] = 0
        with pytest.raises(ValidationError) as exc:
            HyperparamTuningInput.model_validate(valid_input_dict)
        assert "max_rounds" in str(exc.value)

    def test_negative_file_index_raises(self, valid_input_dict):
        valid_input_dict["file_index"] = -1
        with pytest.raises(ValidationError) as exc:
            HyperparamTuningInput.model_validate(valid_input_dict)
        assert "file_index" in str(exc.value)

    def test_missing_model_type_raises(self, valid_input_dict):
        del valid_input_dict["model_type"]
        with pytest.raises(ValidationError) as exc:
            HyperparamTuningInput.model_validate(valid_input_dict)
        assert "model_type" in str(exc.value)

    def test_storage_local_workspace_and_run_name(self, valid_input_dict):
        inp = HyperparamTuningInput.model_validate(valid_input_dict)
        assert inp.storage.backend == "local"
        assert inp.storage.local.workspace == "./workspace"
        assert inp.storage.local.run_name == "v1"

    def test_storage_defaults_when_omitted(self):
        inp = HyperparamTuningInput(model_type="punet")
        assert inp.storage.backend == "local"
        assert inp.storage.local.workspace == "./siderius_workspace"
        assert inp.storage.local.run_name == "v1"

    def test_storage_invalid_backend_raises(self, valid_input_dict):
        valid_input_dict["storage"] = {"backend": "redis"}
        with pytest.raises(ValidationError) as exc:
            HyperparamTuningInput.model_validate(valid_input_dict)
        assert "backend" in str(exc.value)

    # --- reflect_provider / reflect_model_id (Phase B of break_tuner_agent.md) ---

    def test_reflect_fields_default_to_none(self, valid_input_dict):
        """When the new reflect_* fields are omitted, both default to None
        (which means the reflector uses the planner's provider+model — the
        legacy behavior)."""
        inp = HyperparamTuningInput.model_validate(valid_input_dict)
        assert inp.reflect_provider is None
        assert inp.reflect_model_id is None

    def test_reflect_model_id_only(self, valid_input_dict):
        """Setting only reflect_model_id is valid: same provider, different
        model. Used for the common pro/flash split within gemini."""
        valid_input_dict["reflect_model_id"] = "gemini-2-flash"
        inp = HyperparamTuningInput.model_validate(valid_input_dict)
        assert inp.reflect_provider is None
        assert inp.reflect_model_id == "gemini-2-flash"

    def test_reflect_provider_and_model_id(self, valid_input_dict):
        """Setting both fields is valid: cross-provider routing (e.g.
        planner on gemini, reflector on openai)."""
        valid_input_dict["reflect_provider"] = "openai"
        valid_input_dict["reflect_model_id"] = "gpt-4o-mini"
        inp = HyperparamTuningInput.model_validate(valid_input_dict)
        assert inp.reflect_provider == "openai"
        assert inp.reflect_model_id == "gpt-4o-mini"

    def test_reflect_provider_invalid_value_raises(self, valid_input_dict):
        """reflect_provider is constrained to the same Literal as llm_provider."""
        valid_input_dict["reflect_provider"] = "anthropic"
        with pytest.raises(ValidationError) as exc:
            HyperparamTuningInput.model_validate(valid_input_dict)
        assert "reflect_provider" in str(exc.value)

    def test_reflect_fields_round_trip_through_json(self, valid_input_dict):
        """reflect_provider and reflect_model_id survive a full
        model_dump_json → model_validate_json round-trip."""
        valid_input_dict["reflect_provider"] = "openai"
        valid_input_dict["reflect_model_id"] = "gpt-4o-mini"
        inp = HyperparamTuningInput.model_validate(valid_input_dict)
        dumped = inp.model_dump_json()
        reloaded = HyperparamTuningInput.model_validate_json(dumped)
        assert reloaded.reflect_provider == "openai"
        assert reloaded.reflect_model_id == "gpt-4o-mini"

    def test_reflect_fields_round_trip_when_unset(self, valid_input_dict):
        """The default-None case must also round-trip cleanly."""
        inp = HyperparamTuningInput.model_validate(valid_input_dict)
        dumped = inp.model_dump_json()
        reloaded = HyperparamTuningInput.model_validate_json(dumped)
        assert reloaded.reflect_provider is None
        assert reloaded.reflect_model_id is None


# ---------------------------------------------------------------------------
# 2. Per-record validation — ExperimentRecord
# ---------------------------------------------------------------------------

class TestExperimentRecordSuccess:

    def test_valid_success_record(self, valid_success_record):
        rec = ExperimentRecord.model_validate(valid_success_record)
        assert rec.status == "success"
        assert rec.denoising_score == 1.23
        assert rec.memory.expert_advice_followed == "try deeper architectures"

    def test_timing_fields_present(self, valid_success_record):
        rec = ExperimentRecord.model_validate(valid_success_record)
        assert rec.timing.train_time_s == 120.0
        assert rec.timing.inference_time_s == 30.0
        assert rec.timing.scoring_time_s == 10.0

    def test_missing_exp_id_raises(self, valid_success_record):
        del valid_success_record["exp_id"]
        with pytest.raises(ValidationError) as exc:
            ExperimentRecord.model_validate(valid_success_record)
        assert "exp_id" in str(exc.value)

    def test_invalid_status_raises(self, valid_success_record):
        valid_success_record["status"] = "running"
        with pytest.raises(ValidationError) as exc:
            ExperimentRecord.model_validate(valid_success_record)
        assert "status" in str(exc.value)

    def test_missing_file_index_uses_default(self, valid_success_record):
        del valid_success_record["file_index"]
        record = ExperimentRecord.model_validate(valid_success_record)
        assert record.file_index == ExperimentRecord.model_fields["file_index"].default

    def test_missing_expert_advice_followed_in_memory_raises(self, valid_success_record):
        del valid_success_record["memory"]["expert_advice_followed"]
        with pytest.raises(ValidationError) as exc:
            ExperimentRecord.model_validate(valid_success_record)
        assert "expert_advice_followed" in str(exc.value)

    def test_missing_hypothesis_in_memory_raises(self, valid_success_record):
        del valid_success_record["memory"]["hypothesis"]
        with pytest.raises(ValidationError) as exc:
            ExperimentRecord.model_validate(valid_success_record)
        assert "hypothesis" in str(exc.value)


class TestExperimentRecordOOM:

    def test_valid_oom_record(self, valid_oom_record):
        rec = ExperimentRecord.model_validate(valid_oom_record)
        assert rec.status == "skipped_oom_risk"
        assert rec.denoising_score is None
        assert rec.timing is None

    def test_oom_missing_memory_raises(self, valid_oom_record):
        del valid_oom_record["memory"]
        # memory is Optional so this should pass — OOM records may omit it
        rec = ExperimentRecord.model_validate(valid_oom_record)
        assert rec.memory is None

    def test_oom_missing_file_index_uses_default(self, valid_oom_record):
        del valid_oom_record["file_index"]
        record = ExperimentRecord.model_validate(valid_oom_record)
        assert record.file_index == ExperimentRecord.model_fields["file_index"].default


class TestExperimentRecordExecutionErrors:
    """Test the training/inference error status values."""

    def _make_error_record(self, status: str):
        return {
            "exp_id": "punet_v1_001",
            "status": status,
            "model_type": "punet",
            "timestamp": "2026-04-05 12:00:00",
            "file_index": 6,
            "params": {"model_config": {}, "train_config": {}, "loss_config": {}},
            "denoising_score": None,
            "memory": {
                "expert_advice_followed": "",
                "hypothesis": "test hypothesis",
                "conclusion": "Training failed: CUDA out of memory",
                "discovery": "Model too large",
                "memory_update": "Try smaller architecture.",
            },
        }

    def test_error_training_accepted(self):
        rec = ExperimentRecord.model_validate(self._make_error_record("error_training"))
        assert rec.status == "error_training"

    def test_error_training_oom_accepted(self):
        rec = ExperimentRecord.model_validate(self._make_error_record("error_training_oom"))
        assert rec.status == "error_training_oom"

    def test_error_inference_accepted(self):
        rec = ExperimentRecord.model_validate(self._make_error_record("error_inference"))
        assert rec.status == "error_inference"

    def test_error_inference_oom_accepted(self):
        rec = ExperimentRecord.model_validate(self._make_error_record("error_inference_oom"))
        assert rec.status == "error_inference_oom"

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            ExperimentRecord.model_validate(self._make_error_record("error_scoring"))


# ---------------------------------------------------------------------------
# 3. Exit validation — HyperparamTuningOutput
# ---------------------------------------------------------------------------

class TestHyperparamTuningOutput:

    def test_valid_completed_output(self, valid_output_dict):
        out = HyperparamTuningOutput.model_validate(valid_output_dict)
        assert out.status == "completed"
        assert out.best_denoising_score == 1.23
        assert len(out.all_records) == 1

    def test_valid_partial_output(self, valid_output_dict):
        valid_output_dict["status"] = "partial"
        out = HyperparamTuningOutput.model_validate(valid_output_dict)
        assert out.status == "partial"

    def test_valid_failed_output(self, valid_output_dict):
        valid_output_dict["status"] = "failed"
        valid_output_dict["best_exp_id"] = None
        valid_output_dict["best_denoising_score"] = None
        valid_output_dict["best_config"] = None
        out = HyperparamTuningOutput.model_validate(valid_output_dict)
        assert out.status == "failed"
        assert out.best_denoising_score is None

    def test_invalid_status_raises(self, valid_output_dict):
        valid_output_dict["status"] = "running"
        with pytest.raises(ValidationError) as exc:
            HyperparamTuningOutput.model_validate(valid_output_dict)
        assert "status" in str(exc.value)

    def test_missing_run_name_raises(self, valid_output_dict):
        del valid_output_dict["run_name"]
        with pytest.raises(ValidationError) as exc:
            HyperparamTuningOutput.model_validate(valid_output_dict)
        assert "run_name" in str(exc.value)

    def test_missing_started_at_raises(self, valid_output_dict):
        del valid_output_dict["started_at"]
        with pytest.raises(ValidationError) as exc:
            HyperparamTuningOutput.model_validate(valid_output_dict)
        assert "started_at" in str(exc.value)

    def test_all_records_validated_as_experiment_records(self, valid_output_dict, valid_success_record, valid_oom_record):
        valid_output_dict["all_records"] = [valid_success_record, valid_oom_record]
        out = HyperparamTuningOutput.model_validate(valid_output_dict)
        assert len(out.all_records) == 2
        assert out.all_records[0].status == "success"
        assert out.all_records[1].status == "skipped_oom_risk"

    def test_invalid_record_in_all_records_raises(self, valid_output_dict):
        valid_output_dict["all_records"] = [{"status": "bad_status", "exp_id": "x"}]
        with pytest.raises(ValidationError):
            HyperparamTuningOutput.model_validate(valid_output_dict)


# ---------------------------------------------------------------------------
# Trial-mode fields — backward compatibility and new behavior
# ---------------------------------------------------------------------------

class TestTrialFieldsInput:
    """Verify trial fields on HyperparamTuningInput are optional and default to normal mode."""

    def test_defaults_to_normal_mode(self, valid_input_dict):
        inp = HyperparamTuningInput.model_validate(valid_input_dict)
        assert inp.is_trial is False
        assert inp.trial_portion == 0.1
        assert inp.trial_strategy == "snapshot"
        assert inp.target_files == []
        assert inp.train_validation_align is True

    def test_existing_input_without_trial_fields_validates(self, valid_input_dict):
        """Existing callers that don't pass trial fields should still work."""
        assert "is_trial" not in valid_input_dict
        inp = HyperparamTuningInput.model_validate(valid_input_dict)
        assert inp.is_trial is False

    def test_trial_mode_with_snapshot(self, valid_input_dict):
        valid_input_dict["is_trial"] = True
        valid_input_dict["trial_strategy"] = "snapshot"
        valid_input_dict["trial_portion"] = 0.2
        inp = HyperparamTuningInput.model_validate(valid_input_dict)
        assert inp.is_trial is True
        assert inp.trial_strategy == "snapshot"
        assert inp.trial_portion == 0.2

    def test_trial_mode_with_target(self, valid_input_dict):
        valid_input_dict["is_trial"] = True
        valid_input_dict["trial_strategy"] = "target"
        valid_input_dict["target_files"] = [0, 1, 2, 3]
        inp = HyperparamTuningInput.model_validate(valid_input_dict)
        assert inp.target_files == [0, 1, 2, 3]

    def test_invalid_trial_strategy_raises(self, valid_input_dict):
        valid_input_dict["trial_strategy"] = "invalid_strategy"
        with pytest.raises(ValidationError):
            HyperparamTuningInput.model_validate(valid_input_dict)

    def test_target_strategy_empty_files_raises(self, valid_input_dict):
        """target strategy with empty target_files should be caught at schema level."""
        valid_input_dict["is_trial"] = True
        valid_input_dict["trial_strategy"] = "target"
        valid_input_dict["target_files"] = []
        with pytest.raises(ValidationError, match="target_files must be non-empty"):
            HyperparamTuningInput.model_validate(valid_input_dict)

    def test_target_strategy_without_trial_mode_ok(self, valid_input_dict):
        """target strategy is ignored when is_trial=False — no validation error."""
        valid_input_dict["is_trial"] = False
        valid_input_dict["trial_strategy"] = "target"
        valid_input_dict["target_files"] = []
        inp = HyperparamTuningInput.model_validate(valid_input_dict)
        assert inp.is_trial is False

    def test_trial_portion_out_of_range_raises(self, valid_input_dict):
        valid_input_dict["trial_portion"] = 1.5
        with pytest.raises(ValidationError):
            HyperparamTuningInput.model_validate(valid_input_dict)


class TestTrialFieldsExperimentRecord:
    """Verify trial fields on ExperimentRecord are optional and default correctly."""

    def test_existing_record_without_trial_fields(self, valid_success_record):
        """Records from before the trial feature should still validate."""
        assert "is_trial" not in valid_success_record
        rec = ExperimentRecord.model_validate(valid_success_record)
        assert rec.is_trial is False
        assert rec.trial_strategy is None
        assert rec.trial_portion is None
        assert rec.eval_strategy is None
        assert rec.eval_portion is None
        assert rec.train_portion is None
        assert rec.target_files is None
        assert rec.file_vector is None
        assert rec.training_psd_segments is None
        assert rec.eval_psd_segments is None

    def test_record_with_trial_context(self, valid_success_record):
        valid_success_record["is_trial"] = True
        valid_success_record["trial_strategy"] = "snapshot"
        valid_success_record["trial_portion"] = 0.1
        valid_success_record["eval_strategy"] = "snapshot"
        valid_success_record["eval_portion"] = 0.1
        valid_success_record["train_portion"] = 0.1
        valid_success_record["file_vector"] = [float("nan")] * 20
        valid_success_record["file_vector"][6] = 0.85
        rec = ExperimentRecord.model_validate(valid_success_record)
        assert rec.is_trial is True
        assert rec.trial_strategy == "snapshot"
        assert rec.file_vector[6] == 0.85

    def test_record_with_target_strategy(self, valid_success_record):
        valid_success_record["is_trial"] = True
        valid_success_record["trial_strategy"] = "target"
        valid_success_record["target_files"] = [0, 10, 19]
        rec = ExperimentRecord.model_validate(valid_success_record)
        assert rec.target_files == [0, 10, 19]


class TestTrialFieldsOutput:
    """Verify best_file_vector on HyperparamTuningOutput is optional."""

    def test_output_without_file_vector(self, valid_output_dict):
        """Existing outputs should still validate without best_file_vector."""
        assert "best_file_vector" not in valid_output_dict
        out = HyperparamTuningOutput.model_validate(valid_output_dict)
        assert out.best_file_vector is None

    def test_output_with_file_vector(self, valid_output_dict):
        valid_output_dict["best_file_vector"] = [float("nan")] * 20
        valid_output_dict["best_file_vector"][6] = 1.23
        out = HyperparamTuningOutput.model_validate(valid_output_dict)
        assert out.best_file_vector[6] == 1.23
        assert len(out.best_file_vector) == 20


# ---------------------------------------------------------------------------
# ExperimentPlan validation
# ---------------------------------------------------------------------------

class TestExperimentPlan:
    """Verify ExperimentPlan schema validates brain.plan() output correctly."""

    def test_valid_full_plan(self):
        """All fields present — validates correctly."""
        plan = ExperimentPlan.model_validate({
            "model_type": "punet",
            "hypothesis": "Deeper architecture should help.",
            "reasoning": "Previous runs showed depth matters.",
            "model_config": {"depth": 4},
            "train_config": {"lr": 1e-4, "epochs": 5},
            "loss_config": {"loss_type": "focal"},
            "is_trial": True,
            "trial_strategy": "snapshot",
            "trial_portion": 0.2,
            "train_validation_align": False,
        })
        assert plan.model_type == "punet"
        assert plan.is_trial is True
        assert plan.trial_portion == 0.2
        assert plan.train_validation_align is False

    def test_defaults_when_trial_fields_omitted(self):
        """Only experiment fields provided — trial fields get defaults."""
        plan = ExperimentPlan.model_validate({
            "model_type": "fcnet",
            "model_config": {"depth": 2},
            "train_config": {"lr": 1e-3},
            "loss_config": {"loss_type": "ce"},
        })
        assert plan.is_trial is True  # default favors trial
        assert plan.trial_strategy == "snapshot"
        assert plan.trial_portion == 0.02
        assert plan.target_files == []
        assert plan.train_validation_align is True

    def test_defaults_when_all_fields_omitted(self):
        """Empty dict — all defaults apply."""
        plan = ExperimentPlan.model_validate({})
        assert plan.model_type == "fcnet"
        assert plan.model_cfg == {}
        assert plan.is_trial is True

    def test_invalid_trial_portion_rejected(self):
        """trial_portion=5.0 exceeds max — raises ValidationError."""
        with pytest.raises(ValidationError):
            ExperimentPlan.model_validate({
                "model_type": "punet",
                "trial_portion": 5.0,
            })

    def test_trial_portion_below_min_rejected(self):
        """trial_portion=0.0 below min — raises ValidationError."""
        with pytest.raises(ValidationError):
            ExperimentPlan.model_validate({
                "model_type": "punet",
                "trial_portion": 0.0,
            })

    def test_with_defaults_fallback(self):
        """Invalid trial fields stripped — experiment fields preserved."""
        plan = ExperimentPlan.with_defaults({
            "model_type": "punet",
            "hypothesis": "Test hypothesis",
            "model_config": {"depth": 4},
            "train_config": {"lr": 1e-4},
            "loss_config": {"loss_type": "focal"},
            "trial_portion": 5.0,  # invalid
        })
        assert plan.model_type == "punet"
        assert plan.hypothesis == "Test hypothesis"
        assert plan.trial_portion == 0.02  # fell back to default

    def test_with_defaults_preserves_valid(self):
        """Valid input passes through with_defaults unchanged."""
        plan = ExperimentPlan.with_defaults({
            "model_type": "punet",
            "trial_portion": 0.3,
            "trial_strategy": "anchors",
        })
        assert plan.trial_portion == 0.3
        assert plan.trial_strategy == "anchors"

    def test_with_defaults_unwraps_single_element_list(self):
        """LLM occasionally emits [{...}] instead of {...} — unwrap it."""
        plan = ExperimentPlan.with_defaults([{
            "model_type": "punet",
            "hypothesis": "Wrapped in list",
            "trial_portion": 0.3,
        }])
        assert plan.model_type == "punet"
        assert plan.hypothesis == "Wrapped in list"
        assert plan.trial_portion == 0.3

    def test_with_defaults_rejects_multi_element_list(self):
        with pytest.raises(TypeError, match="list of length 2"):
            ExperimentPlan.with_defaults([{"model_type": "punet"}, {"model_type": "wavenet"}])

    def test_with_defaults_rejects_non_dict(self):
        with pytest.raises(TypeError, match="expected a dict"):
            ExperimentPlan.with_defaults("not a dict")

    def test_target_needs_files(self):
        """target strategy + empty files → error."""
        with pytest.raises(ValidationError, match="target_files required"):
            ExperimentPlan.model_validate({
                "is_trial": True,
                "trial_strategy": "target",
                "target_files": [],
            })

    def test_target_strategy_with_files(self):
        plan = ExperimentPlan.model_validate({
            "is_trial": True,
            "trial_strategy": "target",
            "target_files": [0, 10, 19],
        })
        assert plan.target_files == [0, 10, 19]

    def test_formal_plan(self):
        """is_trial=False validates without trial fields."""
        plan = ExperimentPlan.model_validate({
            "model_type": "punet",
            "is_trial": False,
        })
        assert plan.is_trial is False

    def test_invalid_strategy_rejected(self):
        with pytest.raises(ValidationError):
            ExperimentPlan.model_validate({
                "trial_strategy": "nonexistent",
            })


# ---------------------------------------------------------------------------
# TrialConfig validation
# ---------------------------------------------------------------------------

class TestTrialConfig:
    """Verify TrialConfig schema validates trial/formal decisions correctly."""

    # Common seed values for tests
    _SEEDS = {"train_sampling_seed": 42, "eval_sampling_seed": 42, "train_base_seed": 123}

    def test_trial_mode(self):
        cfg = TrialConfig(
            is_trial=True,
            mode="trial",
            trial_strategy="snapshot",
            trial_portion=0.05,
            train_portion=0.1,
            **self._SEEDS,
        )
        assert cfg.is_trial is True
        assert cfg.mode == "trial"
        assert cfg.file_index is None
        assert cfg.train_sampling_seed == 42
        assert cfg.eval_sampling_seed == 42
        assert cfg.train_base_seed == 123

    def test_formal_mode(self):
        cfg = TrialConfig(
            is_trial=False,
            mode="formal",
            train_portion=0.1,
            **self._SEEDS,
        )
        assert cfg.mode == "formal"
        assert cfg.file_index is None

    def test_single_file_mode(self):
        cfg = TrialConfig(
            is_trial=False,
            mode="single_file",
            file_index=6,
            **self._SEEDS,
        )
        assert cfg.mode == "single_file"
        assert cfg.file_index == 6

    def test_single_file_without_file_index_raises(self):
        with pytest.raises(ValidationError, match="file_index required"):
            TrialConfig(is_trial=False, mode="single_file", **self._SEEDS)

    def test_trial_target_without_files_raises(self):
        with pytest.raises(ValidationError, match="target_files required"):
            TrialConfig(
                is_trial=True,
                mode="trial",
                trial_strategy="target",
                target_files=[],
                **self._SEEDS,
            )

    def test_trial_target_with_files(self):
        cfg = TrialConfig(
            is_trial=True,
            mode="trial",
            trial_strategy="target",
            target_files=[0, 10, 19],
            **self._SEEDS,
        )
        assert cfg.target_files == [0, 10, 19]

    def test_model_dump_roundtrip(self):
        """Serialization and deserialization preserves all fields including seeds."""
        cfg = TrialConfig(
            is_trial=True,
            mode="trial",
            trial_strategy="anchors",
            trial_portion=0.05,
            train_portion=0.2,
            **self._SEEDS,
        )
        dumped = cfg.model_dump()
        restored = TrialConfig.model_validate(dumped)
        assert restored == cfg
        assert dumped["train_sampling_seed"] == 42
        assert dumped["eval_sampling_seed"] == 42
        assert dumped["train_base_seed"] == 123

    def test_invalid_mode_rejected(self):
        with pytest.raises(ValidationError):
            TrialConfig(is_trial=True, mode="unknown", **self._SEEDS)
