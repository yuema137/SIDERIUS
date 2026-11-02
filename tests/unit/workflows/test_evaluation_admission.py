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
            evaluation_sha256="a" * 64,
            source_metric=spec,
            effective_metric=spec,
            components={},
            terms=(),
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


def _loop_with_threshold(metric_id):
    from tests.unit.workflows.test_workflow_source import loop_document
    from workflows.definition import MetricThresholdStop, NoImprovementStop

    # Behind an earlier condition: admission must not stop at the first stop condition.
    return loop_document(
        NoImprovementStop(completed_bodies=2),
        MetricThresholdStop(metric_id=metric_id, threshold=0.5),
    ).definition


def _route_with_threshold(metric_id):
    import json

    from tests.unit.workflows.test_workflow_routes import routed
    from workflows.definition import WorkflowDefinition

    # A second route nested in any_of, behind a case that may match first.
    payload = routed().model_dump(mode="json")
    payload["nodes"] += [
        {"id": name, "capability": "proposal", "request": {"kind": "external", "binding": "seed"}}
        for name in ("spare", "other")
    ]
    payload["routes"].append(
        {
            "id": "score",
            "source": {"kind": "result", "node": "tune"},
            "cases": [
                {
                    "when": {
                        "kind": "enum_in",
                        "observable": "tuning.status",
                        "values": ["failed"],
                    },
                    "targets": ["spare"],
                },
                {
                    "when": {
                        "kind": "any_of",
                        "terms": [
                            {"kind": "is_missing", "observable": "tuning.valid_formal"},
                            {
                                "kind": "metric_at_least",
                                "observable": "tuning.valid_formal",
                                "metric_id": metric_id,
                                "threshold": 0.5,
                            },
                        ],
                    },
                    "targets": ["other"],
                },
            ],
        }
    )
    return WorkflowDefinition.model_validate_json(json.dumps(payload))


def _adaptor_with_threshold(metric_id):
    import json

    from tests.unit.workflows.test_adaptor_declarations import best_run
    from workflows.definition import WorkflowDefinition

    payload = best_run().model_dump(mode="json")
    payload["adaptors"][0]["select"] = {
        "kind": "threshold/v1",
        "basis": "metric",
        "metric_id": metric_id,
        "at_least": 0.5,
    }
    payload["adaptors"][0]["distribute"] = {"kind": "per-item/v1", "count": 2, "on_short": "skip"}
    return WorkflowDefinition.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "build",
    [_loop_with_threshold, _route_with_threshold, _adaptor_with_threshold],
    ids=["metric_threshold", "metric_at_least", "threshold/v1"],
)
def test_nested_authored_threshold_requires_effective_identity(build):
    """Defect: a source-unit threshold anywhere in a real declaration (a later loop stop,
    a nested route leaf in an unvisited case, a metric adaptor) reaches formula execution.

    Real ``WorkflowDefinition`` values: fails if the walk misses a declaration shape
    the schema actually serializes, or if an effective-unit threshold is refused.
    """
    from workflows.evaluation_admission import admit_formula_definition

    for refused in ("source", "component:quality"):
        definition = build(refused)
        with pytest.raises(ValueError, match="effective metric 'effective'"):
            admit_formula_definition(carrier(), definition)
    admit_formula_definition(carrier(), build("effective"))
    # Primary selection (no binding) leaves every declaration untouched.
    admit_formula_definition(SimpleNamespace(selection_binding=None), build("source"))
