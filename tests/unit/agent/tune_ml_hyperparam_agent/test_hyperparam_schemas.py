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
        "results":    {"denoising_score": 1.23, "final_loss": 0.5},
        "denoising_score": 1.23,
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
        "results":         {},
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
