"""Execution facts must reach interpretation without claims from model prose."""

from types import SimpleNamespace

import pytest

from agent.prompt_templates.interpretation.rendering import _build_per_model_prompt
from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningOutput
from execute_tools.metric_order import MetricOrder
from execute_tools.training_history import TrainingResultsContractError, interpret_training_results
from nodes.ml_hyperparameter_tune_agent.planning import _psd_segment_counts
from nodes.ml_hyperparameter_tune_agent.records import _attach_completed_execution_evidence
from nodes.ml_hyperparameter_tune_agent.scope_acquisition import AttemptTopologyFacts
from nodes.result_interpretation_agent import tuning_output_to_model_run_summary
from tests.helpers.metric_fixtures import accuracy_like_spec


def _budget():
    return {
        "policy": {
            "budget_seconds": 300,
            "reserve_fraction": 0.2,
            "max_epochs": 100,
            "started_monotonic_seconds": 1,
        },
        "proposed_epochs": 10,
        "completed_epochs": 1,
        "optimizer_steps": 17,
        "epoch_seconds_including_validation": [140],
        "stop": {
            "completed_epochs": 1,
            "elapsed_seconds": 150,
            "remaining_seconds": 150,
            "reserved_seconds": 60,
            "next_epoch_seconds": 140,
            "action": "stop",
            "reason": "time_budget",
        },
    }


def test_execution_receipts_survive_typed_projection_and_reach_prompt():
    """V5: timing/stop/parameter dtype were persisted but dropped before the LLM."""
    results = interpret_training_results({"training_budget": _budget()}, expected_validation=False)
    attached = {}
    runtime = {"timestamp": "2026-09-19", "calibration_context": {"precision": "float32"}}
    _attach_completed_execution_evidence(attached, results, {"runtime_verification": runtime}, None)
    record = ExperimentRecord.model_validate(
        {
            "exp_id": "observed-formal",
            "status": "success",
            "model_type": "synthetic",
            "timestamp": "2026-09-19",
            "params": {},
            "denoising_score": 0.7,
            **attached,
            "timing": {
                "train_time_s": 146,
                "validation_time_s": 51,
                "inference_time_s": 47,
                "scoring_time_s": 7,
            },
        }
    )
    # Round-trip the same typed path used by persisted tuner output.
    output = HyperparamTuningOutput(
        run_name="execution",
        model_type="synthetic",
        file_index=0,
        status="completed",
        completed_rounds=1,
        total_attempts=1,
        all_records=[record],
        started_at="2026-09-19",
        finished_at="2026-09-19",
        best_denoising_score=0.7,
    )
    output = HyperparamTuningOutput.model_validate_json(output.model_dump_json())
    summary = tuning_output_to_model_run_summary(
        output,
        order=MetricOrder(accuracy_like_spec()),
        required_gate_ids=frozenset(),
    )
    prompt = _build_per_model_prompt(summary, "Claims mixed precision and 5.9 GB.")
    assert prompt.count("Record observed-formal (Formal)") == 1
    assert '"train_time_s":146.0' in prompt
    assert '"validation_time_s":51.0' in prompt
    assert "Parameter dtype: float32" in prompt
    assert "compute precision is not established by parameter dtype" in prompt
    assert "completed epochs=1; optimizer steps=17" in prompt
    assert '"reason":"time_budget"' in prompt
    assert "not evidence of convergence" in prompt


def test_malformed_budget_is_not_silently_dropped_at_training_boundary():
    with pytest.raises(TrainingResultsContractError, match="training_budget"):
        interpret_training_results({"training_budget": {"stop": "bad"}}, expected_validation=False)


def test_opaque_scopes_never_report_whole_file_geometry_as_selected_count():
    """V5: a physical profile is not a count of the task-selected scope."""
    facts = AttemptTopologyFacts(physical_dataset=SimpleNamespace(segments_per_file=37))
    assert _psd_segment_counts(None, None, facts, has_task_scopes=True) == (None, None)
    assert _psd_segment_counts(None, None, facts) == (37, 37)
    assert _psd_segment_counts({}, {"sample": [1, 2]}, facts) == (0, 2)
