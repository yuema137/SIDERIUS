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
    GateExhaustionInfo,
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
        valid_input_dict["reflect_model_id"] = "gemini-2.5-flash"
        inp = HyperparamTuningInput.model_validate(valid_input_dict)
        assert inp.reflect_provider is None
        assert inp.reflect_model_id == "gemini-2.5-flash"

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
# Phase K — HyperparamTuningInput VRAM budget fields. Mirror of the Phase I
# trial/formal time-budget split. Both are independently optional; the tuner
# picks per round based on plan.is_trial (exercised in K.3 tuner tests).
# See docs/resource_estimator_implement.md §10.4.
# ---------------------------------------------------------------------------

class TestVramBudgetFields:

    def test_both_default_none(self, valid_input_dict):
        inp = HyperparamTuningInput.model_validate(valid_input_dict)
        assert inp.trial_vram_budget_gb is None
        assert inp.formal_vram_budget_gb is None

    def test_trial_budget_set_alone(self, valid_input_dict):
        """Setting only the trial budget leaves the formal budget None so the
        formal gate stays disabled — one budget per mode, no cross-contamination."""
        valid_input_dict["trial_vram_budget_gb"] = 4.0
        inp = HyperparamTuningInput.model_validate(valid_input_dict)
        assert inp.trial_vram_budget_gb == 4.0
        assert inp.formal_vram_budget_gb is None

    def test_formal_budget_set_alone(self, valid_input_dict):
        valid_input_dict["formal_vram_budget_gb"] = 8.0
        inp = HyperparamTuningInput.model_validate(valid_input_dict)
        assert inp.trial_vram_budget_gb is None
        assert inp.formal_vram_budget_gb == 8.0

    def test_both_budgets_set(self, valid_input_dict):
        valid_input_dict["trial_vram_budget_gb"] = 4.0
        valid_input_dict["formal_vram_budget_gb"] = 8.0
        inp = HyperparamTuningInput.model_validate(valid_input_dict)
        assert inp.trial_vram_budget_gb == 4.0
        assert inp.formal_vram_budget_gb == 8.0

    def test_budgets_round_trip_through_json(self, valid_input_dict):
        valid_input_dict["trial_vram_budget_gb"] = 4.0
        valid_input_dict["formal_vram_budget_gb"] = 8.0
        inp = HyperparamTuningInput.model_validate(valid_input_dict)
        reloaded = HyperparamTuningInput.model_validate_json(inp.model_dump_json())
        assert reloaded.trial_vram_budget_gb == 4.0
        assert reloaded.formal_vram_budget_gb == 8.0

    def test_budgets_round_trip_when_unset(self, valid_input_dict):
        inp = HyperparamTuningInput.model_validate(valid_input_dict)
        reloaded = HyperparamTuningInput.model_validate_json(inp.model_dump_json())
        assert reloaded.trial_vram_budget_gb is None
        assert reloaded.formal_vram_budget_gb is None

    def test_non_numeric_budget_rejected(self, valid_input_dict):
        valid_input_dict["trial_vram_budget_gb"] = "not a number"
        with pytest.raises(ValidationError) as exc:
            HyperparamTuningInput.model_validate(valid_input_dict)
        assert "trial_vram_budget_gb" in str(exc.value)


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


# ---------------------------------------------------------------------------
# V8 hardening Domain 2a — error_scoring status (commit e247e1d Fix 2a)
# ---------------------------------------------------------------------------

