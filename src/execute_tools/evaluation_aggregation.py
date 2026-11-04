"""Framework-owned weighted utility arithmetic.

The scoring child computes it; the parent re-derives each term from raw values
and the declaration to verify transported evidence (``evaluation_child``).
"""

from __future__ import annotations

import math
import operator
from collections.abc import Iterable, Mapping
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
    ScoreabilityVerdict,
)
from execute_tools.evaluation_results import (
    ComponentEvaluation,
    ConstraintEvaluation,
    ConstraintTerm,
    EvaluationEvidence,
    EvaluationInputsScoreability,
    EvaluationTransportError,
)
from execute_tools.evaluation_spec import MeasurementComponent, MetricComponent, WeightedTerm
from execute_tools.evaluation_validation import formula_terms
from execute_tools.measurement_results import MeasurementResult
from execute_tools.metric_order import MetricOrder
from workflows.evaluation_selection import constraint_terms, effective_metric_spec

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


#: Contract id of a refusal produced only by violated constraints under primary selection.
CONSTRAINT_CONTRACT_ID = "evaluation_constraints/v1"

_OPS = {">=": operator.ge, ">": operator.gt, "<=": operator.le, "<": operator.lt}


def _constraint_value(
    term: ConstraintTerm,
    sources: Mapping[str, MetricResult],
    measurements: Mapping[str, MeasurementResult],
) -> float | None:
    """The raw value a constraint judges: a metric result, or a #1296 measurement.

    A missing or failed measurement yields ``None``, which is never satisfied.
    """
    if term.source_metric_id is not None:
        source = sources.get(term.source_metric_id)
        return None if source is None else source.scalar
    measured = measurements.get(term.constraint.component)
    return None if measured is None or measured.failure is not None else measured.value


def _unavailable_reason(
    term: ConstraintTerm, measurements: Mapping[str, MeasurementResult]
) -> str | None:
    """A failed measurement's own reason, so an infeasible record names the cause."""
    if term.source_metric_id is not None:
        return None
    measured = measurements.get(term.constraint.component)
    if measured is None:
        return "measurement was not recorded"
    return None if measured.failure is None else f"measurement failed: {measured.failure}"


def evaluate_constraint(
    term: ConstraintTerm, raw: float | None, reason: str | None = None
) -> ConstraintEvaluation:
    """The single constraint arithmetic, shared by the child and the parent verifier.

    Exact comparison of the decimal representations; a missing or nonfinite
    value is never satisfied (fail closed), and there is no implicit tolerance.
    """
    constraint = term.constraint
    label = f"constraint {constraint.component} {constraint.op} {constraint.threshold}"
    if raw is None or not math.isfinite(raw):
        satisfied, detail = False, f"{label} has no finite value: {reason or raw}"
    else:
        value, threshold = Fraction(str(raw)), Fraction(str(constraint.threshold))
        satisfied = bool(_OPS[constraint.op](value, threshold))
        detail = f"{label} {'satisfied' if satisfied else 'violated'}: {raw}"
    return ConstraintEvaluation(
        component_id=constraint.component,
        op=constraint.op,
        threshold=constraint.threshold,
        raw=raw if raw is not None and math.isfinite(raw) else None,
        satisfied=satisfied,
        detail=detail,
    )


def evaluate_constraints(
    terms: Iterable[ConstraintTerm],
    sources: Mapping[str, MetricResult],
    measurements: Mapping[str, MeasurementResult] | None = None,
) -> tuple[tuple[ConstraintEvaluation, ...], list[ScoreabilityFailure]]:
    """Every constraint is conjunctive; each violation is a named scoreability failure."""
    verdicts = tuple(
        evaluate_constraint(
            term,
            _constraint_value(term, sources, measurements or {}),
            _unavailable_reason(term, measurements or {}),
        )
        for term in terms
    )
    failures = [
        ScoreabilityFailure(requirement=f"constraint:{v.component_id}", detail=v.detail)
        for v in verdicts
        if not v.satisfied
    ]
    return verdicts, failures


def constrain_primary(
    evaluation: ResolvedEvaluation,
    source_spec: MetricSpec,
    primary: MetricResult | NotScoreableResult,
    secondaries: list[MetricResult],
    measurements: Mapping[str, MeasurementResult] | None = None,
) -> tuple[MetricResult | NotScoreableResult, EvaluationEvidence | None]:
    """Primary selection with constraints: the source scalar ranks only if feasible.

    A source refusal keeps its own contract verdict and carries no evidence.
    """
    if not isinstance(primary, MetricResult):
        return primary, None
    source, failures = _source_evidence(source_spec, primary)
    if source is not None:
        results = index_source_results([*secondaries, source])
        verdicts, violated = evaluate_constraints(
            constraint_terms(evaluation), results, measurements
        )
        failures.extend(violated)
    else:
        verdicts = ()
    record = EvaluationEvidence(
        evaluation_sha256=evaluation.sha256,
        effective_metric_id=source_spec.id,
        source_metric_result=source,
        aggregate=None if failures else primary.scalar,
        failures=tuple(failures),
        constraints=verdicts,
    )
    if failures:
        verdict = ScoreabilityVerdict(contract_id=CONSTRAINT_CONTRACT_ID, failures=tuple(failures))
        return NotScoreableResult(
            metric_id=source_spec.id, direction=source_spec.direction, verdict=verdict
        ), record
    return primary, record


def measurement_raw(component_id: str, measurements: Mapping[str, MeasurementResult]) -> float:
    """The finite raw measurement value a term needs; failures refuse with their reason."""
    result = measurements.get(component_id)
    if result is None:
        raise ValueError("required measurement is missing")
    if result.failure is not None:
        raise ValueError(f"required measurement failed: {result.failure}")
    if result.value is None or not math.isfinite(result.value):
        raise ValueError("required measurement is null or nonfinite")
    return result.value


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
    measurements: Mapping[str, MeasurementResult] | None = None,
) -> tuple[MetricResult | NotScoreableResult, EvaluationEvidence]:
    """Require all referenced evidence; never silently renormalize missing terms.

    Declared constraints are judged on raw values beside the terms; a violation
    is a named failure, so an infeasible candidate is not scoreable (#1295).
    """
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
            if type(component) is MeasurementComponent:
                raw = measurement_raw(component.id, measurements or {})
            elif type(component) is MetricComponent:
                raw = _component_value(component, results, evaluation)
            else:
                raise ValueError("component kind has no runtime value support")
            resolved = evaluation.components[term.component]
            assert resolved.direction is not None
            item, contribution = term_evaluation(
                term, raw, total, resolved.direction, resolved.identity
            )
            evidence.append(item)
            contributions.append(contribution)
        except ValueError as error:
            failures.append(ScoreabilityFailure(requirement=term.component, detail=str(error)))
    constraints, violated = evaluate_constraints(
        constraint_terms(evaluation), results, measurements
    )
    failures.extend(violated)
    verdict = contract.evidence_verdict(tuple(failures))
    scalar = float(sum(contributions, Fraction())) if verdict.scoreable else None
    record = EvaluationEvidence(
        evaluation_sha256=evaluation.sha256,
        effective_metric_id=effective.id,
        source_metric_result=source,
        components=tuple(evidence),
        aggregate=scalar,
        failures=tuple(failures),
        constraints=constraints,
    )
    if not verdict.scoreable:
        return NotScoreableResult(
            metric_id=effective.id, direction=effective.direction, verdict=verdict
        ), record
    return MetricResult(
        metric_id=effective.id, direction=effective.direction, scalar=scalar
    ), record
