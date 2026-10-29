"""The four LLM COMBINE strategy declarations (B2), discriminated on a versioned ``kind``.

Declared here beside the deterministic kinds so an adaptor's COMBINE slot can name
them; they are inert data. Whether a kind may run is decided by
``workflows.judge_strategies.admit_llm_strategy``, which refuses every kind whose
implementation has not landed. Model routing is never declared: ``route_slot``
names a ``WorkflowLLMConfig.judge`` slot the operator configures.
Contract: ``src/workflows/judge_strategies/judge-strategies-contract.md``.
"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from agent.schemas.judge_task import MAX_DEBATE_ROUNDS, RubricRef

from .adaptor_strategies import MAX_ADAPTOR_OUTPUTS, Fallback
from .base import DeclarationModel


class _LLMStrategyCommon(DeclarationModel):
    """Parameters every LLM kind carries (B2 §2.1)."""

    route_slot: Literal["aggregate", "debate"]
    max_calls: Annotated[int, Field(gt=0)]
    on_failure: Literal["fail"] | Fallback = "fail"
    guidance: Literal["task_blocks", "none"]
    criterion: str = Field(min_length=1, max_length=2000)


class DebateJudgeStrategy(_LLMStrategyCommon):
    kind: Literal["debate-judge/v1"] = "debate-judge/v1"
    rounds: Annotated[int, Field(ge=1, le=MAX_DEBATE_ROUNDS)]
    critic: bool
    judge_output: Literal["rank", "synthesize"]
    synthesize_count: Annotated[int, Field(ge=1, le=MAX_ADAPTOR_OUTPUTS)] | None = None

    @model_validator(mode="after")
    def count_iff_synthesize(self) -> Self:
        if (self.judge_output == "synthesize") != (self.synthesize_count is not None):
            raise ValueError("debate-judge/v1 declares synthesize_count iff it synthesizes")
        return self


class RubricRankStrategy(_LLMStrategyCommon):
    """Score items against an exact rubric; code computes totals and the ranking."""

    kind: Literal["rubric-rank/v1"] = "rubric-rank/v1"
    rubric: RubricRef
    scoring: Literal["per_item", "batch"]
    repeats: Annotated[int, Field(ge=1, le=3)]
    tie_break: Literal["input_order"] = "input_order"


class PrimaryAdvisorsStrategy(_LLMStrategyCommon):
    kind: Literal["primary-advisors-llm/v1"] = "primary-advisors-llm/v1"
    primary: Literal["declared", "metric_best", "first_admissible"]
    primary_item: str | None = Field(default=None, min_length=1)  # an item id, "<port>:<position>"
    advice: Literal["single_call", "per_advisor"]

    @model_validator(mode="after")
    def item_iff_declared(self) -> Self:
        if (self.primary == "declared") != (self.primary_item is not None):
            raise ValueError("primary-advisors-llm/v1 names primary_item iff primary is declared")
        return self


class JudgeMergeStrategy(_LLMStrategyCommon):
    kind: Literal["judge-merge/v1"] = "judge-merge/v1"
    synthesize_count: Annotated[int, Field(ge=1, le=MAX_ADAPTOR_OUTPUTS)]
    min_parents: Annotated[int, Field(ge=2)]


LLMStrategy = Annotated[
    DebateJudgeStrategy | RubricRankStrategy | PrimaryAdvisorsStrategy | JudgeMergeStrategy,
    Field(discriminator="kind"),
]
