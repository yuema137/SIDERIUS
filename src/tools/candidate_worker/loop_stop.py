"""Stateless stop-condition contract for the authored finite loop.

The decision is a pure function of an explicit typed input: verified per-body
scores, the declared conditions and the reconciled run metric. It never reads or
mutates native history (``ChainState``) and never calls a provider: a declared
``JudgeStop`` enters as a recorded verdict (``StopEvaluationInput.judge_verdict``),
produced by ``loop_judge`` only when ``needs_stop_judge`` says the boundary is judged.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from execute_tools.evaluation_metric import (
    MetricDirection,
    MetricSpec,
    StampedMetricSpec,
    reconcile_metric_specs,
)
from execute_tools.metric_order import MetricOrder
from workflows.definition.models import (
    AuthoredLoop,
    JudgeStop,
    MetricThresholdStop,
    NoImprovementStop,
    StopAction,
    StopCondition,
)

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

if TYPE_CHECKING:
    from .models import CandidateRunReceipt, CandidateRunRequest


class StopConditionError(ValueError):
    """A declared condition cannot be evaluated; the loop fails rather than ignore it."""


class JudgeStopError(StopConditionError):
    """A declared ``on_failure="fail"`` judge produced no decision; the loop fails."""


class StopModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BodyScore(StopModel):
    """Projection of one verified completed body; immutable, never native history."""

    iteration: int = Field(gt=0)
    valid_formal: float | None = Field(allow_inf_nan=False)
    metric_spec: MetricSpec | None


class MetricThresholdReason(StopModel):
    kind: Literal["metric_threshold"] = "metric_threshold"
    condition_index: int = Field(ge=0)
    iteration: int = Field(gt=0)
    metric_id: str
    direction: MetricDirection
    threshold: float = Field(allow_inf_nan=False)
    incumbent: float = Field(allow_inf_nan=False)
    incumbent_iteration: int = Field(gt=0)


class NoImprovementReason(StopModel):
    kind: Literal["no_improvement"] = "no_improvement"
    condition_index: int = Field(ge=0)
    iteration: int = Field(gt=0)
    k: int = Field(gt=0)
    non_improving_bodies: int = Field(gt=0)
    last_improvement_iteration: int | None
    incumbent: float | None = Field(allow_inf_nan=False)


class JudgeStopReason(StopModel):
    """Points at the recorded judge evidence; the rationale stays in that record."""

    kind: Literal["judge"] = "judge"
    condition_index: int = Field(ge=0)
    iteration: int = Field(gt=0)
    evidence_path: str = Field(min_length=1)  # relative to the run workspace
    evidence_sha256: Digest
    request_sha256: Digest


StopReason = Annotated[
    MetricThresholdReason | NoImprovementReason | JudgeStopReason, Field(discriminator="kind")
]


class JudgeBoundaryVerdict(StopModel):
    """The verified outcome of one boundary's judge call; ``None`` is a recorded abstention."""

    iteration: int = Field(gt=0)
    decision: Literal["stop", "continue"] | None
    evidence_path: str = Field(min_length=1)
    evidence_sha256: Digest
    request_sha256: Digest


class IncumbentFold(StopModel):
    """The deterministic incumbent over completed bodies: strictly better, first wins."""

    incumbent: float | None = Field(allow_inf_nan=False)
    incumbent_iteration: int | None
    non_improving: int = Field(ge=0)


class StopEvaluationInput(StopModel):
    iteration: int = Field(gt=0)
    final_iteration: int = Field(gt=0)
    conditions: tuple[StopCondition, ...]
    bodies: tuple[BodyScore, ...]
    metric: MetricSpec | None
    # The judged boundary's verdict; only a boundary ``needs_stop_judge`` names has one.
    judge_verdict: JudgeBoundaryVerdict | None = None
    # Last earlier boundary where a ``request_input`` condition paused the loop (0 = none).
    # Only ``request_input`` conditions read it; ``stop`` conditions count the whole run.
    # Derived by replay at every boundary, never persisted.
    input_anchor: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def contiguous(self) -> Self:
        if tuple(body.iteration for body in self.bodies) != tuple(range(1, self.iteration + 1)):
            raise ValueError("stop evaluation requires every completed body 1..iteration")
        if self.judge_verdict is not None and self.judge_verdict.iteration != self.iteration:
            raise ValueError("a judge verdict belongs to the boundary it was recorded at")
        if self.input_anchor >= self.iteration:
            raise ValueError("the input anchor must be an earlier boundary")
        return self


