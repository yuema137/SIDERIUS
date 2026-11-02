"""Receipt timing must prove dependencies, not merely valid placements (#1408)."""

import os
from pathlib import Path

import pytest

from tests.helpers.candidate_fanout import FALLBACK_ROUTE, routed_request, selection_request
from tools.candidate_worker import launch_candidate, parallel_dispatch
from tools.candidate_worker.graph_evidence import verify_graph_trace
from tools.candidate_worker.models import CandidateRunReceipt
from tools.candidate_worker.parallel_models import UnitReceipt

from .test_native import native_runner
from .test_parallel_dispatch import _budget, _parallel, _Starter
from .test_training import training_runner

__all__ = ["native_runner", "training_runner"]


def _launched(receipt: CandidateRunReceipt) -> CandidateRunReceipt:
    return CandidateRunReceipt.model_validate_json(
        (Path(receipt.workspace) / "candidate_run/launch.json").read_bytes()
    )


@pytest.mark.parametrize("shape", ["direct", "route", "fan-in"])
def test_consumer_cannot_start_before_a_source_ends(prepared, training_runner, monkeypatch, shape):
    """Swap adjacent end/start events: all old checks pass, only causality refuses."""
    base = _parallel(prepared, _budget(units=4))
    if shape == "route":
        route = {
            **FALLBACK_ROUTE,
            "cases": [
                {
                    "when": {"kind": "bool_is", "observable": "validation.passed", "value": True},
                    "targets": ["build1"],
                }
            ],
        }
        request = routed_request(prepared, routes=(route,))
    elif shape == "fan-in":
        request = selection_request(prepared)
    else:
        request = base
    request = request.model_copy(update={"parallel": base.parallel})
    monkeypatch.setattr(
        parallel_dispatch, "start_unit", _Starter(0, hold={"build0": 0, "build1": 0})
    )
    receipt = launch_candidate(request)
    assert receipt.graph_trace is not None, receipt.error
    initial = _launched(receipt)
    verify_graph_trace(request, initial, receipt)
    control = Path(receipt.workspace) / "candidate_run/units"
    target = {"direct": "check0", "route": "build1", "fan-in": "pick"}[shape]
    entries = {
        item.node_id: item for item in (*receipt.graph_trace.nodes, *receipt.graph_trace.adaptors)
    }
    records = {
        path.parent.name: UnitReceipt.model_validate_json(path.read_bytes())
        for path in control.glob("*/placement.json")
    }
    source = max(entries[target].predecessors, key=lambda key: records[key].ended_event)
    if shape == "route":
        assert source == "check0"  # control edge; build1's data comes from propose
    end, start = records[source].ended_event, records[target].started_event
    assert end < start
    for node, update in (
        (source, {"ended_event": start}),
        (target, {"started_event": end, "queued_event": None}),
    ):
        path = control / node / "placement.json"
        os.chmod(path, 0o600)
        path.write_text(records[node].model_copy(update=update).model_dump_json())
    with pytest.raises(ValueError, match="started before its sources ended"):
        verify_graph_trace(request, initial, receipt)


@pytest.mark.parametrize("units", [1, 2, 4])
@pytest.mark.parametrize("hold", [0, 1, 3, 8, 13])
@pytest.mark.parametrize(
    "failing",
    [
        (),
        ("build0",),
        ("build1",),
        ("build0", "build1"),
        ("check0",),
        ("check1",),
        ("check0", "check1"),
        ("build0", "check1"),
        ("check0", "build1"),
        ("propose",),
        ("build0", "build1", "check0", "check1"),
        ("build1", "check1"),
    ],
)
def test_real_dispatcher_causality_enumeration(
    prepared, native_runner, monkeypatch, units, hold, failing
):
    """180 real scheduler traces vary failures, completion delays and available slots."""
    starter = _Starter(
        3,
        failing=frozenset(failing),
        hold={"build0": hold, "build1": 0, "check0": hold, "check1": 0},
    )
    monkeypatch.setattr(parallel_dispatch, "start_unit", starter)
    monkeypatch.setattr(parallel_dispatch, "POLL_SECONDS", 0)
    request = _parallel(prepared, _budget(units=units))
    receipt = launch_candidate(request)
    assert receipt.graph_trace is not None, receipt.error
    assert receipt.status == ("failed" if failing else "accepted"), receipt.error
    verify_graph_trace(request, _launched(receipt), receipt)
