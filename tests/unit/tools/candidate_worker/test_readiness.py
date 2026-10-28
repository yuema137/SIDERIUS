"""Serial readiness authority: one pure rule shared by dispatch and replay."""

import sys

import pytest

from tests.helpers.candidate_fanout import fanout_request
from tools.candidate_worker import launch_candidate, readiness
from tools.candidate_worker.graph_evidence import verify_graph_trace
from tools.candidate_worker.readiness import NodeReadiness, ReadinessInput, next_dispatch

from .test_graph import initial
from .test_native import native_runner


def decide(*nodes, aborted=False):
    return next_dispatch(
        ReadinessInput(
            nodes=tuple(
                NodeReadiness(node_id=node_id, predecessors=tuple(preds), state=state)
                for node_id, preds, state in nodes
            ),
            aborted=aborted,
        )
    )


BLOCKED = "dependency_not_successful"


@pytest.mark.parametrize(
    ("nodes", "aborted", "expected"),
    [
        # Declaration order is not topological: a consumer listed first must wait.
        ((("check", ("build",), "pending"), ("build", (), "pending")), False, ("build", ())),
        # A running predecessor is not terminal: nothing acts, nothing is closed.
        ((("build", (), "running"), ("check", ("build",), "pending")), False, (None, ())),
        # Rejection blocks its consumer before a later independent sibling runs.
        (
            (
                ("propose", (), "succeeded"),
                ("check_a", ("propose",), "rejected"),
                ("tune", ("check_a",), "pending"),
                ("check_b", ("propose",), "pending"),
            ),
            False,
            (None, (("tune", "blocked", BLOCKED),)),
        ),
        # Once the blocked consumer is closed, the independent sibling still runs.
        (
            (
                ("propose", (), "succeeded"),
                ("check_a", ("propose",), "rejected"),
                ("tune", ("check_a",), "blocked"),
                ("check_b", ("propose",), "pending"),
            ),
            False,
            ("check_b", ()),
        ),
        # Blocked propagates transitively.
        (
            (("a", (), "blocked"), ("b", ("a",), "pending")),
            False,
            (None, (("b", "blocked", BLOCKED),)),
        ),
        # Failure stop: after an abort even a source node with no predecessors is blocked.
        (
            (("a", (), "failed"), ("b", (), "pending")),
            True,
            (None, (("b", "blocked", BLOCKED),)),
        ),
        # Every node decided: the graph is complete.
        ((("a", (), "succeeded"), ("b", ("a",), "rejected")), False, (None, ())),
    ],
)
def test_next_dispatch_orders_dispatch_block_and_abort(nodes, aborted, expected):
    output = decide(*nodes, aborted=aborted)
    assert (output.next, output.terminal) == expected


def test_undeclared_predecessor_refuses_instead_of_guessing_readiness():
    with pytest.raises(ValueError, match="not a declared node"):
        decide(("b", ("ghost",), "pending"))


def test_dispatch_and_replay_both_consume_the_single_readiness_owner(
    prepared, native_runner, monkeypatch
):
    """Fails if either call site re-derives readiness inline instead of using the owner."""
    from tools.candidate_worker import phases

    def failed(*args, **kwargs):
        raise RuntimeError("uncertain native failure")

    monkeypatch.setattr(phases, "run_implementation", failed)
    original = readiness.next_dispatch
    callers: list[str] = []

    def spy(value):
        callers.append(sys._getframe(1).f_globals["__name__"])
        return original(value)

    monkeypatch.setattr(readiness, "next_dispatch", spy)
    request = fanout_request(prepared)
    receipt = launch_candidate(request)
    assert receipt.status == "failed"
    assert "tools.candidate_worker.graph" in callers
    callers.clear()
    verify_graph_trace(
        request, initial(request).model_copy(update={"run_id": receipt.run_id}), receipt
    )
    assert set(callers) == {"tools.candidate_worker.graph_evidence"}
