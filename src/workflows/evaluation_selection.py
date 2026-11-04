"""Derive selection identity without replacing the executable source metric."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from execute_tools.evaluation_metric import MetricSpec
from execute_tools.evaluation_results import (
    ConstraintTerm,
    EvaluationInputsScoreability,
    SelectionBinding,
    SelectionTerm,
)
from execute_tools.evaluation_spec import (
    EvaluationConstraint,
    MeasurementComponent,
    MetricComponent,
    WeightedTerm,
)
from execute_tools.evaluation_validation import formula_terms
from execute_tools.metric_order import MetricOrder

if TYPE_CHECKING:
    from workflows.evaluation_composition import ResolvedEvaluation
    from workflows.task_composition import RunTaskComposition


def effective_metric_spec(source: MetricSpec, evaluation: ResolvedEvaluation | None) -> MetricSpec:
    if evaluation is None or not formula_terms(evaluation.spec):
        return source
    return MetricSpec(
        id=generated_metric_id(evaluation),
        direction=MetricOrder.utility_direction(),
        aggregation="evaluation.weighted_sum/v1",
        scoreability=EvaluationInputsScoreability(
            evaluation_sha256=evaluation.sha256,
            required_components=tuple(t.component for t in formula_terms(evaluation.spec)),
        ),
    )


class SelectionCarrier(Protocol):
    @property
    def selection_binding(self) -> SelectionBinding | None: ...


def selection_binding(composition: RunTaskComposition) -> SelectionBinding | None:
    """Bound when the scoring child must emit evaluation evidence: formula or constraints."""
    evaluation = composition.evaluation
    if evaluation is None or not (formula_terms(evaluation.spec) or evaluation.spec.constraints):
        return None
    return SelectionBinding(
        evaluation_sha256=evaluation.sha256,
        source_metric=composition.metric.spec,
        effective_metric=effective_metric_spec(composition.metric.spec, evaluation),
        components={
            term.component: evaluation.components[term.component].identity
            for term in formula_terms(evaluation.spec)
        },
        terms=tuple(_selection_term(evaluation, term) for term in formula_terms(evaluation.spec)),
        constraints=constraint_terms(evaluation),
        measurements={
            c.id: c.measurement
            for c in evaluation.spec.components
            if isinstance(c, MeasurementComponent)
        },
    )


def constraint_terms(evaluation: ResolvedEvaluation) -> tuple[ConstraintTerm, ...]:
    return tuple(_constraint_term(evaluation, c) for c in evaluation.spec.constraints)


def _constraint_term(
    evaluation: ResolvedEvaluation, constraint: EvaluationConstraint
) -> ConstraintTerm:
    component = next(c for c in evaluation.spec.components if c.id == constraint.component)
    return ConstraintTerm(
        constraint=constraint,
        source_metric_id=component.metric if isinstance(component, MetricComponent) else None,
    )


def _selection_term(evaluation: ResolvedEvaluation, term: WeightedTerm) -> SelectionTerm:
    component = next(c for c in evaluation.spec.components if c.id == term.component)
    return SelectionTerm(
        term=term,
        source_metric_id=component.metric if isinstance(component, MetricComponent) else None,
        direction=evaluation.components[term.component].direction,
        source_measurement=component.id if isinstance(component, MeasurementComponent) else None,
    )


def selection_metric(composition: SelectionCarrier | None, source: MetricSpec) -> MetricSpec:
    binding = bound_selection(composition)
    return binding.effective_metric if binding else source


def bound_selection(composition: SelectionCarrier | None) -> SelectionBinding | None:
    """Older composition projections have no optional selection binding."""
    return getattr(composition, "selection_binding", None)


def selection_inspection(evaluation: ResolvedEvaluation) -> dict[str, object]:
    if not formula_terms(evaluation.spec):
        return {}
    return {
        "effective_metric_id": generated_metric_id(evaluation),
        "effective_direction": MetricOrder.utility_direction(),
        "effective_units": "utility [0,1]",
    }


def generated_metric_id(evaluation: ResolvedEvaluation) -> str:
    return f"evaluation.weighted_sum.v1.{evaluation.sha256}"
