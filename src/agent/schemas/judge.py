"""Typed records for one LLM judge call: request, validated verdict, evidence.

The judge consumes facts the deterministic core already produced (metric ranks,
values, direction words, Health class); it never scores. Every call is
recorded as write-once :class:`JudgeCallEvidence`, and readback re-derives the
outcome from that record without calling a provider (see
``agent/judge/judge-contract.md``).
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.schemas.data_analysis.common import canonical_sha256

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
CallRole = Literal["advocate", "critic", "judge", "scorer", "advisor", "reviser", "merger", "stop"]
HealthClass = Literal["valid", "invalid", "unknown"]


class JudgeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


class DirectionWords(JudgeModel):
    """``MetricOrder.direction_words()`` carried as data; never re-derived here."""

    verb: Literal["maximize", "minimize"]
    comparative: Literal["higher", "lower"]
    antonym: Literal["higher", "lower"]

    @model_validator(mode="after")
    def coherent(self) -> Self:
        expected = "higher" if self.verb == "maximize" else "lower"
        if self.comparative != expected or self.antonym == self.comparative:
            raise ValueError("direction words must come from one MetricOrder")
        return self


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
        if (self.incumbent is None) != (self.incumbent_iteration is None):
            raise ValueError("incumbent value and iteration are set together")
        if len(self.interpretation_digests) != len(self.interpretation_excerpts):
            raise ValueError("each interpretation excerpt needs its digest")
        return self


class CallRequest(JudgeModel):
    """Hashed identity of one call; no timestamps or host facts."""

    invocation_sha256: Digest | None
    call_role: CallRole
    call_index: int = Field(ge=0)
    prior_turns: tuple[Digest, ...]
    stop: StopJudgeRequest | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if len(self.prior_turns) != self.call_index:
            raise ValueError("prior_turns must cover every earlier call of the chain")
        if (self.call_role == "stop") != (self.stop is not None):
            raise ValueError("a stop request is carried exactly by call_role 'stop'")
        if self.call_role == "stop" and self.invocation_sha256 is not None:
            raise ValueError("a stop call belongs to no strategy invocation")
        if self.call_role != "stop" and self.invocation_sha256 is None:
            raise ValueError("a strategy call names its invocation")
        return self


class StopVerdict(JudgeModel):
    kind: Literal["stop_decision"]
    decision: Literal["stop", "continue"]
    rationale: str = Field(min_length=1, max_length=2000)
    confidence: Literal["low", "medium", "high"]


# Strategy payload kinds join this as a discriminated union in their own PRs.
CallPayload = StopVerdict


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
