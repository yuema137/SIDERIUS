"""Render supplied timing authorities without choosing an experiment strategy."""

from agent.schemas.planner_timing import PlannerTimingContext


def render_timing_context(context: PlannerTimingContext | None) -> str:
    if context is None:
        return (
            "\n### TIMING CONTROL CONTEXT — incomplete\n"
            "Task/workflow timing constraints were not supplied in full. Unknown "
            "constraints do not imply adjustable parameters. Any separately supplied "
            "overrides and caps are partial information; do not claim a complete control surface.\n"
        )
    return (
        "\n### TIMING CONTROL CONTEXT\n"
        "These are supplied execution facts, not a search strategy. Coverage is limited "
        "to the timing surface; model/plugin validation still applies.\n"
        "Read the resolution sequence: operator plan overrides; forced mode and "
        "inheritance; task objective; partial-scope Trial normalization; role epoch cap; "
        "task/workflow parameter rules; role workload sources; validation_max_portion. "
        "A resolved_plan source reads the resulting validated plan, not your original JSON. "
        "Later rules can replace an earlier requested value. Exact rules replace values; "
        "ranges, allowed sets and named predicates constrain them without choosing a value. "
        "Task and workflow rules must both hold; rules cannot exceed the role epoch ceiling.\n"
        "inheritance_values use internal plan names (model_cfg/loss_cfg and train-config keys); "
        "inheritance_unless_authored names retry fields retained if present in your train_config. "
        "Empty inheritance_values means no fields are inherited in this invocation. "
        "Role alternatives are conditional, not a recommendation to switch modes.\n"
        "validation_max_portion caps each resolved training/evaluation portion; "
        "validation_max_train_samples caps training samples per epoch. "
        "validation_max_samples bounds the evaluation scope used for final scoring and "
        "also bounds epoch validation, including an independently selected epoch-validation "
        "scope. These sample ceilings remain subject to the task capability's scope units. "
        "With an explicit "
        "training_validation_portion, epoch-loss validation uses its independent fixed snapshot; "
        "changing final evaluation scope does not change that snapshot. Otherwise epoch "
        "validation follows the selected evaluation scope, subject to its bounds.\n"
        "With training_budget_reserve_fraction supplied, cooperative execution may continue "
        "beyond proposed epochs within the role cap and budget; proposed epochs are not a "
        "guaranteed execution horizon. All null bounds mean that particular bound is absent, "
        "not that other constraints are absent. Values not yet authored remain unresolved.\n"
        "Use measured costs and these facts to form a hypothesis. No parameter adjustment "
        "order, data-volume target or proportional speedup is prescribed here.\n"
        + context.model_dump_json(indent=2)
        + "\n"
    )
