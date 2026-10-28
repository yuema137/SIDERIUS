"""Issue #845: loss locks must name fields that ``LossConfig`` consumes."""

from pathlib import Path

import pytest
import yaml

from agent.schemas.hyperparam_tuning import ExperimentPlan
from agent.schemas.parameter_rules import (
    ParameterRule,
    ParameterRuleError,
    ParameterRules,
    apply_parameter_rules,
    resolve_parameter_rule_document,
)
from ml_models.models_format_sandbox import LossConfig
from workflows.task_composition import TaskCompositionError, compose_run_task_bindings


@pytest.mark.parametrize(
    "path",
    [
        "loss_config.gammmma",
        "loss_config.gamma.typo",
        # Custom-loss plugin hyperparameters are not transported per attempt.
        "loss_config.snr_threshold",
    ],
)
def test_loss_rules_refuse_paths_outside_consuming_schema(path: str) -> None:
    """Without traversal, LossConfig drops the typo key and the lock has no effect."""
    with pytest.raises(ValueError, match=rf"{path}.*LossConfig"):
        ParameterRules.model_validate({path: {"exact": 3}})


@pytest.mark.parametrize("owner", ["task_rules", "workflow_rules"])
def test_shared_resolver_rechecks_mutated_loss_rule_paths(owner: str) -> None:
    """Without the resolver guard, a mutated rule dictionary bypasses declaration checks."""
    rules = ParameterRules()
    rules.rules["loss_config.gammmma"] = ParameterRule(exact=3)
    with pytest.raises(ParameterRuleError, match=r"loss_config\.gammmma"):
        resolve_parameter_rule_document({"loss_config": {"gamma": 2.0}}, **{owner: rules})
    plan = ExperimentPlan(train_config={"epochs": 1}, loss_config={"gamma": 2.0})
    with pytest.raises(ParameterRuleError, match=r"loss_config\.gammmma"):
        apply_parameter_rules(plan, **{owner: rules})


@pytest.mark.parametrize(
    ("authored", "locks", "consumed"),
    [
        (
            {"loss_type": "focal", "gamma": 2.0},
            {"gamma": 3.0, "reduction": "sum", "use_class_weights": True},
            {"gamma": 3.0, "reduction": "sum", "use_class_weights": True},
        ),
        (
            {"loss_type": "focal"},
            {"loss_type": "custom", "loss_name": "snr_weighted_mse"},
            {"loss_type": "custom", "loss_name": "snr_weighted_mse"},
        ),
    ],
)
def test_built_in_and_custom_routing_locks_reach_the_consumed_loss(
    authored: dict, locks: dict, consumed: dict
) -> None:
    """A copied or partial field list would refuse valid built-in or custom-routing locks."""
    rules = ParameterRules.model_validate(
        {f"loss_config.{field}": {"exact": value} for field, value in locks.items()}
    )
    plan = ExperimentPlan(train_config={"epochs": 1}, loss_config=authored)
    effective = apply_parameter_rules(plan, workflow_rules=rules)
    loss = LossConfig.model_validate(effective.loss_cfg).model_dump()
    assert {field: loss[field] for field in consumed} == consumed


def test_task_loader_refuses_loss_typo_before_composition(tmp_path: Path) -> None:
    """Without loader reachability, an ineffective task loss lock reaches planning."""
    root = Path(__file__).resolve().parents[4]
    manifest = yaml.safe_load((root / "configs/task_composition/quickstart.yaml").read_text())
    manifest["parameter_rules"] = {"loss_config.gammmma": {"exact": 3}}
    path = tmp_path / "composition.yaml"
    path.write_text(yaml.safe_dump(manifest))
    with pytest.raises(TaskCompositionError, match=r"loss_config\.gammmma.*LossConfig"):
        compose_run_task_bindings(str(path))
