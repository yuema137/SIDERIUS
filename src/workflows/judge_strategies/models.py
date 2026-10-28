"""Typed values B6 passes to and receives from the LLM strategy owner.

All values are frozen; the owner holds no state between calls. The invocation's
hashed identity excludes its host-specific ``evidence_dir``.
Contract: ``judge-strategies-contract.md`` beside this file.
"""

from pathlib import Path
from typing import Literal, Self

from pydantic import Field, JsonValue, model_validator

from agent.schemas.data_analysis.common import canonical_sha256
from agent.schemas.judge import Digest, FailureCode, ItemProjection, JudgeModel
from agent.schemas.judge_task import (
    JudgeTaskBlocks,
    RubricRef,
    RubricSpec,
    judge_guidance_sha256,
    rubric_ref,
)
from workflows.adaptors.items import AdaptorInputRef
from workflows.definition.adaptor_strategies import CardinalityBound
from workflows.definition.base import Identifier
from workflows.definition.llm_strategies import LLMStrategy, RubricRankStrategy

STRATEGY_EVIDENCE_FILE = "strategy.json"
CALLS_DIR = "calls"


class StrategyError(ValueError):
    """An LLM strategy cannot run or replay; raised before any provider contact on run."""


class StrategyItem(JudgeModel):
    """One admissible input, built by ``strategy_items`` from a verified adaptor item."""

    ref: AdaptorInputRef
    contract: str = Field(min_length=1)
    projection: ItemProjection

    @property
    def item_id(self) -> str:
        """B6 dispatch identity ``<port>:<position>``; never scientific meaning."""
        return f"{self.ref.port}:{self.ref.position}"

    @model_validator(mode="after")
    def projection_matches_contract(self) -> Self:
        if self.projection.contract != self.contract:
            raise ValueError("an item's projection must come from its own contract's projector")
        return self


