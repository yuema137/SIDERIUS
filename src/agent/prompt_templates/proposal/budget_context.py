"""Configured phase budgets delivered directly to every proposer request."""

from agent.prompt_rendering import prompt_boundary
from agent.schemas.proposal import ProposalInput


@prompt_boundary("proposal.time_budget_context")
def render_proposer_time_budget_context(inp: ProposalInput) -> str:
    """Render each supplied value independently, without inferring missing limits."""
    lines = ["## Configured time budgets"]
    for phase, minutes in (
        ("Trial", inp.trial_time_budget_minutes),
        ("Formal", inp.formal_time_budget_minutes),
    ):
        value = "not configured in this input" if minutes is None else f"{minutes} minutes"
        lines.append(f"- {phase} time budget: {value}")
    lines.append(
        "Use these configured budgets when considering the architecture and workload. "
        "Each is a phase budget, not a utilization target or a total experiment/API spending limit. "
        "The proposer-side static time estimate is advisory: it does not reject or "
        "revise proposals, and it does not establish a parameter-count ceiling. "
        "These values do not change the declared task, workflow permissions or "
        "native training capabilities; execution uses its resolved resource policy."
    )
    return "\n".join(lines)
