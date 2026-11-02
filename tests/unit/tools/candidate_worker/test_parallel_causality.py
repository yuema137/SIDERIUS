"""Receipt timing must prove dependencies, not merely valid placements (#1408)."""

import os
from itertools import product
from pathlib import Path

import pytest

from tests.helpers.candidate_fanout import FALLBACK_ROUTE, routed_request, selection_request
from tools.candidate_worker import adaptor_phase, launch_candidate, parallel_dispatch, readiness
from tools.candidate_worker.graph_evidence import DrainWindow, verify_graph_trace
from tools.candidate_worker.graph_models import DISPATCHED_STATES, GraphNodeEvidence
from tools.candidate_worker.models import CandidateRunReceipt
from tools.candidate_worker.parallel_evidence import _check_causality
from tools.candidate_worker.parallel_models import UnitReceipt
from tools.candidate_worker.unit_models import unit_paths

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


# See ../README.md and parallel-causality-testing.md for coverage and opt-in usage.
_FAILURES = (
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
)
# Hold vectors are build0, build1, check0, check1. Preserve the original
# matrix first, then cross independent branch/check timings with every failure set.
_HOLDS = tuple((hold, 0, hold, 0) for hold in (0, 1, 3, 8, 13))
_CROSS_BRANCH_HOLDS = ((0, 3, 1, 1), (8, 8, 1, 2), (3, 0, 0, 2))
# Product index -> expected per-node outcome at the first failure.
_REPRESENTATIVES = {
    0: "SSSSS",
    8: "SSSSS",
    15: "SF---",
    19: "SFD--",
    22: "SFS-S",
    30: "SSFS-",
    34: "SSF--",
    37: "SDF--",
    49: "SFf--",
    52: "SfF--",
    60: "SS-F-",
    64: "SSSFD",
    67: "SSSFS",
    75: "SSSSF",
    82: "SDS-F",
    94: "SSSFf",
    112: "SfS-F",
    135: "F----",
    196: "SFS-D",
    202: "SSFD-",
    217: "SSDF-",
    250: "SFS-f",
    253: "SSfF-",
    256: "SSFf-",
}


def _enumeration_cases():
    full = os.environ.get("SIDERIUS_FULL_PARALLEL_CAUSALITY") == "1"
    combinations = (
        *product(_FAILURES, _HOLDS, (1, 2, 4)),
        *product(_FAILURES, _CROSS_BRANCH_HOLDS, (1, 2, 4)),
    )
    return [
        pytest.param(failing, hold, units, _REPRESENTATIVES.get(index), id=f"trace-{index}")
        for index, (failing, hold, units) in enumerate(combinations)
        if full or index in _REPRESENTATIVES
    ]


def _failure_order(receipt: CandidateRunReceipt) -> str:
    """S: completed; F: first failure; D/f: draining success/failure; -: undispatched."""
    control = Path(receipt.workspace) / "candidate_run/units"
    records = {
        path.parent.name: UnitReceipt.model_validate_json(path.read_bytes())
        for path in control.glob("*/placement.json")
    }
    first = min((r.ended_event for r in records.values() if r.exit != "returned"), default=None)
    return "".join(
        _receipt_order(records.get(node), first)
        for node in ("propose", "build0", "build1", "check0", "check1")
    )


def _receipt_order(record: UnitReceipt | None, first: int | None) -> str:
    if record is None:
        return "-"
    if record.ended_event == first:
        return "F"
    if first is not None and record.ended_event > first:
        return "D" if record.exit == "returned" else "f"
    return "S"


@pytest.mark.parametrize("failing,hold,units,expected", _enumeration_cases())
def test_real_dispatcher_causality_enumeration(
    prepared, native_runner, monkeypatch, units, hold, failing, expected
):
    """Real dispatcher representatives; opt in to all 288 timing/capacity combinations."""
    starter = _Starter(
        3,
        failing=frozenset(failing),
        hold=dict(zip(("build0", "build1", "check0", "check1"), hold, strict=True)),
    )
    monkeypatch.setattr(parallel_dispatch, "start_unit", starter)
    monkeypatch.setattr(parallel_dispatch, "POLL_SECONDS", 0)
    request = _parallel(prepared, _budget(units=units))
    receipt = launch_candidate(request)
    assert receipt.graph_trace is not None, receipt.error
    assert receipt.status == ("failed" if failing else "accepted"), receipt.error
    verify_graph_trace(request, _launched(receipt), receipt)
    if expected is not None:
        assert _failure_order(receipt) == expected
    if expected is not None and not failing and units > 1:
        assert any(len(active) > 1 for active in starter.overlaps)