class StrategyInvocation(JudgeModel):
    """One adaptor invocation of one LLM strategy, items in B6 declared order."""

    adaptor_id: Identifier
    iteration: int = Field(gt=0)
    strategy: LLMStrategy
    items: tuple[StrategyItem, ...] = Field(min_length=1)
    output_contract: str = Field(min_length=1)
    expected_count: CardinalityBound
    rubric: RubricSpec | None = None  # resolved from strategy.rubric; required iff rubric-rank
    task_guidance: JudgeTaskBlocks | None = None  # required iff strategy.guidance == "task_blocks"
    evidence_dir: Path  # B6-assigned, write-once; not part of the hashed identity

    @model_validator(mode="after")
    def coherent(self) -> Self:
        ids = [item.item_id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("invocation items must be distinct adaptor inputs")
        if len({item.contract for item in self.items}) != 1:
            raise ValueError("invocation items must share one input contract")
        expects_rubric = isinstance(self.strategy, RubricRankStrategy)
        if expects_rubric != (self.rubric is not None):
            raise ValueError("a resolved rubric is supplied iff the strategy is rubric-rank/v1")
        if isinstance(self.strategy, RubricRankStrategy):
            assert self.rubric is not None
            if rubric_ref(self.rubric) != self.strategy.rubric:
                raise ValueError("the supplied rubric is not the one the strategy references")
        if (self.strategy.guidance == "task_blocks") != (self.task_guidance is not None):
            raise ValueError("task guidance is supplied iff the strategy declares task_blocks")
        return self

    @property
    def task_guidance_sha256(self) -> str | None:
        return None if self.task_guidance is None else judge_guidance_sha256(self.task_guidance)


def invocation_sha256(invocation: StrategyInvocation) -> str:
    """Host-independent identity of an invocation (``evidence_dir`` excluded)."""
    return canonical_sha256(invocation.model_dump(mode="json", exclude={"evidence_dir"}))


class CriterionValue(JudgeModel):
    criterion: str = Field(min_length=1)
    value: float = Field(allow_inf_nan=False)  # median of the repeats' integers


class RubricScore(JudgeModel):
    """A rubric score: never a metric, never ranked by ``MetricOrder``."""

    rubric: RubricRef
    item_id: str = Field(min_length=1)
    per_criterion: tuple[CriterionValue, ...] = Field(min_length=1)
    # Σ(weight × median) / Σ weight, computed by framework code; lies on the rubric
    # scale [scale_min, scale_max], which threshold/v1 (basis rubric) reads.
    weighted_mean: float = Field(allow_inf_nan=False)


class ItemRanking(JudgeModel):
    """Every invocation item, best first; ``scores`` aligned with ``order``."""

    order: tuple[str, ...] = Field(min_length=1)
    scores: tuple[RubricScore, ...]

    @model_validator(mode="after")
    def aligned(self) -> Self:
        if len(set(self.order)) != len(self.order):
            raise ValueError("a ranking lists each item once")
        if tuple(score.item_id for score in self.scores) != self.order:
            raise ValueError("rubric scores must align with the ranking order")
        return self


class CombinedItem(JudgeModel):
    """One value a combining kind produced: validated, framework-stamped, with its parents."""

    output_index: int = Field(ge=0)
    parents: tuple[str, ...] = Field(min_length=1)  # invocation item ids
    value: dict[str, JsonValue]  # JSON form of a native value of the output contract
    value_sha256: Digest

    @model_validator(mode="after")
    def digest_matches(self) -> Self:
        if self.value_sha256 != canonical_sha256(self.value):
            raise ValueError("value_sha256 does not match the combined value")
        return self


class CombinedItems(JudgeModel):
    """Every value of a combining kind, in output order; B6 SELECTs them with ``all/v1``."""

    contract: str = Field(min_length=1)
    items: tuple[CombinedItem, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def indexed(self) -> Self:
        if [item.output_index for item in self.items] != list(range(len(self.items))):
            raise ValueError("combined items are indexed 0..k-1 in output order")
        return self


# Strategy-level failures (no single call failed). Pre-call: too few admissible items
# to run the kind, or a declared primary item that is not admissible. After a decided
# chain: an output count that differs from the declared one.
StrategyFailureCode = Literal["insufficient_items", "primary_unavailable", "cardinality_mismatch"]
PRECALL_FAILURES: frozenset[str] = frozenset({"insufficient_items", "primary_unavailable"})


class StrategyOutcome(JudgeModel):
    """The decision one invocation produced; re-derived exactly on replay."""

    status: Literal["decided", "fallback", "failed"]
    ranking: ItemRanking | None
    # Omitted when absent, so ranking-kind evidence bytes do not carry the field.
    combined: CombinedItems | None = Field(default=None, exclude_if=lambda value: value is None)
    failure_code: FailureCode | StrategyFailureCode | None
    fallback_combine: str | None  # Fallback.combine kind B6 must run, iff status == "fallback"

    @model_validator(mode="after")
    def coherent(self) -> Self:
        decided = self.status == "decided"
        produced = (self.ranking is not None) + (self.combined is not None)
        if (produced == 1) != decided or produced > 1 or decided == (self.failure_code is not None):
            raise ValueError(
                "a ranking or combined items are recorded exactly when decided; "
                "a failure code otherwise"
            )
        if (self.status == "fallback") != (self.fallback_combine is not None):
            raise ValueError("a fallback combine is named exactly when the status is fallback")
        return self


class StrategyEvidence(JudgeModel):
    """One write-once record per invocation, anchoring every call in order."""

    schema_version: Literal["siderius.judge-strategy/v1"] = "siderius.judge-strategy/v1"
    invocation_sha256: Digest
    strategy_kind: str = Field(min_length=1)
    static_call_bound: int = Field(gt=0)
    calls: tuple[Digest, ...]
    outcome: StrategyOutcome

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if len(self.calls) > self.static_call_bound:
            raise ValueError("recorded calls exceed the static call bound")
        if (not self.calls) != (self.outcome.failure_code in PRECALL_FAILURES):
            raise ValueError("an invocation makes no call exactly when it fails before any call")
        return self


class StrategyResult(JudgeModel):
    """What B6 consumes: the outcome plus the digest of its anchoring evidence file."""

    outcome: StrategyOutcome
    evidence_sha256: Digest


StrategyRefusalCode = Literal[
    "kind_not_implemented",
    "unbounded_port",
    "mixed_contracts",
    "unprojectable_contract",
    "output_contract_mismatch",
    "select_incompatible",
    "metric_scored_reorder",
    "call_bound_exceeds_max_calls",
    "insufficient_capacity",
    "output_not_emittable",
    "cardinality_mismatch",
    "primary_rule_unavailable",
    "primary_item_undeclared",
]


class StrategyRefusal(JudgeModel):
    code: StrategyRefusalCode
    message: str = Field(min_length=1)


class StrategyAdmission(JudgeModel):
    """Static admission of one declared LLM strategy; admitted iff ``refusals`` is empty."""

    static_call_bound: int | None = Field(gt=0)
    required_route_slot: Literal["aggregate", "debate"]
    refusals: tuple[StrategyRefusal, ...] = ()

    @property
    def admitted(self) -> bool:
        return not self.refusals
