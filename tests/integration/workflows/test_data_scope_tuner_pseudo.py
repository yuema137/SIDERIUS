"""Pseudo-integration coverage for DataScope tuner wiring (DS5b).

Covers, on the RecordingLLMBridge + RecordingSandbox pseudo stack:
  * partial-scope LLM-plan normalization with persisted provenance
    (planned_* vs effective strategies + reason) and run-invariant stamps;
  * materialized effective HealthGate config in the workspace + run_config
    stamps;
  * disabled-mode runs: no gate evaluation, empty gate results, records
    self-describe (health_gate_enabled=False) and classify VALID
    (best_valid_* populated);
  * scope_violation results terminate the run on FIRST occurrence
    (status="failed", termination_reason="scope_violation" — no retries,
    no max_fail_rounds wait).

Sample-set scoping itself is guaranteed by the constructive layer
(test_sample_set_builder) and the sandbox boundary (test_sandbox_scope);
this file asserts the tuner-level glue. See
docs/design/enable_partial_file_list.md (Commit DS5b).
"""

from __future__ import annotations

import copy
import importlib
import json
import os
from pathlib import Path

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from execute_tools.dataset_config import DataScope
from execute_tools.health_checks.config import EFFECTIVE_CONFIG_BASENAME
from execute_tools.health_checks.schemas import (
    GateAction,
    GateResult,
    HealthCheckResult,
    PersistedHealthGateResult,
)
from execute_tools.task_data_path import (
    EvaluationReadRequest,
    ScopeBuildRequest,
    TaskHealthCoverageError,
)
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from nodes.ml_hyperparameter_tune_agent.health_coverage import validate_attempt_health_coverage
from tests.fixtures.tuner_composed_task import TunerComposedTask
from tests.helpers.recording_llm_bridge import RecordingLLMBridge
from tests.helpers.recording_sandbox import RecordingSandbox
from tests.helpers.tuner_composed_effects import composed_tuner_effects
from tests.helpers.tuner_composed_fixture import composed_run


@pytest.mark.parametrize("round_kind", ["trial", "formal"])
def test_fixture_coverage_uses_actual_rows_after_scope_transport(round_kind):
    """A partition label cannot cover a monitored partition whose rows are absent."""
    task = TunerComposedTask()
    scope = task.build_eval_scope(
        ScopeBuildRequest(
            round_kind=round_kind,
            portion=0.125,
            selection_strategy="target",
            target_partitions=(4, 7, 9),
        )
    )
    scope = task.deserialize_scope(task.serialize_scope(scope))

    def check(value):
        return validate_attempt_health_coverage(
            data_path=task,
            evaluation_scope=value,
            round_kind=round_kind,
            health_binding="fixture_health.yaml",
            health_gate_files=(4, 7, 9),
            composed=True,
            health_enabled=True,
        )

    assert check(scope).covered is True
    scope["rows"] = [row for row in scope["rows"] if row[1] != 7]
    with pytest.raises(TaskHealthCoverageError, match="partitions must exactly describe"):
        check(scope)
    scope["partitions"] = [4, 9]
    with pytest.raises(TaskHealthCoverageError, match="omit monitored partitions \\[7\\]"):
        check(scope)


def test_fixture_coverage_refuses_training_rows_disguised_as_eval():
    """Changing the scope label must not let train identities satisfy Health coverage."""
    task = TunerComposedTask()
    scope = task.build_training_scope(
        ScopeBuildRequest(round_kind="trial", portion=0.125, selection_strategy="snapshot")
    )
    scope["leg"] = "eval"
    with pytest.raises(TaskHealthCoverageError, match="malformed Health coverage"):
        validate_attempt_health_coverage(
            data_path=task,
            evaluation_scope=scope,
            round_kind="trial",
            health_binding="fixture_health.yaml",
            composed=True,
            health_enabled=True,
        )


