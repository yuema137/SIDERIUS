"""Issue 1205: one resolved batch must reach probes, training and provenance."""

import sys
import time
from dataclasses import replace
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import torch
from torch.utils.data import DataLoader, TensorDataset

from agent.schemas.parameter_rules import ParameterRuleError, ParameterRules
from core.runtime_control.gpu_measurement_identity import build_planned_identity
from core.training_seeds import TrainingSeedPlan
from execute_tools.task_data_path import bind_task_data_path
from execute_tools.task_probe_batch import _first_training_batch
from execute_tools.train_engine_sandbox import refuse_zero_optimizer_steps
from nodes.ml_hyperparameter_tune_agent.contracts import (
    AttemptIdentity,
    AttemptOrdering,
    AttemptStage,
    RunBindings,
)
from nodes.ml_hyperparameter_tune_agent.planning import prepare_attempt
from nodes.ml_hyperparameter_tune_agent.training_batch_plan import TrainingBatchPlanError
from tests.unit.nodes.ml_hyperparameter_tune_agent.test_c12p_b11_composed_seg_size_authoring import (
    _bindings,
    _Brain,
    _composed_input,
    _ScopeRecorder,
)


class _Rows(_ScopeRecorder):
    def __init__(self, rows):
        super().__init__()
        self.rows = rows
        self.sampling = None
        self.constructions = 0
        self.bindings: RunBindings | None = None

    def training_dataset(self, scope, params):
        self.constructions += 1
        assert scope == {"leg": "training"}
        self.sampling = params
        count = min(self.rows, params.max_samples or self.rows)
        # Large-scope controls count without allocating paper-sized tensors.
        if count > 1000:
            return range(count)
        return TensorDataset(torch.ones(count, 2), torch.zeros(count, 1))


class _Plan(_Brain):
    def __init__(self, drop_last=True, batch_size=32):
        self.drop_last = drop_last
        self.batch_size = batch_size

    def plan(self, *args, **kwargs):
        result = super().plan(*args, **kwargs)
        result["train_cfg"] = {
            "batch_size": self.batch_size,
            "epochs": 1,
            "drop_last": self.drop_last,
        }
        return result


def _prepare(
    tmp_path,
    rows,
    *,
    rules=None,
    drop_last=True,
    max_samples=None,
    workflow_rules=None,
    overrides=None,
    trial=False,
    winner=None,
    authored_batch=32,
):
    inputs = _composed_input()
    inputs.is_trial = trial
    assert inputs.task_composition_ref is not None
    inputs.task_composition_ref = inputs.task_composition_ref.model_copy(
        update={"parameter_rules": rules}
    )
    inputs.validation_max_train_samples = max_samples
    inputs.workflow_parameter_rules = workflow_rules
    inputs.plan_overrides = overrides or {}
    source = _Rows(rows)
    bindings = replace(
        _bindings(inputs, tmp_path, source),
        brain=_Plan(drop_last, authored_batch),
        max_rounds=2 if trial else 1,
    )
    source.bindings = bindings
    with bind_task_data_path(source):
        prepared = prepare_attempt(
            bindings,
            attempt_ordering=AttemptOrdering(),
            identity=AttemptIdentity(round_index=1, attempt_in_round=1, is_formal_round=not trial),
            total_attempts=1,
            attempts_this_round=1,
            formal_trial_winner=winner,
        )
    return prepared, source


def _identity(prepared, config):
    return build_planned_identity(
        model_type=prepared.model_type,
        model_config=prepared.model_config,
        train_config=config,
    ).model_dump_json()