class TestExperimentRecordErrorScoringStatus:
    """The Fix 2a scoring-crash handler in ml_hyperparameter_tune_agent.py
    builds an ExperimentRecord with status='error_scoring' and validates it
    via model_validate. If the schema's status Literal does not include
    'error_scoring', that validate call raises ValidationError mid-handler
    and the iteration crashes — the exact failure mode Fix 2a was supposed
    to prevent. These tests pin the contract.
    """

    def _error_scoring_record(self) -> dict:
        """Mirror the exact dict shape built by Fix 2a in
        ml_hyperparameter_tune_agent.py at the scoring crash branch."""
        return {
            "exp_id":          "punet_v1_007",
            "status":          "error_scoring",
            "model_type":      "punet",
            "timestamp":       "2026-04-30 16:00:00",
            "file_index":      6,
            "params":          {"model_config": {}, "train_config": {}, "loss_config": {}},
            "denoising_score": None,
            "timing": {
                "train_time_s":     45.0,
                "inference_time_s": 12.0,
                "scoring_time_s":   2.0,
            },
            "memory": {
                "expert_advice_followed": "try focal loss",
                "hypothesis":    "focal loss with depth=4",
                "conclusion":    "Scoring crashed: RuntimeError: anchor_map mismatch",
                "discovery": (
                    "Training and inference completed but scoring "
                    "raised RuntimeError: anchor_map mismatch"
                ),
                "memory_update": (
                    "Scoring crash — training succeeded so the "
                    "checkpoint may be reusable. Investigate the "
                    "scoring path before retrying this config."
                ),
            },
        }

    def test_error_scoring_validates_cleanly(self):
        """The Fix 2a record dict must round-trip through model_validate."""
        rec = ExperimentRecord.model_validate(self._error_scoring_record())
        assert rec.status == "error_scoring"
        assert rec.denoising_score is None
        assert rec.timing.scoring_time_s == 2.0

    def test_error_scoring_memory_carries_crash_evidence(self):
        """Conclusion and discovery must preserve the exception detail so the
        next iter's proposer/planner can read what went wrong."""
        rec = ExperimentRecord.model_validate(self._error_scoring_record())
        assert "Scoring crashed" in rec.memory.conclusion
        assert "RuntimeError" in rec.memory.discovery

    def test_error_scoring_round_trips_through_json(self):
        """Persistence path: dict → ExperimentRecord → JSON → dict → ExperimentRecord."""
        import json
        rec = ExperimentRecord.model_validate(self._error_scoring_record())
        as_json = rec.model_dump_json()
        rehydrated = ExperimentRecord.model_validate(json.loads(as_json))
        assert rehydrated.status == "error_scoring"
        assert rehydrated.memory.conclusion == rec.memory.conclusion

    def test_unknown_error_variant_still_rejected(self):
        """Sanity: the Literal still rejects fabricated statuses — we only
        widened it by exactly one entry."""
        bad = self._error_scoring_record()
        bad["status"] = "error_storage"
        with pytest.raises(ValidationError) as exc:
            ExperimentRecord.model_validate(bad)
        assert "status" in str(exc.value)


# ---------------------------------------------------------------------------
# Phase J — ExperimentMemory time fields (planner-feedback channel)
# ---------------------------------------------------------------------------

class TestExperimentMemoryTimeFields:
    """The three optional time fields on ExperimentMemory carry pre-flight
    estimator context to the next planner round via experiment_history.
    All three default to None so records emitted before the gate ran (or with
    the gate disabled) validate unchanged. See docs/resource_estimator_implement.md
    §J.1.
    """

    def _base_memory(self):
        return {
            "expert_advice_followed": "test",
            "hypothesis": "test",
        }

    def test_time_fields_default_none(self):
        mem = ExperimentMemory.model_validate(self._base_memory())
        assert mem.time_estimate_minutes is None
        assert mem.time_budget_minutes is None
        assert mem.time_mode is None

    def test_time_fields_accept_concrete_values(self):
        mem = ExperimentMemory.model_validate({
            **self._base_memory(),
            "time_estimate_minutes": 2.3,
            "time_budget_minutes": 5.0,
            "time_mode": "trial",
        })
        assert mem.time_estimate_minutes == 2.3
        assert mem.time_budget_minutes == 5.0
        assert mem.time_mode == "trial"

    def test_time_mode_accepts_formal(self):
        mem = ExperimentMemory.model_validate({
            **self._base_memory(),
            "time_mode": "formal",
        })
        assert mem.time_mode == "formal"

    def test_time_mode_rejects_other_strings(self):
        """Literal["trial", "formal"] — anything else must fail validation."""
        with pytest.raises(ValidationError) as exc:
            ExperimentMemory.model_validate({
                **self._base_memory(),
                "time_mode": "snapshot",
            })
        assert "time_mode" in str(exc.value)

    def test_existing_record_round_trip_unchanged(self, valid_success_record):
        """Records produced before Phase J (no time_* keys) still validate and
        the three time fields read back as None."""
        rec = ExperimentRecord.model_validate(valid_success_record)
        assert rec.memory.time_estimate_minutes is None
        assert rec.memory.time_budget_minutes is None
        assert rec.memory.time_mode is None


