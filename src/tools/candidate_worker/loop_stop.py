"""Stateless stop-condition contract for the authored finite loop.

The decision is a pure function of an explicit typed input: verified per-body
scores, the declared conditions and the reconciled run metric. It never reads or
mutates native history (``ChainState``); a future judge implements the same
``StopEvaluationInput -> StopEvaluationOutput`` contract.
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
    MetricThresholdStop,
    NoImprovementStop,
    StopCondition,
)

if TYPE_CHECKING:
    from .models import CandidateRunReceipt, CandidateRunRequest


class StopConditionError(ValueError):
    """A declared condition cannot be evaluated; the loop fails rather than ignore it."""


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


StopReason = Annotated[MetricThresholdReason | NoImprovementReason, Field(discriminator="kind")]


class StopEvaluationInput(StopModel):
    iteration: int = Field(gt=0)
    final_iteration: int = Field(gt=0)
    conditions: tuple[StopCondition, ...]
    bodies: tuple[BodyScore, ...]
    metric: MetricSpec | None

    @model_validator(mode="after")
    def contiguous(self) -> Self:
        if tuple(body.iteration for body in self.bodies) != tuple(range(1, self.iteration + 1)):
            raise ValueError("stop evaluation requires every completed body 1..iteration")
        return self


class StopEvaluationOutput(StopModel):
    decision: Literal["continue", "stop"]
    reason: StopReason | None = None

    @model_validator(mode="after")
    def reason_iff_stop(self) -> Self:
        if (self.decision == "stop") != (self.reason is not None):
            raise ValueError("a stop decision requires exactly one reason")
        return self


def evaluate_stop(value: StopEvaluationInput) -> StopEvaluationOutput:
    """Pure decision at one completed-body boundary; first met condition in order wins."""
    if value.iteration >= value.final_iteration or not value.conditions:
        # The final limit owns its boundary: completion there carries no stop reason.
        return StopEvaluationOutput(decision="continue")
    if value.metric is None:
        raise StopConditionError(
            f"stop condition 0 ({value.conditions[0].kind}) requires a run metric; none is bound"
        )
    order = MetricOrder(value.metric)
    incumbent: float | None = None
    incumbent_iteration: int | None = None
    non_improving = 0
    for body in value.bodies:
        score = body.valid_formal
        if score is not None and (incumbent is None or order.is_better(score, incumbent)):
            incumbent, incumbent_iteration, non_improving = score, body.iteration, 0
        else:
            non_improving += 1
    for index, condition in enumerate(value.conditions):
        match condition:
            case MetricThresholdStop():
                if condition.metric_id != value.metric.id:
                    raise StopConditionError(
                        f"stop condition {index} (metric_threshold) names metric "
                        f"{condition.metric_id!r}; the run metric is {value.metric.id!r}"
                    )
                if incumbent is not None and order.is_at_least(incumbent, condition.threshold):
                    assert incumbent_iteration is not None
                    reason: MetricThresholdReason | NoImprovementReason = MetricThresholdReason(
                        condition_index=index,
                        iteration=value.iteration,
                        metric_id=value.metric.id,
                        direction=order.direction,
                        threshold=condition.threshold,
                        incumbent=incumbent,
                        incumbent_iteration=incumbent_iteration,
                    )
                    return StopEvaluationOutput(decision="stop", reason=reason)
            case NoImprovementStop():
                if non_improving >= condition.completed_bodies:
                    reason = NoImprovementReason(
                        condition_index=index,
                        iteration=value.iteration,
                        k=condition.completed_bodies,
                        non_improving_bodies=non_improving,
                        last_improvement_iteration=incumbent_iteration,
                        incumbent=incumbent,
                    )
                    return StopEvaluationOutput(decision="stop", reason=reason)
            case _:
                raise StopConditionError(f"stop condition {index} ({condition.kind}) unsupported")
    return StopEvaluationOutput(decision="continue")


def stop_input(
    loop: AuthoredLoop, seed_metric: MetricSpec | None, bodies: tuple[BodyScore, ...]
) -> StopEvaluationInput:
    """Build the evaluator input; the metric is reconciled once over seed and body stamps."""
    metric = reconcile_metric_specs(
        [
            StampedMetricSpec(label=f"loop body {body.iteration}", spec=body.metric_spec)
            for body in bodies
            if body.metric_spec is not None
        ],
        bound=seed_metric,
        bound_label="the loop's captured interpretation seed",
    )
    return StopEvaluationInput(
        iteration=len(bodies),
        final_iteration=loop.final_iteration,
        conditions=loop.stop_conditions,
        bodies=bodies,
        metric=metric,
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
