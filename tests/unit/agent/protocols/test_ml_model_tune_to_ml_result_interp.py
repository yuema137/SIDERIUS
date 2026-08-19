"""
Unit tests for agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py

Parametrized to collapse one-attribute-per-test extraction noise into
multi-assertion baselines. Each baseline pins a distinct contract:
single-record extraction, round-list extraction, empty-records defaults,
formal-round handoff, and storage pass-through.

Tests cover:
  local_all_records
    - Returns a valid InterpretationInput with exactly one ModelRunSummary
    - All single-record attributes (model_type, run_name, scores,
      best_file_vector, best_model_params, psd segment counts,
      trial_portion) extracted from the canonical success record
    - Round-list attributes (round_scores, round_conclusions,
      round_trial_portions, round_model_params) extracted across mixed
      success + skipped records
    - Empty all_records yields ModelRunSummary with None / [] defaults
    - Formal-round record is recognised and surfaces formal_score +
      formal_file_vector
    - storage is passed through correctly

  database_all_records
    - Raises NotImplementedError (placeholder, not yet implemented)
"""

import pytest

from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningOutput
from agent.schemas.interpretation import InterpretationInput, ModelRunSummary
from agent.schemas.protocols.ml_model_tune_to_ml_result_interp import (
    database_all_records,
    local_all_records,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from tests.helpers.metric_fixtures import shipped_spec

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
        denoising_score=1.5,
        final_loss=0.5,
        model_params=50000,
        file_vector=[
            0.001,
            0.01,
            0.1,
            0.5,
            1.0,
            2.0,
            5.0,
            78.0,
            1.5,
            2.5,
            3.0,
            7.0,
            1.3,
            0.9,
            40.0,
            21.0,
            5.0,
            5.0,
            3.0,
            0.8,
        ],
        training_psd_segments=200,
        eval_psd_segments=200,
        is_trial=True,
        trial_strategy="snapshot",
        trial_portion=0.05,
        memory={
            "expert_advice_followed": "",
            "hypothesis": "Try depth 3",
            "conclusion": "Improved score to 1.5.",
        },
    )


