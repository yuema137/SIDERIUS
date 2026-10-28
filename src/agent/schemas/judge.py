"""Typed records for one LLM judge call: request, validated verdict, evidence.

The judge consumes facts the deterministic core already produced (metric ranks,
values, direction words, Health class); it never scores. Every call is
recorded as write-once :class:`JudgeCallEvidence`, and readback re-derives the
outcome from that record without calling a provider (see
``agent/judge/judge-contract.md``).
"""

from __future__ import annotations

from typing import Annotated, Literal, Self, get_args

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from agent.schemas.data_analysis.common import canonical_sha256
from agent.schemas.judge_task import JudgeTaskBlocks, RubricSpec
from execute_tools.evaluation_metric import MetricDirection, MetricIdentityKey
from execute_tools.metric_order import MetricOrder

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
CallRole = Literal["advocate", "critic", "judge", "scorer", "advisor", "reviser", "merger", "stop"]
HealthClass = Literal["valid", "invalid", "unknown"]


class JudgeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


class DirectionWords(JudgeModel):
    """``MetricOrder.direction_words`` carried as data; never re-derived here."""

    verb: Literal["maximize", "minimize"]
    comparative: MetricDirection
    antonym: MetricDirection

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.model_dump() not in _ORDER_WORDS:
            raise ValueError("direction words must come from one MetricOrder")
        return self


# Every word set the direction owner can produce; the owner, not this module,
# maps a direction to words.
_ORDER_WORDS = tuple(
    MetricOrder(MetricIdentityKey(id="direction-words", direction=direction)).direction_words
    for direction in get_args(MetricDirection)
)


class JudgeBodyFacts(JudgeModel):
    """One completed body as the judge sees it: rank, value and Health, separately."""

    iteration: int = Field(gt=0)
    value: float | None
    rank: int | None = Field(ge=1)
    health: HealthClass

    @model_validator(mode="after")
    def health_gates_value(self) -> Self:
        if (self.value is None) != (self.rank is None):
            raise ValueError("a body has a rank exactly when it has a value")
        if self.value is not None and self.health != "valid":
            raise ValueError("only a Health-valid body may present a metric value")
        return self


class StopJudgeRequest(JudgeModel):
    kind: Literal["stop"] = "stop"
    condition_index: int = Field(ge=0)
    iteration: int = Field(gt=0)
    final_iteration: int = Field(gt=0)
    bodies: tuple[JudgeBodyFacts, ...] = Field(min_length=1)
    incumbent: float | None
    incumbent_iteration: int | None = Field(gt=0)
    non_improving_bodies: int = Field(ge=0)
    metric_id: str = Field(min_length=1)
    direction_words: DirectionWords
    interpretation_digests: tuple[Digest, ...]
    interpretation_excerpts: tuple[Annotated[str, Field(max_length=2000)], ...]
    criterion: str = Field(min_length=1, max_length=2000)
    task_guidance_sha256: Digest | None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.iteration >= self.final_iteration:
            raise ValueError("the final boundary is never judged")
        iterations = [body.iteration for body in self.bodies]
        if iterations != sorted(set(iterations)) or iterations[-1] != self.iteration:
            raise ValueError("bodies must be increasing and end at the judged iteration")
        if self.non_improving_bodies > len(self.bodies):
            raise ValueError("non_improving_bodies cannot exceed the completed bodies")
        self._require_ranked_incumbent()
        if len(self.interpretation_digests) != len(self.interpretation_excerpts):
            raise ValueError("each interpretation excerpt needs its digest")
        if len(self.interpretation_excerpts) > len(self.bodies):
            raise ValueError("at most one interpretation excerpt per completed body")
        return self

    def _require_ranked_incumbent(self) -> None:
        if (self.incumbent is None) != (self.incumbent_iteration is None):
            raise ValueError("incumbent value and iteration are set together")
        ranked = [body for body in self.bodies if body.rank is not None]
        if self.incumbent is None:
            if ranked:
                raise ValueError("ranked bodies require an incumbent")
            return
        if not any(
            body.iteration == self.incumbent_iteration
            and body.rank == 1
            and body.value == self.incumbent
            for body in ranked
        ):
            raise ValueError("the incumbent must be a rank-1 body with the same value")


#: Deterministic projection bounds: one item never dominates a prompt.
MAX_PROJECTED_FIELDS = 64
MAX_PROJECTED_CHARS = 4000
#: Items any one judge call may list (rubric batch scoring, merge, revision, debate),
#: so every prompt that lists all items has a fixed size bound.
MAX_SCORED_ITEMS_PER_CALL = 16


class ProjectedField(JudgeModel):
    name: str = Field(min_length=1, max_length=100)
    text: str = Field(max_length=MAX_PROJECTED_CHARS)


