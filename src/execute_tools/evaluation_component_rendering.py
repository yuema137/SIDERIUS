"""Pure builtin component hooks; registrations remain the dispatch authority."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from agent.schemas.judge_task import RubricSpec, rubric_sha256
from execute_tools.evaluation_spec import MeasurementComponent, MetricComponent, RubricComponent

if TYPE_CHECKING:
    from execute_tools.evaluation_registry import ComponentRenderContext


def number(value: float) -> str:
    """Keep authored precision without gratuitous integral decimal suffixes."""
    return str(int(value)) if value.is_integer() else str(value)


def indent_text(value: str, prefix: str = "  ") -> str:
    """Keep authored lines inside their field even with non-LF line separators."""
    normalized = re.sub(r"\r\n?|[\u2028\u2029]", "\n", value)
    return normalized.replace("\n", "\n" + prefix)


def render_metric_component(component: MetricComponent, context: ComponentRenderContext) -> str:
    words = context.direction_words
    bounds = component.range
    descriptive = (
        f"[{number(bounds.lower)}, {number(bounds.upper)}] (descriptive only)"
        if bounds is not None
        else "not declared"
    )
    return "\n".join(
        (
            f"- {component.id} (metric: {indent_text(component.metric)})",
            f"  Meaning: {indent_text(component.meaning)}",
            f"  Units: {indent_text(component.units or 'not declared')}",
            f"  Preference: {words['verb']} ({words['comparative']} is better)",
            f"  Descriptive range: {descriptive}",
        )
    )


def render_rubric_details(rubric: RubricSpec) -> list[str]:
    lines = [
        f"Rubric: {rubric.id}@{rubric.version}; sha256={rubric_sha256(rubric)}",
        f"Integer scale: [{rubric.scale_min}, {rubric.scale_max}]",
    ]
    lines.extend(
        f"Criterion: {criterion.name}; weight {number(criterion.weight)}; "
        f"{indent_text(criterion.description)}"
        for criterion in rubric.criteria
    )
    return lines


def render_rubric_component(component: RubricComponent, context: ComponentRenderContext) -> str:
    if context.rubric is None:
        raise ValueError(f"Evaluation rubric {component.id!r} has no resolved rendering input")
    return "\n".join(
        [f"- {component.id} (rubric)", f"  Meaning: {indent_text(component.meaning)}"]
        + ["  " + line for line in render_rubric_details(context.rubric)]
        + ["  Role: qualitative evidence; not a deterministic scalar."]
    )


def render_measurement_component(
    component: MeasurementComponent, context: ComponentRenderContext
) -> str:
    from execute_tools.measurement_results import MEASUREMENT_UNITS

    words = context.direction_words
    bounds = component.range
    descriptive = (
        f"[{number(bounds.lower)}, {number(bounds.upper)}] (descriptive only)"
        if bounds is not None
        else "not declared"
    )
    lines = [
        f"- {component.id} (measurement: {component.measurement})",
        f"  Meaning: {indent_text(component.meaning)}",
        f"  Units: {MEASUREMENT_UNITS[component.measurement]}",
        f"  Preference: {words['verb']} ({words['comparative']} is better)",
        f"  Descriptive range: {descriptive}",
        "  Source: the serialized trained checkpoint, measured once per candidate.",
    ]
    protocol = component.protocol
    if protocol is not None:
        shape = "x".join(str(dim) for dim in protocol.input_shape)
        lines.append(
            f"  Protocol: one synthetic input of shape {shape}; {protocol.warmup} untimed "
            f"warm-up forwards, then the median of {protocol.repeats} timed forwards on the "
            "training device (not data loading or I/O time)."
        )
    return "\n".join(lines)