class StopEvaluationOutput(StopModel):
    """``stop`` completes the loop; ``request_input`` pauses it and asks the operator."""

    decision: Literal["continue", "stop", "request_input"]
    reason: StopReason | None = None

    @model_validator(mode="after")
    def reason_iff_decided(self) -> Self:
        if (self.decision != "continue") != (self.reason is not None):
            raise ValueError("a stop or input-request decision requires exactly one reason")
        return self


class InputRequestSummary(StopModel):
    """Bounded deterministic facts shown when a condition pauses the loop for input."""

    iteration: int = Field(gt=0)
    final_iteration: int = Field(gt=0)
    metric_id: str = Field(min_length=1)
    direction: MetricDirection
    incumbent: float | None = Field(allow_inf_nan=False)
    incumbent_iteration: int | None = Field(gt=0)
    non_improving_bodies: int = Field(ge=0)
    input_anchor: int = Field(ge=0)  # previous input pause boundary; 0 = none
    bodies_since_input: int = Field(gt=0)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if (
            self.iteration >= self.final_iteration
            or self.bodies_since_input != self.iteration - self.input_anchor
            or (self.incumbent is None) != (self.incumbent_iteration is None)
        ):
            raise ValueError("input request summary is incoherent")
        return self


class LoopInputRequest(StopModel):
    """A met ``request_input`` condition paused the loop at ``reason.iteration``."""

    reason: StopReason
    summary: InputRequestSummary

    @model_validator(mode="after")
    def same_boundary(self) -> Self:
        if self.reason.iteration != self.summary.iteration:
            raise ValueError("input request reason and summary name different boundaries")
        return self


def incumbent_fold(bodies: tuple[BodyScore, ...], order: MetricOrder) -> IncumbentFold:
    """The one incumbent fold every stop decision and judge request reads."""
    incumbent: float | None = None
    incumbent_iteration: int | None = None
    non_improving = 0
    for body in bodies:
        score = body.valid_formal
        if score is not None and (incumbent is None or order.is_better(score, incumbent)):
            incumbent, incumbent_iteration, non_improving = score, body.iteration, 0
        else:
            non_improving += 1
    return IncumbentFold(
        incumbent=incumbent, incumbent_iteration=incumbent_iteration, non_improving=non_improving
    )


def _threshold_met(
    bodies: tuple[BodyScore, ...], order: MetricOrder, condition: MetricThresholdStop
) -> bool:
    incumbent = incumbent_fold(bodies, order).incumbent
    return incumbent is not None and order.is_at_least(incumbent, condition.threshold)


def _deterministic_reason(
    value: StopEvaluationInput, metric: MetricSpec, action: StopAction
) -> MetricThresholdReason | NoImprovementReason | None:
    """First met deterministic condition of ``action`` in declared order; a judge is skipped.

    A ``request_input`` condition counts from ``input_anchor``: ``no_improvement`` needs
    ``k`` bodies since the last input pause, and ``metric_threshold`` fires once, at the
    boundary where the incumbent first reaches it after that pause.
    """
    order = MetricOrder(metric)
    fold = incumbent_fold(value.bodies, order)
    incumbent, incumbent_iteration = fold.incumbent, fold.incumbent_iteration
    anchored = action == "request_input"
    for index, condition in enumerate(value.conditions):
        if condition.on_met != action:
            continue
        match condition:
            case MetricThresholdStop():
                if _threshold_met(value.bodies, order, condition) and not (
                    anchored
                    and _threshold_met(value.bodies[: value.input_anchor], order, condition)
                ):
                    assert incumbent is not None and incumbent_iteration is not None
                    assert incumbent_iteration is not None
                    return MetricThresholdReason(
                        condition_index=index,
                        iteration=value.iteration,
                        metric_id=metric.id,
                        direction=order.direction,
                        threshold=condition.threshold,
                        incumbent=incumbent,
                        incumbent_iteration=incumbent_iteration,
                    )
            case NoImprovementStop():
                counted = (
                    min(fold.non_improving, value.iteration - value.input_anchor)
                    if anchored
                    else fold.non_improving
                )
                if counted >= condition.completed_bodies:
                    return NoImprovementReason(
                        condition_index=index,
                        iteration=value.iteration,
                        k=condition.completed_bodies,
                        non_improving_bodies=fold.non_improving,
                        last_improvement_iteration=incumbent_iteration,
                        incumbent=incumbent,
                    )
            case JudgeStop():
                continue  # Structurally after every deterministic condition (Q-B2-6).
            case _:
                raise StopConditionError(f"stop condition {index} ({condition.kind}) unsupported")
    return None