@pytest.mark.parametrize("trial", [False, True])
def test_scope_fit_reaches_real_probe_training_and_identity(tmp_path, capsys, monkeypatch, trial):
    """Removing the planning call leaves batch 32 and fails the first assertion.

    The same witness includes locked/empty refusal and large-scope controls;
    passing only those controls cannot hide a disconnected production fix.
    """
    prepared, source = _prepare(tmp_path, 12, trial=trial)
    assert prepared.plan.train_cfg["batch_size"] == 12
    assert prepared.plan.is_trial == trial
    assert prepared.active_params["train_config"] == prepared.record_params["train_config"]
    assert prepared.active_params["train_config"] == prepared.plan.train_cfg
    assert prepared.record_params["training_batch_fit"] == {
        "role": "trial" if trial else "formal",
        "requested_batch_size": 32,
        "resolved_batch_size": 12,
        "available_samples": 12,
    }
    assert source.sampling is not None
    assert (
        source.sampling.epoch_seed
        == TrainingSeedPlan(prepared.trial_config.seed_context).epoch(0).subsample
    )
    assert source.sampling.train_portion == prepared.trial_config.train_portion
    dataset = source.training_dataset(prepared.task_scopes.training, source.sampling)
    probe = _first_training_batch(dataset, prepared.plan.train_cfg["batch_size"], drop_last=True)
    assert probe[0].shape == (12, 2)
    model = torch.nn.Linear(2, 1)
    torch.nn.init.constant_(model.weight, 0.5)
    torch.nn.init.zeros_(model.bias)
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    steps = 0
    before = model.weight.detach().clone()
    for inputs, targets in DataLoader(
        dataset, batch_size=prepared.active_params["train_config"]["batch_size"], drop_last=True
    ):
        optimizer.zero_grad()
        torch.nn.functional.mse_loss(model(inputs), targets).backward()
        optimizer.step()
        steps += 1
    refuse_zero_optimizer_steps(steps, epoch=0, batch_size=12, rows=12)
    assert steps == 1 and not torch.equal(before, model.weight)
    assert _identity(prepared, prepared.plan.train_cfg) == _identity(
        prepared, prepared.active_params["train_config"]
    )
    event = next(
        e for e in prepared.execution_provenance.events if e.field_path == "train_cfg.batch_size"
    )
    assert (event.proposed, event.executed, event.authority) == (
        "32",
        "12",
        "training_scope_batch_fit",
    )
    assert capsys.readouterr().out.count("[training_batch]") == 1

    locked = ParameterRules.model_validate({"train_config.batch_size": {"exact": 32}})
    with pytest.raises(TrainingBatchPlanError, match="task parameter_rules exact lock"):
        _prepare(tmp_path, 12, rules=locked)
    with pytest.raises(TrainingBatchPlanError, match="workflow parameter_rules exact lock"):
        _prepare(tmp_path, 12, workflow_rules=locked)
    with pytest.raises(TrainingBatchPlanError, match="operator plan_overrides lock"):
        _prepare(tmp_path, 12, overrides={"train_config": {"batch_size": 32}})
    with pytest.raises(TrainingBatchPlanError, match="no training samples"):
        _prepare(tmp_path, 0)

    # TIDMAD-sized scopes retain both plan bytes and measurement identity.
    large, _ = _prepare(tmp_path, 2_010_000_000)
    with monkeypatch.context() as baseline:
        baseline.setattr(
            sys.modules[prepare_attempt.__module__],
            "resolve_training_batch_plan",
            lambda plan, **kwargs: (plan, None),
        )
        fitting, _ = _prepare(tmp_path, 2_010_000_000)
    assert large.plan.model_dump_json() == fitting.plan.model_dump_json()
    assert large.record_params == fitting.record_params
    assert _identity(large, large.active_params["train_config"]) == _identity(
        fitting, fitting.active_params["train_config"]
    )
    assert not any(
        e.field_path == "train_cfg.batch_size" for e in large.execution_provenance.events
    )
    assert "[training_batch]" not in capsys.readouterr().out
    assert "training_batch_fit" not in large.execution_provenance.model_dump()


