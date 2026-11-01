"""Scoring-child aggregation and validated source/effective evidence transport."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from execute_tools.evaluation_aggregation import aggregate_evaluation
from execute_tools.evaluation_metric import MetricResult, NotScoreableError, NotScoreableResult
from execute_tools.evaluation_results import EvaluationEvidence, SelectionBinding
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
    if evaluation is None or not formula_terms(evaluation.spec):
        return outcome, secondaries
    result, evidence = aggregate_evaluation(
        evaluation,
        composition.metric.spec,
        outcome,
        [MetricResult.model_validate(r) for r in secondaries.get("secondary_metric_results", ())],
    )
    return result, {**secondaries, "evaluation_result": evidence.model_dump(mode="json")}


def validate_child_evaluation(
    results: dict[str, Any], composition: SelectionCarrier | None
) -> EvaluationEvidence | None:
    binding = bound_selection(composition)
    if binding is None:
        return None
    evidence = EvaluationEvidence.model_validate(results.get("evaluation_result"))
    spec = binding.effective_metric
    if (
        evidence.evaluation_sha256 != binding.evaluation_sha256
        or evidence.effective_metric_id != spec.id
    ):
        raise ValueError("Scoring child evaluation identity differs from the bound composition")
    if evidence.failures:
        refusal = NotScoreableResult.model_validate(results.get("not_scoreable"))
        raise EvaluationNotScoreableError(refusal, evidence)
    if evidence.aggregate is None:
        raise ValueError("Scoring child omitted the effective scalar")
    metric = MetricResult.model_validate(results.get("metric_result"))
    if metric.metric_id != spec.id or metric.direction != spec.direction:
        raise ValueError("Scoring child effective metric identity mismatch")
    if metric.scalar != evidence.aggregate or results.get("denoising_score") != evidence.aggregate:
        raise ValueError("Scoring child effective scalar disagrees with component evidence")
    _validate_source_components(evidence, binding)
    return evidence


def _validate_source_components(evidence: EvaluationEvidence, binding: SelectionBinding) -> None:
    source = evidence.source_metric_result
    if (
        source is None
        or source.metric_id != binding.source_metric.id
        or source.direction != binding.source_metric.direction
    ):
        raise ValueError("Scoring child source identity mismatch")
    expected = tuple(binding.components)
    if tuple(c.component_id for c in evidence.components) != expected:
        raise ValueError("Scoring child omitted or reordered required components")
    for item in evidence.components:
        if item.identity != binding.components[item.component_id]:
            raise ValueError("Scoring child component identity mismatch")


def evaluation_record_fields(results: dict[str, Any]) -> dict[str, Any]:
    if "evaluation_result" not in results:
        return {}
    evidence = EvaluationEvidence.model_validate(results["evaluation_result"])
    return {"evaluation_result": evidence.model_dump(mode="json")}


def scoring_refusal_fields(path: str) -> dict[str, Any]:
    """Recover only structured formula refusal evidence after a child exit."""
    import json
    from pathlib import Path

    try:
        payload = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict) or "evaluation_result" not in payload:
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
