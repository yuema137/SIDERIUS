"""Issue #1048: a boolean rule value must not be coerced into a number."""

from typing import Literal

import pytest
from pydantic import BaseModel, create_model

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


class _BoolProbeBase(BaseModel):
    model_type: str = "bool_probe_plugin"
    hidden: int = 8
    label: str = "a"
    flag: bool | None = None
    mode: Literal["auto", False] = "auto"


# Generated plugins are not linted to this repository's style and may spell an
# optional field ``typing.Optional[bool]``, whose origin (``typing.Union``)
# differs from ``bool | None`` (``types.UnionType``).
_GENERATED_STYLE: dict = {}
exec("from typing import Optional\noptional_bool = Optional[bool]\n", _GENERATED_STYLE)

_BoolProbeConfig = create_model(
    "_BoolProbeConfig",
    __base__=_BoolProbeBase,
    optional_flag=(_GENERATED_STYLE["optional_bool"], None),
)


@pytest.fixture
def bool_probe(monkeypatch: pytest.MonkeyPatch) -> str:
    get_config_class("punet")  # populate the registry before patching it
    monkeypatch.setitem(PLUGIN_CONFIG_REGISTRY, "bool_probe_plugin", _BoolProbeConfig)
    return "bool_probe_plugin"


def _model_plan(model_type: str) -> ExperimentPlan:
    # Production shape: the executed model is the top-level model_type.
    return ExperimentPlan(model_type=model_type, model_config={"hidden": 8, "optional_flag": True})


@pytest.mark.parametrize("field", ["hidden", "label"])
def test_boolean_values_on_executed_model_config_fields_are_refused(
    bool_probe: str, field: str
) -> None:
    """A plugin's int field would silently execute ``true`` as 1."""
    rules = ParameterRules.model_validate({f"model_config.{field}": {"exact": True}})
    with pytest.raises(
        ParameterRuleError, match=rf"model_config\.{field}.*boolean.*_BoolProbeConfig"
    ):
        apply_parameter_rules(_model_plan(bool_probe), workflow_rules=rules)


@pytest.mark.parametrize(
    ("field", "rule"),
    [
        ("flag", {"exact": True}),
        ("optional_flag", {"allowed": [True, False]}),
        ("mode", {"exact": False}),
    ],
)
def test_optional_and_literal_boolean_fields_keep_boolean_rules(
    bool_probe: str, field: str, rule: dict
) -> None:
    """Missing union or Literal handling would refuse a boolean the field really keeps."""
    rules = ParameterRules.model_validate({f"model_config.{field}": rule})
    effective = apply_parameter_rules(_model_plan(bool_probe), workflow_rules=rules)
    if "exact" in rule:
        consumed = _BoolProbeConfig.model_validate(effective.model_cfg)
        assert getattr(consumed, field) is rule["exact"]


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
