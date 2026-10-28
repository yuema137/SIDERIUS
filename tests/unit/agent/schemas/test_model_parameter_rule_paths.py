"""Issue #1047: model locks must name fields the selected model config consumes."""

import pytest
from pydantic import BaseModel, Field

from agent.schemas.hyperparam_tuning import ExperimentPlan
from agent.schemas.parameter_rules import (
    ParameterRuleError,
    ParameterRules,
    apply_parameter_rules,
    resolve_parameter_rule_document,
)
from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY, get_config_class


class _IgnoringPluginConfig(BaseModel):
    """Plugin config with pydantic's default ``extra="ignore"``, like shipped plugins."""

    model_type: str = "rule_probe_plugin"
    segmentation_size: int = Field(default=40, ge=1)
    hidden: int = 8


@pytest.fixture
def plugin(monkeypatch: pytest.MonkeyPatch) -> str:
    get_config_class("punet")  # populate the registry before patching it
    monkeypatch.setitem(PLUGIN_CONFIG_REGISTRY, "rule_probe_plugin", _IgnoringPluginConfig)
    return "rule_probe_plugin"


def _plan(model_type: str) -> ExperimentPlan:
    return ExperimentPlan(
        model_config={"model_type": model_type, "segmentation_size": 40},
        train_config={"epochs": 1},
    )


@pytest.mark.parametrize(
    ("model_type", "path", "schema"),
    [
        ("rule_probe_plugin", "model_config.hiddden", "_IgnoringPluginConfig"),
        ("punet", "model_config.segmentaton_size", "PUNetConfig"),
    ],
)
def test_model_rules_refuse_paths_the_selected_config_drops(
    plugin: str, model_type: str, path: str, schema: str
) -> None:
    """Without the resolve-time check the plugin config ignores the key and the lock is lost."""
    rules = ParameterRules.model_validate({path: {"exact": 16}})
    with pytest.raises(ParameterRuleError, match=rf"{path}.*{schema}"):
        apply_parameter_rules(_plan(model_type), workflow_rules=rules)


def test_check_uses_the_model_type_selected_by_an_exact_rule(plugin: str) -> None:
    """Checking the authored model type would judge the typo against the wrong schema."""
    rules = ParameterRules.model_validate(
        {
            "model_config.model_type": {"exact": plugin},
            "model_config.depth": {"exact": 16},
        }
    )
    # ``depth`` exists on the authored built-in PUNetConfig, not on the plugin.
    with pytest.raises(ParameterRuleError, match=r"model_config\.depth.*_IgnoringPluginConfig"):
        resolve_parameter_rule_document(_plan("punet").model_dump(by_alias=True), task_rules=rules)


def test_consumed_and_unregistered_model_targets_stay_valid(plugin: str) -> None:
    """Over-restriction would refuse valid locks or proposals for not-yet-implemented models."""
    rules = ParameterRules.model_validate(
        {"model_config.hidden": {"exact": 16}, "model_config.segmentation_size": {"exact": 80}}
    )
    effective = apply_parameter_rules(_plan(plugin), workflow_rules=rules)
    consumed = _IgnoringPluginConfig.model_validate(effective.model_cfg)
    assert (consumed.hidden, consumed.segmentation_size) == (16, 80)

    # A config that keeps extra keys consumes them; refusing would over-restrict.
    class _AllowingPluginConfig(_IgnoringPluginConfig, extra="allow"):
        pass

    PLUGIN_CONFIG_REGISTRY[plugin] = _AllowingPluginConfig
    extra = ParameterRules.model_validate({"model_config.extra_knob": {"exact": 3}})
    effective = apply_parameter_rules(_plan(plugin), workflow_rules=extra)
    assert _AllowingPluginConfig.model_validate(effective.model_cfg).model_dump()["extra_knob"] == 3

    # A generated model is proposed before its config class exists.
    pending = resolve_parameter_rule_document(
        {"model_config": {"model_type": "not_implemented_yet"}},
        task_rules=rules,
        defer_missing_non_exact=True,
    )
    assert pending["model_config"]["hidden"] == 16
