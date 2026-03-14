"""
Unit tests for agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py

Tests cover:
  local_all_records
    - Returns a valid InterpretationInput
    - summaries contains exactly one ModelRunSummary
    - ModelRunSummary has correct model_type, run_name, scores
    - round_scores and round_conclusions extracted from records
    - storage is passed through correctly
    - works with empty all_records

  database_all_records
    - Raises NotImplementedError (placeholder, not yet implemented)
"""
import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput, ExperimentRecord
from agent.schemas.interpretation import InterpretationInput, ModelRunSummary
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from agent.schemas.protocols.ml_model_tune_to_ml_result_interp import (
    local_all_records,
    database_all_records,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def storage():
    return StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace="/tmp/proto_test", run_name="r1"),
    )


@pytest.fixture
def record_success():
    return ExperimentRecord(
        exp_id="exp_001",
        status="success",
        model_type="punet",
        timestamp="2026-01-01 00:00:00",
        file_index=6,
        params={"model_config": {"depth": 3}, "train_config": {"lr": 1e-4}},
        results={"denoising_score": 1.5},
        denoising_score=1.5,
        memory={
            "expert_advice_followed": "",
            "hypothesis": "Try depth 3",
            "conclusion": "Improved score to 1.5.",
        },
    )


@pytest.fixture
def record_oom():
    return ExperimentRecord(
        exp_id="exp_002",
        status="skipped_oom_risk",
        model_type="punet",
        timestamp="2026-01-01 01:00:00",
        file_index=6,
        params={},
        results={},
        memory={
            "expert_advice_followed": "",
            "hypothesis": "Large batch",
            "conclusion": "Skipped due to OOM risk.",
        },
    )


def make_tuning_output(model_type, run_name, records, best_score=None, best_config=None):
    return HyperparamTuningOutput(
        run_name=run_name,
        model_type=model_type,
        file_index=6,
        status="completed",
        completed_rounds=len([r for r in records if r.status == "success"]),
        total_attempts=len(records),
        best_denoising_score=best_score,
        best_config=best_config,
        all_records=records,
        started_at="2026-01-01T00:00:00",
        finished_at="2026-01-01T01:00:00",
    )


# ---------------------------------------------------------------------------
# local_all_records
# ---------------------------------------------------------------------------

class TestLocalAllRecords:

    def test_returns_interpretation_input(self, storage, record_success):
        output = make_tuning_output("punet", "v1", [record_success], best_score=1.5)
        result = local_all_records(output, storage)
        assert isinstance(result, InterpretationInput)

    def test_single_summary(self, storage, record_success):
        output = make_tuning_output("punet", "v1", [record_success], best_score=1.5)
        result = local_all_records(output, storage)
        assert len(result.summaries) == 1
        assert isinstance(result.summaries[0], ModelRunSummary)

    def test_model_type_passed(self, storage, record_success):
        output = make_tuning_output("fcnet", "run2", [record_success], best_score=1.5)
        result = local_all_records(output, storage)
        assert result.summaries[0].model_type == "fcnet"

    def test_run_name_passed(self, storage, record_success):
        output = make_tuning_output("punet", "my_run", [record_success], best_score=1.5)
        result = local_all_records(output, storage)
        assert result.summaries[0].run_name == "my_run"

    def test_best_score_passed(self, storage, record_success):
        output = make_tuning_output("punet", "v1", [record_success], best_score=1.5)
        result = local_all_records(output, storage)
        assert result.summaries[0].best_denoising_score == 1.5

    def test_worst_score_computed(self, storage, record_success):
        output = make_tuning_output("punet", "v1", [record_success], best_score=1.5)
        result = local_all_records(output, storage)
        assert result.summaries[0].worst_denoising_score == 1.5

    def test_round_scores_extracted(self, storage, record_success, record_oom):
        output = make_tuning_output("punet", "v1", [record_success, record_oom], best_score=1.5)
        result = local_all_records(output, storage)
        assert result.summaries[0].round_scores == [1.5, None]

    def test_round_conclusions_extracted(self, storage, record_success, record_oom):
        output = make_tuning_output("punet", "v1", [record_success, record_oom], best_score=1.5)
        result = local_all_records(output, storage)
        assert result.summaries[0].round_conclusions[0] == "Improved score to 1.5."
        assert "OOM" in result.summaries[0].round_conclusions[1]

    def test_empty_records(self, storage):
        output = make_tuning_output("punet", "v1", [])
        result = local_all_records(output, storage)
        assert result.summaries[0].round_scores == []
        assert result.summaries[0].completed_rounds == 0

    def test_storage_passed_through(self, storage, record_success):
        output = make_tuning_output("punet", "v1", [record_success], best_score=1.5)
        result = local_all_records(output, storage)
        assert result.storage.local.workspace == "/tmp/proto_test"
        assert result.storage.local.run_name == "r1"


# ---------------------------------------------------------------------------
# database_all_records
# ---------------------------------------------------------------------------

class TestDatabaseAllRecords:

    def test_raises_not_implemented(self, storage):
        output = make_tuning_output("punet", "v1", [])
        with pytest.raises(NotImplementedError):
            database_all_records(output, storage)