# ---------------------------------------------------------------------------
# Phase K — ExperimentMemory VRAM fields (planner-feedback channel, mirror of
# the time fields). Mode is shared with the time fields via `time_mode`; no
# separate vram_mode. See docs/resource_estimator_implement.md §10.4.
# ---------------------------------------------------------------------------

class TestExperimentMemoryVramFields:
    """The two optional VRAM fields on ExperimentMemory carry pre-flight
    estimator context to the next planner round via experiment_history,
    mirroring the time fields. Both default to None so pre-Phase-K records
    (and records where the gate was disabled) validate unchanged."""

    def _base_memory(self):
        return {
            "expert_advice_followed": "test",
            "hypothesis": "test",
        }

    def test_vram_fields_default_none(self):
        mem = ExperimentMemory.model_validate(self._base_memory())
        assert mem.vram_estimate_gb is None
        assert mem.vram_budget_gb is None

    def test_vram_fields_accept_concrete_values(self):
        mem = ExperimentMemory.model_validate({
            **self._base_memory(),
            "vram_estimate_gb": 2.3,
            "vram_budget_gb": 4.0,
        })
        assert mem.vram_estimate_gb == 2.3
        assert mem.vram_budget_gb == 4.0

    def test_vram_fields_independent_of_time_fields(self):
        """Setting VRAM fields alone must not force the time fields — the two
        gates are independent. The per-round tuner populates whichever the
        gate saw."""
        mem = ExperimentMemory.model_validate({
            **self._base_memory(),
            "vram_estimate_gb": 1.7,
            "vram_budget_gb": 4.0,
        })
        assert mem.time_estimate_minutes is None
        assert mem.time_budget_minutes is None
        assert mem.time_mode is None

    def test_existing_record_round_trip_unchanged(self, valid_success_record):
        """Records produced before Phase K (no vram_* keys) still validate and
        the two VRAM fields read back as None."""
        rec = ExperimentRecord.model_validate(valid_success_record)
        assert rec.memory.vram_estimate_gb is None
        assert rec.memory.vram_budget_gb is None


# ---------------------------------------------------------------------------
# K.2.5-8 — ExperimentMemory.inference_batch_uncalibrated. Populated by the
# tuner when the inference estimator substituted the runtime fallback batch
# (25) for an unregistered model_type. Optional so pre-K.2.5-8 records and
# records where the gate did not run still validate. See §10.14 K.2.5-8.
# ---------------------------------------------------------------------------

class TestExperimentMemoryInferenceBatchUncalibrated:

    def _base_memory(self):
        return {
            "expert_advice_followed": "test",
            "hypothesis": "test",
        }

    def test_field_defaults_to_none(self):
        mem = ExperimentMemory.model_validate(self._base_memory())
        assert mem.inference_batch_uncalibrated is None

    def test_field_accepts_true(self):
        mem = ExperimentMemory.model_validate({
            **self._base_memory(),
            "inference_batch_uncalibrated": True,
        })
        assert mem.inference_batch_uncalibrated is True

    def test_field_accepts_false(self):
        mem = ExperimentMemory.model_validate({
            **self._base_memory(),
            "inference_batch_uncalibrated": False,
        })
        assert mem.inference_batch_uncalibrated is False

    def test_field_round_trips_through_json(self):
        mem = ExperimentMemory.model_validate({
            **self._base_memory(),
            "inference_batch_uncalibrated": True,
        })
        reloaded = ExperimentMemory.model_validate_json(mem.model_dump_json())
        assert reloaded.inference_batch_uncalibrated is True

    def test_existing_record_round_trip_unchanged(self, valid_success_record):
        """Records produced before K.2.5-8 (no inference_batch_uncalibrated key)
        still validate and the field reads back as None."""
        rec = ExperimentRecord.model_validate(valid_success_record)
        assert rec.memory.inference_batch_uncalibrated is None