def test_adaptor_waits_for_the_source_of_a_skipped_route_arm():
    """Without traversal through X, pick appears source-free and its forged start passes."""
    entries = {
        "check0": GraphNodeEvidence(
            node_id="check0",
            capability="validation",
            predecessors=(),
            storage="check0",
            state="succeeded",
        ),
        "X": GraphNodeEvidence(
            node_id="X",
            capability="implementation",
            predecessors=("check0",),
            storage="X",
            state="skipped",
            reason="route_not_selected",
        ),
        "pick": GraphNodeEvidence(
            node_id="pick",
            capability="adaptor",
            predecessors=("X",),
            storage="pick",
            state="rejected",
            reason="no_admissible_input",
        ),
    }
    # X has no receipt. Its route decision can only close it after check0 ends.
    source = UnitReceipt(
        node_id="check0",
        started_event=1,
        ended_event=2,
        started_at="start",
        ended_at="end",
        exit="returned",
    )
    pick = UnitReceipt(
        node_id="pick",
        started_event=3,
        ended_event=4,
        started_at="start",
        ended_at="end",
        exit="returned",
    )
    _check_causality(
        {"check0": source, "pick": pick},
        entries,
        DrainWindow(ended={"check0": 2, "pick": 4}, failure_end=None),
    )
    # Swap source end and pick start: both receipts remain internally ordered,
    # and the global event permutation is preserved. Only the dependency is false.
    forged_source = source.model_copy(update={"ended_event": 3})
    forged_pick = pick.model_copy(update={"started_event": 2})
    with pytest.raises(ValueError, match="'pick' started before its sources ended"):
        _check_causality(
            {"check0": forged_source, "pick": forged_pick},
            entries,
            DrainWindow(ended={"check0": 3, "pick": 4}, failure_end=None),
        )


# Dispatched adaptor states (#1454): see parallel-causality-testing.md.
_TERMINAL = (
    ("succeeded", None),
    ("rejected", "validation_rejected"),
    ("failed", "native_failure"),
    ("blocked", "dependency_not_successful"),
    ("skipped", "route_not_selected"),
    ("skipped", "insufficient_items"),
)


def test_adaptor_states_share_the_one_dispatched_definition():
    """Fails if an adaptor can end ``skipped`` (or any non-dispatched state) after
    running, or readiness can close one other than ``blocked``: then a valid
    parallel trace's receipt check (``_dispatched``) and readiness replay
    (``DISPATCHED_STATES``) would disagree about that adaptor."""
    from typing import get_args

    from workflows.adaptors.run import AdaptorOutcome

    assert frozenset(get_args(AdaptorOutcome.model_fields["status"].annotation)) == (
        DISPATCHED_STATES
    )
    for (left, left_reason), (right, right_reason), aborted in product(
        _TERMINAL, _TERMINAL, (False, True)
    ):
        nodes = (
            readiness.NodeReadiness(node_id="a", predecessors=(), state=left, reason=left_reason),
            readiness.NodeReadiness(node_id="b", predecessors=(), state=right, reason=right_reason),
            readiness.NodeReadiness(
                node_id="pick", predecessors=("a", "b"), state="pending", kind="adaptor"
            ),
        )
        step = readiness.next_dispatch(readiness.ReadinessInput(nodes=nodes, aborted=aborted))
        assert step.next == "pick" or step.terminal == (
            ("pick", "blocked", "dependency_not_successful"),
        ), (left, right, aborted, step)


def _selection_run(prepared, monkeypatch, failing: frozenset[str] = frozenset()):
    """S1 fan-in (``pick``) under the real parallel dispatcher."""
    base = _parallel(prepared, _budget(units=4))
    request = selection_request(prepared).model_copy(update={"parallel": base.parallel})
    monkeypatch.setattr(parallel_dispatch, "start_unit", _Starter(0, failing=failing))
    monkeypatch.setattr(parallel_dispatch, "POLL_SECONDS", 0)
    receipt = launch_candidate(request)
    assert receipt.graph_trace is not None, receipt.error
    return request, receipt


@pytest.mark.parametrize("outcome", ["succeeded", "rejected", "failed", "blocked"])
def test_real_dispatcher_adaptor_states_verify(
    prepared, native_runner, training_runner, monkeypatch, outcome
):
    """Each reachable adaptor state, produced by the real parallel dispatcher, is
    accepted, and it has a receipt iff it is in ``DISPATCHED_STATES``. Fails if the
    receipt check and the replay define an executed adaptor differently.

    The rejected adaptor relabelled ``skipped`` (no record, a skip reason; its
    consumer stays blocked) is refused with its receipt (receipt check) and
    without it (readiness replay): no run produces that state, so neither
    definition may accept it."""
    if outcome == "rejected":  # every validation rejects: nothing admissible
        native_runner.reject = True
    elif outcome == "failed":

        def raising(*args, **kwargs):
            raise RuntimeError("adaptor fault")

        monkeypatch.setattr(adaptor_phase, "decide", raising)
    # A failed source closes the adaptor undispatched.
    failing = frozenset({"check0"} if outcome == "blocked" else ())
    request, receipt = _selection_run(prepared, monkeypatch, failing)
    (pick,) = receipt.graph_trace.adaptors
    assert pick.state == outcome
    initial = _launched(receipt)
    path = unit_paths(initial, "pick", iteration=1)[0].with_name("placement.json")
    assert path.exists() == (pick.state in DISPATCHED_STATES)
    verify_graph_trace(request, initial, receipt)
    if outcome != "rejected":
        return
    forged = pick.model_copy(
        update={
            "state": "skipped",
            "reason": "insufficient_items",
            "record_path": None,
            "record_sha256": None,
        }
    )
    skipped = receipt.model_copy(
        update={"graph_trace": receipt.graph_trace.model_copy(update={"adaptors": (forged,)})}
    )
    with pytest.raises(ValueError, match="'pick' receipt contradicts its state"):
        verify_graph_trace(request, initial, skipped)
    path.rename(path.with_name("placement.json.moved"))
    with pytest.raises(ValueError, match="violates serial readiness"):
        verify_graph_trace(request, initial, skipped)
