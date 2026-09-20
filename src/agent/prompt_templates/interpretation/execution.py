"""Bounded observed execution context for scientific interpretation."""

from agent.prompt_templates.timing_attribution import TIMING_SPLIT_SEMANTICS
from agent.schemas.interpretation import InterpretationExecutionEvidence


def render_execution_evidence(evidence: list[InterpretationExecutionEvidence]) -> list[str]:
    """Render identified observations; descriptions and config are not measurements."""
    if not evidence:
        return []
    lines = [
        "### Observed execution",
        "Use these recorded facts over architecture-description claims. Missing values are unknown.",
        TIMING_SPLIT_SEMANTICS,
    ]
    for item in evidence:
        lines.append(f"Record {item.exp_id} ({'Trial' if item.is_trial else 'Formal'}):")
        if item.timing is not None:
            lines.append(f"Phase wall times (seconds): {item.timing.model_dump_json()}")
        lines.append(
            f"Parameter dtype: {item.parameter_dtype or 'unavailable'}; "
            "autocast/operator compute precision is not established by parameter dtype."
        )
        if item.validation_samples is not None:
            lines.append(
                f"Materialized validation samples: {item.validation_samples} "
                "(dataset rows, not physical parent segments)."
            )
        for phase, memory in item.phase_memory.items():
            lines.append(f"{phase} process memory observation: {memory.model_dump_json()}")
        budget = item.training_budget
        if budget is not None:
            lines.extend(
                [
                    f"Training budget: {budget.policy.budget_seconds:g} s; "
                    f"epoch cap={budget.policy.max_epochs}; proposed epochs={budget.proposed_epochs}; "
                    f"completed epochs={budget.completed_epochs}; optimizer steps={budget.optimizer_steps}.",
                    f"Final budget decision: {budget.stop.model_dump_json()}",
                    f"Checkpoint selection: {budget.checkpoint_selection}; "
                    f"scientific early stopping={budget.scientific_early_stopping}. "
                    "A time-budget stop is not evidence of convergence or failure to obey proposed epochs.",
                ]
            )
    return lines
