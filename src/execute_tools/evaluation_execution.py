"""Explicit run-local execution of a complete candidate evaluation.

The deployment owns transport, artifact export, authorization and cancellation.
This interface grants no data access. A bound executor never falls back to local
inference or private-data reads after failure. No binding keeps native execution.
"""

import math
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool, model_validator

from agent.schemas.model_io_contract import ModelIOContract
from execute_tools.evaluation_metric import (
    MetricResult,
    MetricSpec,
    NotScoreableError,
    NotScoreableResult,
)
from execute_tools.health_checks.schemas import CandidateHealthValidity, PersistedHealthGateResult


class CandidateEvaluationRequest(BaseModel):
    """Public execution inputs for one trained candidate, not caller authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    run_name: str
    exp_id: str
    model_type: str
    workspace: str
    models_dir: str
    model_configuration: dict[str, JsonValue]
    training_configuration: dict[str, JsonValue]
    loss_configuration: dict[str, JsonValue] | None = None
    model_io: ModelIOContract | None = None
    requested_scope: dict[str, JsonValue]
    metric: MetricSpec
    secondary_metrics: tuple[MetricSpec, ...] = ()
    is_trial: StrictBool


class CandidateEvaluationResult(BaseModel):
    """Facts returned by the evaluator; scope is what it ACTUALLY evaluated.

    The original receipt remains external evidence. The record carries its
    location and exact candidate identity beside the requested and actual scope.
    Combined runtime includes export/transport/inference/scoring/Health; callers
    must not describe it as separately measured inference or metric kernel time.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    run_name: str
    exp_id: str
    model_type: str
    candidate_digest: str = Field(min_length=1)
    receipt_path: str = Field(min_length=1)
    requested_scope: dict[str, JsonValue]
    evaluated_scope: dict[str, JsonValue] = Field(min_length=1)
    timing_accounting: Literal["combined_under_scoring_time_s"] = "combined_under_scoring_time_s"
    metric: MetricResult | NotScoreableResult
    health_status: CandidateHealthValidity
    health_gate_results: tuple[PersistedHealthGateResult, ...]
    health_config_digest: str = Field(min_length=1)
    eligible_for_selection: StrictBool
    failure_reason: str | None = None
    secondary_results: tuple[MetricResult, ...] = ()
    secondary_refusals: tuple[NotScoreableResult, ...] = ()
    secondary_errors: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def eligible_result_has_scoring_and_health_evidence(self) -> Self:
        if self.eligible_for_selection and (
            not isinstance(self.metric, MetricResult)
            or self.metric.scalar is None
            or not math.isfinite(self.metric.scalar)
            or self.health_status is not CandidateHealthValidity.VALID
        ):
            raise ValueError("eligible evaluation lacks finite score or valid Health evidence")
        if not self.eligible_for_selection and not self.failure_reason:
            raise ValueError("ineligible evaluation must preserve its refusal reason")
        return self


class CandidateEvaluationRefused(NotScoreableError):
    """A scientific refusal with the complete evaluator receipt retained."""

    def __init__(self, evaluation: CandidateEvaluationResult):
        if not isinstance(evaluation.metric, NotScoreableResult):
            raise TypeError("evaluation refusal requires a not-scoreable metric outcome")
        super().__init__(evaluation.metric)
        self.evaluation = evaluation


class CandidateEvaluationExecutor(Protocol):
    def evaluate(self, request: CandidateEvaluationRequest) -> CandidateEvaluationResult:
        """Evaluate the candidate; transport failure raises, scientific refusal returns."""
        ...


_ACTIVE: ContextVar[CandidateEvaluationExecutor | None] = ContextVar(
    "siderius_candidate_evaluation", default=None
)


@contextmanager
def bind_candidate_evaluation(executor: CandidateEvaluationExecutor) -> Iterator[None]:
    """Bind explicitly in the process that runs the native node; nesting restores."""
    if not callable(getattr(executor, "evaluate", None)):
        raise TypeError("candidate evaluator must implement evaluate")
    token = _ACTIVE.set(executor)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def candidate_evaluation_executor() -> CandidateEvaluationExecutor | None:
    return _ACTIVE.get()


def execute_candidate_evaluation(
    executor: CandidateEvaluationExecutor, request: CandidateEvaluationRequest
) -> CandidateEvaluationResult:
    """Validate cross-boundary identity before native policy consumes feedback."""
    result = executor.evaluate(request)
    if not isinstance(result, CandidateEvaluationResult):
        raise TypeError("candidate evaluator must return a validated result")
    if (result.run_name, result.exp_id, result.model_type, result.requested_scope) != (
        request.run_name,
        request.exp_id,
        request.model_type,
        request.requested_scope,
    ):
        raise ValueError("evaluation belongs to another attempt or request scope")
    if (result.metric.metric_id, result.metric.direction) != (
        request.metric.id,
        request.metric.direction,
    ):
        raise ValueError("evaluation metric differs from the bound task declaration")
    declared = {metric.id: metric.direction for metric in request.secondary_metrics}
    outcomes = [*result.secondary_results, *result.secondary_refusals]
    reported = [item.metric_id for item in outcomes] + list(result.secondary_errors)
    if len(reported) != len(set(reported)) or set(reported) != set(declared):
        raise ValueError("evaluation omitted or duplicated declared secondary outcomes")
    if any(declared[item.metric_id] != item.direction for item in outcomes):
        raise ValueError("secondary metric direction differs from its declaration")
    return result
