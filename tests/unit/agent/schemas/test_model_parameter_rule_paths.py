"""Issue #1047: model locks must name fields the executed model's config consumes.

Plans use the production shape: the executed model is the top-level
``model_type`` (or ``force_model``); the planner never fills the nested
``model_config.model_type`` mirror before rules run.
"""

import pytest
from pydantic import BaseModel, Field

from agent.schemas.hyperparam_tuning import EpochCapResolution, ExperimentPlan
from agent.schemas.parameter_rules import (
    ParameterRuleError,
    ParameterRules,
    apply_parameter_rules,
    resolve_parameter_rule_document,
)
from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY, get_config_class
from nodes.ml_hyperparameter_tune_agent.planning import _apply_effective_parameter_rules


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
        model_type=model_type,
        model_config={"segmentation_size": 40},
        train_config={"epochs": 1},
    )


def _rules(rules: dict) -> ParameterRules:
    return ParameterRules.model_validate(rules)


@pytest.mark.parametrize(
    ("model_type", "path", "schema"),
    [
        ("rule_probe_plugin", "model_config.hiddden", "_IgnoringPluginConfig"),
        ("punet", "model_config.segmentaton_size", "PUNetConfig"),
    ],
)
def test_model_rules_refuse_paths_the_executed_config_drops(
    plugin: str, model_type: str, path: str, schema: str
) -> None:
    """Without the check, the executed config ignores the key and the lock is lost."""
    with pytest.raises(ParameterRuleError, match=rf"{path}.*{schema}"):
        apply_parameter_rules(_plan(model_type), workflow_rules=_rules({path: {"exact": 16}}))


@pytest.mark.parametrize(
    ("authored", "forced", "path", "schema"),
    [
        # ``depth`` exists on the authored PUNetConfig, not on the forced plugin.
        ("punet", "rule_probe_plugin", "model_config.depth", "_IgnoringPluginConfig"),
        # ``hidden`` exists on the authored plugin, not on the forced PUNetConfig.
        ("rule_probe_plugin", "punet", "model_config.hidden", "PUNetConfig"),
    ],
)
def test_planning_checks_the_force_model_not_the_authored_model(
    plugin: str, authored: str, forced: str, path: str, schema: str
) -> None:
    """Checking the plan's own model_type would judge the lock against the wrong config."""
    with pytest.raises(ParameterRuleError, match=rf"{path}.*{schema}"):
        _apply_effective_parameter_rules(
            _plan(authored),
            composition_ref=None,
            workflow_rules=_rules({path: {"exact": 16}}),
            epoch_cap=EpochCapResolution(cap=None, source=None),
            executed_model_type=forced,
        )


@pytest.mark.parametrize(
    "rule",
    [{"exact": "punet"}, {"allowed": ["punet", "wavenet"]}],
)
def test_model_type_rule_is_judged_against_the_executed_model(plugin: str, rule: dict) -> None:
    """The planner overwrites the nested mirror, so a disagreeing lock would be silently lost."""
    with pytest.raises(ParameterRuleError, match=r"model_config\.model_type"):
        apply_parameter_rules(
            _plan(plugin), workflow_rules=_rules({"model_config.model_type": rule})
        )
    effective = apply_parameter_rules(
        _plan("punet"), workflow_rules=_rules({"model_config.model_type": rule})
    )
    assert effective.model_cfg["model_type"] == "punet"


def test_tuner_fails_closed_without_a_config_class_but_proposals_defer(plugin: str) -> None:
    """An unchecked tuner plan would execute a lock nobody could validate."""
    rules = _rules({"model_config.hidden": {"exact": 16}})
    with pytest.raises(ParameterRuleError, match=r"no registered configuration class"):
        apply_parameter_rules(_plan("not_implemented_yet"), workflow_rules=rules)
    # A generated model is proposed before its config class exists.
    pending = resolve_parameter_rule_document(
        {"model_config": {}},
        task_rules=rules,
        defer_missing_non_exact=True,
        defer_unknown_model=True,
    )
    assert pending["model_config"]["hidden"] == 16


def test_consumed_and_extra_allowing_model_targets_stay_valid(plugin: str) -> None:
    """Over-restriction would refuse valid locks or keys an allowing config keeps."""
    rules = _rules(
        {"model_config.hidden": {"exact": 16}, "model_config.segmentation_size": {"exact": 80}}
    )
    effective = apply_parameter_rules(_plan(plugin), workflow_rules=rules)
    consumed = _IgnoringPluginConfig.model_validate(effective.model_cfg)
    assert (consumed.hidden, consumed.segmentation_size) == (16, 80)

    class _AllowingPluginConfig(_IgnoringPluginConfig, extra="allow"):
        pass

    PLUGIN_CONFIG_REGISTRY[plugin] = _AllowingPluginConfig
    extra = _rules({"model_config.extra_knob": {"exact": 3}})
    effective = apply_parameter_rules(_plan(plugin), workflow_rules=extra)
    assert _AllowingPluginConfig.model_validate(effective.model_cfg).model_dump()["extra_knob"] == 3
