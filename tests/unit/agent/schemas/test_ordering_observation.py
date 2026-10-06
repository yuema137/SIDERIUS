"""Current absence is explicit; historical serialization and reading stay intact."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import ExperimentRecord
from agent.schemas.ordering import ResolvedOrdering
from nodes.result_interpretation_agent.evidence import _round_ordering
from workflows.run_one_iteration import _ordering_by_experiment


def record(**overrides):
    return ExperimentRecord.model_validate(
        {
            "exp_id": "e1",
            "status": "error",
            "model_type": "synthetic",
            "timestamp": "2026-10-06T00:00:00Z",
            "params": {},
            **overrides,
        }
    )


def test_explicit_unresolved_and_legacy_absence_are_different_after_reload():
    old = record()
    current = record(ordering_observation={"selection_state": "unresolved"})
    assert "ordering_observation" not in old.model_dump()
    assert "ordering_observation" not in _round_ordering(old).model_dump()
    reloaded = [ExperimentRecord.model_validate_json(r.model_dump_json()) for r in [old, current]]
    views = [_round_ordering(r) for r in reloaded]
    assert [(v.resolution_source, v.resolved_order_strategy) for v in views] == [
        ("legacy_default", "shuffle"),
        ("unresolved", None),
    ]
    manifests = _ordering_by_experiment(SimpleNamespace(all_records=reloaded))
    assert "ordering_observation" not in manifests[0]
    assert manifests[1]["ordering_observation"]["selection_state"] == "unresolved"


@pytest.mark.parametrize("phase", ["preflight", "training", "inference"])
def test_selection_survives_refusal_without_inferring_traversal(phase):
    current = record(
        status="skipped_resource_admission",
        resolved_order_strategy="sequential",
        resolved_file_order=[2, 0, 1],
        ordering_resolution_source="operator_override",
        ordering_observation={"selection_state": "selected", "refused_before_phase": phase},
    )
    view = _round_ordering(current)
    assert view.resolved_file_order == [2, 0, 1]
    assert view.ordering_observation.refused_before_phase == phase
    assert view.resolution_source == "operator_override"


@pytest.mark.parametrize(
    "fields",
    [
        {
            "ordering_observation": {"selection_state": "unresolved"},
            "resolved_order_strategy": "shuffle",
        },
        {
            "ordering_observation": {"selection_state": "unresolved"},
            "ordering_resolution_source": "default",
        },
        {"ordering_observation": {"selection_state": "selected"}},
        {
            "ordering_observation": {"selection_state": "selected"},
            "resolved_order_strategy": "shuffle",
            "ordering_resolution_source": "legacy_default",
        },
        {
            "ordering_observation": {"selection_state": "selected"},
            "resolved_order_strategy": "shuffle",
            "ordering_resolution_source": "default",
            "resolved_file_order": [0],
        },
        {
            "ordering_observation": {"selection_state": "selected"},
            "resolved_order_strategy": "sequential",
            "ordering_resolution_source": "default",
            "resolved_file_order": [0, 0],
        },
    ],
)
def test_contradictory_current_evidence_is_refused_at_ingress_and_reader(fields):
    with pytest.raises(ValidationError):
        record(**fields)
    with pytest.raises(ValueError):
        ResolvedOrdering.from_record(SimpleNamespace(**fields))


def test_old_preflight_shape_is_not_rewritten_as_current_selection():
    old = record(status="skipped_time_risk")
    view = _round_ordering(old)
    assert view.resolution_source == "not_executed"
    assert view.resolved_order_strategy is None
    assert "ordering_observation" not in view.model_dump()