def _decide(value: StopEvaluationInput) -> StopEvaluationOutput | tuple[int, JudgeStop]:
    """A decision, or the judge condition this boundary must consult before deciding.

    Precedence: met ``stop`` deterministic conditions, then met ``request_input``
    deterministic conditions (each in declared order), then the judge.
    """
    if value.iteration >= value.final_iteration or not value.conditions:
        # The final limit owns its boundary: completion there carries no stop reason.
        return StopEvaluationOutput(decision="continue")
    if value.metric is None:
        raise StopConditionError(
            f"stop condition 0 ({value.conditions[0].kind}) requires a run metric; none is bound"
        )
    require_threshold_metrics(value.conditions, value.metric)
    for action in ("stop", "request_input"):
        reason = _deterministic_reason(value, value.metric, action)
        if reason is not None:
            return StopEvaluationOutput(decision=action, reason=reason)
    judged = pending_judge(value.conditions)
    if judged is None or not _judge_eligible(value, judged[1]):
        return StopEvaluationOutput(decision="continue")
    return judged


def _judge_eligible(value: StopEvaluationInput, judge: JudgeStop) -> bool:
    """A ``request_input`` judge counts its minimum from the last input pause."""
    start = value.input_anchor if judge.on_met == "request_input" else 0
    return value.iteration - start >= judge.min_completed_bodies


def pending_judge(conditions: tuple[StopCondition, ...]) -> tuple[int, JudgeStop] | None:
    """The declared judge condition and its index (validation admits at most one)."""
    return next(
        ((index, item) for index, item in enumerate(conditions) if isinstance(item, JudgeStop)),
        None,
    )


def judge_call_bound(loop: AuthoredLoop) -> int:
    """Static per-run JudgeStop call bound: one call per judgeable boundary, else 0."""
    judged = pending_judge(loop.stop_conditions)
    return 0 if judged is None else loop.final_iteration - judged[1].min_completed_bodies


def skipped_stop_judge(value: StopEvaluationInput) -> tuple[int, int] | None:
    """``(judge index, deciding condition index)`` when a deterministic stop pre-empted a
    boundary the judge would otherwise have been consulted at; else ``None``.
    """
    judged = pending_judge(value.conditions)
    if judged is None or not _judge_eligible(value, judged[1]):
        return None
    decided = _decide(value)
    if not isinstance(decided, StopEvaluationOutput) or decided.reason is None:
        return None
    return judged[0], decided.reason.condition_index


def needs_stop_judge(value: StopEvaluationInput) -> bool:
    """Whether this boundary is judged: the worker calls iff true; readback requires evidence iff true.

    True only below the final boundary, at or after ``min_completed_bodies``, and when no
    deterministic condition fired. A supplied verdict is ignored here.
    """
    return not isinstance(_decide(value), StopEvaluationOutput)


def evaluate_stop(value: StopEvaluationInput) -> StopEvaluationOutput:
    """Pure decision at one completed-body boundary.

    Deterministic conditions decide first (``stop`` before ``request_input``, each in
    declared order); a declared judge decides only when none fired, from the boundary's
    recorded verdict (an abstention continues). A judge "stop" verdict takes its
    condition's ``on_met`` action.
    """
    decided = _decide(value)
    if isinstance(decided, StopEvaluationOutput):
        return decided
    index, judge = decided
    verdict = value.judge_verdict
    if verdict is None:
        raise StopConditionError(
            f"stop condition {index} (judge) has no recorded verdict for body {value.iteration}"
        )
    if verdict.decision != "stop":
        return StopEvaluationOutput(decision="continue")
    reason = JudgeStopReason(
        condition_index=index,
        iteration=value.iteration,
        evidence_path=verdict.evidence_path,
        evidence_sha256=verdict.evidence_sha256,
        request_sha256=verdict.request_sha256,
    )
    return StopEvaluationOutput(decision=judge.on_met, reason=reason)


def input_summary(value: StopEvaluationInput) -> InputRequestSummary:
    """The deterministic facts shown with an input request at this boundary (O(1) size)."""
    assert value.metric is not None
    order = MetricOrder(value.metric)
    fold = incumbent_fold(value.bodies, order)
    return InputRequestSummary(
        iteration=value.iteration,
        final_iteration=value.final_iteration,
        metric_id=value.metric.id,
        direction=order.direction,
        incumbent=fold.incumbent,
        incumbent_iteration=fold.incumbent_iteration,
        non_improving_bodies=fold.non_improving,
        input_anchor=value.input_anchor,
        bodies_since_input=value.iteration - value.input_anchor,
    )


