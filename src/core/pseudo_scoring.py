"""Synthetic formula-evaluation evidence for pseudo scoring.

A composed run that declares a formula ``evaluation`` selection requires the
scoring child to transport component evidence; the parent rejects a payload
without it (``execute_tools.evaluation_child.validate_child_evaluation``).
StubSandbox launches no scoring child, so this module composes the same
transported manifest the child would, draws synthetic source metric values,
and passes them through the child's aggregation owner
(``aggregate_child_outcome``). No aggregation arithmetic is reimplemented
here, and no task identifier, label or Health threshold selects a value.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from execute_tools.evaluation_child import aggregate_child_outcome
from execute_tools.evaluation_metric import EvaluationMetric, MetricResult, NotScoreableResult
from execute_tools.evaluation_spec import MetricComponent
from execute_tools.evaluation_validation import formula_terms
from workflows.task_composition import active_task_manifest_path, compose_scoring_child_bindings


def _term_bounds(composition: Any) -> dict[str, tuple[float, float]]:
    """Map each formula-referenced metric id to its term's ``[lower, upper]``.

    Terms name distinct components and components name distinct metrics
    (``evaluation_validation``), so each metric has at most one term.
    """
    components = {c.id: c for c in composition.evaluation.spec.components}
    return {
        component.metric: (term.lower, term.upper)
        for term in formula_terms(composition.evaluation.spec)
        if isinstance(component := components[term.component], MetricComponent)
    }


def _declares_evaluation(manifest: str) -> bool:
    """Cheap pre-check so runs without ``evaluation`` never re-compose per call."""
    raw = yaml.safe_load(Path(manifest).read_text(encoding="utf-8"))
    return isinstance(raw, dict) and raw.get("evaluation") is not None


def _synthetic_result(
    metric: EvaluationMetric,
    rng: random.Random,
    bounds: dict[str, tuple[float, float]],
    fallback: float | None = None,
    per_sample: Sequence[float] | None = None,
) -> MetricResult:
    spec = metric.spec
    if spec.id in bounds:
        scalar = rng.uniform(*bounds[spec.id])
    else:
        # Unreferenced metrics keep the legacy synthetic band.
        scalar = rng.uniform(-3.0, -2.0) if fallback is None else fallback
    return MetricResult(
        metric_id=spec.id,
        direction=spec.direction,
        scalar=scalar,
        per_sample=None if per_sample is None else list(per_sample),
    )


def synthetic_formula_scoring(
    rng: random.Random, source_scalar: float, file_vector: Sequence[float]
) -> dict[str, Any] | None:
    """Scoring-child result fields for a formula-selection run, or ``None``.

    ``None`` means the run is un-composed or declares neither formula terms nor
    constraints (#1295, which judge the same synthetic values); the
    caller then keeps its legacy synthetic payload and random stream unchanged.
    Formula-referenced source metrics draw within their declared term bounds;
    an unreferenced primary keeps ``source_scalar``. A non-scoreable outcome
    (for example, a non-metric component) returns the child's refusal fields.
    """
    manifest = active_task_manifest_path()
    if manifest is None or not _declares_evaluation(manifest):
        return None
    metric, composition = compose_scoring_child_bindings(manifest)
    if composition is None or composition.evaluation is None:
        return None
    spec = composition.evaluation.spec
    if not (formula_terms(spec) or spec.constraints):
        return None
    bounds = _term_bounds(composition)
    primary = _synthetic_result(metric, rng, bounds, source_scalar, per_sample=file_vector)
    secondaries = {
        "secondary_metric_results": [
            _synthetic_result(m, rng, bounds).model_dump(mode="json")
            for m in composition.secondary_metrics
        ],
        "secondary_metric_refusals": [],
        "secondary_metric_errors": [],
    }
    outcome, fields = aggregate_child_outcome(composition, primary, secondaries)
    if isinstance(outcome, NotScoreableResult):
        return {
            **fields,
            "denoising_score": None,
            "file_vector": None,
            "not_scoreable": outcome.model_dump(mode="json"),
        }
    return {
        **fields,
        "denoising_score": outcome.scalar,
        "file_vector": outcome.per_sample,
        "metric_result": outcome.model_dump(mode="json", exclude={"per_sample"}),
    }
