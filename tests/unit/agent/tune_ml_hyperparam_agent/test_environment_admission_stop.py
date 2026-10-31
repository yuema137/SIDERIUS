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
from core.runtime_control.admission import (
    AdmissionDecision,
    AdmissionReason,
    evaluate_gpu_admission,
    stops_phase,
)
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from nodes.scoring_reference import ReferenceScores
from tests.helpers.run_seed import TEST_RUN_SEED

pytestmark = pytest.mark.usefixtures("synthetic_run_authorities", "synthetic_physical_data_root")

_NODE = "nodes.ml_hyperparameter_tune_agent"
_MESSAGE = "GPU phase not started: current environment evidence is unavailable."


def _drive(
    tmp_path: Path,
    training_status: dict | list[dict],
    *,
    phase: str = "training",
    max_rounds: int = 2,
    trial_attempts: int = 3,
) -> tuple[HyperparamTuningOutput, int, int, list[dict]]:
    agent_input = HyperparamTuningInput(
        # This fixture exercises legacy single-file attempts, not trial scheduling.
        is_trial=False,
        run_seed=TEST_RUN_SEED,
        planner_strategy="native-timing-v1",
        model_type="punet",
        file_index=6,
        max_rounds=max_rounds,
        attempts_per_round=trial_attempts,
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
    phase_calls = 0

    def skill(folder, sandbox, **kwargs):
        nonlocal training_calls, phase_calls
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
        if folder == f"{phase}_skill":
            phase_calls += 1
            if isinstance(training_status, list):
                return training_status[min(phase_calls - 1, len(training_status) - 1)]
            return training_status
        if folder == "training_skill":
            return {"status": "success", "results": {"final_loss": 0.5, "model_params": 1}}
        if folder == "inference_skill":
            return {"status": "success"}
        if folder == "denoising_score_skill":
            return {"status": "success", "results": {"denoising_score": -2.5}}
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
        if phase == "inference":
            assert training_calls == output.total_attempts  # Inference retry never retrains.
        return output, brain.plan.call_count, phase_calls, saved


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
@pytest.mark.parametrize("phase", ["training", "inference"])
def test_environment_refusal_stops_without_replanning(
    tmp_path: Path, reason_code: AdmissionReason, phase: str
):
    output, plans, training_calls, _saved = _drive(tmp_path, _refusal(reason_code), phase=phase)
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
@pytest.mark.parametrize("phase", ["training", "inference"])
def test_incomplete_admission_stops_without_duplicate_record(
    tmp_path: Path, missing_field: str, phase: str
):
    """Missing codes and invalid evidence must not become nine model retries."""
    status = _refusal("environment_headroom_unproven")
    del status["admission"][missing_field]
    output, plans, training_calls, saved = _drive(tmp_path, status, phase=phase)
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


def test_incomplete_resource_refusal_preserves_code_status_and_retries(tmp_path: Path):
    """A recognized resource verdict survives missing AdmissionDecision fields."""
    status = {
        "status": "skipped_resource_admission",
        "message": "Measured demand exceeds headroom; reduce settings.",
        "admission": {"reason_code": "insufficient_headroom"},
    }
    output, plans, training_calls, saved = _drive(tmp_path, status)
    assert output.total_attempts == training_calls == plans == 9
    assert len(saved) == len(output.all_records) == 9
    assert {record["status"] for record in saved} == {"skipped_resource_admission"}
    assert {record["memory"]["reason_code"] for record in saved} == {"insufficient_headroom"}
    assert output.termination_reason == "aborted_fail_rounds"
    assert output.environment_admission_refusal is None


def _sampler_refusal() -> dict:
    decision = evaluate_gpu_admission(
        snapshot=None,
        requirement_mib=None,
        requirement_provenance=None,
        mode="formal",
        sampling_error="temporary sampler failure",
    )
    assert stops_phase("enforce", decision.reason_code, evidence=decision.evidence)
    return {
        "status": "skipped_resource_admission",
        "message": decision.reason,
        "admission": decision.model_dump(mode="json"),
    }


@pytest.mark.parametrize("phase", ["training", "inference"])
@pytest.mark.parametrize("max_rounds", [1, 2])
def test_transient_sampling_recovers_without_replanning(
    tmp_path: Path, phase: str, max_rounds: int
):
    """A sampler refusal followed by success reaches scoring, on the same plan."""
    success = {"status": "success", "results": {"final_loss": 0.5, "model_params": 1}}
    output, plans, calls, _ = _drive(
        tmp_path, [_sampler_refusal(), success], phase=phase, max_rounds=max_rounds
    )
    assert output.termination_reason == "completed"
    assert output.best_denoising_score == -2.5
    assert calls == plans + 1
    assert plans == output.total_attempts == max_rounds
    assert output.environment_admission_refusal is None


@pytest.mark.parametrize("phase", ["training", "inference"])
@pytest.mark.parametrize("max_rounds, expected_calls", [(1, 3), (2, 2)])
def test_persistent_sampling_exhausts_budget_without_replanning(
    tmp_path: Path, phase: str, max_rounds: int, expected_calls: int
):
    output, plans, calls, saved = _drive(
        tmp_path, _sampler_refusal(), phase=phase, max_rounds=max_rounds, trial_attempts=2
    )
    assert calls == expected_calls
    assert plans == output.total_attempts == 1
    assert output.termination_reason == "infrastructure_abort"
    assert output.consecutive_fail_rounds_at_exit == 0
    assert len(saved) == len(output.all_records) == 1
    assert output.environment_admission_refusal is not None
    assert output.environment_admission_refusal.detail == "sampler_error"


@pytest.mark.parametrize("phase", ["training", "inference"])
@pytest.mark.parametrize(
    "detail", ["telemetry_unavailable", "device_identity_mismatch", "inconsistent_accounting"]
)
def test_non_sampler_measurement_refusals_do_not_retry(tmp_path: Path, phase: str, detail: str):
    status = _refusal("measurement_unavailable")
    status["admission"]["detail"] = detail
    status["message"] = "sampler_error"  # Text never determines recovery.
    output, plans, calls, _ = _drive(tmp_path, status, phase=phase)
    assert calls == plans == 1
    assert output.termination_reason == "infrastructure_abort"


@pytest.mark.parametrize("phase", ["training", "inference"])
def test_sampling_uses_only_remaining_attempt_allowance(tmp_path: Path, phase: str):
    """A previous resource failure leaves two sampling tries, not three."""
    output, plans, calls, _ = _drive(
        tmp_path, [_refusal("insufficient_headroom"), _sampler_refusal()], phase=phase
    )
    assert calls == 3
    assert plans == output.total_attempts == 2
    assert output.termination_reason == "infrastructure_abort"
    assert output.consecutive_fail_rounds_at_exit == 0


def test_sampling_backoff_is_bounded_and_injectable():
    """Each retry waits, capped at one second; the terminal result adds no wait."""
    from types import SimpleNamespace

    from nodes.ml_hyperparameter_tune_agent.contracts import AttemptIdentity
    from nodes.ml_hyperparameter_tune_agent.phase_admission import run_admitted_skill

    bindings = SimpleNamespace(agent_input=SimpleNamespace(attempts_per_round=6), sandbox=object())
    delays = []
    with patch(
        f"{_NODE}.runtime._run_skill",
        side_effect=[_sampler_refusal()] * 5 + [{"status": "success"}],
    ):
        status, refusal = run_admitted_skill(
            bindings,
            SimpleNamespace(active_params={}),
            AttemptIdentity(round_index=1, attempt_in_round=1, is_formal_round=False),
            phase="training",
            sleep=delays.append,
        )
    assert status == {"status": "success"}
    assert refusal is None
    assert delays == [0.25, 0.5, 1.0, 1.0, 1.0]
