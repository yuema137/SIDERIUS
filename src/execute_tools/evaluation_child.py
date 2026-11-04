"""Scoring-child aggregation and validated source/effective evidence transport."""

from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING, Any

from execute_tools.evaluation_aggregation import (
    aggregate_evaluation,
    constrain_primary,
    evaluate_constraints,
    index_source_results,
    term_evaluation,
    weight_total,
)
from execute_tools.evaluation_metric import MetricResult, NotScoreableError, NotScoreableResult
from execute_tools.evaluation_results import (
    EvaluationEvidence,
    EvaluationTransportError,
    SelectionBinding,
)
from execute_tools.evaluation_validation import formula_terms
from workflows.evaluation_selection import SelectionCarrier, bound_selection

if TYPE_CHECKING:
    from workflows.task_composition import RunTaskComposition


class EvaluationNotScoreableError(NotScoreableError):
    def __init__(self, refusal: NotScoreableResult, evidence: EvaluationEvidence):
        super().__init__(refusal)
        self.evaluation_result = evidence


def aggregate_child_outcome(
    composition: RunTaskComposition | None,
    outcome: MetricResult | NotScoreableResult,
    secondaries: dict[str, Any],
) -> tuple[MetricResult | NotScoreableResult, dict[str, Any]]:
    if composition is None:
        return outcome, secondaries
    evaluation = composition.evaluation
    if evaluation is None:
        return outcome, secondaries
    results = [
        MetricResult.model_validate(r) for r in secondaries.get("secondary_metric_results", ())
    ]
    measurements = secondaries.get("measurement_results", ())
    if formula_terms(evaluation.spec):
        result, evidence = aggregate_evaluation(
            evaluation, composition.metric.spec, outcome, results, measurements
        )
    elif evaluation.spec.constraints:
        result, evidence = constrain_primary(
            evaluation, composition.metric.spec, outcome, results, measurements
        )
        if evidence is None:
            return result, secondaries
    else:
        return outcome, secondaries
    return result, {**secondaries, "evaluation_result": evidence.model_dump(mode="json")}


def validate_child_evaluation(
    results: dict[str, Any], composition: SelectionCarrier | None
) -> EvaluationEvidence | None:
    binding = bound_selection(composition)
    if binding is None:
        return None
    if not isinstance(results.get("evaluation_result"), dict):
        raise EvaluationTransportError("Scoring child omitted formula evaluation evidence")
    evidence = EvaluationEvidence.model_validate(results["evaluation_result"])
    spec = binding.effective_metric
    if (
        evidence.evaluation_sha256 != binding.evaluation_sha256
        or evidence.effective_metric_id != spec.id
    ):
        raise EvaluationTransportError(
            "Scoring child evaluation identity differs from the bound composition"
        )
    if evidence.failures:
        refusal = NotScoreableResult.model_validate(results.get("not_scoreable"))
        raise EvaluationNotScoreableError(refusal, evidence)
    if evidence.aggregate is None:
        raise EvaluationTransportError("Scoring child omitted the effective scalar")
    metric = MetricResult.model_validate(results.get("metric_result"))
    if metric.metric_id != spec.id or metric.direction != spec.direction:
        raise EvaluationTransportError("Scoring child effective metric identity mismatch")
    if not binding.is_formula and (
        evidence.source_metric_result is None
        or evidence.source_metric_result.scalar != evidence.aggregate
        or evidence.components
    ):
        raise EvaluationTransportError(
            "Constrained primary selection must adopt the source scalar unchanged"
        )
    if metric.scalar != evidence.aggregate or results.get("denoising_score") != evidence.aggregate:
        raise EvaluationTransportError(
            "Scoring child effective scalar disagrees with component evidence"
        )
    _validate_source_components(evidence, binding)
    _validate_component_arithmetic(evidence, binding, results)
    return evidence


def _validate_source_components(evidence: EvaluationEvidence, binding: SelectionBinding) -> None:
    source = evidence.source_metric_result
    if (
        source is None
        or source.metric_id != binding.source_metric.id
        or source.direction != binding.source_metric.direction
    ):
        raise EvaluationTransportError("Scoring child source identity mismatch")
    expected = tuple(binding.components)
    if tuple(c.component_id for c in evidence.components) != expected:
        raise EvaluationTransportError("Scoring child omitted or reordered required components")
    for item in evidence.components:
        if item.identity != binding.components[item.component_id]:
            raise EvaluationTransportError("Scoring child component identity mismatch")


