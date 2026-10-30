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
        ([("proposal", "failed"), ("validation", "blocked")], ("proposal",)),
        ([("validation", "rejected")], ()),
        ([("implementation", "failed"), ("tuning", "failed")], ("implementation", "tuning")),
        ([("proposal", "failed"), ("proposal", "failed")], ("proposal",)),
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
    assert observed.failed_phases == (("proposal",) if final_status == "failed" else ())
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
    assert status.outcome is not None and status.outcome.failed_phases == ("proposal",)


def test_list_keeps_good_rows_when_one_loop_outcome_refuses(console_config, monkeypatch):
    """A late loop integrity refusal degrades only its row; status still refuses."""
    from tools.candidate_operations.models import OperationFailure

    good = _snapshot(uuid4(), receipt("failed", [("proposal", "failed")]))
    corrupt = _snapshot(
        uuid4(),
        receipt("failed").model_copy(
            update={
                "graph_trace": None,
                "loop_trace": LoopTrace(attempted_iterations=1),
            }
        ),
    )
    monkeypatch.setattr(service, "loop_status", lambda *args, **kwargs: None)
    entries = [
        SimpleNamespace(snapshot=value, run_name="run", project_id=None, admitted_at="now")
        for value in (good, corrupt, good.model_copy(update={"operation_id": uuid4()}))
    ]
    monkeypatch.setattr(
        service,
        "list_operations",
        lambda *args: SimpleNamespace(entries=entries, unreadable=0, examined=3, incomplete=False),
    )
    monkeypatch.setattr(outcomes, "loop_root_operation", lambda *args: object())

    def refuse(*args):
        raise OperationFailure("integrity", "verified loop iterations are unavailable")

    monkeypatch.setattr(outcomes, "verified_bodies", refuse)
    console = service.CandidateConsole(console_config)
    rows = console.operations().operations
    assert len(rows) == 3 and rows[1].outcome is None
    assert rows[0].outcome is not None and rows[0].outcome.failed_phases == ("proposal",)
    assert rows[2].outcome == rows[0].outcome
    monkeypatch.setattr(service, "operation_admitted", lambda *args: True)
    monkeypatch.setattr(service, "read_operation", lambda *args: corrupt)
    with pytest.raises(OperationFailure, match="unavailable"):
        console.status(corrupt.operation_id)


def test_list_outcome_cache_uses_receipt_identity_but_status_rechecks(console_config, monkeypatch):
    from tools.candidate_console.models import OutcomeEvidence
    from tools.candidate_operations.models import OperationFailure

    snapshot = _snapshot(uuid4(), receipt("failed")).model_copy(update={"receipt_digest": "a" * 64})
    calls = []

    def project(store, value):
        calls.append(value.receipt_digest)
        return OutcomeEvidence(failed_phases=("proposal",))

    monkeypatch.setattr(service, "outcome_evidence", project)
    console = service.CandidateConsole(console_config)
    assert console._list_outcome(snapshot) == console._list_outcome(snapshot)
    assert calls == ["a" * 64]
    changed = snapshot.model_copy(update={"receipt_digest": "b" * 64})
    console._list_outcome(changed)
    assert calls == ["a" * 64, "b" * 64]

    def refuse(*args):
        raise OperationFailure("integrity", "changed loop evidence")

    monkeypatch.setattr(service, "outcome_evidence", refuse)
    monkeypatch.setattr(service, "operation_admitted", lambda *args: True)
    monkeypatch.setattr(service, "read_operation", lambda *args: snapshot)
    with pytest.raises(OperationFailure, match="changed loop evidence"):
        console.status(snapshot.operation_id)
    uncached = snapshot.model_copy(update={"receipt_digest": "c" * 64})
    with pytest.raises(OperationFailure, match="changed loop evidence"):
        console._list_outcome(uncached)
    monkeypatch.setattr(service, "outcome_evidence", project)
    assert console._list_outcome(uncached) is not None
    assert calls[-1] == "c" * 64


def test_failed_adaptor_keeps_its_capability_id(console_config):
    aggregate = receipt("failed").model_copy(
        update={
            "graph_trace": GraphTrace(
                nodes=(),
                adaptors=(
                    GraphNodeEvidence(
                        node_id="join",
                        capability="adaptor",
                        predecessors=(),
                        storage="storage",
                        state="failed",
                    ),
                ),
            )
        }
    )
    observed = outcomes.outcome_evidence(
        console_config.operation_store, _snapshot(uuid4(), aggregate)
    )
    assert observed is not None and observed.failed_phases == ("adaptor",)