# ---------------------------------------------------------------------------
# Phase K (K.7) — GateExhaustionInfo schema. Populated by the tuner when an
# iteration ends without ever training successfully AND >=1 attempt was
# rejected by the pre-flight resource gate. Consumed by the next iteration's
# proposer via ProposalInput.prior_iteration_gate_exhaustion (K.7.2).
# See docs/resource_estimator_implement.md §10.13.2.
# ---------------------------------------------------------------------------

class TestGateExhaustionInfo:

    def _full_kwargs(self):
        """One realistic populated instance — VRAM-bound trial-mode failure
        mirroring the §10.13.3 example: 9 attempts, all VRAM-gated, baseline
        already over budget at 1.6x, worst at 2.0x, time within budget."""
        return {
            "total_attempts": 9,
            "vram_gated_attempts": 9,
            "time_gated_attempts": 0,
            "other_failure_attempts": 0,
            "active_mode": "trial",
            "vram_budget_gb": 4.0,
            "time_budget_minutes": 20.0,
            "baseline_vram_estimate_gb": 6.4,
            "baseline_vram_factor": 1.6,
            "baseline_time_estimate_minutes": 12.0,
            "baseline_time_factor": 0.6,
            "worst_vram_factor": 2.0,
            "worst_time_factor": 0.6,
            "summary_message": (
                "All 9 attempts were rejected by the pre-flight VRAM gate. "
                "Baseline 1.6x over budget; worst 2.0x. Architecture too heavy."
            ),
        }

    def test_full_populated_validates(self):
        info = GateExhaustionInfo.model_validate(self._full_kwargs())
        assert info.total_attempts == 9
        assert info.vram_gated_attempts == 9
        assert info.time_gated_attempts == 0
        assert info.other_failure_attempts == 0
        assert info.active_mode == "trial"
        assert info.vram_budget_gb == 4.0
        assert info.baseline_vram_factor == 1.6
        assert info.worst_vram_factor == 2.0

    def test_required_fields_only_with_optionals_default_none(self):
        """Only counts + active_mode + summary_message are required — all
        budget/factor fields default to None so a gate-exhaustion record can
        be built even when one axis is fully disabled."""
        info = GateExhaustionInfo.model_validate({
            "total_attempts": 3,
            "vram_gated_attempts": 0,
            "time_gated_attempts": 3,
            "other_failure_attempts": 0,
            "active_mode": "formal",
            "summary_message": "All 3 attempts were rejected by the time gate.",
        })
        assert info.vram_budget_gb is None
        assert info.time_budget_minutes is None
        assert info.baseline_vram_estimate_gb is None
        assert info.baseline_vram_factor is None
        assert info.baseline_time_estimate_minutes is None
        assert info.baseline_time_factor is None
        assert info.worst_vram_factor is None
        assert info.worst_time_factor is None

    def test_missing_required_count_raises(self):
        kwargs = self._full_kwargs()
        del kwargs["total_attempts"]
        with pytest.raises(ValidationError) as exc:
            GateExhaustionInfo.model_validate(kwargs)
        assert "total_attempts" in str(exc.value)

    def test_missing_summary_message_raises(self):
        kwargs = self._full_kwargs()
        del kwargs["summary_message"]
        with pytest.raises(ValidationError) as exc:
            GateExhaustionInfo.model_validate(kwargs)
        assert "summary_message" in str(exc.value)

    def test_missing_active_mode_raises(self):
        kwargs = self._full_kwargs()
        del kwargs["active_mode"]
        with pytest.raises(ValidationError) as exc:
            GateExhaustionInfo.model_validate(kwargs)
        assert "active_mode" in str(exc.value)

    def test_active_mode_rejects_other_strings(self):
        """Literal["trial", "formal"] — anything else must fail. Mirrors the
        time_mode test on ExperimentMemory."""
        kwargs = self._full_kwargs()
        kwargs["active_mode"] = "snapshot"
        with pytest.raises(ValidationError) as exc:
            GateExhaustionInfo.model_validate(kwargs)
        assert "active_mode" in str(exc.value)

    def test_round_trip_through_json(self):
        info = GateExhaustionInfo.model_validate(self._full_kwargs())
        reloaded = GateExhaustionInfo.model_validate_json(info.model_dump_json())
        assert reloaded == info

    # --- Fix 1 — disallowed_architectural_patterns field. See
    # docs/reliable_resource_proposer.md §7 Decision 1 + §9 Commit 1 checklist. ---

    def test_disallowed_patterns_default_empty(self):
        """New Fix-1 field must default to [] so pre-Fix-1 records and every
        existing GateExhaustionInfo test continue to round-trip unchanged."""
        info = GateExhaustionInfo.model_validate(self._full_kwargs())
        assert info.disallowed_architectural_patterns == []

    def test_disallowed_patterns_accepts_populated_list(self):
        """Tuner populates this with v1 vocabulary tags when the classifier
        fires on a gate-exhausted iteration (Commit 3)."""
        kwargs = self._full_kwargs()
        kwargs["disallowed_architectural_patterns"] = [
            "recurrent_over_T",
            "scan_over_T",
        ]
        info = GateExhaustionInfo.model_validate(kwargs)
        assert info.disallowed_architectural_patterns == [
            "recurrent_over_T",
            "scan_over_T",
        ]

    def test_disallowed_patterns_round_trip_through_json(self):
        """Patterns must survive model_dump_json → model_validate_json so the
        proposer reads the same list the tuner wrote (Commit 4)."""
        kwargs = self._full_kwargs()
        kwargs["disallowed_architectural_patterns"] = [
            "scan_over_T",
            "dense_attention_over_T",
        ]
        info = GateExhaustionInfo.model_validate(kwargs)
        reloaded = GateExhaustionInfo.model_validate_json(info.model_dump_json())
        assert reloaded.disallowed_architectural_patterns == [
            "scan_over_T",
            "dense_attention_over_T",
        ]

    def test_disallowed_patterns_rejects_non_list(self):
        """A bare string (common LLM mistake) must be rejected so a
        mispopulated field cannot silently render as one-char-per-line tags."""
        kwargs = self._full_kwargs()
        kwargs["disallowed_architectural_patterns"] = "recurrent_over_T"
        with pytest.raises(ValidationError) as exc:
            GateExhaustionInfo.model_validate(kwargs)
        assert "disallowed_architectural_patterns" in str(exc.value)

    def test_existing_full_instance_round_trip_preserves_new_field(self):
        """Round-tripping the canonical _full_kwargs() instance through JSON
        must preserve the empty default — no silent drift into missing or
        None on reload (backward-compat guard for Commit 3/4)."""
        info = GateExhaustionInfo.model_validate(self._full_kwargs())
        reloaded = GateExhaustionInfo.model_validate_json(info.model_dump_json())
        assert reloaded.disallowed_architectural_patterns == []
        assert reloaded == info


