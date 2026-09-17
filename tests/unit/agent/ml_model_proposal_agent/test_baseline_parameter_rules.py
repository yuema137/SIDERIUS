"""The effective candidate baseline must be resolved before resource preflight."""

import pytest

from agent.schemas.hyperparam_tuning import TaskCompositionRef
from agent.schemas.parameter_rules import ParameterRuleError, ParameterRules
from nodes.ml_model_proposal_agent.parameter_rules import (
    render_proposal_parameter_rules,
    resolve_proposal_baseline_config,
)


def _baseline() -> dict:
    return {"model_config": {"width": 8}}


def _rules(path: str, rule: dict) -> ParameterRules:
    return ParameterRules.model_validate({path: rule})


def _resolve(
    baseline: dict,
    *,
    task: ParameterRules | None = None,
    workflow: ParameterRules | None = None,
) -> dict:
    composition = (
        TaskCompositionRef(
            semantic_fingerprint="synthetic",
            task_data_path_id="synthetic",
            task_health_binding=None,
            parameter_rules=task,
        )
        if task is not None
        else None
    )
    return resolve_proposal_baseline_config(
        baseline,
        composition_ref=composition,
        workflow_rules=workflow,
    )


def test_exact_rule_inserts_missing_candidate_dimension_without_mutating_llm_output() -> None:
    """Fails if the budget preflight still sees an absent segmentation dimension."""
    authored = _baseline()
    rules = _rules("model_config.segmentation_size", {"exact": 40_000})

    effective = _resolve(authored, workflow=rules)

    assert "segmentation_size" not in authored["model_config"]
    assert effective["model_config"]["segmentation_size"] == 40_000
    assert effective["model_config"]["width"] == 8


def test_task_and_workflow_constraints_remain_peers() -> None:
    """Fails if a workflow exact lock bypasses the task's legal range."""
    task = _rules("model_config.segmentation_size", {"range": {"min": 1_000, "max": 50_000}})
    accepted = _rules("model_config.segmentation_size", {"exact": 40_000})
    refused = _rules("model_config.segmentation_size", {"exact": 100_000})

    assert (
        _resolve(_baseline(), task=task, workflow=accepted)["model_config"]["segmentation_size"]
        == 40_000
    )
    with pytest.raises(ParameterRuleError, match="requires value <= 50000"):
        _resolve(_baseline(), task=task, workflow=refused)


def test_missing_non_exact_rule_is_deferred_but_authored_invalid_value_refuses() -> None:
    """A future tuner knob need not be invented by the Proposer."""
    rules = _rules("train_config.batch_size", {"range": {"min": 1, "max": 8}})
    assert _resolve(_baseline(), workflow=rules) == _baseline()

    authored = _baseline()
    authored["train_config"] = {"batch_size": 16}
    with pytest.raises(ParameterRuleError, match="requires value <= 8"):
        _resolve(authored, workflow=rules)


def test_unconstrained_and_rendering_modes_preserve_legacy_behavior() -> None:
    """No declared rule must not change object identity or prompt bytes."""
    authored = _baseline()
    assert _resolve(authored) is authored
    assert render_proposal_parameter_rules(None, None) == ""
    assert "model_config.segmentation_size: exact 40000" in render_proposal_parameter_rules(
        None, _rules("model_config.segmentation_size", {"exact": 40_000})
    )
