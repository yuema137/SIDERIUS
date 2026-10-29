"""Environment refusals stop the real tuner loop; model failures still retry.

The refusal regression fails at the attempt/plan counts when the training
refusal branch is reverted. No provider, GPU, or scientific dataset is used.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput, HyperparamTuningOutput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from core.runtime_control.admission import AdmissionDecision, AdmissionReason
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from nodes.scoring_reference import ReferenceScores
from tests.helpers.run_seed import TEST_RUN_SEED

pytestmark = pytest.mark.usefixtures("synthetic_run_authorities", "synthetic_physical_data_root")

_NODE = "nodes.ml_hyperparameter_tune_agent"
_MESSAGE = "GPU phase not started: current environment evidence is unavailable."


def _drive(
    tmp_path: Path, training_status: dict
) -> tuple[HyperparamTuningOutput, int, int, list[dict]]:
    agent_input = HyperparamTuningInput(
        run_seed=TEST_RUN_SEED,
        planner_strategy="native-timing-v1",
        model_type="punet",
        file_index=6,
        max_rounds=2,
        attempts_per_round=3,
        attempts_per_formal_round=3,
        max_fail_rounds=3,
        llm_provider="gemini",
        llm_model_id="test-model",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="environment_stop"),
        ),
        progress_bar=False,
    )
    reference = ReferenceScores(
        raw_per_file_log=[-2.7] * 20,
        gt_per_file_log=[7.0] * 20,
        raw_per_file_linear_sum=[2.0] * 20,
        gt_per_file_linear_sum=[2000.0] * 20,
        raw_per_file_n_segments=[200] * 20,
        gt_per_file_n_segments=[200] * 20,
        raw_scalar_full=-2.7,
        gt_scalar_full=7.0,
        s_max=295_715_680.14,
    )
    training_calls = 0

    def skill(folder, sandbox, **kwargs):
        nonlocal training_calls
        if folder == "check_config_format_skill":
            return {"status": "success", "data": {"punet": {"fields": ["depth"]}}}
        if folder == "evaluate_vram_skill":
            return {
                "status": "success",
                "feasible": True,
                "estimated_gb": 2.5,
                "limit_gb": 6.0,
                "vram_budget_gb": 8.0,
                "verdict": "FITS",
            }
        if folder == "training_skill":
            training_calls += 1
            return training_status
        raise AssertionError(f"Unexpected downstream skill: {folder}")

    saved: list[dict] = []
    configs = tmp_path / "configs"
    configs.mkdir()
    with (
        patch(f"{_NODE}.LLMBridge") as bridge,
        patch(f"{_NODE}.TidmadSandbox") as sandbox_type,
        patch(f"{_NODE}.load_reference_scores", return_value=reference),
        patch(f"{_NODE}.runtime._run_skill", side_effect=skill),
        patch(f"{_NODE}.round_health.get_gates_for_position", return_value=[]),
        patch(f"{_NODE}.ml_hyperparameter_tune_agent.time.sleep"),
    ):
        brain = bridge.return_value
        brain.plan.return_value = {
            "model_type": "punet",
            "hypothesis": "h",
            "reasoning": "r",
            "model_config": {"depth": 4, "segmentation_size": 40000, "batch_size": 1},
            "train_config": {"epochs": 5, "lr": 1e-4},
            "loss_config": {"loss_type": "ce"},
        }
        sandbox = sandbox_type.return_value
        sandbox.get_summary.side_effect = lambda: list(saved)
        sandbox.save_record.side_effect = saved.append
        sandbox.dirs = {"configs": str(configs)}
        output = HyperparamTuningAgent().run(agent_input)
        return output, brain.plan.call_count, training_calls, saved


def _refusal(reason_code: AdmissionReason) -> dict:
    decision = AdmissionDecision(
        admitted=False,
        reason_code=reason_code,
        requirement_source="unavailable",
        reason=_MESSAGE,
    )
    return {
        "status": "skipped_resource_admission",
        "message": _MESSAGE,
        "admission": decision.model_dump(mode="json"),
    }


@pytest.mark.parametrize(
    "reason_code",
    [
        "environment_headroom_unproven",
        "measurement_unavailable",
        "policy_unavailable",
    ],
)
def test_environment_refusal_stops_without_replanning(tmp_path: Path, reason_code: AdmissionReason):
    output, plans, training_calls, _saved = _drive(tmp_path, _refusal(reason_code))
    assert output.total_attempts == training_calls == 1
    assert plans == 1  # The initial plan only: zero replans.
    assert output.completed_rounds == output.consecutive_fail_rounds_at_exit == 0
    assert output.termination_reason == "infrastructure_abort"
    assert output.status == "failed"
    assert output.best_denoising_score is None
    assert output.environment_admission_refusal is not None
    assert output.environment_admission_refusal.reason_code == reason_code
    assert output.environment_admission_refusal.reason == _MESSAGE
    assert len(output.all_records) == 1
    record = output.all_records[0]
    assert record.status == "skipped_infrastructure_failure"
    persisted = list(tmp_path.rglob("run_output_environment_stop.json"))
    assert len(persisted) == 1
    payload = json.loads(persisted[0].read_text())
    assert payload["environment_admission_refusal"]["reason_code"] == reason_code
    assert payload["environment_admission_refusal"]["reason"] == _MESSAGE


@pytest.mark.parametrize(
    "training_status",
    [
        {"status": "error", "message": "Training loss became NaN"},
        {"status": "error", "message": "CUDA out of memory. Reduce batch size."},
        _refusal("insufficient_headroom"),
    ],
)
def test_model_failures_preserve_attempt_and_round_retries(tmp_path: Path, training_status: dict):
    output, plans, training_calls, _saved = _drive(tmp_path, training_status)
    assert output.total_attempts == training_calls == plans == 9
    assert output.consecutive_fail_rounds_at_exit == 3
    assert output.termination_reason == "aborted_fail_rounds"
    assert output.environment_admission_refusal is None


@pytest.mark.parametrize("missing_field", ["reason_code", "requirement_source"])
def test_incomplete_admission_stops_without_duplicate_record(tmp_path: Path, missing_field: str):
    """Missing codes and invalid evidence must not become nine model retries."""
    status = _refusal("environment_headroom_unproven")
    del status["admission"][missing_field]
    output, plans, training_calls, saved = _drive(tmp_path, status)
    assert output.total_attempts == training_calls == plans == 1
    assert output.consecutive_fail_rounds_at_exit == 0
    assert output.termination_reason == "infrastructure_abort"
    assert len(output.all_records) == 1  # No second attempt_failure after validation fails.
    record = output.all_records[0]
    assert record.status == "skipped_infrastructure_failure"
    refusal = output.environment_admission_refusal
    assert refusal is not None
    expected_code = (
        "policy_unavailable" if missing_field == "reason_code" else "environment_headroom_unproven"
    )
    assert refusal.reason_code == saved[0]["memory"]["reason_code"] == expected_code
    assert refusal.reason == _MESSAGE