class TestHyperparamTuningOutputGateExhaustion:
    """K.7 — the new optional gate_exhaustion field on HyperparamTuningOutput.
    Defaults to None so pre-K.7 outputs validate unchanged; accepts a
    populated GateExhaustionInfo when the tuner builds one."""

    def test_default_none_when_omitted(self, valid_output_dict):
        assert "gate_exhaustion" not in valid_output_dict
        out = HyperparamTuningOutput.model_validate(valid_output_dict)
        assert out.gate_exhaustion is None

    def test_accepts_populated_info(self, valid_output_dict):
        valid_output_dict["gate_exhaustion"] = {
            "total_attempts": 9,
            "vram_gated_attempts": 9,
            "time_gated_attempts": 0,
            "other_failure_attempts": 0,
            "active_mode": "trial",
            "vram_budget_gb": 4.0,
            "time_budget_minutes": 20.0,
            "baseline_vram_estimate_gb": 6.4,
            "baseline_vram_factor": 1.6,
            "baseline_time_estimate_minutes": 12.0,
            "baseline_time_factor": 0.6,
            "worst_vram_factor": 2.0,
            "worst_time_factor": 0.6,
            "summary_message": "VRAM-gated baseline 1.6x; worst 2.0x.",
        }
        out = HyperparamTuningOutput.model_validate(valid_output_dict)
        assert out.gate_exhaustion is not None
        assert out.gate_exhaustion.vram_gated_attempts == 9
        assert out.gate_exhaustion.active_mode == "trial"
        assert out.gate_exhaustion.worst_vram_factor == 2.0

    def test_round_trip_preserves_gate_exhaustion(self, valid_output_dict):
        valid_output_dict["gate_exhaustion"] = {
            "total_attempts": 3,
            "vram_gated_attempts": 0,
            "time_gated_attempts": 3,
            "other_failure_attempts": 0,
            "active_mode": "formal",
            "summary_message": "All 3 attempts were rejected by the time gate.",
        }
        out = HyperparamTuningOutput.model_validate(valid_output_dict)
        reloaded = HyperparamTuningOutput.model_validate_json(out.model_dump_json())
        assert reloaded.gate_exhaustion == out.gate_exhaustion


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