class ItemProjection(JudgeModel):
    """Bounded, deterministic view of one verified value, built by its contract's projector."""

    contract: str = Field(min_length=1)
    fields: tuple[ProjectedField, ...] = Field(min_length=1, max_length=MAX_PROJECTED_FIELDS)


class JudgedItem(JudgeModel):
    """One admissible item as a judge sees it; ``item_id`` is the adaptor's ``<port>:<position>``."""

    item_id: str = Field(min_length=1)
    projection: ItemProjection


class RubricScoringRequest(JudgeModel):
    """One ``rubric-rank/v1`` scoring call: score ``items`` on every rubric criterion.

    ``repeat`` distinguishes the declared repeats of the same scoring call; it is
    hashed but not rendered.
    """

    kind: Literal["rubric_scoring"] = "rubric_scoring"
    rubric: RubricSpec
    criterion: str = Field(min_length=1, max_length=2000)
    repeat: int = Field(ge=0)
    items: tuple[JudgedItem, ...] = Field(min_length=1, max_length=MAX_SCORED_ITEMS_PER_CALL)
    guidance: JudgeTaskBlocks | None

    @model_validator(mode="after")
    def distinct_items(self) -> Self:
        ids = [item.item_id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("a scoring call lists each item once")
        return self


def _distinct_items(items: tuple[JudgedItem, ...]) -> None:
    ids = [item.item_id for item in items]
    if len(set(ids)) != len(ids):
        raise ValueError("a judge call lists each item once")


class MergeRequest(JudgeModel):
    """One ``judge-merge/v1`` call: synthesize ``synthesize_count`` new values from ``items``.

    ``output_contract`` names the catalogue contract every synthesized value must
    satisfy; each value cites at least ``min_parents`` distinct listed items.
    """

    kind: Literal["merge"] = "merge"
    criterion: str = Field(min_length=1, max_length=2000)
    output_contract: str = Field(min_length=1)
    synthesize_count: int = Field(ge=1)
    min_parents: int = Field(ge=2)
    items: tuple[JudgedItem, ...] = Field(min_length=2, max_length=MAX_SCORED_ITEMS_PER_CALL)
    guidance: JudgeTaskBlocks | None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _distinct_items(self.items)
        if self.min_parents > len(self.items):
            raise ValueError("min_parents cannot exceed the listed items")
        return self


# Role content kind -> the call roles that may carry it. Further strategy content
# kinds join the CallContent union and this table in their own changes.
class AdviceRequest(JudgeModel):
    """One ``primary-advisors-llm/v1`` advisor call: what ``advisor`` suggests for ``primary``."""

    kind: Literal["advice"] = "advice"
    criterion: str = Field(min_length=1, max_length=2000)
    output_contract: str = Field(min_length=1)
    primary: JudgedItem
    advisor: JudgedItem
    guidance: JudgeTaskBlocks | None

    @model_validator(mode="after")
    def distinct(self) -> Self:
        _distinct_items((self.primary, self.advisor))
        return self


class AdvisoryNote(JudgeModel):
    """An advisor call's verdict; also carried, verbatim, into the revision request."""

    kind: Literal["advice"]
    advisor_item: str = Field(min_length=1)
    suggestions: tuple[Annotated[str, Field(min_length=1, max_length=1000)], ...] = Field(
        min_length=1, max_length=12
    )


class RevisionRequest(JudgeModel):
    """The ``primary-advisors-llm/v1`` reviser call: revise ``primary`` using ``advisors``.

    ``notes`` is empty for ``advice="single_call"`` and holds one advisor call's note
    per advisor, in advisor order, for ``advice="per_advisor"``.
    """

    kind: Literal["revision"] = "revision"
    criterion: str = Field(min_length=1, max_length=2000)
    output_contract: str = Field(min_length=1)
    primary: JudgedItem
    advisors: tuple[JudgedItem, ...] = Field(min_length=1)
    notes: tuple[AdvisoryNote, ...]
    guidance: JudgeTaskBlocks | None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _distinct_items((self.primary, *self.advisors))
        noted = tuple(note.advisor_item for note in self.notes)
        if noted and noted != tuple(item.item_id for item in self.advisors):
            raise ValueError("revision notes are absent or one per advisor in advisor order")
        return self


CallContent = Annotated[
    StopJudgeRequest | RubricScoringRequest | MergeRequest | AdviceRequest | RevisionRequest,
    Field(discriminator="kind"),
]
_ROLES_BY_CONTENT: dict[str, frozenset[str]] = {
    "stop": frozenset({"stop"}),
    "rubric_scoring": frozenset({"scorer"}),
    "merge": frozenset({"merger"}),
    "advice": frozenset({"advisor"}),
    "revision": frozenset({"reviser"}),
}


class CallRequest(JudgeModel):
    """Hashed identity of one call; no timestamps or host facts."""

    invocation_sha256: Digest | None
    call_role: CallRole
    call_index: int = Field(ge=0)
    prior_turns: tuple[Digest, ...]
    content: CallContent

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if len(self.prior_turns) != self.call_index:
            raise ValueError("prior_turns must cover every earlier call of the chain")
        if self.call_role not in _ROLES_BY_CONTENT[self.content.kind]:
            raise ValueError(f"call_role {self.call_role!r} cannot carry {self.content.kind!r}")
        is_stop = self.content.kind == "stop"
        if is_stop and (self.invocation_sha256 is not None or self.call_index != 0):
            raise ValueError("a stop call is a single call outside any strategy invocation")
        if not is_stop and self.invocation_sha256 is None:
            raise ValueError("a strategy call names its invocation")
        return self


class StopVerdict(JudgeModel):
    kind: Literal["stop_decision"]
    decision: Literal["stop", "continue"]
    rationale: str = Field(min_length=1, max_length=2000)
    confidence: Literal["low", "medium", "high"]


class CriterionScore(JudgeModel):
    criterion: str = Field(min_length=1)
    score: int


class ItemCriterionScores(JudgeModel):
    item_id: str = Field(min_length=1)
    scores: tuple[CriterionScore, ...] = Field(min_length=1)


class RubricVerdict(JudgeModel):
    """Per-criterion integers only; the weighted mean is computed by framework code."""

    kind: Literal["rubric"]
    item_scores: tuple[ItemCriterionScores, ...] = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=2000)


