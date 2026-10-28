"""Routed execution profile (B1-PR5): Q1(a) fallback arm over the S1 selection shape.

Offline pseudo integration: real native node bodies with a stub provider, real
readiness, route evaluation, adaptor execution and verifier re-derivation; only the
tuner is stubbed. `check0` passing skips the fallback branch `build1`/`check1`;
`check0` rejecting runs it, and the first-admissible adaptor trains its candidate.
"""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from tests.helpers.candidate_fanout import (
    FALLBACK_ROUTE,
    ROUTED_PROFILE,
    SELECTION_PROFILE,
    SELECTION_TRACE_SHA256,
    routed_request,
    selection_request,
    trace_projection,
)
from tools.candidate_worker import launch_candidate, route_phase
from tools.candidate_worker.graph_evidence import verify_graph_trace
from tools.candidate_worker.route_eval import RouteConditionError
from workflows.definition.candidate import ROUTING_NOT_ADMITTED
from workflows.definition.fanout import execution_families

from .test_adaptor_selection import record, rejecting, states, trained
from .test_graph import initial
from .test_native import native_runner as native_runner
from .test_training import training_runner as training_runner

__all__ = ["native_runner", "rejecting", "trained", "training_runner"]

SKIP = ("skipped", "route_not_selected")


def run(request):
    receipt = launch_candidate(request)
    parent = initial(request).model_copy(update={"run_id": receipt.run_id})
    return receipt, parent


def test_passing_first_validator_skips_the_fallback_arm(
    prepared, training_runner, rejecting, trained
):
    """Default arm: no case matched, so build1/check1 never run and build0 trains.

    Fails if the route is ignored (build1 would be dispatched) or if the skipped
    adaptor input lacks a skip record citing the deciding route evidence.
    """
    request = routed_request(prepared)
    receipt, parent = run(request)
    assert receipt.status == "completed", receipt.error
    assert states(receipt)["build1"] == SKIP and states(receipt)["check1"] == SKIP
    ((implementation, _),) = trained
    assert "/build0/" in implementation.model_file_path
    (evidence,) = receipt.graph_trace.routes
    assert (evidence.decision.selected_case, evidence.decision.skipped_targets) == (
        None,
        ("build1",),
    )
    cited = {item["ref"]["source"]["node"]: item for item in record(receipt)["admissible"]}
    assert cited["check1"]["admission"] == "skipped"
    assert cited["check1"]["ref"]["record_sha256"] == route_phase.evidence_digest(evidence)
    assert receipt.validation_passed is True
    verify_graph_trace(request, parent, receipt)


def test_rejected_first_validator_runs_the_fallback_and_rescues_the_body(
    prepared, training_runner, rejecting, trained
):
    """Case 0: check0 rejects, so the control-only edge lets build1 run (B1-Q1).

    Fails under the PR4 rule (a rejected route source blocks its targets): build1
    would be blocked, the adaptor would select nothing and the body be rejected.
    """
    rejecting.add(0)
    request = routed_request(prepared)
    receipt, parent = run(request)
    assert receipt.status == "completed", receipt.error
    assert states(receipt)["check0"] == ("rejected", "validation_rejected")
    assert states(receipt)["build1"] == ("succeeded", None)
    ((implementation, validation),) = trained
    assert "/build1/" in implementation.model_file_path and validation.passed
    assert receipt.graph_trace.routes[0].decision.selected_targets == ("build1",)
    assert receipt.validation_passed is True
    verify_graph_trace(request, parent, receipt)


def test_both_rejected_rejects_the_body_and_blocks_tuning(
    prepared, training_runner, rejecting, trained
):
    rejecting.update((0, 1))
    request = routed_request(prepared)
    receipt, parent = run(request)
    assert states(receipt)["pick"] == ("rejected", "no_admissible_input")
    assert states(receipt)["train"] == ("blocked", "dependency_not_successful")
    assert trained == []
    assert (receipt.status, receipt.validation_passed) == ("rejected", False)
    verify_graph_trace(request, parent, receipt)


def _forge_trace(receipt, **update):
    return receipt.model_copy(update={"graph_trace": receipt.graph_trace.model_copy(update=update)})


