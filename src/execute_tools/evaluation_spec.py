"""Opt-in evaluation declarations; arithmetic and launch admission are separate owners."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializeAsAny,
    StringConstraints,
    TypeAdapter,
    ValidationInfo,
    field_validator,
    model_validator,
)

from agent.schemas.judge_refs import Digest, Identifier, Version
from execute_tools.evaluation_metric import MetricDirection

Text = Annotated[str, StringConstraints(pattern=r"\S")]
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Positive = Annotated[Number, Field(gt=0)]


class EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


class SymbolRef(EvaluationModel):
    """User kind registrations are file-backed so their code is content-pinned."""

    file: Text
    symbol: Text

    @model_validator(mode="before")
    @classmethod
    def file_only(cls, value: object) -> object:
        if isinstance(value, dict) and "module" in value:
            raise ValueError(
                "evaluation component_kinds requires file: references; module: is refused"
            )
        return value


class ValueRange(EvaluationModel):
    lower: Number
    upper: Number

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.lower >= self.upper:
            raise ValueError("range.lower must be less than range.upper")
        return self


class EvaluationRubricRef(EvaluationModel):
    id: Identifier
    version: Version
    # Authored assertion is checked; resolved identity carries the authoritative hash.
    sha256: Digest | None = Field(default=None, exclude=True)


class ComponentSpec(EvaluationModel):
    kind: Text
    id: Identifier
    meaning: Text = Field(max_length=1000)


class MetricComponent(ComponentSpec):
    kind: Literal["metric"]
    metric: Text
    units: Text | None = Field(default=None, max_length=128)
    range: ValueRange | None = None


class LatencyProtocol(EvaluationModel):
    """One synthetic input, untimed warm-up forwards, then timed repeats (median)."""

    input_shape: tuple[Annotated[int, Field(strict=True, ge=1)], ...] = Field(
        min_length=1, max_length=8, strict=False
    )
    warmup: Annotated[int, Field(strict=True, ge=0, le=1000)] = 10
    repeats: Annotated[int, Field(strict=True, ge=1, le=10000)] = 50
    timeout_seconds: Annotated[Positive, Field(le=3600)] = 300.0


class MeasurementComponent(ComponentSpec):
    """A builtin model-level measurement of the serialized trained checkpoint (#1296)."""

    kind: Literal["measurement"]
    measurement: Literal[
        "trainable_parameter_count", "total_parameter_count", "model_bytes", "inference_latency_ms"
    ]
    direction: MetricDirection
    range: ValueRange | None = None
    protocol: LatencyProtocol | None = None

    @model_validator(mode="after")
    def protocol_applies(self) -> Self:
        timed = self.measurement == "inference_latency_ms"
        if timed and self.protocol is None:
            raise ValueError("inference_latency_ms requires a protocol with input_shape")
        if not timed and self.protocol is not None:
            raise ValueError(f"measurement {self.measurement!r} takes no protocol")
        return self


class RubricComponent(ComponentSpec):
    kind: Literal["rubric"]
    rubric: EvaluationRubricRef


class WeightedTerm(EvaluationModel):
    component: Identifier
    weight: Positive
    lower: Number
    upper: Number
    out_of_range: Literal["refuse", "clip"]

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.lower >= self.upper:
            raise ValueError("term.lower must be less than term.upper")
        return self


class WeightedSumParams(EvaluationModel):
    terms: tuple[WeightedTerm, ...] = Field(min_length=1, strict=False)

    @model_validator(mode="after")
    def unique_terms(self) -> Self:
        refs = [term.component for term in self.terms]
        if len(set(refs)) != len(refs):
            raise ValueError("formula terms must name distinct components")
        return self


class WeightedSumFormula(EvaluationModel):
    family: Literal["weighted_sum"]
    params: WeightedSumParams


class PrimarySelection(EvaluationModel):
    kind: Literal["primary"]


class FormulaSelection(EvaluationModel):
    kind: Literal["formula"]
    # Retain the discriminator when later versions add a formula family.
    formula: WeightedSumFormula = Field(discriminator="family")


DeterministicRanking = Annotated[PrimarySelection | FormulaSelection, Field(discriminator="kind")]


class RubricBalanceSelection(EvaluationModel):
    kind: Literal["rubric_balance"]
    rubric: EvaluationRubricRef
    guidance: Text = Field(max_length=1000)
    deterministic_ranking: DeterministicRanking


EvaluationSelection = Annotated[
    PrimarySelection | FormulaSelection | RubricBalanceSelection, Field(discriminator="kind")
]


class EvaluationConstraint(EvaluationModel):
    component: Identifier
    op: Literal[">=", ">", "<=", "<"]
    threshold: Number


class EvaluationSpec(EvaluationModel):
    schema_version: Literal["siderius.evaluation/v1"] = "siderius.evaluation/v1"
    component_kinds: dict[Text, SymbolRef] = Field(default_factory=dict)
    components: tuple[SerializeAsAny[ComponentSpec], ...] = Field(
        min_length=1, max_length=32, strict=False
    )
    selection: EvaluationSelection
    constraints: tuple[EvaluationConstraint, ...] = Field(default=(), max_length=64, strict=False)

    @field_validator("components", mode="before")
    @classmethod
    def registered_variants(cls, value: object, info: ValidationInfo) -> object:
        from execute_tools.evaluation_registry import builtin_registry, component_adapter

        adapter = (info.context or {}).get("component_adapter")
        if adapter is None:
            adapter = component_adapter(builtin_registry())
        if not isinstance(value, (list, tuple)):
            raise ValueError("components must be a sequence")
        return tuple(adapter.validate_python(item) for item in value)

    @model_validator(mode="after")
    def unique_components(self) -> Self:
        ids = [component.id for component in self.components]
        if len(set(ids)) != len(ids):
            raise ValueError("evaluation component ids must be unique")
        return self


# Validate registry declarations before loading any component schema plugin.
ComponentKinds = TypeAdapter(dict[Text, SymbolRef])
