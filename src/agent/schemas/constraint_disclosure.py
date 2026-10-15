"""Read-only disclosure of existing run authorities, never another resolver."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue, model_validator

from agent.schemas.parameter_rules import ParameterRules
from agent.schemas.planner_timing import PlannerTimingContext

ConstraintSection = Literal["task_rules", "workflow_rules", "objective", "overrides", "execution"]
CONSTRAINT_SECTIONS: tuple[ConstraintSection, ...] = (
    "task_rules",
    "workflow_rules",
    "objective",
    "overrides",
    "execution",
)


class ExecutionConstraintFacts(BaseModel):
    """Declared controls copied from owners; no effective value is guessed here."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    max_epochs: int | None = None
    trial_max_epochs: int | None = None
    formal_max_epochs: int | None = None
    validation_max_portion: float | None = None
    validation_max_train_samples: int | None = None
    validation_max_samples: int | None = None
    training_validation_portion: float | None = None
    trial_time_budget_minutes: float | None = None
    formal_time_budget_minutes: float | None = None
    trial_vram_budget_gb: float | None = None
    formal_vram_budget_gb: float | None = None
    formal_training_scope_source: Literal["operator", "agent"] | None = None
    formal_portion: float | None = None
    formal_train_portion: float | None = None
    formal_eval_portion: float | None = None
    force_formal_round: bool | None = None


class ConstraintContext(BaseModel):
    """Known sections refer only to this finite surface, not arbitrary plugins.

    Missing context/sections mean incomplete information. An effective baseline
    is not a lock; only the carried authority declares its restriction.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    known_sections: tuple[ConstraintSection, ...] = ()
    task_rules: ParameterRules | None = None
    workflow_rules: ParameterRules | None = None
    objective: dict[str, JsonValue] | None = None
    overrides: dict[str, JsonValue] | None = None
    execution: ExecutionConstraintFacts | None = None
    timing: PlannerTimingContext | None = None

    @model_validator(mode="after")
    def validate_coverage(self) -> "ConstraintContext":
        if "execution" in self.known_sections and self.execution is None:
            raise ValueError("known execution section requires explicit execution facts")
        return self
