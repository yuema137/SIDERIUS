"""Opt-in planner ownership of formal training never changes evaluation ownership."""

from __future__ import annotations

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from core.run_invariants import (
    RunInvariants,
    RunInvariantsViolation,
    ensure_run_invariants,
    validate_run_invariants,
)
from nodes.ml_hyperparameter_tune_agent.policy import (
    _disclose_inapplicable_trial_overrides,
    _resolve_sample_set_cfg,
)
from tests.helpers.experiment_plans import make_scope_plan


def test_legacy_formal_training_scope_stays_operator_owned(tmp_path):
    inp = _input(tmp_path, formal_portion=0.3, formal_train_portion=0.8)
    plan = make_scope_plan(
        trial_strategy="anchors", trial_portion=0.6, train_portion=0.7, eval_portion=0.2
    )
    cfg = _resolve_sample_set_cfg("formal", inp, plan)
    assert (cfg["trial_portion"], cfg["train_portion"], cfg["eval_portion"]) == (
        0.3,
        0.8,
        1.0,
    )


def test_agent_chooses_training_for_both_roles_but_not_formal_evaluation(tmp_path):
    inp = _input(
        tmp_path,
        formal_training_scope_source="agent",
        formal_portion=0.1,
        formal_train_portion=1.0,
        formal_eval_portion=1.0,
    )
    plan = make_scope_plan(trial_portion=0.6, train_portion=0.7, eval_portion=0.2)
    trial = _resolve_sample_set_cfg("trial", inp, plan)
    formal = _resolve_sample_set_cfg("formal", inp, plan)
    assert (trial["trial_portion"], trial["train_portion"], trial["eval_portion"]) == (
        0.6,
        0.7,
        0.2,
    )
    assert (
        formal["trial_strategy"],
        formal["trial_portion"],
        formal["train_portion"],
    ) == ("anchors", 0.6, 0.7)
    assert (formal["eval_strategy"], formal["eval_portion"]) == ("snapshot", 1.0)


def test_agent_mode_does_not_claim_used_training_overrides_were_discarded(tmp_path):
    inp = _input(
        tmp_path,
        max_rounds=2,
        formal_training_scope_source="agent",
        plan_overrides={"trial_portion": 0.4, "eval_portion": 0.3},
    )
    note = _disclose_inapplicable_trial_overrides("formal", inp)
    assert note is not None
    assert "eval_portion" in note
    assert "'trial_portion'" not in note


def test_resume_refuses_training_scope_source_change(tmp_path):
    common = dict(
        resolved_data_scope=[0, 1],
        health_gate_enabled=False,
        health_config_sha256=None,
        runtime_estimator_identity="est-1",
        runtime_policy_identity="pol-1",
    )
    workspace = str(tmp_path / "locked")
    assert ensure_run_invariants(
        workspace, RunInvariants(**common, formal_training_scope_source="agent")
    ) == "created"
    with pytest.raises(RunInvariantsViolation, match="formal_training_scope_source"):
        validate_run_invariants(
            workspace, RunInvariants(**common, formal_training_scope_source="operator")
        )


def _input(tmp_path, **kwargs):
    from agent.schemas.storage import LocalStorageConfig, StorageConfig

    return HyperparamTuningInput(
        model_type="punet",
        file_index=0,
        llm_provider="openai",
        llm_model_id="test-model",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="scope_test"),
        ),
        **kwargs,
    )
