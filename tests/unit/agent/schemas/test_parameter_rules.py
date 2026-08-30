"""Regression tests for the unified effective-plan parameter-rule contract."""

import pytest

from agent.schemas.hyperparam_tuning import (
    EpochCapResolution,
    ExperimentPlan,
    TaskCompositionRef,
)
from agent.schemas.parameter_rules import (
    ParameterRuleError,
    ParameterRules,
    apply_parameter_rules,
    register_parameter_predicate,
)
from ml_models.models_format_sandbox import LossConfig
from nodes.ml_hyperparameter_tune_agent.planning import _apply_effective_parameter_rules


def _plan(*, batch_size: int = 2, epochs: int = 3) -> ExperimentPlan:
    return ExperimentPlan.model_validate(
        {
            "model_type": "wavenet",
            "hypothesis": "test",
            "reasoning": "test",
            "model_config": {},
            "train_config": {"batch_size": batch_size, "epochs": epochs},
            "loss_config": {"loss_type": "smooth_l1"},
            "is_trial": True,
        }
    )


def _composition_ref(
    rules: ParameterRules,
    *,
    objective: LossConfig | None = None,
) -> TaskCompositionRef:
    return TaskCompositionRef(
        semantic_fingerprint="synthetic-parameter-rules",
        task_data_path_id="synthetic_parameter_rules",
        task_health_binding=None,
        objective=objective,
        parameter_rules=rules,
    )


def test_exact_inserts_an_omitted_leaf_and_other_rules_preserve_agent_choice() -> None:
    """Catches exact locks becoming validation-only or ranges becoming defaults."""
    plan = _plan()
    plan.train_cfg.pop("batch_size")
    rules = ParameterRules.model_validate(
        {
            "train_config.batch_size": {"exact": 1},
            "train_config.epochs": {"range": {"min": 1, "max": 5}},
            "model_config.width": {"allowed": [64, 128]},
        }
    )
    plan.model_cfg["width"] = 128

    effective = apply_parameter_rules(plan, workflow_rules=rules)

    assert effective.train_cfg["batch_size"] == 1
    assert effective.train_cfg["epochs"] == 3
    assert effective.model_cfg["width"] == 128


def test_task_rule_cannot_be_overwritten_by_a_conflicting_workflow_lock() -> None:
    """Catches workflow exact rules silently replacing task-owned constraints."""
    task = ParameterRules.model_validate({"train_config.batch_size": {"exact": 1}})
    workflow = ParameterRules.model_validate({"train_config.batch_size": {"exact": 2}})

    with pytest.raises(ParameterRuleError, match="exact rules conflict"):
        apply_parameter_rules(_plan(), task_rules=task, workflow_rules=workflow)


def test_workflow_can_narrow_a_task_range_but_cannot_escape_it() -> None:
    """Catches merge logic that treats one owner as a last-writer override."""
    task = ParameterRules.model_validate({"train_config.epochs": {"range": {"min": 1, "max": 10}}})
    accepted = ParameterRules.model_validate({"train_config.epochs": {"exact": 5}})
    refused = ParameterRules.model_validate({"train_config.epochs": {"exact": 20}})

    assert (
        apply_parameter_rules(_plan(), task_rules=task, workflow_rules=accepted).train_cfg["epochs"]
        == 5
    )
    with pytest.raises(ParameterRuleError, match="requires value <= 10"):
        apply_parameter_rules(_plan(), task_rules=task, workflow_rules=refused)


def test_registered_predicate_executes_and_an_unknown_name_refuses() -> None:
    """Catches predicate declarations being accepted without executable enforcement."""
    register_parameter_predicate("test_positive_odd", lambda value: value > 0 and value % 2 == 1)
    accepted = ParameterRules.model_validate(
        {"train_config.epochs": {"predicate": "test_positive_odd"}}
    )
    unknown = ParameterRules.model_validate(
        {"train_config.epochs": {"predicate": "not_registered"}}
    )

    assert apply_parameter_rules(_plan(), workflow_rules=accepted).train_cfg["epochs"] == 3
    with pytest.raises(ParameterRuleError, match="unregistered predicate"):
        apply_parameter_rules(_plan(), workflow_rules=unknown)


def test_one_rule_kind_is_required() -> None:
    """Catches ambiguous declarations whose precedence would otherwise be implicit."""
    with pytest.raises(ValueError, match="exactly one"):
        ParameterRules.model_validate({"train_config.batch_size": {"exact": 1, "allowed": [1, 2]}})


def test_planning_boundary_applies_the_composed_exact_lock() -> None:
    """Catches planning bypassing the validated composition-owned rule set."""
    rules = ParameterRules.model_validate({"train_config.batch_size": {"exact": 1}})

    effective = _apply_effective_parameter_rules(
        _plan(batch_size=8),
        composition_ref=_composition_ref(rules),
        epoch_cap=EpochCapResolution(cap=None, source=None),
    )

    assert effective.train_cfg["batch_size"] == 1


def test_planning_boundary_preserves_objective_and_epoch_authorities() -> None:
    """Catches parameter rules bypassing either independent planning authority."""
    loss_rules = ParameterRules.model_validate({"loss_config.loss_type": {"exact": "smooth_l1"}})
    with pytest.raises(ParameterRuleError, match="sole owner of loss semantics"):
        _apply_effective_parameter_rules(
            _plan(),
            composition_ref=_composition_ref(
                loss_rules,
                objective=LossConfig(loss_type="ce"),
            ),
            epoch_cap=EpochCapResolution(cap=None, source=None),
        )

    epoch_rules = ParameterRules.model_validate({"train_config.epochs": {"exact": 5}})
    with pytest.raises(ParameterRuleError, match="above the active max_epochs ceiling 2"):
        _apply_effective_parameter_rules(
            _plan(epochs=1),
            composition_ref=_composition_ref(epoch_rules),
            epoch_cap=EpochCapResolution(cap=2, source="max_epochs"),
        )