def input_request(
    value: StopEvaluationInput, output: StopEvaluationOutput
) -> LoopInputRequest | None:
    """The recorded input request for a ``request_input`` decision, else ``None``."""
    if output.decision != "request_input":
        return None
    assert output.reason is not None
    return LoopInputRequest(reason=output.reason, summary=input_summary(value))


def require_threshold_metrics(conditions: tuple[StopCondition, ...], metric: MetricSpec) -> None:
    """The one identity check: every ``metric_threshold`` must name the run metric.

    Checked over ALL conditions, so an earlier met condition cannot hide a mismatch.
    """
    for index, condition in enumerate(conditions):
        if isinstance(condition, MetricThresholdStop) and condition.metric_id != metric.id:
            raise StopConditionError(
                f"stop condition {index} (metric_threshold) names metric "
                f"{condition.metric_id!r}; the run metric is {metric.id!r}"
            )


def reconcile_stop_metric(
    seed_metric: MetricSpec | None, stamped: list[StampedMetricSpec]
) -> MetricSpec | None:
    """The run metric the evaluator ranks by: the captured seed reconciled with stamps."""
    return reconcile_metric_specs(
        stamped, bound=seed_metric, bound_label="the loop's captured interpretation seed"
    )


def admit_stop_conditions(
    loop: AuthoredLoop, seed_metric: MetricSpec | None, composed_metric: MetricSpec
) -> None:
    """Refuse an unevaluable declaration before any body is dispatched.

    Every body's tuning record stamps the composed run metric, so reconciling the seed
    with that spec yields exactly the identity ``evaluate_stop`` will later rank by.
    """
    if not loop.stop_conditions:
        return
    metric = reconcile_stop_metric(
        seed_metric,
        [StampedMetricSpec(label="the run's bound task composition", spec=composed_metric)],
    )
    assert metric is not None
    require_threshold_metrics(loop.stop_conditions, metric)


def stop_input(
    loop: AuthoredLoop,
    seed_metric: MetricSpec | None,
    bodies: tuple[BodyScore, ...],
    *,
    input_anchor: int = 0,
) -> StopEvaluationInput:
    """Build the evaluator input; the metric is reconciled once over seed and body stamps."""
    metric = reconcile_stop_metric(
        seed_metric,
        [
            StampedMetricSpec(label=f"loop body {body.iteration}", spec=body.metric_spec)
            for body in bodies
            if body.metric_spec is not None
        ],
    )
    return StopEvaluationInput(
        iteration=len(bodies),
        final_iteration=loop.final_iteration,
        conditions=loop.stop_conditions,
        bodies=bodies,
        metric=metric,
        input_anchor=input_anchor,
    )


def captured_metric(
    request: "CandidateRunRequest", initial: "CandidateRunReceipt"
) -> MetricSpec | None:
    """The metric explicitly declared by the captured interpretation seed, if any."""
    from agent.schemas.interpretation import InterpretationInput
    from workflows.definition.fanout import execution_families

    from .fanout_inputs import captured_contents

    edge = execution_families(
        request.preview.document.definition, request.preview.execution_profile
    ).interpretation
    assert edge is not None
    contents = captured_contents(request, Path(initial.workspace), iteration=1)
    return InterpretationInput.model_validate_json(
        contents[f"external.{edge.input_binding}"]
    ).metric_spec


def project_body_score(
    request: "CandidateRunRequest", body: "CandidateRunReceipt", iteration: int
) -> BodyScore:
    """Map one verified completed body's tuning record to its immutable score."""
    # Lazy: the parent import must not discover native plugins before child binding.
    from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
    from workflows.definition.fanout import execution_families

    tuning = execution_families(
        request.preview.document.definition, request.preview.execution_profile
    ).tuning
    assert tuning is not None and body.graph_trace is not None and body.status == "completed"
    path = next(item for item in body.graph_trace.nodes if item.node_id == tuning).record_path
    assert path is not None
    output = HyperparamTuningOutput.model_validate_json(Path(path).read_bytes())
    return BodyScore(
        iteration=iteration,
        valid_formal=output.best_valid_formal_denoising_score,
        metric_spec=output.metric_spec,
    )