def test_fixture_empty_inventory_does_not_hide_prediction_files(tmp_path):
    """Record files are not predictions; real fixture predictions cannot be ignored."""
    task = TunerComposedTask()
    request = EvaluationReadRequest(
        deliverable_dir=str(tmp_path), exp_id="001", run_name="fixture", model_type="model"
    )
    (tmp_path / "records").mkdir()
    (tmp_path / "records" / "summary.json").write_text("{}")
    assert task.enumerate_output_artifacts(request).relative_paths == ()
    prediction = tmp_path / "tuner_fixture_predictions_model_fixture_001_0004.json"
    prediction.write_text("{}")
    with pytest.raises(ValueError, match="must not contain inference outputs"):
        task.enumerate_output_artifacts(request)
    assert prediction.exists()


TUNER_MODULE = "nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent"
PSEUDO = "tests/pseudo_data"
REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_json(path):
    with open(REPO_ROOT / path) as handle:
        return json.load(handle)


def _canned(n: int, score=None):
    training = _load_json(f"{PSEUDO}/train_outputs/punet/execute_training.json")
    inference = _load_json(f"{PSEUDO}/train_outputs/punet/execute_inference.json")
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
    score = {"file_vector": None, "denoising_score": 0.75} if score is None else score
    return {
        "execute_training": [copy.deepcopy(training) for _ in range(n)],
        "execute_inference": [copy.deepcopy(inference) for _ in range(n)],
        "execute_scoring": [
            {"status": "success", "results": copy.deepcopy(score)} for _ in range(n)
        ],
    }


def _bridge(n: int, plan_overlay: dict | None = None) -> RecordingLLMBridge:
    plan = _load_json(f"{PSEUDO}/api_call_outputs/ml_hyperparameter_tune_agent/generate.json")
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
        hypothesis="Exercise declared scope transport", reasoning="Synthetic classification fixture"
    )
    if plan_overlay:
        plan.update(plan_overlay)
    reflection = _load_json(f"{PSEUDO}/api_call_outputs/ml_hyperparameter_tune_agent/reflect.json")
    reflection = {key: "Supplied fixture feedback; no scientific inference." for key in reflection}
    return RecordingLLMBridge(
        responses={
            "generate": [copy.deepcopy(plan) for _ in range(n)],
            "reflect": [copy.deepcopy(reflection) for _ in range(n)],
        }
    )


def _agent(bridge, sandbox) -> HyperparamTuningAgent:
    return HyperparamTuningAgent(
        bridge_factory=lambda **_kwargs: bridge,
        sandbox_factory=lambda **_kwargs: sandbox,
    )


def _input(tmp_path, run_name: str, rounds: int, **overrides) -> HyperparamTuningInput:
    base = dict(
        model_type="quickstart_reference_mlp",
        max_rounds=rounds,
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
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name=run_name),
        ),
        progress_bar=False,
    )
    base.update(overrides)
    return HyperparamTuningInput(**base)


@pytest.fixture
def _fast(monkeypatch):
    tuner = importlib.import_module(TUNER_MODULE)
    monkeypatch.setattr(tuner.time, "sleep", lambda *_a, **_k: None)
    return tuner


@pytest.fixture
def _gates_pass(monkeypatch, _fast):
    """Neutral pass-through gate adapter (real peeks would I/O-fail on the
    pseudo stack); asserts gate machinery is reachable via call count."""
    calls = {"n": 0}

    def _adapter(ctx, **_kwargs):
        assert _kwargs["gate_ids"] == ["collapse"]
        calls["n"] += 1
        check = HealthCheckResult(
            check_name="categorical_dominant_fraction", passed=True, reason="fixture passed"
        )
        result = GateResult(
            gate_id="collapse",
            round_index=ctx.round_index,
            passed=True,
            action=GateAction.CONTINUE,
            check_results=[check],
        )
        persisted = PersistedHealthGateResult(
            gate_name=result.gate_id,
            execution_status="passed",
            check_passed=True,
            would_invalidate_under_production_policy=False,
            resolved_action=GateAction.CONTINUE,
            gate_role="blocking",
            configured_action=GateAction.INVALIDATE_ROUND,
            healthgate_mode="blocking",
            check_verdicts={"categorical_dominant_fraction": "passed"},
        )
        return [result], [persisted], GateAction.CONTINUE

    monkeypatch.setattr(
        importlib.import_module("nodes.ml_hyperparameter_tune_agent.round_health"),
        "evaluate_and_persist_health_gates",
        _adapter,
    )
    return calls


