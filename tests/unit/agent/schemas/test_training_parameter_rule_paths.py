"""Issue #844: locks must name fields the native trainer can consume."""

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
from ml_models.models_format_sandbox import TrainConfig
from workflows.task_composition import TaskCompositionError, compose_run_task_bindings


@pytest.mark.parametrize(
    "path",
    [
        "train_config.num_epochs",
        "train_config.train_portion",
        "train_config.epochs.typo",
        "train_config.lr_schedule.typo",
        "train_config.lr_schedule.kind.typo",
    ],
)
def test_training_rules_refuse_paths_outside_consuming_schema(path: str) -> None:
    """Without traversal, typo locks survive and execution ignores their keys."""
    with pytest.raises(ValueError, match=rf"{path}.*TrainConfig"):
        ParameterRules.model_validate({path: {"exact": 1}})


@pytest.mark.parametrize("owner", ["task_rules", "workflow_rules"])
def test_shared_resolver_rechecks_mutated_training_rule_paths(owner: str) -> None:
    """Without the resolver guard, mutable dictionaries bypass declaration checks."""
    rules = ParameterRules()
    rules.rules["train_config.num_epochs"] = ParameterRule(exact=1)
    with pytest.raises(ParameterRuleError, match=r"train_config\.num_epochs"):
        resolve_parameter_rule_document({"train_config": {"epochs": 7}}, **{owner: rules})
    with pytest.raises(ParameterRuleError, match=r"train_config\.num_epochs"):
        apply_parameter_rules(ExperimentPlan(train_config={"epochs": 7}), **{owner: rules})


@pytest.mark.parametrize(
    ("schedule", "path", "value"),
    [
        ({"kind": "step", "step_size_epochs": 2, "gamma": 0.5}, "gamma", 0.25),
        ({"kind": "cosine", "horizon_epochs": 4, "min_lr": 0.0}, "horizon_epochs", 6),
    ],
)
def test_actual_schedule_branches_and_omitted_exact_fields_stay_consumable(
    schedule: dict, path: str, value: float
) -> None:
    """Rejecting unions or requiring authored leaves would break valid exact locks."""
    plan = ExperimentPlan(train_config={"lr_schedule": schedule})
    rules = ParameterRules.model_validate(
        {
            "train_config.epochs": {"exact": 5},
            f"train_config.lr_schedule.{path}": {"exact": value},
            "model_config.plugin_extension": {"exact": {"arbitrary": True}},
        }
    )
    effective = apply_parameter_rules(plan, workflow_rules=rules)
    consumed = TrainConfig.model_validate(effective.train_cfg)
    assert consumed.epochs == 5
    assert consumed.lr_schedule.model_dump()[path] == value
    assert effective.model_cfg["plugin_extension"] == {"arbitrary": True}
    assert "epochs" not in plan.train_cfg
    assert schedule[path] != value


def test_task_loader_refuses_training_typo_before_composition(tmp_path: Path) -> None:
    """Without loader reachability, invalid task locks can reach readiness/planning."""
    root = Path(__file__).resolve().parents[4]
    manifest = yaml.safe_load((root / "configs/task_composition/quickstart.yaml").read_text())
    manifest["parameter_rules"] = {"train_config.train_portion": {"exact": 1.0}}
    path = tmp_path / "composition.yaml"
    path.write_text(yaml.safe_dump(manifest))
    with pytest.raises(TaskCompositionError, match=r"train_config\.train_portion.*TrainConfig"):
        compose_run_task_bindings(str(path))
