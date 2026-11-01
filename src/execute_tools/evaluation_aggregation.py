"""Framework-owned weighted utility arithmetic; executed only by the scoring child."""

from __future__ import annotations

import math
from fractions import Fraction
from typing import TYPE_CHECKING

from execute_tools.evaluation_metric import (
    MetricIdentityKey,
    MetricResult,
    MetricSpec,
    NotScoreableResult,
    ScoreabilityFailure,
)
from execute_tools.evaluation_results import (
    ComponentEvaluation,
    EvaluationEvidence,
    EvaluationInputsScoreability,
)
from execute_tools.evaluation_spec import MetricComponent, WeightedTerm
from execute_tools.evaluation_validation import formula_terms
from execute_tools.metric_order import MetricOrder
from workflows.evaluation_selection import effective_metric_spec

if TYPE_CHECKING:
    from workflows.evaluation_composition import ResolvedEvaluation


def _component_value(
    component: MetricComponent,
    results: dict[str, MetricResult],
    evaluation: ResolvedEvaluation,
) -> float:
    result = results.get(component.metric)
    if result is None:
        raise ValueError("required source metric is missing, refused or errored")
    direction = evaluation.components[component.id].direction
    if result.metric_id != component.metric or result.direction != direction:
        raise ValueError("source metric identity disagrees with the composed component")
    if result.scalar is None or not math.isfinite(result.scalar):
        raise ValueError("required source metric is null or nonfinite")
    return result.scalar


def _term_evidence(
    term: WeightedTerm, raw: float, total: Fraction, evaluation: ResolvedEvaluation
) -> tuple[ComponentEvaluation, Fraction]:
    value, lower, upper = (Fraction(str(v)) for v in (raw, term.lower, term.upper))
    clipped = not lower <= value <= upper
    if clipped and term.out_of_range == "refuse":
        raise ValueError(f"raw value {raw} is outside [{term.lower}, {term.upper}]")
    normalized = (min(upper, max(lower, value)) - lower) / (upper - lower)
    resolved = evaluation.components[term.component]
    assert resolved.direction is not None
    order = MetricOrder(MetricIdentityKey(term.component, resolved.direction))
    utility = order.normalized_utility(normalized)
    contribution = Fraction(str(term.weight)) / total * utility
    return ComponentEvaluation(
        component_id=term.component,
        identity=resolved.identity,
        raw=raw,
        normalized=float(normalized),
        utility=float(utility),
        weight=term.weight,
        lower=term.lower,
        upper=term.upper,
        out_of_range=term.out_of_range,
        contribution=float(contribution),
        clipped=clipped,
    ), contribution


def _source_evidence(
    source_spec: MetricSpec,
    primary: MetricResult | NotScoreableResult,
) -> tuple[MetricResult | None, list[ScoreabilityFailure]]:
    failures: list[ScoreabilityFailure] = []
    source = primary if isinstance(primary, MetricResult) else None
    if source is None or source.scalar is None or not math.isfinite(source.scalar):
        failures.append(
            ScoreabilityFailure(
                requirement="source_primary", detail="Source primary is not scoreable or finite."
            )
        )
        source = None
    elif source.metric_id != source_spec.id or source.direction != source_spec.direction:
        failures.append(
            ScoreabilityFailure(
                requirement="source_primary", detail="Source primary identity mismatch."
            )
        )
    return source, failures


def aggregate_evaluation(
    evaluation: ResolvedEvaluation,
    source_spec: MetricSpec,
    primary: MetricResult | NotScoreableResult,
    secondaries: list[MetricResult],
) -> tuple[MetricResult | NotScoreableResult, EvaluationEvidence]:
    """Require all referenced evidence; never silently renormalize missing terms."""
    effective = effective_metric_spec(source_spec, evaluation)
    contract = effective.scoreability
    assert isinstance(contract, EvaluationInputsScoreability)
    source, failures = _source_evidence(source_spec, primary)
    results = {r.metric_id: r for r in secondaries}
    if source is not None:
        results[source.metric_id] = source
    components = {c.id: c for c in evaluation.spec.components}
    terms = formula_terms(evaluation.spec)
    total = sum((Fraction(str(t.weight)) for t in terms), Fraction())
    evidence: list[ComponentEvaluation] = []
    contributions: list[Fraction] = []
    for term in terms:
        component = components[term.component]
        try:
            if type(component) is not MetricComponent:
                raise ValueError("component kind has no runtime value support")
            raw = _component_value(component, results, evaluation)
            item, contribution = _term_evidence(term, raw, total, evaluation)
            evidence.append(item)
            contributions.append(contribution)
        except ValueError as error:
            failures.append(ScoreabilityFailure(requirement=term.component, detail=str(error)))
    verdict = contract.evidence_verdict(tuple(failures))
    scalar = float(sum(contributions, Fraction())) if verdict.scoreable else None
    record = EvaluationEvidence(
        evaluation_sha256=evaluation.sha256,
        effective_metric_id=effective.id,
        source_metric_result=source,
        components=tuple(evidence),
        aggregate=scalar,
        failures=tuple(failures),
    )
    if not verdict.scoreable:
        return NotScoreableResult(
            metric_id=effective.id, direction=effective.direction, verdict=verdict
        ), record
    return MetricResult(
        metric_id=effective.id, direction=effective.direction, scalar=scalar
    ), record
