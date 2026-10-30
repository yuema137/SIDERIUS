"""Failure attribution and completed counts must come from verified iterations."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.unit.tools.candidate_console.test_loop_stop import _snapshot
from tools.candidate_console import outcomes, service
from tools.candidate_worker.graph_models import GraphNodeEvidence, GraphTrace
from tools.candidate_worker.loop_models import LoopTrace
from tools.candidate_worker.models import CandidateRunReceipt


def receipt(status, phases=()):
    return CandidateRunReceipt(
        run_id="run",
        run_name="run",
        workspace="/fixture",
        declaration_digest="d" * 64,
        status=status,
        node_ids=(),
        selected_constructor_routes=(),
        ledger_path="ledger",
        log_path="log",
        validation_passed=False,
        graph_trace=GraphTrace(
            nodes=tuple(
                GraphNodeEvidence(
                    node_id=str(index),
                    capability=phase,
                    predecessors=(),
                    storage="storage",
                    state=state,
                )
                for index, (phase, state) in enumerate(phases)
            )
        ),
    )


@pytest.mark.parametrize(
    "phases,expected",
    [
        ([("proposal", "failed"), ("validation", "blocked")], ("Propose model",)),
        ([("validation", "rejected")], ()),
        ([("implementation", "failed"), ("tuning", "failed")], ("Implement", "Train & tune")),
        ([], ()),
    ],
)
def test_phase_names_only_failed_nodes(console_config, phases, expected):
    observed = outcomes.outcome_evidence(
        console_config.operation_store, _snapshot(uuid4(), receipt("failed", phases))
    )
    assert observed is not None
    assert observed.failed_phases == expected


@pytest.mark.parametrize(
    "completed,final_status", [(0, "failed"), (1, "failed"), (3, "completed"), (2, "paused")]
)
def test_loop_counts_verified_completed_receipts(
    console_config, monkeypatch, completed, final_status
):
    bodies = tuple(receipt("completed") for _ in range(completed))
    if final_status == "failed":
        bodies += (receipt("failed", [("proposal", "failed")]),)
    aggregate = receipt(final_status).model_copy(
        update={"graph_trace": None, "loop_trace": LoopTrace(attempted_iterations=len(bodies))}
    )
    root = object()
    monkeypatch.setattr(outcomes, "loop_root_operation", lambda *args: root)
    calls = []

    def verified(submission, terminal):
        calls.append((submission, terminal))
        return bodies

    monkeypatch.setattr(outcomes, "verified_bodies", verified)
    observed = outcomes.outcome_evidence(
        console_config.operation_store, _snapshot(uuid4(), aggregate)
    )
    assert observed is not None
    assert observed.completed_iterations == completed
    assert observed.failed_phases == (("Propose model",) if final_status == "failed" else ())
    assert calls == [(root, aggregate)]


def test_status_and_list_share_receipt_outcome(console_config, monkeypatch):
    snapshot = _snapshot(uuid4(), receipt("failed", [("proposal", "failed")]))
    monkeypatch.setattr(service, "operation_admitted", lambda *args: True)
    monkeypatch.setattr(service, "read_operation", lambda *args: snapshot)
    monkeypatch.setattr(service, "loop_status", lambda *args, **kwargs: None)
    entry = SimpleNamespace(snapshot=snapshot, run_name="run", project_id=None, admitted_at="now")
    monkeypatch.setattr(
        service,
        "list_operations",
        lambda *args: SimpleNamespace(entries=[entry], unreadable=0, examined=1, incomplete=False),
    )
    console = service.CandidateConsole(console_config)
    status = console.status(snapshot.operation_id)
    listed = console.operations().operations[0]
    assert status.outcome == listed.outcome
    assert listed.outcome is not None and listed.outcome.validation_passed is False
    assert status.outcome is not None and status.outcome.failed_phases == ("Propose model",)