@pytest.fixture
def record_formal():
    """A formal (non-trial) round record."""
    return ExperimentRecord(
        exp_id="exp_003",
        status="success",
        model_type="punet",
        timestamp="2026-01-01 02:00:00",
        file_index=6,
        params={"model_config": {"depth": 3}, "train_config": {"lr": 1e-4}},
        denoising_score=1.2,
        final_loss=0.4,
        model_params=50000,
        file_vector=[
            0.002,
            0.02,
            0.15,
            0.6,
            1.1,
            2.2,
            5.5,
            80.0,
            1.6,
            2.6,
            3.1,
            7.5,
            1.4,
            1.0,
            41.0,
            22.0,
            5.2,
            5.1,
            3.2,
            0.9,
        ],
        training_psd_segments=4000,
        eval_psd_segments=4000,
        is_trial=False,
        memory={
            "expert_advice_followed": "",
            "hypothesis": "Formal validation",
            "conclusion": "Formal score 1.2 on full data.",
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
        # Step 09a C2 — a real tuner stamps its already-resolved MetricSpec on
        # every output; the interpreter now REFUSES a score-bearing input that
        # carries none. Stamping here keeps this fixture a faithful stand-in.
        metric_spec=shipped_spec(),
    )


# ---------------------------------------------------------------------------
# local_all_records
# ---------------------------------------------------------------------------


class TestLocalAllRecords:
    def test_single_record_baseline_extracts_all_summary_fields(
        self,
        storage,
        record_success,
    ):
        """One canonical success record -> the protocol must populate every
        documented single-record field on ModelRunSummary. Replaces 12 flat
        single-assertion tests (returns_interpretation_input, single_summary,
        model_type_passed, run_name_passed, best_score_passed,
        worst_score_computed, best_file_vector_extracted,
        best_model_params_extracted, training_psd_segments_extracted,
        trial_portion_extracted, storage_passed_through, no_formal_round).

        With only one success record, worst == best (single-element set),
        and there is no formal round so formal_* fields stay None."""
        output = make_tuning_output(
            "fcnet",
            "my_run",
            [record_success],
            best_score=1.5,
        )
        result = local_all_records(output, storage)

        assert isinstance(result, InterpretationInput)
        assert len(result.summaries) == 1
        summary = result.summaries[0]
        assert isinstance(summary, ModelRunSummary)

        # Identity / score pass-through.
        assert summary.model_type == "fcnet"
        assert summary.run_name == "my_run"
        assert summary.best_denoising_score == 1.5
        assert summary.worst_denoising_score == 1.5

        # File-vector + model-size pass-through.
        assert summary.best_file_vector is not None
        assert len(summary.best_file_vector) == 20
        assert summary.best_file_vector[7] == 78.0  # highest value
        assert summary.best_model_params == 50000

        # PSD segment counts pass through.
        assert summary.training_psd_segments == 200
        assert summary.eval_psd_segments == 200

        # Trial-mode metadata pass-through.
        assert summary.trial_portion == 0.05

        # No formal round in this fixture.
        assert summary.formal_score is None
        assert summary.formal_file_vector is None

        # Storage round-trips intact.
        assert result.storage.local.workspace == "/tmp/proto_test"
        assert result.storage.local.run_name == "r1"

    def test_round_lists_extracted_across_mixed_records(
        self,
        storage,
        record_success,
        record_oom,
    ):
        """Two records (success + OOM-skip) -> every per-round list on
        ModelRunSummary must carry both entries in order, with the OOM
        record contributing None for numeric fields and a conclusion
        string mentioning 'OOM'. Replaces four flat single-assertion tests
        (round_scores_extracted, round_conclusions_extracted,
        round_trial_portions_extracted, round_model_params_extracted)."""
        output = make_tuning_output(
            "punet",
            "v1",
            [record_success, record_oom],
            best_score=1.5,
        )
        summary = local_all_records(output, storage).summaries[0]

        assert summary.round_scores == [1.5, None]
        assert summary.round_conclusions[0] == "Improved score to 1.5."
        assert "OOM" in summary.round_conclusions[1]
        assert summary.round_trial_portions == [0.05, None]
        assert summary.round_model_params == [50000, None]

    def test_empty_records_yields_default_summary(self, storage):
        """Zero records -> the ModelRunSummary still exists (one per
        tuning output) but every per-round list is empty and every
        per-record scalar is None. Replaces two flat tests
        (empty_records + empty_records_new_fields)."""
        output = make_tuning_output("punet", "v1", [])
        summary = local_all_records(output, storage).summaries[0]

        # Scalar fields default to None / 0.
        assert summary.completed_rounds == 0
        assert summary.best_file_vector is None
        assert summary.best_model_params is None
        assert summary.training_psd_segments is None
        assert summary.formal_score is None

        # List fields default to [].
        assert summary.round_scores == []
        assert summary.round_trial_portions == []
        assert summary.round_model_params == []

    def test_formal_round_surfaces_formal_score_and_vector(
        self,
        storage,
        record_success,
        record_formal,
    ):
        """When a formal (is_trial=False) record exists alongside trial
        rounds, the protocol must extract formal_score + formal_file_vector
        from it. Kept separate from the single-record baseline because the
        formal-round path is a distinct branch in the protocol code."""
        output = make_tuning_output(
            "punet",
            "v1",
            [record_success, record_formal],
            best_score=1.5,
        )
        summary = local_all_records(output, storage).summaries[0]

        assert summary.formal_score == 1.2
        assert summary.formal_file_vector is not None
        assert len(summary.formal_file_vector) == 20


# ---------------------------------------------------------------------------
# database_all_records
# ---------------------------------------------------------------------------


class TestDatabaseAllRecords:
    def test_raises_not_implemented(self, storage):
        output = make_tuning_output("punet", "v1", [])
        with pytest.raises(NotImplementedError):
            database_all_records(output, storage)