def _validate_component_arithmetic(
    evidence: EvaluationEvidence, binding: SelectionBinding, results: dict[str, Any]
) -> None:
    """Re-derive every term and the aggregate from raw source values and the declaration.

    The parent never adopts a child's derived numbers on trust: each raw value
    must equal the transported source result it names, and normalization,
    utility, contribution and aggregate must equal the shared arithmetic.
    """
    assert evidence.source_metric_result is not None
    sources = index_source_results(
        [
            evidence.source_metric_result,
            *(MetricResult.model_validate(r) for r in results.get("secondary_metric_results", ())),
        ]
    )
    total = weight_total(t.term for t in binding.terms)
    aggregate = Fraction()
    for item, selection in zip(evidence.components, binding.terms, strict=True):
        source = sources.get(selection.source_metric_id or "")
        if source is None or selection.direction is None or source.scalar != item.raw:
            raise EvaluationTransportError(
                f"Component {item.component_id!r} raw value disagrees with its source result"
            )
        try:
            expected, contribution = term_evaluation(
                selection.term, item.raw, total, selection.direction, item.identity
            )
        except ValueError as error:
            raise EvaluationTransportError(
                f"Component {item.component_id!r} evidence violates its declaration: {error}"
            ) from error
        if expected != item:
            raise EvaluationTransportError(
                f"Component {item.component_id!r} evidence disagrees with recomputed arithmetic"
            )
        aggregate += contribution
    if binding.is_formula and float(aggregate) != evidence.aggregate:
        raise EvaluationTransportError("Scoring child aggregate disagrees with its components")
    expected_constraints, violated = evaluate_constraints(
        binding.constraints, sources, results.get("measurement_results", ())
    )
    if expected_constraints != evidence.constraints or violated:
        raise EvaluationTransportError(
            "Scoring child constraint verdicts disagree with the declared constraints"
        )


def evaluation_record_fields(results: dict[str, Any]) -> dict[str, Any]:
    if "evaluation_result" not in results:
        return {}
    evidence = EvaluationEvidence.model_validate(results["evaluation_result"])
    return {"evaluation_result": evidence.model_dump(mode="json")}


def read_scoring_output(path: str) -> dict[str, Any]:
    """The scoring child's ``--output_json`` payload, with non-finite values decoded.

    The single parent-side reader of that file. The child writes it through
    ``core.record_encoding``; a payload without encoding metadata is finite (or
    a legacy null projection) and is returned unchanged.
    """
    import json
    from pathlib import Path

    from core.record_encoding import decode_record

    payload = decode_record(json.loads(Path(path).read_text()))
    if not isinstance(payload, dict):
        raise ValueError("scoring output JSON must be an object")
    return payload


def scoring_refusal_fields(path: str) -> dict[str, Any]:
    """Recover only structured formula refusal evidence after a child exit."""
    try:
        payload = read_scoring_output(path)
    except (OSError, ValueError):
        return {}
    if "evaluation_result" not in payload:
        return {}
    evidence = EvaluationEvidence.model_validate(payload["evaluation_result"])
    refusal = NotScoreableResult.model_validate(payload.get("not_scoreable"))
    return {
        "results": {
            "not_scoreable": refusal.model_dump(mode="json"),
            "evaluation_result": evidence.model_dump(mode="json"),
            "denoising_score": None,
        }
    }


def source_health_inputs(results: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Preserve the original source scalar/vector for task Health checks."""
    if "evaluation_result" not in results:
        return kwargs
    from execute_tools.health_checks.schemas import PerSampleEvidence

    evidence = EvaluationEvidence.model_validate(results["evaluation_result"])
    source = evidence.source_metric_result
    if source is None:
        raise ValueError("Successful formula scoring requires source evidence for Health")
    return {
        **kwargs,
        "denoising_score": source.scalar,
        "file_vector": list(source.per_sample or []),
        "per_sample_evidence": PerSampleEvidence.for_per_sample(source.per_sample),
    }