def test_verifier_re_derives_route_decisions(prepared, training_runner, rejecting, trained):
    """A forged decision, a forged source digest or a dropped decision is refused."""
    request = routed_request(prepared)
    receipt, parent = run(request)
    assert receipt.status == "completed", receipt.error
    (evidence,) = receipt.graph_trace.routes
    flipped = evidence.decision.model_copy(
        update={
            "selected_case": 0,
            "selected_targets": ("build1",),
            "skipped_targets": (),
            "case_results": (True,),
        }
    )
    forgeries = (
        (evidence.model_copy(update={"decision": flipped}),),
        (evidence.model_copy(update={"source_record_sha256": "0" * 64}),),
    )
    for routes in forgeries:
        with pytest.raises(ValueError, match="route evidence does not match"):
            verify_graph_trace(request, parent, _forge_trace(receipt, routes=routes))
    with pytest.raises(ValueError, match="route evidence does not match"):
        verify_graph_trace(request, parent, _forge_trace(receipt, routes=()))


def test_route_metric_mismatch_is_refused_before_any_dispatch(
    prepared, training_runner, monkeypatch, native_runner
):
    """Fails if route metric admission ran after a node: a record would be orphaned."""
    calls = []

    def refuse(branches, metric):
        calls.append(metric)
        raise RouteConditionError("route fallback names metric 'other'")

    monkeypatch.setattr(route_phase, "admit_route_metrics", refuse)
    request = routed_request(prepared)
    receipt, _ = run(request)
    assert receipt.status == "failed" and receipt.graph_trace is None
    assert calls and calls[0] is not None  # the composed run metric, derived once
    assert not (Path(receipt.workspace) / request.run_name / "graph_instances").exists()


def test_routed_documents_are_refused_by_every_other_profile(prepared):
    definition = routed_request(prepared).preview.document.definition
    assert execution_families(definition, ROUTED_PROFILE).selection is not None
    for profile in (SELECTION_PROFILE, "native-proposal-fanout/v1"):
        with pytest.raises(ValueError, match=ROUTING_NOT_ADMITTED):
            execution_families(definition, profile)
    unrouted = selection_request(prepared).preview.document.definition
    with pytest.raises(ValueError, match="requires at least one declared route"):
        execution_families(unrouted, ROUTED_PROFILE)


@pytest.mark.parametrize("rejected", sorted(SELECTION_TRACE_SHA256))
def test_unrouted_selection_trace_bytes_are_unchanged(
    prepared, training_runner, rejecting, trained, rejected
):
    """Fails if routed execution moves the bytes of an existing selection run."""
    rejecting.update(rejected)
    request = selection_request(prepared)
    receipt, parent = run(request)
    payload = trace_projection(receipt)
    assert hashlib.sha256(payload.encode()).hexdigest() == SELECTION_TRACE_SHA256[rejected]
    assert '"routes"' not in payload
    verify_graph_trace(request, parent, receipt)


def test_console_graph_results_list_the_skipped_arm(
    prepared, training_runner, rejecting, trained, monkeypatch
):
    from tools.candidate_console import graph_results
    from tools.candidate_operations.models import CandidateOperation

    request = routed_request(prepared)
    receipt, _ = run(request)
    assert receipt.status == "completed", receipt.error
    operation_id = UUID(hex=receipt.run_id)
    monkeypatch.setattr(
        graph_results,
        "read_operation",
        lambda *_: SimpleNamespace(state="completed", receipt=receipt),
    )
    monkeypatch.setattr(
        graph_results,
        "lookup_operation_request",
        lambda *_: CandidateOperation(request_id=operation_id, request=request),
    )
    view = graph_results.read_graph_results(SimpleNamespace(operation_store=object()), operation_id)
    (body,) = view.bodies
    assert body.tuning_state == "succeeded" and body.result is not None
    assert [(item.node_id, item.reason) for item in body.skipped] == [
        ("build1", "route_not_selected"),
        ("check1", "route_not_selected"),
    ]
    assert json.loads(view.model_dump_json())["bodies"][0]["skipped"][0]["node_id"] == "build1"


def test_fallback_route_declares_a_control_only_target(prepared):
    """The fallback target reads only the proposal: its route edge is control-only."""
    definition = routed_request(prepared).preview.document.definition
    routing = route_phase.node_routing(definition)
    assert routing["build1"].route == FALLBACK_ROUTE["id"]
    assert routing["build1"].control == "check0"
    assert set(routing) == {"build1"}
