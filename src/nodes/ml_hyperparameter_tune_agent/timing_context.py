"""Compose existing execution authorities into bounded planner timing facts."""

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.planner_timing import PlannerTimingContext, RoleTimingContext
from nodes.ml_hyperparameter_tune_agent.policy import (
    _formal_inheritance_spec,
    _sample_set_sources,
)


def partial_scope_strategy_overrides(partial: bool, is_trial: bool) -> dict[str, str]:
    """The existing partial Trial normalization, shared with execution."""
    return (
        {"trial_strategy": "snapshot", "eval_strategy": "snapshot"} if partial and is_trial else {}
    )


def build_timing_context(
    agent_input: HyperparamTuningInput,
    *,
    trial_allowed: bool,
    is_formal_round: bool,
    current_round: int,
    trial_winner: dict | None,
    memory_history: list,
    scope_is_partial: bool,
) -> PlannerTimingContext:
    """Read owners; never select a winner, instantiate a plan, or execute a plugin."""
    forced = is_formal_round and agent_input.force_formal_round
    handler, preserve, recovery = _formal_inheritance_spec(
        agent_input.formal_round_strategy, memory_history, current_round
    )
    inheritance = (
        handler.assignments(trial_winner) if forced and trial_winner is not None and handler else {}
    )
    modes = (
        ("formal",)
        if forced and trial_allowed
        else (("trial", "formal") if trial_allowed else ("single_file",))
    )
    roles = []
    for mode in modes:
        cap = agent_input.resolve_epoch_cap(is_trial=mode == "trial")
        roles.append(
            RoleTimingContext(
                mode=mode,
                workload=_sample_set_sources(mode, agent_input),
                epoch_cap=cap.cap,
                epoch_cap_source=cap.source,
            )
        )
    composition = agent_input.task_composition_ref
    return PlannerTimingContext(
        plan_overrides=agent_input.plan_overrides,
        task_rules=composition.parameter_rules if composition else None,
        workflow_rules=agent_input.workflow_parameter_rules,
        roles=tuple(roles),
        formal_training_scope_source=agent_input.formal_training_scope_source,
        formal_eval_portion=agent_input.formal_eval_portion,
        trial_allowed=trial_allowed,
        forced_formal=forced,
        inheritance_strategy=agent_input.formal_round_strategy,
        inheritance_values=inheritance,
        inheritance_unless_authored=preserve if inheritance else (),
        inheritance_winner=str(trial_winner["exp_id"]) if forced and trial_winner else None,
        inheritance_recovery=recovery if forced else None,
        partial_scope_strategy_overrides=partial_scope_strategy_overrides(scope_is_partial, True),
        validation_max_portion=agent_input.validation_max_portion,
        validation_max_train_samples=agent_input.validation_max_train_samples,
        validation_max_samples=agent_input.validation_max_samples,
        training_validation_portion=agent_input.training_validation_portion,
        training_budget_reserve_fraction=agent_input.training_budget_reserve_fraction,
    )
