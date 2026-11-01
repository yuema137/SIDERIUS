"""Transport inactive-rule receipts from effective plans to persisted history."""

from typing import Any

from agent.schemas.hyperparam_tuning import ExperimentPlan


def inactive_parameter_rule_record(plan: ExperimentPlan) -> dict[str, Any]:
    """Keep unaffected records unchanged; never pass receipts to the executor."""
    if not plan.inactive_parameter_rules:
        return {}
    return {
        "inactive_parameter_rules": [
            r.model_dump(mode="json") for r in plan.inactive_parameter_rules
        ]
    }


def attach_inactive_parameter_rules(record: dict[str, Any]) -> None:
    """Promote attempt receipts at the shared validated persistence boundary."""
    params = record.get("params", {})
    if "inactive_parameter_rules" in params:
        record["params"] = dict(params)
        record["inactive_parameter_rules"] = record["params"].pop("inactive_parameter_rules")
