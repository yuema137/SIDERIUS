"""Cross-declaration validation and inspection of composed evaluation semantics."""

from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction
from typing import Any

from execute_tools.evaluation_metric import MetricIdentityKey
from execute_tools.evaluation_registry import ComponentKindRegistration, ResolvedComponent
from execute_tools.evaluation_spec import (
    EvaluationSpec,
    FormulaSelection,
    MetricComponent,
    RubricBalanceSelection,
    WeightedTerm,
)
from execute_tools.metric_order import MetricOrder


def formula_terms(spec: EvaluationSpec) -> tuple[WeightedTerm, ...]:
    selection = spec.selection
    if isinstance(selection, RubricBalanceSelection):
        selection = selection.deterministic_ranking
    return selection.formula.params.terms if isinstance(selection, FormulaSelection) else ()


def validate_references(
    spec: EvaluationSpec,
    registry: Mapping[str, ComponentKindRegistration],
    resolved: Mapping[str, ResolvedComponent],
) -> None:
    components = {component.id: component for component in spec.components}
    metric_refs = [c.metric for c in spec.components if isinstance(c, MetricComponent)]
    if len(set(metric_refs)) != len(metric_refs):
        raise ValueError("multiple evaluation components alias the same metric")
    references = [term.component for term in formula_terms(spec)]
    references.extend(constraint.component for constraint in spec.constraints)
    for reference in references:
        component = components.get(reference)
        if component is None:
            raise ValueError(f"evaluation references undeclared component {reference!r}")
        if registry[component.kind].value_kind != "quantitative":
            raise ValueError(f"component {reference!r} is not deterministic quantitative evidence")
        if resolved[reference].direction is None:
            raise ValueError(f"quantitative component {reference!r} has no resolved direction")
    _consistent_constraints(spec)


def _consistent_constraints(spec: EvaluationSpec) -> None:
    bounds: dict[str, tuple[float, bool, float, bool]] = {}
    for constraint in spec.constraints:
        low, low_open, high, high_open = bounds.get(
            constraint.component, (float("-inf"), False, float("inf"), False)
        )
        value = constraint.threshold
        if constraint.op in (">", ">="):
            if value > low:
                low, low_open = value, constraint.op == ">"
            elif value == low:
                low_open = low_open or constraint.op == ">"
        else:
            if value < high:
                high, high_open = value, constraint.op == "<"
            elif value == high:
                high_open = high_open or constraint.op == "<"
        if low > high or (low == high and (low_open or high_open)):
            raise ValueError(f"constraints on {constraint.component!r} have no feasible value")
        bounds[constraint.component] = low, low_open, high, high_open


def inspection(spec: EvaluationSpec, resolved: Mapping[str, ResolvedComponent]) -> dict[str, Any]:
    """Author-facing warnings and marginal utility rates; never ranks candidates."""
    warnings = []
    for constraint in spec.constraints:
        direction = resolved[constraint.component].direction
        if direction is None:
            continue
        order = MetricOrder(MetricIdentityKey(constraint.component, direction))
        if constraint.op[0] != order.at_least_symbol[0]:
            warnings.append(
                f"Constraint {constraint.component} {constraint.op} {constraint.threshold} "
                f"opposes its {order.direction_words['verb']} preference; it remains allowed."
            )
    terms = formula_terms(spec)
    total = sum((Fraction(str(term.weight)) for term in terms), Fraction())
    rates = []
    for term in terms:
        direction = resolved[term.component].direction
        assert direction is not None
        order = MetricOrder(MetricIdentityKey(term.component, direction))
        magnitude = (
            Fraction(str(term.weight))
            / total
            / (Fraction(str(term.upper)) - Fraction(str(term.lower)))
        )
        sign = int(order.toward_better(0.0, 1.0))
        rates.append(
            {
                "component": term.component,
                "utility_per_raw_unit_exact": str(sign * magnitude),
                "out_of_range": term.out_of_range,
            }
        )
    return {"warnings": warnings, "marginal_rates": rates}