class TestExperimentRecordSchemaViolation:
    """Phase D.4 — skipped_schema_violation records are emitted when the plugin's
    Pydantic config class rejects a tuner-proposed model_config (e.g. via a
    @model_validator(mode='after') cross-field invariant). They share the shape
    of skipped_oom_risk / skipped_time_risk: denoising_score=None, no timing,
    and memory.conclusion + memory.memory_update carry the structured violation
    info for the next round's planner."""

    def _base_record(self):
        return {
            "exp_id":          "dual_path_skip_fusion_cnn_run_007",
            "status":          "skipped_schema_violation",
            "model_type":      "dual_path_skip_fusion_cnn",
            "timestamp":       "2026-04-17 14:00:00",
            "file_index":      6,
            "params":          {"model_config": {}, "train_config": {}, "loss_config": {}},
            "denoising_score": None,
            "memory": {
                "expert_advice_followed": "",
                "hypothesis":    "widen bottleneck",
                "conclusion":    (
                    "Skipped: config violated plugin schema. "
                    "Violating fields: context_bottleneck_channels. "
                    "Offending values: stem=32, l2=96, l3=128, bottleneck=96."
                ),
                "discovery":     "nondecreasing channels rule enforced by plugin",
                "memory_update": (
                    "DO NOT repeat context_bottleneck_channels=96 with "
                    "context_level3_channels=128. Plugin requires "
                    "stem <= l2 <= l3 <= bottleneck."
                ),
            },
        }

    def test_valid_schema_violation_record(self):
        rec = ExperimentRecord.model_validate(self._base_record())
        assert rec.status == "skipped_schema_violation"
        assert rec.denoising_score is None
        assert rec.timing is None

    def test_memory_update_preserved(self):
        rec = ExperimentRecord.model_validate(self._base_record())
        assert "DO NOT repeat" in rec.memory.memory_update

    def test_invalid_status_literal_still_rejected(self):
        """Ensure we didn't accidentally open the Literal too wide."""
        r = self._base_record()
        r["status"] = "skipped_something_else"
        with pytest.raises(ValidationError) as exc:
            ExperimentRecord.model_validate(r)
        assert "status" in str(exc.value)


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
            ExperimentRecord.model_validate(self._make_error_record("error_storage"))


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


# ---------------------------------------------------------------------------
# Phase L — per-round attempt budget + fail-round abort schema fields
# See docs/resource_estimator_implement.md §11.3.
# ---------------------------------------------------------------------------

