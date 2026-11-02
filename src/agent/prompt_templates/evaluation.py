"""One evaluation boundary: declaration text, never candidate arithmetic."""

from __future__ import annotations

from fractions import Fraction

from agent.evaluation_context import EvaluationPromptContext, active_evaluation_prompt_context
from agent.prompt_rendering import prompt_boundary
from execute_tools.evaluation_component_rendering import indent_text, number, render_rubric_details
from execute_tools.evaluation_metric import MetricIdentityKey
from execute_tools.evaluation_spec import (
    DeterministicRanking,
    FormulaSelection,
    MetricComponent,
    RubricBalanceSelection,
    RubricComponent,
    WeightedTerm,
)
from execute_tools.evaluation_validation import inspection
from execute_tools.metric_order import MetricOrder

_HEADER = """[TASK EVALUATION]
These are task-declared evaluation rules, not observed results.
Health determines result validity; constraints determine feasibility; selection determines preference among feasible results.
Metric component values use post-transform MetricResult.scalar units. Descriptive ranges do not enforce validity, feasibility or normalization.
The deterministic core computes scores and constraint outcomes. Do not invent measurements, compute replacement scores or treat rubric judgments as scalar metrics.
Components:"""


def render_weighted_term(
    term: WeightedTerm, context: EvaluationPromptContext, total: Fraction, rate: str
) -> list[str]:
    direction = context.components[term.component].direction
    if direction is None:
        raise ValueError(f"Evaluation term {term.component!r} has no resolved direction")
    order = MetricOrder(MetricIdentityKey(term.component, direction))
    lower, upper = number(term.lower), number(term.upper)
    best = number(order.best((term.lower, term.upper), key=lambda value: value))
    worst = number(order.worst((term.lower, term.upper), key=lambda value: value))
    clipped = term.out_of_range == "clip"
    value = f"clip({term.component}, {lower}, {upper})" if clipped else term.component
    outside = "0 after clipping" if clipped else "refuse, no utility"
    return [
        f"- {term.component}: weight {number(term.weight)}; normalized weight "
        f"{Fraction(str(term.weight)) / total}; normalization bounds [{lower}, {upper}]; "
        f"out_of_range={term.out_of_range}.",
        f"  u_{term.component} = ({value} - {worst})/({best} - {worst}).",
        f"  Marginal utility per raw unit inside bounds: {rate}; outside bounds: {outside}.",
    ]


def render_deterministic_selection(
    selection: DeterministicRanking, context: EvaluationPromptContext
) -> list[str]:
    if not isinstance(selection, FormulaSelection):
        words = MetricOrder(context.primary).direction_words
        return [
            "- kind: primary",
            f"- Deterministic ranking: {indent_text(context.primary.id)}; "
            f"{words['verb']} ({words['comparative']} is better).",
        ]
    terms = selection.formula.params.terms
    total = sum((Fraction(str(term.weight)) for term in terms), Fraction())
    denominator = str(total) if total.denominator == 1 else f"({total})"
    expression = " + ".join(f"{number(t.weight)}*u_{t.component}" for t in terms)
    # Utility is maximized by the formula contract, independently of metric direction.
    lines = [
        "- kind: formula; family: weighted_sum",
        f"- Utility: ({expression})/{denominator}; range [0, 1]; maximize (higher is better).",
    ]
    rates = inspection(context.spec, context.components)["marginal_rates"]
    for term, rate in zip(terms, rates, strict=True):
        lines.extend(render_weighted_term(term, context, total, rate["utility_per_raw_unit_exact"]))
    return lines


def selection_rubric_lines(
    selection: RubricBalanceSelection, context: EvaluationPromptContext
) -> list[str]:
    rubric = context.rubric(selection.rubric)
    lines = render_rubric_details(rubric)
    already_disclosed = any(
        isinstance(component, RubricComponent) and context.rubric(component.rubric) == rubric
        for component in context.spec.components
    )
    # Equality includes resolved content, not merely a reused name/version.
    return lines[:1] if already_disclosed else lines


def render_selection(context: EvaluationPromptContext) -> list[str]:
    selection = context.spec.selection
    if not isinstance(selection, RubricBalanceSelection):
        return render_deterministic_selection(selection, context)
    return (
        ["- kind: rubric_balance"]
        + ["- " + line for line in selection_rubric_lines(selection, context)]
        + [
            f"- Guidance: {indent_text(selection.guidance)}",
            "- Rubric balancing applies only at admitted judged selection sites.",
            "- deterministic_ranking:",
        ]
        + [
            "  " + line
            for line in render_deterministic_selection(selection.deterministic_ranking, context)
        ]
        + [
            "- Within a tuning run, ranking uses deterministic_ranking, "
            "never an unrecorded LLM score."
        ]
    )


def render_constraints(context: EvaluationPromptContext) -> list[str]:
    if not context.spec.constraints:
        return ["- None declared."]
    components = {component.id: component for component in context.spec.components}
    lines = [
        "- All constraints must hold on raw component values before normalization or clipping."
    ]
    for constraint in context.spec.constraints:
        component = components[constraint.component]
        # Plugin units belong to its hook; do not inspect arbitrary variant attributes.
        units = (
            component.units or "(units not declared)"
            if isinstance(component, MetricComponent)
            else "(component units; see declaration above)"
        )
        lines.append(
            f"- {constraint.component} {constraint.op} {number(constraint.threshold)} "
            f"{indent_text(units)}"
        )
    return lines


@prompt_boundary("evaluation.spec")
def render_evaluation_spec(context: EvaluationPromptContext | None) -> str:
    if context is None:
        return ""
    sections = [_HEADER]
    for component in context.spec.components:
        sections.append(
            context.registry[component.kind].render(
                component, context.component_context(component.id)
            )
        )
    sections += [
        "Selection:",
        *render_selection(context),
        "Constraints:",
        *render_constraints(context),
    ]
    warnings = inspection(context.spec, context.components)["warnings"]
    if warnings:
        sections += ["Composition warnings:", *warnings]
    sections.append("[END TASK EVALUATION]")
    return "\n".join(sections)


def append_evaluation_spec(prompt: str) -> str:
    context = active_evaluation_prompt_context()
    # Historical profiles must never meet a new boundary on an absent-spec task.
    if context is None:
        return prompt
    section = render_evaluation_spec(context)
    return prompt + "\n\n" + section if section else prompt
