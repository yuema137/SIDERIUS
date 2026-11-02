"""Console presentation of a resolved request and its retained planner proposal."""

from agent.schemas.execution_provenance import AUTHORITY_DESCRIPTIONS, ExecutionProvenance
from agent.schemas.hyperparam_tuning import ExperimentPlan


def render_effective_plan(
    *,
    exp_id: str,
    model_type: str,
    plan: ExperimentPlan,
    provenance: ExecutionProvenance,
) -> str:
    """Read final resolution evidence without inferring policy or execution success."""
    lines = [
        f"Action: {model_type.upper()} | ID: {exp_id}",
        "Effective configuration for this attempt (prepared request; execution/results pending):",
    ]
    for event in provenance.events:
        authority = AUTHORITY_DESCRIPTIONS.get(event.authority, event.authority)
        lines.append(
            f"  {event.field_path}: proposed {event.proposed} -> effective {event.executed} "
            f"[authority: {authority}]"
        )
    if provenance.diverged:
        lines.append(
            "Authored proposal (superseded by the effective configuration above; "
            "prose retained as history):"
        )
    else:
        lines.append("  No authored configuration values were overridden.")
        lines.append("Authored proposal (not observed execution/results):")
    lines.extend(
        (
            f"  Proposal hypothesis: {plan.hypothesis}",
            f"  Proposal reasoning: {plan.reasoning or 'No reasoning provided.'}",
        )
    )
    return "\n".join(lines)
