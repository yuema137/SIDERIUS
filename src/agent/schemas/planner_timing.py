"""Transient planner facts; execution owners remain the constraint authorities."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue

from agent.schemas.parameter_rules import ParameterRules


class WorkloadSource(BaseModel):
    """One execution field reads a resolved plan field or an owner-supplied value."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    field: str
    owner: Literal["resolved_plan", "run", "execution_contract"]
    source: str
    value: JsonValue = None


PortionField = Literal["trial_portion", "train_portion", "eval_portion"]


class ValidationPortionClamp(BaseModel):
    """One executed portion that ``validation_max_portion`` reduced below its source.

    Read from planning's own before/after pair (``_planned_portions`` and the
    resolved ``cfg_*`` portions, the same pair recorded as
    ``validation_workload_ceiling``); the ceiling is ``min``, so
    ``executed_value`` is the configured ceiling whenever this record exists.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    field: PortionField
    source_value: float
    executed_value: float


class RoleTimingContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: Literal["trial", "formal", "single_file"]
    workload: tuple[WorkloadSource, ...]
    epoch_cap: int | None
    epoch_cap_source: str | None


class PlannerTimingContext(BaseModel):
    """Complete for the bounded timing surface, not every plugin constraint.

    A missing object means incomplete information, never unconstrained control.
    Values are supplied by owners; this carrier selects no strategy or budget.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    plan_overrides: dict[str, JsonValue]
    task_rules: ParameterRules | None
    workflow_rules: ParameterRules | None
    roles: tuple[RoleTimingContext, ...]
    formal_training_scope_source: Literal["operator", "agent"]
    formal_eval_portion: float
    trial_allowed: bool
    forced_formal: bool
    inheritance_strategy: str
    inheritance_values: dict[str, JsonValue]
    inheritance_unless_authored: tuple[str, ...]
    inheritance_winner: str | None
    inheritance_recovery: str | None
    partial_scope_strategy_overrides: dict[str, str]
    validation_max_portion: float | None
    validation_max_train_samples: int | None
    validation_max_samples: int | None
    training_validation_portion: float | None
    training_budget_reserve_fraction: float | None
