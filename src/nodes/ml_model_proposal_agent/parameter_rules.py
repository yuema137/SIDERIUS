"""Resolve declared parameter rules before Proposer's baseline preflight."""

from __future__ import annotations

import json
from collections.abc import Mapping

from agent.schemas.hyperparam_tuning import TaskCompositionRef
from agent.schemas.parameter_rules import (
    ParameterRuleError,
    ParameterRules,
    resolve_parameter_rule_document,
    validate_parameter_rule_ownership,
)


def render_proposal_parameter_rules(
    composition_ref: TaskCompositionRef | None,
    workflow_rules: ParameterRules | None,
) -> str:
    """Show the LLM the same typed rules enforced on its baseline."""
    task_rules = composition_ref.parameter_rules if composition_ref is not None else None
    lines = ["## Machine-enforced candidate parameter rules"]
    for owner, rules in (("task", task_rules), ("workflow", workflow_rules)):
        if rules is None:
            continue
        for path, rule in sorted(rules.rules.items()):
            value = rule.model_dump(mode="json")[rule.kind]
            lines.append(f"- {owner} {path}: {rule.kind} {json.dumps(value, sort_keys=True)}")
    if len(lines) == 1:
        return ""
    lines.append(
        "Exact values become the effective baseline before the resource preflight; "
        "other rules validate supplied values. Include every known model input "
        "dimension in baseline_config."
    )
    return "\n".join(lines)


def resolve_proposal_baseline_config(
    baseline_config: object,
    *,
    composition_ref: TaskCompositionRef | None,
    workflow_rules: ParameterRules | None,
) -> object:
    """Resolve typed rules before the effective proposal's Pydantic boundary.

    Exact rules select values before the wall-time preflight. Other rules
    validate baseline fields that the Proposer actually supplied; fields left
    for the tuner remain subject to the tuner's strict effective-plan gate.
    With no declared rules, the raw baseline and legacy behavior are unchanged.
    """
    task_rules = composition_ref.parameter_rules if composition_ref is not None else None
    if not (task_rules and task_rules.rules) and not (workflow_rules and workflow_rules.rules):
        return baseline_config
    if not isinstance(baseline_config, Mapping):
        raise ParameterRuleError("baseline_config must be a mapping before parameter rules apply")

    validate_parameter_rule_ownership(
        objective_declared=composition_ref is not None and composition_ref.objective is not None,
        task_rules=task_rules,
        workflow_rules=workflow_rules,
    )
    baseline = dict(baseline_config)
    for rules in (task_rules, workflow_rules):
        if rules is None:
            continue
        for path, rule in rules.rules.items():
            if rule.kind == "exact":
                baseline.setdefault(path.split(".", 1)[0], {})

    return resolve_parameter_rule_document(
        baseline,
        task_rules=task_rules,
        workflow_rules=workflow_rules,
        defer_missing_non_exact=True,
    )