class TestPhaseLAttemptBudgetInput:
    """Three new HyperparamTuningInput fields wired with schema defaults."""

    def test_defaults(self, valid_input_dict):
        agent_input = HyperparamTuningInput.model_validate(valid_input_dict)
        assert agent_input.attempts_per_round == 3
        assert agent_input.attempts_per_formal_round == 5
        assert agent_input.max_fail_rounds == 3

    def test_overrides_accepted(self, valid_input_dict):
        valid_input_dict.update(
            attempts_per_round=2,
            attempts_per_formal_round=8,
            max_fail_rounds=4,
        )
        agent_input = HyperparamTuningInput.model_validate(valid_input_dict)
        assert agent_input.attempts_per_round == 2
        assert agent_input.attempts_per_formal_round == 8
        assert agent_input.max_fail_rounds == 4

    def test_zero_rejected_for_attempts_per_round(self, valid_input_dict):
        valid_input_dict["attempts_per_round"] = 0
        with pytest.raises(ValidationError):
            HyperparamTuningInput.model_validate(valid_input_dict)

    def test_zero_rejected_for_attempts_per_formal_round(self, valid_input_dict):
        valid_input_dict["attempts_per_formal_round"] = 0
        with pytest.raises(ValidationError):
            HyperparamTuningInput.model_validate(valid_input_dict)

    def test_zero_rejected_for_max_fail_rounds(self, valid_input_dict):
        valid_input_dict["max_fail_rounds"] = 0
        with pytest.raises(ValidationError):
            HyperparamTuningInput.model_validate(valid_input_dict)


class TestPhaseLAttemptBudgetOutput:
    """Five new HyperparamTuningOutput fields: 3 echoes + 2 terminal-state."""

    def test_defaults_when_not_provided(self, valid_output_dict):
        """A pre-Phase-L output blob must still validate (forward compat)."""
        out = HyperparamTuningOutput.model_validate(valid_output_dict)
        assert out.attempts_per_round == 3
        assert out.attempts_per_formal_round == 5
        assert out.max_fail_rounds == 3
        assert out.consecutive_fail_rounds_at_exit == 0
        assert out.termination_reason == "completed"

    def test_explicit_completed_run(self, valid_output_dict):
        valid_output_dict.update(
            attempts_per_round=3,
            attempts_per_formal_round=5,
            max_fail_rounds=3,
            consecutive_fail_rounds_at_exit=0,
            termination_reason="completed",
        )
        out = HyperparamTuningOutput.model_validate(valid_output_dict)
        assert out.termination_reason == "completed"
        assert out.consecutive_fail_rounds_at_exit == 0

    def test_aborted_fail_rounds_run(self, valid_output_dict):
        valid_output_dict.update(
            consecutive_fail_rounds_at_exit=3,
            termination_reason="aborted_fail_rounds",
        )
        out = HyperparamTuningOutput.model_validate(valid_output_dict)
        assert out.termination_reason == "aborted_fail_rounds"
        assert out.consecutive_fail_rounds_at_exit == 3

    def test_invalid_termination_reason_rejected(self, valid_output_dict):
        valid_output_dict["termination_reason"] = "max_attempts"
        with pytest.raises(ValidationError):
            HyperparamTuningOutput.model_validate(valid_output_dict)

    def test_negative_consecutive_fail_rounds_rejected(self, valid_output_dict):
        valid_output_dict["consecutive_fail_rounds_at_exit"] = -1
        with pytest.raises(ValidationError):
            HyperparamTuningOutput.model_validate(valid_output_dict)


class TestPhaseLExperimentMemoryRoundFields:
    """round_index + attempt_in_round on ExperimentMemory."""

    def test_optional_for_backward_compat(self):
        """Pre-Phase-L records have no round_index/attempt_in_round."""
        mem = ExperimentMemory(
            expert_advice_followed="x",
            hypothesis="h",
        )
        assert mem.round_index is None
        assert mem.attempt_in_round is None

    def test_explicit_values_preserved(self):
        mem = ExperimentMemory(
            expert_advice_followed="x",
            hypothesis="h",
            round_index=2,
            attempt_in_round=5,
        )
        assert mem.round_index == 2
        assert mem.attempt_in_round == 5

    def test_round_fields_round_trip_through_record(self, valid_success_record):
        valid_success_record["memory"]["round_index"] = 1
        valid_success_record["memory"]["attempt_in_round"] = 2
        record = ExperimentRecord.model_validate(valid_success_record)
        assert record.memory.round_index == 1
        assert record.memory.attempt_in_round == 2


