"""Run-local evaluation kind registrations and deferred runtime capabilities.

Only the composer loads registrations. No ambient registry or plugin execution
occurs at import; future renderers dispatch through these same registrations.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import reduce
from operator import or_
from types import MappingProxyType
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from agent.schemas.judge_task import (
    JudgeTaskDeclarations,
    RubricSpec,
    resolve_rubric_ref,
    rubric_ref,
)
from execute_tools.evaluation_metric import MetricDirection, MetricSpec
from execute_tools.evaluation_spec import (
    ComponentSpec,
    EvaluationRubricRef,
    MeasurementComponent,
    MetricComponent,
    RubricComponent,
    SymbolRef,
)

# Each runtime owner enables its capability only after wiring every consumer.
IMPLEMENTED_CAPABILITIES: Mapping[str, bool] = MappingProxyType(
    {
        "evaluation rendering": True,
        "formula aggregation": True,
        "feasibility constraints": True,
        "measurements": True,
        "rubric components": True,
        "rubric balancing": True,
    }
)


class ResolvedComponent(BaseModel):
    """Composed facts, not a measurement result or an executable runtime grant."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, allow_inf_nan=False)

    direction: MetricDirection | None = None
    identity: dict[str, JsonValue] = Field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationLoadContext:
    metrics: Mapping[str, MetricSpec]
    judge_task: JudgeTaskDeclarations | None
    load_symbol: Callable[[SymbolRef, str], tuple[Any, Mapping[str, JsonValue]]]


@dataclass(frozen=True)
class ComponentRenderContext:
    """#1293 supplies directional words from MetricOrder, never from prose."""

    direction_words: Mapping[str, str] = field(default_factory=dict)
    rubric: RubricSpec | None = None


@dataclass(frozen=True)
class ComponentKindRegistration:
    kind: str
    version: str
    schema: type[ComponentSpec]
    load: Callable[[Any, EvaluationLoadContext], ResolvedComponent]
    fingerprint: Callable[[Any, ResolvedComponent], Mapping[str, JsonValue]]
    render: Callable[[Any, ComponentRenderContext], str]
    value_kind: Literal["quantitative", "rubric"]
    required_capabilities: frozenset[str] = frozenset()


def component_adapter(registry: Mapping[str, ComponentKindRegistration]) -> TypeAdapter:
    """Build the union from the one registration table, including user variants."""
    variants = tuple(registration.schema for registration in registry.values())
    union = reduce(or_, variants)
    return TypeAdapter(Annotated[union, Field(discriminator="kind")])


def _validate_identity_serialization(schema: type[ComponentSpec]) -> None:
    """Reject schema hooks that can hide validated values from the resume identity.

    Inspect the compiled schema so nested models, Annotated serializers and
    serializer decorators follow the same rule, including recursive definitions.
    """
    pending: list[Any] = [schema.__pydantic_core_schema__]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            if (
                "serialization" in node
                or node.get("serialization_exclude")
                or node.get("serialization_exclude_if") is not None
            ):
                raise ValueError(
                    "component kind schemas must not exclude fields or use custom serializers; "
                    "all validated values must participate in evaluation identity"
                )
            pending.extend(node.values())
        elif isinstance(node, (list, tuple)):
            pending.extend(node)


def validate_registration(name: str, value: object) -> ComponentKindRegistration:
    if not isinstance(value, ComponentKindRegistration):
        raise ValueError(f"component kind {name!r} must export ComponentKindRegistration")
    if not isinstance(value.schema, type) or not issubclass(value.schema, ComponentSpec):
        raise ValueError(f"component kind {name!r} schema must extend ComponentSpec")
    config = value.schema.model_config
    if any(
        config.get(key) != expected
        for key, expected in (("extra", "forbid"), ("frozen", True), ("strict", True))
    ):
        raise ValueError(f"component kind {name!r} schema must be extra=forbid, frozen and strict")
    _validate_identity_serialization(value.schema)
    discriminator = value.schema.model_fields["kind"].annotation
    if value.kind != name or get_args(discriminator) != (name,):
        raise ValueError(f"component kind {name!r} disagrees with registration/schema kind")
    if not value.version.strip() or value.value_kind not in ("quantitative", "rubric"):
        raise ValueError(f"component kind {name!r} has invalid version/value_kind")
    if not all(callable(hook) for hook in (value.load, value.fingerprint, value.render)):
        raise ValueError(f"component kind {name!r} requires load, fingerprint and render hooks")
    if not isinstance(value.required_capabilities, frozenset) or any(
        not isinstance(capability, str) or not capability.strip()
        for capability in value.required_capabilities
    ):
        raise ValueError(f"component kind {name!r} has invalid required capabilities")
    return value


def _metric(component: MetricComponent, ctx: EvaluationLoadContext) -> ResolvedComponent:
    spec = ctx.metrics.get(component.metric)
    if spec is None:
        raise ValueError(f"component {component.id!r} names undeclared metric {component.metric!r}")
    return ResolvedComponent(
        direction=spec.direction,
        identity={"metric": spec.model_dump(mode="json", exclude_defaults=True)},
    )


def resolve_evaluation_rubric(ref: EvaluationRubricRef, task: JudgeTaskDeclarations | None):
    available = task.rubrics if task else ()
    for rubric in available:
        if (rubric.id, rubric.version) == (ref.id, ref.version):
            resolved = rubric_ref(rubric)
            if ref.sha256 is not None:
                resolve_rubric_ref(resolved.model_copy(update={"sha256": ref.sha256}), available)
            return resolved
    raise ValueError(f"undeclared evaluation rubric {ref.id!r} version {ref.version!r}")


def _rubric(component: RubricComponent, ctx: EvaluationLoadContext) -> ResolvedComponent:
    ref = resolve_evaluation_rubric(component.rubric, ctx.judge_task)
    return ResolvedComponent(identity={"rubric": ref.model_dump(mode="json")})


def _measurement(component: MeasurementComponent, ctx: EvaluationLoadContext) -> ResolvedComponent:
    """Direction is authored; the declaration itself is the identity (no external code)."""
    return ResolvedComponent(
        direction=component.direction,
        identity={"measurement": component.measurement, "version": "1"},
    )


def _identity(component: ComponentSpec, resolved: ResolvedComponent) -> Mapping[str, JsonValue]:
    return resolved.identity


def builtin_registry() -> dict[str, ComponentKindRegistration]:
    from execute_tools.evaluation_component_rendering import (
        render_measurement_component,
        render_metric_component,
        render_rubric_component,
    )

    return {
        "metric": ComponentKindRegistration(
            "metric",
            "1",
            MetricComponent,
            _metric,
            _identity,
            render_metric_component,
            "quantitative",
        ),
        "rubric": ComponentKindRegistration(
            "rubric",
            "1",
            RubricComponent,
            _rubric,
            _identity,
            render_rubric_component,
            "rubric",
            frozenset({"rubric components"}),
        ),
        "measurement": ComponentKindRegistration(
            "measurement",
            "1",
            MeasurementComponent,
            _measurement,
            _identity,
            render_measurement_component,
            "quantitative",
            frozenset({"measurements"}),
        ),
    }
