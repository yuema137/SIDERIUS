"""Fail closed before launching unsupported evaluation routes or ambiguous units."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from execute_tools.evaluation_spec import MeasurementComponent, MetricComponent
from execute_tools.evaluation_validation import formula_terms
from workflows.evaluation_selection import SelectionCarrier, bound_selection

if TYPE_CHECKING:
    from workflows.evaluation_composition import ResolvedEvaluation


def require_component_runtime(evaluation: ResolvedEvaluation | None) -> None:
    if evaluation is None:
        return
    referenced = {t.component for t in formula_terms(evaluation.spec)}
    referenced.update(c.component for c in evaluation.spec.constraints)
    runtime_kinds = (MetricComponent, MeasurementComponent)
    for component in evaluation.spec.components:
        if component.id in referenced and type(component) not in runtime_kinds:
            raise ValueError(
                f"Evaluation composition succeeded, but component {component.id!r} "
                f"of kind {component.kind!r} has no runtime value support."
            )
    require_measurement_route(evaluation)


def require_measurement_route(evaluation: ResolvedEvaluation | None) -> None:
    """Measurements run only in the native task-owned scoring child (#1296)."""
    if evaluation is None or not any(
        isinstance(c, MeasurementComponent) for c in evaluation.spec.components
    ):
        return
    from execute_tools.evaluation_execution import candidate_evaluation_executor

    if candidate_evaluation_executor() is not None:
        raise ValueError(
            "Measurement components do not support route CandidateEvaluationExecutor; "
            "use native TASK_OWNED scoring-child execution."
        )


def require_formula_route(composition: SelectionCarrier | None, route: str = "TASK_OWNED") -> None:
    binding = bound_selection(composition)
    if binding is None:
        return
    from execute_tools.evaluation_execution import candidate_evaluation_executor

    if candidate_evaluation_executor() is not None:
        route = "CandidateEvaluationExecutor"
    if route != "TASK_OWNED":
        raise ValueError(
            f"Formula aggregation does not support route {route}; use native TASK_OWNED "
            "scoring-child execution or primary selection."
        )


def require_effective_target(metric_id: str | None, effective_id: str, setting: str) -> None:
    if metric_id and metric_id.startswith("component:"):
        raise ValueError(
            f"{setting}: raw component targets are not supported; use effective metric {effective_id!r}."
        )
    if metric_id != effective_id:
        raise ValueError(
            f"{setting} must explicitly name effective metric {effective_id!r}; source-metric units cannot be compared to utility."
        )


def admit_evaluation_settings(composition: SelectionCarrier | None, settings: Any) -> None:
    """Used by workflow and standalone tuner entry points before their first effect."""
    require_formula_route(composition)
    binding = bound_selection(composition)
    if binding is None:
        return
    effective = binding.effective_metric
    if getattr(settings, "target_score", None) is not None:
        require_effective_target(
            getattr(settings, "target_score_metric", None), effective.id, "--target_score_metric"
        )
    active = []
    if getattr(settings, "enable_chain_incumbent_formal_gates", False):
        active.extend(("skip_formal_min_delta", "bypass_formal_time_budget_min_delta"))
    if getattr(settings, "degenerate_penalty_score", None) is not None:
        active.append("degenerate_penalty_score")
    if active:
        require_effective_target(
            getattr(settings, "score_units_metric", None),
            effective.id,
            "score_units_metric for " + ", ".join(active),
        )


def admit_formula_definition(composition: SelectionCarrier, definition: Any) -> None:
    """Check all thresholds, including unvisited branches, before graph dispatch."""
    binding = bound_selection(composition)
    if binding is None:
        return
    effective_id = binding.effective_metric.id
    pending = [definition.model_dump(mode="python")]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            kind = item.get("kind")
            if kind in ("metric_threshold", "metric_at_least") or (
                kind == "threshold/v1" and item.get("basis") == "metric"
            ):
                require_effective_target(item.get("metric_id"), effective_id, str(kind))
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
