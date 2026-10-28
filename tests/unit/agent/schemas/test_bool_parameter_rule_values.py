"""Issue #1048: a boolean rule value must not be coerced into a number."""

import pytest
from pydantic import BaseModel

from agent.schemas.hyperparam_tuning import ExperimentPlan
from agent.schemas.parameter_rules import (
    ParameterRule,
    ParameterRuleError,
    ParameterRules,
    apply_parameter_rules,
)
from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY, TrainConfig, get_config_class


@pytest.mark.parametrize(
    ("path", "rule"),
    [
        ("train_config.batch_size", {"exact": True}),
        ("train_config.batch_size", {"allowed": [True, 2]}),
        ("loss_config.gamma", {"exact": False}),
    ],
)
def test_boolean_values_on_numeric_fixed_fields_are_refused(path: str, rule: dict) -> None:
    """Without the type check, TrainConfig/LossConfig read ``true`` as 1 and ``false`` as 0."""
    with pytest.raises(ValueError, match=rf"{path}.*boolean"):
        ParameterRules.model_validate({path: rule})


def test_shared_resolver_rechecks_mutated_boolean_values() -> None:
    """Without the resolver guard, a mutated rule dictionary bypasses declaration checks."""
    rules = ParameterRules()
    rules.rules["train_config.batch_size"] = ParameterRule(exact=True)
    with pytest.raises(ParameterRuleError, match=r"train_config\.batch_size.*boolean"):
        apply_parameter_rules(ExperimentPlan(train_config={"batch_size": 4}), task_rules=rules)


def test_boolean_values_on_selected_model_config_fields_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plugin's integer field would silently execute ``true`` as 1."""

    class _Config(BaseModel):
        model_type: str = "bool_probe_plugin"
        hidden: int = 8

    get_config_class("punet")  # populate the registry before patching it
    monkeypatch.setitem(PLUGIN_CONFIG_REGISTRY, "bool_probe_plugin", _Config)
    rules = ParameterRules.model_validate({"model_config.hidden": {"exact": True}})
    plan = ExperimentPlan(model_config={"model_type": "bool_probe_plugin"})
    with pytest.raises(ParameterRuleError, match=r"model_config\.hidden.*boolean.*_Config"):
        apply_parameter_rules(plan, workflow_rules=rules)


def test_boolean_fields_keep_boolean_rules() -> None:
    """Refusing every boolean would break shipped locks such as ``drop_last: false``."""
    rules = ParameterRules.model_validate(
        {
            "train_config.drop_last": {"exact": False},
            "loss_config.use_class_weights": {"allowed": [True, False]},
        }
    )
    plan = ExperimentPlan(train_config={"drop_last": True}, loss_config={"use_class_weights": True})
    effective = apply_parameter_rules(plan, workflow_rules=rules)
    assert TrainConfig.model_validate(effective.train_cfg).drop_last is False
