"""Framework-owned weighted utility arithmetic.

The scoring child computes it; the parent re-derives each term from raw values
and the declaration to verify transported evidence (``evaluation_child``).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from fractions import Fraction
from typing import TYPE_CHECKING

from pydantic import JsonValue

from execute_tools.evaluation_metric import (
    MetricDirection,
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
    EvaluationTransportError,
)
from execute_tools.evaluation_spec import MetricComponent, WeightedTerm
from execute_tools.evaluation_validation import formula_terms
from execute_tools.metric_order import MetricOrder
from workflows.evaluation_selection import effective_metric_spec

if TYPE_CHECKING:
    from workflows.evaluation_composition import ResolvedEvaluation


def index_source_results(results: Iterable[MetricResult]) -> dict[str, MetricResult]:
    """Map source results by metric id; an ambiguous duplicate fails transport."""
    indexed: dict[str, MetricResult] = {}
    for result in results:
        if result.metric_id in indexed:
            raise EvaluationTransportError(
                f"duplicate source metric result {result.metric_id!r} in evaluation evidence"
            )
        indexed[result.metric_id] = result
    return indexed


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


def weight_total(terms: Iterable[WeightedTerm]) -> Fraction:
    return sum((Fraction(str(t.weight)) for t in terms), Fraction())


def term_evaluation(
    term: WeightedTerm,
    raw: float,
    total: Fraction,
    direction: MetricDirection,
    identity: dict[str, JsonValue],
) -> tuple[ComponentEvaluation, Fraction]:
    """The single term arithmetic, shared by the child and the parent verifier."""
    value, lower, upper = (Fraction(str(v)) for v in (raw, term.lower, term.upper))
    clipped = not lower <= value <= upper
    if clipped and term.out_of_range == "refuse":
        raise ValueError(f"raw value {raw} is outside [{term.lower}, {term.upper}]")
    normalized = (min(upper, max(lower, value)) - lower) / (upper - lower)
    order = MetricOrder(MetricIdentityKey(term.component, direction))
    utility = order.normalized_utility(normalized)
    contribution = Fraction(str(term.weight)) / total * utility
    return ComponentEvaluation(
        component_id=term.component,
        identity=identity,
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
    results = index_source_results([*secondaries, *([source] if source is not None else [])])
    components = {c.id: c for c in evaluation.spec.components}
    terms = formula_terms(evaluation.spec)
    total = weight_total(terms)
    evidence: list[ComponentEvaluation] = []
    contributions: list[Fraction] = []
    for term in terms:
        component = components[term.component]
        try:
            if type(component) is not MetricComponent:
                raise ValueError("component kind has no runtime value support")
            raw = _component_value(component, results, evaluation)
            resolved = evaluation.components[term.component]
            assert resolved.direction is not None
            item, contribution = term_evaluation(
                term, raw, total, resolved.direction, resolved.identity
            )
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
