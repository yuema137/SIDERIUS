"""Formula launches must reject unsupported routes and source-unit thresholds."""

from types import SimpleNamespace

import pytest

from execute_tools.evaluation_metric import MetricSpec, PresenceScoreabilityContract
from execute_tools.evaluation_results import SelectionBinding
from workflows.evaluation_admission import (
    admit_evaluation_settings,
    require_effective_target,
    require_formula_route,
)


def carrier():
    spec = MetricSpec(
        id="effective",
        direction="higher",
        aggregation="evaluation.weighted_sum/v1",
        scoreability=PresenceScoreabilityContract(),
    )
    return SimpleNamespace(
        selection_binding=SelectionBinding(
            evaluation_sha256="a" * 64, source_metric=spec, effective_metric=spec, components={}
        )
    )


@pytest.mark.parametrize("target", [None, "source", "component:quality"])
def test_legacy_target_units_refuse_before_any_work(target):
    with pytest.raises(ValueError, match="effective metric"):
        admit_evaluation_settings(
            carrier(), SimpleNamespace(target_score=0.8, target_score_metric=target)
        )


def test_explicit_effective_units_and_disabled_default_gates():
    admit_evaluation_settings(
        carrier(), SimpleNamespace(target_score=0.8, target_score_metric="effective")
    )
    admit_evaluation_settings(
        carrier(),
        SimpleNamespace(enable_chain_incumbent_formal_gates=True, score_units_metric="effective"),
    )
    with pytest.raises(ValueError, match="skip_formal_min_delta"):
        admit_evaluation_settings(
            carrier(), SimpleNamespace(enable_chain_incumbent_formal_gates=True)
        )
    with pytest.raises(ValueError, match="degenerate_penalty_score"):
        admit_evaluation_settings(carrier(), SimpleNamespace(degenerate_penalty_score=-1.0))


def test_anchor_route_is_named_and_absent_evaluation_is_unchanged():
    with pytest.raises(ValueError, match="ANCHOR_NORMALIZED"):
        require_formula_route(carrier(), "ANCHOR_NORMALIZED")
    require_formula_route(SimpleNamespace(selection_binding=None), "ANCHOR_NORMALIZED")
    admit_evaluation_settings(None, SimpleNamespace(target_score=3.0))


def test_raw_component_target_is_explicitly_unsupported():
    with pytest.raises(ValueError, match="raw component targets are not supported"):
        require_effective_target("component:quality", "effective", "metric_threshold")


def test_external_executor_refuses_before_dispatch(monkeypatch):
    monkeypatch.setattr(
        "execute_tools.evaluation_execution.candidate_evaluation_executor", lambda: object()
    )
    with pytest.raises(ValueError, match="CandidateEvaluationExecutor"):
        admit_evaluation_settings(carrier(), SimpleNamespace())
    admit_evaluation_settings(None, SimpleNamespace())


@pytest.mark.parametrize("kind", ["metric_threshold", "metric_at_least", "threshold/v1"])
def test_nested_authored_threshold_requires_effective_identity(kind):
    """Even a threshold in an unvisited branch must refuse before execution."""
    from workflows.evaluation_admission import admit_formula_definition

    threshold = {"kind": kind, "basis": "metric", "metric_id": "source"}
    definition = SimpleNamespace(model_dump=lambda **_: {"branches": [{"stop": threshold}]})
    with pytest.raises(ValueError, match="effective metric"):
        admit_formula_definition(carrier(), definition)
    threshold["metric_id"] = "effective"
    admit_formula_definition(carrier(), definition)
