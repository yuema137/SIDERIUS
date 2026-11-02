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
from execute_tools.evaluation_spec import WeightedTerm

__all__ = [
    "ComponentEvaluation",
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


class EvaluationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal["siderius.evaluation-result/v1"] = "siderius.evaluation-result/v1"
    evaluation_sha256: str
    effective_metric_id: str
    source_metric_result: MetricResult | None = None
    components: tuple[ComponentEvaluation, ...] = Field(default=(), strict=False)
    aggregate: float | None = None
    failures: tuple[ScoreabilityFailure, ...] = Field(default=(), strict=False)


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
    if metric.per_sample is not None:
        raise ValueError("Formula utility has no declared per-sample decomposition")