class SynthesizedDraft(JudgeModel):
    """One synthesized value as the LLM wrote it, before contract validation and stamping.

    ``value`` is checked against the request's output contract by the consumer's
    ``check_payload``; ``parents`` are the listed item ids it draws on.
    """

    parents: tuple[str, ...] = Field(min_length=1)
    value: dict[str, JsonValue]


class SynthesisVerdict(JudgeModel):
    kind: Literal["synthesis"]
    items: tuple[SynthesizedDraft, ...] = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=2000)


# Further strategy payload kinds join this union in their own changes.
CallPayload = Annotated[
    StopVerdict | RubricVerdict | SynthesisVerdict | AdvisoryNote, Field(discriminator="kind")
]


class PromptIdentity(JudgeModel):
    template: str = Field(min_length=1)
    template_sha256: Digest
    prompt_sha256: Digest
    response_schema_sha256: Digest


class JudgeRoute(JudgeModel):
    """Resolved route; retries are finite and output is explicitly bounded."""

    provider: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    reasoning_effort: str | None
    max_output_tokens: int = Field(gt=0)
    max_retries: int = Field(ge=0)


class JudgeRoutes(JudgeModel):
    """The judge routes and run-level call cap one run resolved; the run lock compares them.

    Built from ``WorkflowLLMConfig.judge`` by ``workflows.llm_config.locked_judge_routes``;
    a recorded call's ``JudgeCallEvidence.route`` must equal its family's route, and a
    run's judge calls never exceed ``max_judge_calls`` (Q-B2-10).
    """

    stop: JudgeRoute | None = None
    aggregate: JudgeRoute | None = None
    debate: JudgeRoute | None = None
    max_judge_calls: int | None = Field(default=None, gt=0)


FailureCode = Literal["provider_error", "invalid_payload", "inadmissible_choice", "deadline"]


class JudgeCallEvidence(JudgeModel):
    """One write-once file per call; usage rows stay in ``token_usage.jsonl``."""

    schema_version: Literal["siderius.judge-call/v1"] = "siderius.judge-call/v1"
    request: CallRequest
    request_sha256: Digest
    prompt: PromptIdentity
    route: JudgeRoute
    status: Literal["decided", "failed", "timed_out"]
    payload: CallPayload | None
    failure_code: FailureCode | None
    failure_message: str | None = Field(max_length=2000)
    usage_label: str = Field(min_length=1)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.request_sha256 != canonical_sha256(self.request):
            raise ValueError("request_sha256 does not match the recorded request")
        if (self.status == "decided") != (self.payload is not None):
            raise ValueError("a payload is recorded exactly when the call decided")
        if (self.status == "decided") != (self.failure_code is None):
            raise ValueError("a failure code is recorded exactly when the call did not decide")
        if (self.status == "timed_out") != (self.failure_code == "deadline"):
            raise ValueError("timed_out is recorded exactly with failure code 'deadline'")
        if (self.failure_message is None) != (self.failure_code is None):
            raise ValueError("a failure message accompanies exactly a failure code")
        return self