# ---------------------------------------------------------------------------
# score_table fields (Phase 3 of docs/aggregated_score_table_awareness.md)
# ---------------------------------------------------------------------------


def _make_score_table_dict(num_sampled: int = 20):
    """Build a minimal but schema-valid ScoreComparisonTable dict."""
    rows = [
        {
            "file_index":     i,
            "raw_baseline":   0.1 * i,
            "ground_truth":   0.5 * i,
            "model":          0.3 * i,
            "gain_vs_raw":    0.2 * i,
            "headroom_vs_gt": 0.2 * i,
        }
        for i in range(20)
    ]
    return {
        "rows": rows,
        "aggregate": {
            "raw_baseline_scalar":   1.0,
            "ground_truth_scalar":   10.0,
            "model_scalar":          5.0,
            "percent_of_ceiling_log": 0.5,
            "num_sampled_files":     num_sampled,
        },
        "s_max_global":      2.957e8,
        "reference_source":  "reference_data/raw_and_ground_score.md",
        "rendered_markdown": "### stub table\n",
    }


class TestExperimentRecordScoreTable:
    """score_table on ExperimentRecord — additive, None by default."""

    def test_optional_for_backward_compat(self, valid_success_record):
        """Pre-Phase-3 records have no score_table."""
        record = ExperimentRecord.model_validate(valid_success_record)
        assert record.score_table is None

    def test_populated_score_table_round_trips(self, valid_success_record):
        valid_success_record["score_table"] = _make_score_table_dict()
        record = ExperimentRecord.model_validate(valid_success_record)
        assert record.score_table is not None
        assert record.score_table.aggregate.num_sampled_files == 20
        assert len(record.score_table.rows) == 20

    def test_invalid_score_table_rejected(self, valid_success_record):
        bad = _make_score_table_dict()
        bad["rows"] = bad["rows"][:19]  # length-19 — schema requires 20
        valid_success_record["score_table"] = bad
        with pytest.raises(ValidationError):
            ExperimentRecord.model_validate(valid_success_record)


class TestHyperparamTuningOutputScoreTables:
    """best_score_table + formal_score_table on HyperparamTuningOutput."""

    def test_both_optional_by_default(self, valid_output_dict):
        out = HyperparamTuningOutput.model_validate(valid_output_dict)
        assert out.best_score_table is None
        assert out.formal_score_table is None

    def test_best_score_table_populated(self, valid_output_dict):
        valid_output_dict["best_score_table"] = _make_score_table_dict(num_sampled=5)
        out = HyperparamTuningOutput.model_validate(valid_output_dict)
        assert out.best_score_table is not None
        assert out.best_score_table.aggregate.num_sampled_files == 5

    def test_formal_score_table_populated(self, valid_output_dict):
        valid_output_dict["formal_score_table"] = _make_score_table_dict(num_sampled=20)
        out = HyperparamTuningOutput.model_validate(valid_output_dict)
        assert out.formal_score_table is not None
        assert out.formal_score_table.aggregate.num_sampled_files == 20

    def test_both_tables_independently_populated(self, valid_output_dict):
        """best_score_table and formal_score_table can differ — e.g. when the
        best round was trial-mode and a separate formal round also landed."""
        valid_output_dict["best_score_table"] = _make_score_table_dict(num_sampled=5)
        valid_output_dict["formal_score_table"] = _make_score_table_dict(num_sampled=20)
        out = HyperparamTuningOutput.model_validate(valid_output_dict)
        assert out.best_score_table.aggregate.num_sampled_files == 5
        assert out.formal_score_table.aggregate.num_sampled_files == 20