def test_sampling_ceiling_and_tail_policy_keep_constraints(tmp_path):
    """A raw large scope can still need a clamp after task-owned row selection."""
    capped, _ = _prepare(tmp_path, 100, max_samples=12)
    assert capped.plan.train_cfg["batch_size"] == 12
    retained, _ = _prepare(tmp_path, 12, drop_last=False)
    assert retained.plan.train_cfg["batch_size"] == 32
    constrained = ParameterRules.model_validate(
        {"train_config.batch_size": {"range": {"min": 16, "max": 64}}}
    )
    with pytest.raises(ParameterRuleError):
        _prepare(tmp_path, 12, rules=constrained)
    winner = {
        "exp_id": "winning_trial",
        "denoising_score": 1.0,
        "params": {
            "model_config": _Brain().plan([])["model_cfg"],
            "train_config": {"batch_size": 64, "epochs": 1, "lr": 0.001},
            "loss_config": {"loss_type": "ce"},
        },
    }
    inherited, _ = _prepare(tmp_path, 12, winner=winner)
    event = next(
        e for e in inherited.execution_provenance.events if e.field_path == "train_cfg.batch_size"
    )
    assert (event.proposed, event.executed, event.authority) == (
        "32",
        "12",
        "training_scope_batch_fit",
    )
    restored, _ = _prepare(tmp_path, 12, winner=winner, authored_batch=12)
    assert not any(
        e.field_path == "train_cfg.batch_size" for e in restored.execution_provenance.events
    )
    receipt = restored.execution_provenance.training_batch_fit
    assert receipt is not None
    assert (
        receipt.requested_batch_size,
        receipt.resolved_batch_size,
        receipt.available_samples,
    ) == (64, 12, 12)
    assert restored.execution_provenance.model_dump()["training_batch_fit"]["role"] == "formal"
    assert restored.record_params["training_batch_fit"] == receipt.model_dump()
    trial, _ = _prepare(tmp_path, 12, trial=True)
    inherited_trial, _ = _prepare(
        tmp_path,
        100,
        winner={
            "exp_id": "clamped_trial",
            "denoising_score": 1.0,
            "params": {
                **trial.record_params,
                "train_config": {**trial.plan.train_cfg, "lr": 0.001},
            },
        },
    )
    assert inherited_trial.plan.train_cfg["batch_size"] == 12
    assert inherited_trial.execution_provenance.training_batch_fit is None


@pytest.mark.parametrize("rows", [12, 2_010_000_000])
def test_preflight_reuses_count_and_both_probe_routes_use_owner_sampling(
    tmp_path, monkeypatch, rows
):
    """Dropping the cached-row handoff constructs twice; wrong sampling changes the spec."""
    prepared, source = _prepare(tmp_path, rows)
    bindings = source.bindings
    assert bindings is not None
    assert prepared.resolved_training_rows == rows
    counted_sampling = source.sampling
    assert source.constructions == 1
    execution = import_module("nodes.ml_hyperparameter_tune_agent.execution")
    gpu = import_module("nodes.ml_hyperparameter_tune_agent.gpu_execution")
    probe = import_module("nodes.ml_hyperparameter_tune_agent.probe_data")
    monkeypatch.setattr(probe, "active_task_manifest_path", lambda: str(tmp_path / "task.yaml"))
    monkeypatch.setattr(
        probe,
        "resolve_task_scope_capability",
        lambda _: SimpleNamespace(serialize_scope=lambda scope: str(scope)),
    )
    reference = bindings.agent_input.task_composition_ref
    bindings.agent_input.task_composition_ref = reference.model_copy(
        update={"segmentation_applicability": "temporal"}
    )
    bindings.sandbox.plugin_dir = None
    bindings.sandbox.loss_dir = None
    bindings.sandbox.device_identity = SimpleNamespace(uuid="GPU-test")

    class ProbeReached(Exception):
        pass

    captured = []

    def capture(**kwargs):
        captured.append(kwargs["task_probe_data"])
        raise ProbeReached

    monkeypatch.setattr(execution, "run_production_preflight", capture)
    with bind_task_data_path(source), pytest.raises(ProbeReached):
        execution.run_admission_preflight(
            bindings,
            prepared,
            AttemptIdentity(round_index=1, attempt_in_round=1, is_formal_round=True),
            AttemptStage("guardrails"),
            formal_trial_winner=None,
            physical_rejections_buffer=[],
        )
    assert source.constructions == 1
    assert captured[0].sampling == counted_sampling

    # Stop at construction of the real GPU request, before any worker launch.
    monkeypatch.setattr(gpu, "GpuMeasurementSpec", capture)
    state = Mock()
    state.policy.worker_rss_limit_bytes = 1024**3
    with bind_task_data_path(source), pytest.raises(ProbeReached):
        gpu._spec(bindings, prepared, "training", state, time.monotonic() + 60, tmp_path)
    assert captured[1].sampling == counted_sampling
    assert source.constructions == 1
