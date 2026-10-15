"""One rendering boundary for read-only current-run constraint disclosure."""

import json

from agent.prompt_rendering import prompt_boundary
from agent.schemas.constraint_disclosure import CONSTRAINT_SECTIONS, ConstraintContext


@prompt_boundary("constraints.disclosure")
def render_constraint_disclosure(context: ConstraintContext | None) -> str:
    """Historical text may be selected explicitly; execution is never affected."""
    context = context or ConstraintContext()
    missing = [name for name in CONSTRAINT_SECTIONS if name not in context.known_sections]
    coverage = (
        "Incomplete constraint information; missing authority sections: " + ", ".join(missing)
        if missing
        else "All sections of this bounded disclosure are supplied; other plugin restrictions may exist."
    )
    facts = context.model_dump(mode="json", exclude_none=True)
    return (
        "[CURRENT RUN EXECUTION CONSTRAINTS]\n"
        + coverage
        + "\nMissing information does not mean a parameter is adjustable. "
        "Task and workflow rules both apply; exact values are locked even when a proposal already matches. "
        "Ranges, allowed sets and predicates restrict choices without selecting a value. "
        "Task objectives, operator overrides and execution caps retain their existing owners and precedence. "
        "Mode-specific controls apply to their named phase. Trial portion overrides do not freeze Formal portions; "
        "Formal training scope is operator-owned only when formal_training_scope_source is operator; "
        "Formal evaluation remains operator-owned via formal_eval_portion. "
        "A baseline value alone is not a lock. Time budgets are not a claim of a hard wall-clock kill. "
        "These are current-run constraints, not corrections to historical results or published methods. "
        "Preserve source-paper facts and measured evidence; distinguish unavailable interventions from false findings. "
        "Separate requested, resolved and executed values using recorded execution provenance.\n"
        + json.dumps(facts, sort_keys=True, indent=2)
    )


def append_constraint_disclosure(prompt: str, context: ConstraintContext | None) -> str:
    section = render_constraint_disclosure(context)
    return prompt + "\n\n" + section if section else prompt