class TestPartialScopeNormalizationAndStamps:
    def test_llm_target_plan_normalized_with_provenance(self, tmp_path, monkeypatch, _gates_pass):
        bridge = _bridge(
            2,
            plan_overlay={
                "trial_strategy": "target",
                "target_files": [3, 11],
                "eval_strategy": "anchors",
            },
        )
        sandbox = RecordingSandbox(base_dir=str(tmp_path), run_name="scoped", canned=_canned(2))
        inp = _input(
            tmp_path,
            "scoped",
            rounds=2,
            data_scope=DataScope(file_indices=[4, 5, 6, 7, 8, 9]),
            health_gate_files=[4, 7, 9],
        )
        with composed_tuner_effects(
            monkeypatch, sandbox=sandbox, bridge=bridge, expected_attempts=2
        ):
            with composed_run(tmp_path, inp, health=True):
                output = _agent(bridge, sandbox).run(inp)

        assert output.status == "completed"
        assert output.resolved_data_scope == [4, 5, 6, 7, 8, 9]
        assert output.health_gate_enabled is True
        assert output.health_config_sha256
        for record in output.all_records:
            assert record.trial_strategy == "snapshot"
            assert record.eval_strategy == "snapshot"
            assert record.planned_trial_strategy == "target"
            assert record.planned_eval_strategy == "anchors"
            assert record.strategy_normalization_reason == "partial_data_scope"
            assert record.resolved_data_scope == [4, 5, 6, 7, 8, 9]
            assert record.health_gate_enabled is True
        assert _gates_pass["n"] == 2  # gate machinery reachable each round
        assert len(sandbox.training_kwargs) == 2
        for call in sandbox.training_kwargs:
            scopes = call["execution_bindings"].task_scopes
            assert scopes.acquired
            assert scopes.training["partitions"] == [4, 5, 6, 7, 8, 9]
            assert scopes.evaluation["partitions"] == [4, 5, 6, 7, 8, 9]
            assert scopes.training["leg"] == "train"
            assert scopes.evaluation["leg"] == "eval"

        # Materialized effective config + run_config stamps on disk.
        effective = os.path.join(str(tmp_path), EFFECTIVE_CONFIG_BASENAME)
        assert os.path.exists(effective)
        assert output.health_checks_config == effective
        run_config = _load_json(os.path.join(str(tmp_path), "run_config_scoped.json"))
        assert run_config["resolved_data_scope"] == [4, 5, 6, 7, 8, 9]
        assert run_config["health_gate_enabled"] is True
        assert run_config["health_checks_config_effective"] == effective
        assert run_config["health_config_sha256"] == output.health_config_sha256

    def test_snapshot_plan_under_partial_scope_no_normalization(
        self, tmp_path, monkeypatch, _gates_pass
    ):
        bridge = _bridge(1)  # pseudo plan defaults to snapshot
        sandbox = RecordingSandbox(base_dir=str(tmp_path), run_name="clean", canned=_canned(1))
        inp = _input(
            tmp_path,
            "clean",
            rounds=1,
            data_scope=DataScope(file_indices=[4, 5, 6, 7, 8, 9]),
            health_gate_files=[4, 7, 9],
        )
        with composed_tuner_effects(
            monkeypatch, sandbox=sandbox, bridge=bridge, expected_attempts=1
        ):
            with composed_run(tmp_path, inp, health=True):
                output = _agent(bridge, sandbox).run(inp)
        record = output.all_records[0]
        assert output.status == "completed"
        assert output.completed_rounds == 1
        assert record.status == "success"
        assert record.strategy_normalization_reason is None
        assert record.planned_trial_strategy == "snapshot"

    def test_full_scope_default_behavior(self, tmp_path, monkeypatch, _gates_pass):
        """Default scope: full stamps, no normalization, effective config
        materialized from this fixture's explicit declaration."""
        bridge = _bridge(1)
        sandbox = RecordingSandbox(base_dir=str(tmp_path), run_name="full", canned=_canned(1))
        inp = _input(tmp_path, "full", rounds=1)
        with composed_tuner_effects(
            monkeypatch, sandbox=sandbox, bridge=bridge, expected_attempts=1
        ):
            with composed_run(tmp_path, inp, health=True):
                output = _agent(bridge, sandbox).run(inp)
        assert output.resolved_data_scope == list(range(20))
        assert output.status == "completed"
        assert output.completed_rounds == 1
        assert output.all_records[0].status == "success"
        assert output.all_records[0].strategy_normalization_reason is None
        assert os.path.exists(os.path.join(str(tmp_path), EFFECTIVE_CONFIG_BASENAME))


