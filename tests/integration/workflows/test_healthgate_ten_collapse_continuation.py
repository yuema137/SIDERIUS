"""Pseudo-integration coverage for collapsed-but-completed tuning rounds."""

from __future__ import annotations

import copy
import importlib
import json

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from execute_tools.health_checks.schemas import GateAction, GateResult, HealthCheckResult
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from tests.helpers.recording_llm_bridge import RecordingLLMBridge
from tests.helpers.recording_sandbox import RecordingSandbox


def _load_json(path):
    with open(path) as handle:
        return json.load(handle)


def test_ten_collapsed_rounds_are_recorded_and_do_not_terminate(tmp_path, monkeypatch):
    """Ten HealthGate failures with CONTINUE remain completed experiments."""
    tuner_module = importlib.import_module(
        "nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent"
    )

    monkeypatch.setattr(tuner_module.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tuner_module, "get_gates_for_position", lambda _round: ["collapse"])

    def failed_continue(_gate_id, ctx):
        check = HealthCheckResult(
            check_name="output_diversity",
            passed=False,
            reason="output_diversity: near-constant class-127 output",
            metrics={"unique_count": 1},
        )
        return GateResult(
            gate_id="collapse",
            round_index=ctx.round_index,
            passed=False,
            action=GateAction.CONTINUE,
            check_results=[check],
            failure_reason=check.reason,
        )

    monkeypatch.setattr(tuner_module, "evaluate_gate", failed_continue)

    plan = _load_json(
        "tests/pseudo_data/api_call_outputs/ml_hyperparameter_tune_agent/generate.json"
    )
    plan.update({"is_trial": True, "train_portion": 0.1})
    plan["train_config"].update({"epochs": 1, "device": "cpu"})
    reflection = _load_json(
        "tests/pseudo_data/api_call_outputs/ml_hyperparameter_tune_agent/reflect.json"
    )
    training = _load_json("tests/pseudo_data/train_outputs/punet/execute_training.json")
    inference = _load_json("tests/pseudo_data/train_outputs/punet/execute_inference.json")
    collapsed_score = {"file_vector": [None] * 20, "scalar": float("-inf")}

    bridge = RecordingLLMBridge(
        responses={
            "generate": [copy.deepcopy(plan) for _ in range(10)],
            "reflect": [copy.deepcopy(reflection) for _ in range(10)],
        }
    )
    sandbox = RecordingSandbox(
        base_dir=str(tmp_path),
        run_name="ten_collapses",
        canned={
            "execute_training": [copy.deepcopy(training) for _ in range(10)],
            "execute_inference": [copy.deepcopy(inference) for _ in range(10)],
            "score_vector": [copy.deepcopy(collapsed_score) for _ in range(10)],
        },
    )
    agent = HyperparamTuningAgent(
        bridge_factory=lambda **_kwargs: bridge,
        sandbox_factory=lambda **_kwargs: sandbox,
    )
    agent_input = HyperparamTuningInput(
        model_type="punet",
        max_rounds=10,
        attempts_per_round=1,
        attempts_per_formal_round=1,
        max_fail_rounds=3,
        force_formal_round=False,
        max_epochs=1,
        is_trial=True,
        trial_portion=0.05,
        train_portion=0.1,
        eval_portion=0.05,
        trial_time_budget_minutes=None,
        trial_vram_budget_gb=1000.0,
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="ten_collapses"),
        ),
        progress_bar=False,
    )

    output = agent.run(agent_input)

    assert output.completed_rounds == 10
    assert output.total_attempts == 10
    assert output.consecutive_fail_rounds_at_exit == 0
    assert output.termination_reason == "completed"
    assert len(output.all_records) == 10
    assert len(sandbox.saved_records) == 10
    assert len([call for call in bridge.calls if call[0] == "plan"]) == 10
    assert all(record.status == "failed_mode_collapse" for record in output.all_records)
    assert all(record.failure_reason for record in output.all_records)
    assert all(record.gate_action == "continue" for record in output.all_records)
    assert all(
        record.memory.round_index == index for index, record in enumerate(output.all_records, 1)
    )
