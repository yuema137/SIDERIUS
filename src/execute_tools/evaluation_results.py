"""Typed evidence for deterministic selection, separate from source Health values."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from execute_tools.evaluation_metric import (
    EvaluationInputsScoreability,
    MetricDirection,
    MetricResult,
    MetricSpecField,
    NotScoreableResult,
    ScoreabilityFailure,
)
from execute_tools.evaluation_spec import EvaluationConstraint, WeightedTerm

__all__ = [
    "ComponentEvaluation",
    "ConstraintEvaluation",
    "ConstraintTerm",
    "EvaluationEvidence",
    "EvaluationInputsScoreability",
    "EvaluationTransportError",
    "SelectionBinding",
    "SelectionTerm",
    "validate_record_evaluation",
]


class EvaluationTransportError(ValueError):
    """Child/parent evaluation evidence is malformed, ambiguous or inconsistent.

    Distinct from a scientific refusal: transport errors never become a
    scoreable or not-scoreable verdict; the attempt fails as a scoring error.
    """


class ComponentEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    component_id: str
    identity: dict[str, JsonValue]
    raw: float
    normalized: float
    utility: float
    weight: float
    lower: float
    upper: float
    out_of_range: Literal["refuse", "clip"]
    contribution: float
    clipped: bool


class ConstraintEvaluation(BaseModel):
    """One declared constraint judged on its raw component value (#1295)."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    component_id: str
    op: Literal[">=", ">", "<=", "<"]
    threshold: float
    raw: float | None
    satisfied: bool
    detail: str


class EvaluationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal["siderius.evaluation-result/v1"] = "siderius.evaluation-result/v1"
    evaluation_sha256: str
    effective_metric_id: str
    source_metric_result: MetricResult | None = None
    components: tuple[ComponentEvaluation, ...] = Field(default=(), strict=False)
    aggregate: float | None = None
    failures: tuple[ScoreabilityFailure, ...] = Field(default=(), strict=False)
    constraints: tuple[ConstraintEvaluation, ...] = Field(
        default=(), strict=False, exclude_if=lambda value: not value
    )


class ConstraintTerm(BaseModel):
    """One declared constraint plus where its raw value is read from.

    ``source_metric_id`` names the metric result for a metric component; it is
    ``None`` for a non-metric quantitative component (#1296 measurements), whose
    value is read from ``measurement_results`` by component id.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    constraint: EvaluationConstraint
    source_metric_id: str | None


class SelectionTerm(BaseModel):
    """One declared term plus the source identity its raw value must come from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    term: WeightedTerm
    source_metric_id: str | None
    direction: MetricDirection | None


class SelectionBinding(BaseModel):
    """Composition projection transported to the tuner without executable plugins.

    ``terms`` lets the parent recompute component arithmetic from raw values
    and the declaration instead of trusting the child's derived numbers.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    evaluation_sha256: str
    source_metric: MetricSpecField
    effective_metric: MetricSpecField
    components: dict[str, dict[str, JsonValue]]
    terms: tuple[SelectionTerm, ...] = Field(strict=False)
    constraints: tuple[ConstraintTerm, ...] = Field(
        default=(), strict=False, exclude_if=lambda value: not value
    )

    @property
    def is_formula(self) -> bool:
        """Formula selection replaces the source scalar; constraints alone do not."""
        return self.effective_metric.id != self.source_metric.id


def _validate_refusal_evidence(
    evidence: EvaluationEvidence,
    refusal: NotScoreableResult | None,
) -> None:
    if refusal is None or refusal.metric_id != evidence.effective_metric_id:
        raise ValueError("Evaluation refusal must carry the same effective metric identity")
    if tuple(refusal.verdict.failures) != evidence.failures or evidence.aggregate is not None:
        raise ValueError("Evaluation refusal disagrees with component failures")


def validate_record_evaluation(
    evidence: EvaluationEvidence | None,
    metric: MetricResult | None,
    refusal: NotScoreableResult | None,
) -> None:
    """Do not let persisted evidence contradict the record's ranking identity."""
    if evidence is None:
        return
    if evidence.failures:
        _validate_refusal_evidence(evidence, refusal)
        return
    if metric is None or evidence.aggregate is None or evidence.source_metric_result is None:
        raise ValueError("Successful evaluation requires effective and source metric evidence")
    if metric.metric_id != evidence.effective_metric_id or metric.scalar != evidence.aggregate:
        raise ValueError("Evaluation evidence disagrees with the record's effective metric")
    formula = evidence.source_metric_result.metric_id != evidence.effective_metric_id
    if formula and metric.per_sample is not None:
        raise ValueError("Formula utility has no declared per-sample decomposition")
