"""Pseudo-integration coverage for collapsed-but-completed tuning rounds."""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from execute_tools.health_checks.schemas import (
    GateAction,
    GateResult,
    HealthCheckResult,
    PersistedHealthGateResult,
)
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from tests.helpers.recording_llm_bridge import RecordingLLMBridge
from tests.helpers.recording_sandbox import RecordingSandbox
from tests.helpers.tuner_composed_effects import composed_tuner_effects
from tests.helpers.tuner_composed_fixture import composed_run

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_json(path):
    with open(REPO_ROOT / path) as handle:
        return json.load(handle)


# One past max_fail_rounds=3 — the minimal count proving that collapsed-but-
# COMPLETED rounds never increment the consecutive-failure brake (if they
# did, the run would abort at round 3). Historically 10 ("ten collapses",
# the v15/v16 forensic narrative); reduced 2026-07-23 — rounds 5..10 added
# ~4 min of pure repetition per run with no additional coverage.
N_ROUNDS = 4


def test_ten_collapsed_rounds_are_recorded_and_do_not_terminate(tmp_path, monkeypatch):
    """Collapsed rounds beyond max_fail_rounds with CONTINUE stay completed
    experiments and never terminate the loop."""
    tuner_module = importlib.import_module("nodes.ml_hyperparameter_tune_agent.round_health")

    monkeypatch.setattr(
        importlib.import_module(
            "nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent"
        ).time,
        "sleep",
        lambda *_args, **_kwargs: None,
    )
    health_calls = []

    def failed_continue(_gate_id, ctx):
        check = HealthCheckResult(
            check_name="categorical_dominant_fraction",
            passed=False,
            reason="fixture emitted a constant class output",
            metrics={"dominant_fraction": 1.0},
        )
        return GateResult(
            gate_id="collapse",
            round_index=ctx.round_index,
            passed=False,
            action=GateAction.CONTINUE,
            check_results=[check],
            failure_reason=check.reason,
        )

    def failed_continue_adapter(ctx, **kwargs):
        health_calls.append(kwargs)
        assert kwargs["gate_ids"] == ["collapse"]
        from execute_tools.health_checks.config import load_health_gates_config

        gates = load_health_gates_config(kwargs["config_path"])
        assert len(gates.health_gates) == 1
        assert gates.health_gates[0].gate_role == "blocking"
        assert gates.health_gates[0].on_fail.action == GateAction.CONTINUE
        assert tuner_module.get_gates_for_position(
            ctx.round_index, config_path=kwargs["config_path"]
        ) == ["collapse"]
        result = failed_continue("collapse", ctx)
        persisted = PersistedHealthGateResult(
            gate_name="collapse",
            execution_status="failed",
            check_passed=False,
            would_invalidate_under_production_policy=True,
            resolved_action=GateAction.CONTINUE,
            failure_reason=result.failure_reason,
            metrics={"dominant_fraction": 1.0},
            gate_role="blocking",
            configured_action=GateAction.CONTINUE,
            healthgate_mode="observe_only",
            check_verdicts={"categorical_dominant_fraction": "failed"},
        )
        return [result], [persisted], GateAction.CONTINUE

    monkeypatch.setattr(
        tuner_module,
        "evaluate_and_persist_health_gates",
        failed_continue_adapter,
    )

    plan = _load_json(
        "tests/pseudo_data/api_call_outputs/ml_hyperparameter_tune_agent/generate.json"
    )
    plan.update({"is_trial": True, "train_portion": 0.1})
    plan["model_type"] = "quickstart_reference_mlp"
    plan["model_config"] = {
        "model_type": "quickstart_reference_mlp",
        "segmentation_size": 4,
        "batch_size": 1,
        "hidden_dim": 4,
    }
    plan["loss_config"] = {"loss_type": "ce", "reduction": "mean"}
    plan["train_config"].update({"epochs": 1, "device": "cpu"})
    plan.update(
        hypothesis="Exercise four completed invalid rounds",
        reasoning="Synthetic classification fixture",
    )
    reflection = _load_json(
        "tests/pseudo_data/api_call_outputs/ml_hyperparameter_tune_agent/reflect.json"
    )
    reflection = {key: "Supplied fixture feedback; no scientific inference." for key in reflection}
    training = _load_json("tests/pseudo_data/train_outputs/punet/execute_training.json")
    from execute_tools.training_history import objective_config_fingerprint
    from ml_models.loss_models_sandbox import LossConfig

    training["results"].update(final_loss=0.5, loss_history=[0.5], model_params=30)
    training["results"]["training_history"].update(
        objective_kind="ce",
        objective_config_fingerprint=objective_config_fingerprint(LossConfig(loss_type="ce")),
        epochs_planned=1,
        epochs_completed=1,
        train_objective=[0.5],
        validation_objective=[0.6],
        validation_seconds=[0.01],
    )
    inference = _load_json("tests/pseudo_data/train_outputs/punet/execute_inference.json")
    collapsed_score = {"file_vector": None, "denoising_score": float("-inf")}

    bridge = RecordingLLMBridge(
        responses={
            "generate": [copy.deepcopy(plan) for _ in range(N_ROUNDS)],
            "reflect": [copy.deepcopy(reflection) for _ in range(N_ROUNDS)],
        }
    )
    sandbox = RecordingSandbox(
        base_dir=str(tmp_path),
        run_name="ten_collapses",
        canned={
            "execute_training": [copy.deepcopy(training) for _ in range(N_ROUNDS)],
            "execute_inference": [copy.deepcopy(inference) for _ in range(N_ROUNDS)],
            "execute_scoring": [
                {"status": "success", "results": copy.deepcopy(collapsed_score)}
                for _ in range(N_ROUNDS)
            ],
        },
    )
    agent = HyperparamTuningAgent(
        bridge_factory=lambda **_kwargs: bridge,
        sandbox_factory=lambda **_kwargs: sandbox,
    )
    agent_input = HyperparamTuningInput(
        model_type="quickstart_reference_mlp",
        max_rounds=N_ROUNDS,
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
        trial_vram_budget_gb=None,
        healthgate_mode="observe_only",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="ten_collapses"),
        ),
        progress_bar=False,
    )

    with composed_tuner_effects(
        monkeypatch, sandbox=sandbox, bridge=bridge, expected_attempts=N_ROUNDS
    ):
        with composed_run(tmp_path, agent_input, health=True):
            output = agent.run(agent_input)

    assert output.completed_rounds == N_ROUNDS
    assert output.total_attempts == N_ROUNDS
    assert output.consecutive_fail_rounds_at_exit == 0
    assert output.termination_reason == "completed"
    assert len(output.all_records) == N_ROUNDS
    assert len(sandbox.saved_records) == N_ROUNDS
    assert len([call for call in bridge.calls if call[0] == "plan"]) == N_ROUNDS
    assert all(record.status == "failed_mode_collapse" for record in output.all_records)
    assert all(record.failure_reason for record in output.all_records)
    assert all(record.gate_action == "continue" for record in output.all_records)
    assert output.best_valid_exp_id is None
    assert len(health_calls) == N_ROUNDS
    assert output.health_config_sha256
    assert all(len(record.health_gate_results) == 1 for record in output.all_records)
    assert all(
        record.health_gate_results[0].gate_role == "blocking" for record in output.all_records
    )
    assert all(
        record.health_gate_results[0].configured_action == "continue"
        for record in output.all_records
    )
    persisted = sandbox.get_summary()
    assert len(persisted) == N_ROUNDS
    assert [row["exp_id"] for row in persisted] == [row.exp_id for row in output.all_records]
    assert all(row["status"] == "failed_mode_collapse" for row in persisted)
    assert all(
        record.memory.round_index == index for index, record in enumerate(output.all_records, 1)
    )
