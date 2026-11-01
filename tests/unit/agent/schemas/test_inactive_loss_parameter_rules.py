"""Issue #1039: conditional loss rules must disclose inactivity and refuse fixed dead rules."""

from pathlib import Path

import pytest
import yaml

from agent.schemas.hyperparam_tuning import ExperimentPlan
from agent.schemas.parameter_rules import (
    ParameterRuleError,
    ParameterRules,
    apply_parameter_rules,
    resolve_parameter_rule_document,
    validate_parameter_rule_ownership,
)
from ml_models.models_format_sandbox import LossConfig
from workflows.task_composition import TaskCompositionError, compose_run_task_bindings


@pytest.mark.parametrize(
    ("loss_type", "field", "value"),
    [
        ("focal", "beta", 2.0),
        ("focal_cw", "beta", 2.0),
        ("ce", "alpha", 0.3),
        ("ce", "gamma", 3.0),
        ("ce", "beta", 2.0),
        ("smooth_l1", "alpha", None),
        ("smooth_l1", "gamma", 3.0),
        ("smooth_l1", "use_class_weights", False),
        ("custom", "alpha", 0.3),
        ("custom", "gamma", 3.0),
        ("custom", "beta", 2.0),
    ],
)
@pytest.mark.parametrize("owner", ["task_rules", "workflow_rules"])
def test_inactive_exact_locks_are_disclosed(loss_type: str, field: str, value, owner: str, capsys):
    """Dynamic loss choice remains valid, with typed receipts and visible disclosure."""
    rules = ParameterRules.model_validate({f"loss_config.{field}": {"exact": value}})
    plan = ExperimentPlan(loss_config={"loss_type": loss_type})
    effective = apply_parameter_rules(plan, **{owner: rules})
    assert effective.loss_cfg == plan.loss_cfg
    (receipt,) = effective.inactive_parameter_rules
    assert receipt.path == f"loss_config.{field}"
    assert receipt.loss_type == loss_type
    assert receipt.owner == owner.removesuffix("_rules")
    assert receipt.rule.exact == value
    assert "inactive for this attempt" in capsys.readouterr().out


@pytest.mark.parametrize(
    "rule", [{"range": {"min": 1}}, {"allowed": [2]}, {"predicate": "even_integer"}]
)
def test_non_exact_rules_cannot_validate_an_ignored_authored_value(rule: dict):
    """Non-exact rules also used to accept values subsequently erased by the loss."""
    rules = ParameterRules.model_validate({"loss_config.beta": rule})
    effective = apply_parameter_rules(
        ExperimentPlan(loss_config={"loss_type": "focal"}), workflow_rules=rules
    )
    assert (
        effective.inactive_parameter_rules[0].rule.model_dump(mode="json", exclude_none=True)
        == rule
    )
    assert "beta" not in effective.loss_cfg


def test_effective_type_and_default_control_activity():
    """Check the post-lock type, and the consuming schema's omitted-type default."""
    beta = ParameterRules.model_validate({"loss_config.beta": {"exact": 2}})
    smooth = ParameterRules.model_validate({"loss_config.loss_type": {"exact": "smooth_l1"}})
    plan = ExperimentPlan(loss_config={"loss_type": "focal"})
    effective = apply_parameter_rules(plan, task_rules=beta, workflow_rules=smooth)
    assert LossConfig.model_validate(effective.loss_cfg).beta == 2
    assert plan.loss_cfg == {"loss_type": "focal"}
    default = apply_parameter_rules(ExperimentPlan(loss_config={}), workflow_rules=beta)
    assert default.inactive_parameter_rules[0].loss_type == "focal"
    # A baseline with no selected loss may defer until the tuner chooses it.
    assert resolve_parameter_rule_document(
        {"loss_config": {}}, workflow_rules=beta, defer_missing_non_exact=True
    )["loss_config"] == {"beta": 2}


@pytest.mark.parametrize("type_rule", [{"exact": "focal"}, {"allowed": ["focal"]}])
def test_fixed_type_refuses_inactive_rules_at_declaration(type_rule: dict):
    """Fixed combinations must fail before an agent proposes any values."""
    with pytest.raises(ValueError, match=r"loss_config\.beta.*inactive"):
        ParameterRules.model_validate(
            {"loss_config.loss_type": type_rule, "loss_config.beta": {"exact": 2}}
        )


def test_combined_ownership_check_refuses_cross_owner_inactivity():
    """Each owner alone is valid, but their combined fixed loss cannot use beta."""
    task = ParameterRules.model_validate({"loss_config.loss_type": {"exact": "ce"}})
    workflow = ParameterRules.model_validate({"loss_config.beta": {"exact": 2}})
    with pytest.raises(ParameterRuleError, match=r"loss_config\.beta.*inactive.*ce"):
        validate_parameter_rule_ownership(
            objective_declared=False, task_rules=task, workflow_rules=workflow
        )


def test_task_composition_refuses_fixed_inactive_rule(tmp_path: Path):
    """Exercise the manifest loader, not just the isolated declaration validator."""
    root = Path(__file__).resolve().parents[4]
    manifest = yaml.safe_load((root / "configs/task_composition/quickstart.yaml").read_text())
    manifest["parameter_rules"] = {
        "loss_config.loss_type": {"exact": "focal"},
        "loss_config.beta": {"exact": 2},
    }
    path = tmp_path / "composition.yaml"
    path.write_text(yaml.safe_dump(manifest))
    with pytest.raises(TaskCompositionError, match=r"loss_config\.beta.*inactive"):
        compose_run_task_bindings(str(path))


def test_resolver_rechecks_mutated_rules_and_effective_type():
    """A changed rule dictionary cannot bypass activity checks in either caller."""
    rules = ParameterRules.model_validate({"loss_config.beta": {"exact": 2}})
    type_rule = ParameterRules.model_validate({"loss_config.loss_type": {"exact": "focal"}})
    rules.rules.update(type_rule.rules)
    for defer in (False, True):
        with pytest.raises(ParameterRuleError, match=r"loss_config\.beta.*inactive.*focal"):
            resolve_parameter_rule_document(
                {"loss_config": {"loss_type": "smooth_l1"}},
                workflow_rules=rules,
                defer_missing_non_exact=defer,
            )


def test_receipts_reset_when_next_attempt_activates_field():
    """Re-resolution must not carry stale inactivity into another loss route."""
    rules = ParameterRules.model_validate({"loss_config.beta": {"exact": 2}})
    inactive = apply_parameter_rules(
        ExperimentPlan(loss_config={"loss_type": "focal"}), workflow_rules=rules
    )
    inactive.loss_cfg = {"loss_type": "smooth_l1"}
    active = apply_parameter_rules(inactive, workflow_rules=rules)
    assert active.loss_cfg["beta"] == 2
    assert not active.inactive_parameter_rules
    assert "inactive_parameter_rules" not in active.model_dump()


def test_proposal_guidance_explains_conditional_loss_rules():
    """A proposal must not infer that a beta rule forces smooth_l1 loss."""
    from nodes.ml_model_proposal_agent.parameter_rules import render_proposal_parameter_rules

    rules = ParameterRules.model_validate({"loss_config.beta": {"exact": 2}})
    text = render_proposal_parameter_rules(None, rules)
    assert "they do not restrict your loss choice" in text
    assert (
        "inactive"
        not in render_proposal_parameter_rules(
            None, ParameterRules.model_validate({"train_config.epochs": {"exact": 2}})
        ).lower()
    )