class TestDisabledMode:
    def test_no_gate_evaluation_and_valid_candidates(self, tmp_path, monkeypatch, _fast):
        def _boom(*_a, **_k):  # pragma: no cover — the assert is that it never runs
            raise AssertionError("evaluate_and_persist_health_gates called while disabled")

        monkeypatch.setattr(
            importlib.import_module("nodes.ml_hyperparameter_tune_agent.round_health"),
            "evaluate_and_persist_health_gates",
            _boom,
        )

        bridge = _bridge(2)
        sandbox = RecordingSandbox(base_dir=str(tmp_path), run_name="nogates", canned=_canned(2))
        inp = _input(tmp_path, "nogates", rounds=2, health_gate_enabled=False)
        with composed_tuner_effects(
            monkeypatch, sandbox=sandbox, bridge=bridge, expected_attempts=2
        ):
            with composed_run(tmp_path, inp, health=False):
                output = _agent(bridge, sandbox).run(inp)

        assert output.status == "completed"
        assert output.health_gate_enabled is False
        assert output.health_config_sha256 is None
        assert not os.path.exists(os.path.join(str(tmp_path), EFFECTIVE_CONFIG_BASENAME))
        for record in output.all_records:
            assert record.health_gate_enabled is False
            assert record.health_gate_results == []
            assert record.gate_action is None
            assert record.status == "success"
        # Option B: disabled-mode success records are VALID candidates.
        assert output.best_valid_exp_id is not None
        assert len(output.all_records) == 2
        assert output.best_valid_denoising_score == 0.75
        assert output.best_valid_denoising_score == output.best_denoising_score


class TestScopeViolationAbort:
    def test_training_scope_violation_terminates_run(self, tmp_path, monkeypatch, _gates_pass):
        violation = {
            "status": "error",
            "error_type": "scope_violation",
            "message": "error_scope_violation: SampleSet file_index 2 is outside the DataScope",
        }
        canned = _canned(3)
        canned["execute_training"] = [violation] * 3
        bridge = _bridge(3)
        sandbox = RecordingSandbox(base_dir=str(tmp_path), run_name="abort", canned=canned)
        # attempts_per_round=3 would normally retry twice more.
        inp = _input(tmp_path, "abort", rounds=3, attempts_per_round=3)
        with composed_tuner_effects(
            monkeypatch, sandbox=sandbox, bridge=bridge, expected_attempts=1
        ):
            with composed_run(tmp_path, inp, health=True):
                output = _agent(bridge, sandbox).run(inp)

        assert output.status == "failed"
        assert output.termination_reason == "scope_violation"
        assert output.completed_rounds == 0
        # Non-retryable: exactly one planning attempt, one training call.
        assert len([c for c in bridge.calls if c[0] == "plan"]) == 1
        assert len([c for c in sandbox.calls if c[0] == "execute_training"]) == 1
        assert not any(c[0] in {"execute_inference", "execute_scoring"} for c in sandbox.calls)
        assert _gates_pass["n"] == 0
