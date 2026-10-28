"""Custom plan fallback, trial cross-field validation, and record score-table checks."""

from typing import ClassVar

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import (
    ExperimentPlan,
    ExperimentRecord,
    TrialConfig,
)


@pytest.fixture
def valid_success_record():
    return {
        "exp_id": "punet_v1_001",
        "status": "success",
        "model_type": "punet",
        "timestamp": "2026-03-11 10:00:00",
        "file_index": 6,
        "params": {"model_config": {}, "train_config": {}, "loss_config": {}},
        "final_loss": 0.5,
        "loss_history": [0.8, 0.6, 0.5],
        "model_params": 50000,
        "denoising_score": 1.23,
        "timing": {
            "train_time_s": 120.0,
            "inference_time_s": 30.0,
            "scoring_time_s": 10.0,
        },
        "memory": {
            "expert_advice_followed": "try deeper architectures",
            "hypothesis": "deeper encoder improves SNR",
            "conclusion": "score improved by 0.3",
            "discovery": "depth > 3 helps",
            "memory_update": "try depth=4 next",
        },
    }


class TestExperimentPlan:
    """Verify ExperimentPlan schema validates brain.plan() output correctly."""

    def test_plan_rejections(self):
        """Targeted trial plans require at least one target file."""
        with pytest.raises(ValidationError, match="target_files required"):
            ExperimentPlan.model_validate(
                {"is_trial": True, "trial_strategy": "target", "target_files": []}
            )

    @pytest.mark.parametrize(
        "input_value, expected_attr, expected_value",
        [
            pytest.param(
                {
                    "model_type": "punet",
                    "hypothesis": "Test hypothesis",
                    "model_config": {"depth": 4},
                    "train_config": {"lr": 1e-4},
                    "loss_config": {"loss_type": "focal"},
                    "trial_portion": 5.0,  # invalid
                },
                "trial_portion",
                0.02,
                id="invalid_field_falls_back_to_default",
            ),
            pytest.param(
                {"model_type": "punet", "trial_portion": 0.3, "trial_strategy": "anchors"},
                "trial_portion",
                0.3,
                id="valid_input_passes_through",
            ),
            pytest.param(
                [{"model_type": "punet", "hypothesis": "Wrapped in list", "trial_portion": 0.3}],
                "trial_portion",
                0.3,
                id="single_element_list_unwrapped",
            ),
        ],
    )
    def test_with_defaults_shapes(self, input_value, expected_attr, expected_value):
        """``ExperimentPlan.with_defaults`` strips invalid trial fields,
        passes through valid ones, and unwraps the single-element-list
        shape the LLM occasionally emits."""
        plan = ExperimentPlan.with_defaults(input_value)
        assert getattr(plan, expected_attr) == expected_value

    @pytest.mark.parametrize(
        "bad_input, error_type, error_match",
        [
            pytest.param(
                [{"model_type": "punet"}, {"model_type": "wavenet"}],
                TypeError,
                "list of length 2",
                id="multi_element_list_rejected",
            ),
            pytest.param(
                "not a dict",
                TypeError,
                "expected a dict",
                id="non_dict_rejected",
            ),
        ],
    )
    def test_with_defaults_rejections(self, bad_input, error_type, error_match):
        with pytest.raises(error_type, match=error_match):
            ExperimentPlan.with_defaults(bad_input)


class TestTrialConfig:
    """Verify TrialConfig schema validates trial/formal decisions correctly."""

    # Common seed values for tests
    _SEEDS: ClassVar[dict[str, int]] = {
        "train_sampling_seed": 42,
        "eval_sampling_seed": 42,
        "seed_context": {"run_seed": 123},
    }

    @pytest.mark.parametrize(
        "kwargs, error_match",
        [
            pytest.param(
                dict(is_trial=False, mode="single_file"),
                "file_index required",
                id="single_file_without_file_index",
            ),
            pytest.param(
                dict(is_trial=True, mode="trial", trial_strategy="target", target_files=[]),
                "target_files required",
                id="trial_target_with_empty_files",
            ),
        ],
    )
    def test_mode_rejections(self, kwargs, error_match):
        """Single-file and targeted trials require their respective file selections."""
        with pytest.raises(ValidationError, match=error_match):
            TrialConfig(**kwargs, **self._SEEDS)


def _make_score_table_dict(num_sampled: int = 20):
    """Build a minimal but schema-valid ScoreComparisonTable dict."""
    rows = [
        {
            "file_index": i,
            "raw_baseline": 0.1 * i,
            "ground_truth": 0.5 * i,
            "model": 0.3 * i,
            "gain_vs_raw": 0.2 * i,
            "headroom_vs_gt": 0.2 * i,
        }
        for i in range(20)
    ]
    return {
        "rows": rows,
        "aggregate": {
            "raw_baseline_scalar": 1.0,
            "ground_truth_scalar": 10.0,
            "model_scalar": 5.0,
            "percent_of_ceiling_log": 0.5,
            "num_sampled_files": num_sampled,
        },
        "s_max_global": 2.957e8,
        "reference_source": "reference_data/raw_and_ground_score.md",
        "rendered_markdown": "### stub table\n",
    }


class TestExperimentRecordScoreTable:
    """Record validation rejects score-table rows inconsistent with the sampled count."""

    def test_invalid_score_table_rejected(self, valid_success_record):
        bad = _make_score_table_dict()
        bad["rows"] = bad["rows"][:19]  # length-19 — schema requires 20
        valid_success_record["score_table"] = bad
        with pytest.raises(ValidationError):
            ExperimentRecord.model_validate(valid_success_record)


pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")
