"""Resolve declared parameter rules before Proposer's baseline preflight."""

from __future__ import annotations

import json
from collections.abc import Mapping

from agent.prompt_rendering import prompt_boundary
from agent.schemas.generated_model_config import GENERATED_MODEL_CONFIG_GUIDANCE
from agent.schemas.hyperparam_tuning import TaskCompositionRef
from agent.schemas.parameter_rules import (
    ParameterRuleError,
    ParameterRules,
    resolve_parameter_rule_document,
    validate_parameter_rule_ownership,
)


@prompt_boundary("proposer.parameter_rules")
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
        return GENERATED_MODEL_CONFIG_GUIDANCE
    lines.append(
        "Exact values become the effective baseline before the resource preflight; "
        "other rules validate supplied values. Include every known model input "
        "dimension in baseline_config."
    )
    return GENERATED_MODEL_CONFIG_GUIDANCE + "\n\n" + "\n".join(lines)


def resolve_proposal_baseline_config(
    baseline_config: object,
    *,
    proposed_model_type: str | None = None,
    composition_ref: TaskCompositionRef | None,
    workflow_rules: ParameterRules | None,
) -> object:
    """Resolve typed rules before the effective proposal's Pydantic boundary.

    Exact rules select values before the wall-time preflight. Other rules
    validate baseline fields that the Proposer actually supplied; fields left
    for the tuner remain subject to the tuner's strict effective-plan gate.
    With no declared rules, the raw baseline and legacy behavior are unchanged.
    ``model_config`` rules are judged against the proposed model, never a
    template base ``model_type`` named by the baseline. Its config class does
    not exist before implementation, so target and boolean-value checks defer
    to the tuner. ``proposed_model_type=None`` means the proposed model is not
    known yet: those checks are deferred the same way.
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

    # The resolver falls back to a document's top-level ``model_type`` when no
    # executed model is given; here that key is only a template base, so it is
    # hidden from the resolver and restored unchanged.
    template_model_type = baseline.pop("model_type", None)
    resolved = resolve_parameter_rule_document(
        baseline,
        task_rules=task_rules,
        workflow_rules=workflow_rules,
        defer_missing_non_exact=True,
        defer_unknown_model=True,
        executed_model_type=proposed_model_type,
    )
    if "model_type" in baseline_config:
        resolved["model_type"] = template_model_type
    return resolved
