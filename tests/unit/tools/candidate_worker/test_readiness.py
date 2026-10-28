"""Serial readiness authority: one pure rule shared by dispatch and replay."""

import hashlib
import re
import sys

import pytest

from tests.helpers.candidate_fanout import UNROUTED_TRACE_SHA256, fanout_request, trace_projection
from tools.candidate_worker import launch_candidate, readiness
from tools.candidate_worker.graph_evidence import replay_readiness, verify_graph_trace
from tools.candidate_worker.graph_models import GraphNodeEvidence
from tools.candidate_worker.readiness import (
    MergeCandidate,
    MergeReadiness,
    NodeReadiness,
    NodeRouting,
    ReadinessInput,
    next_dispatch,
)
from tools.candidate_worker.route_eval import RouteEvaluationOutput

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
        # A cycle has no node whose inputs are terminal: no action rather than a guess,
        # which both call sites turn into an error.
        ((("a", ("b",), "pending"), ("b", ("a",), "pending")), False, (None, ())),
    ],
)
def test_next_dispatch_orders_dispatch_block_and_abort(nodes, aborted, expected):
    output = decide(*nodes, aborted=aborted)
    assert (output.next, output.terminal) == expected


def test_undeclared_predecessor_refuses_instead_of_guessing_readiness():
    with pytest.raises(ValueError, match="not a declared node"):
        decide(("b", ("ghost",), "pending"))


def test_duplicate_node_id_refuses_instead_of_shadowing_a_state():
    # Without the check the later "pending" entry would shadow the "failed" one.
    with pytest.raises(ValueError, match="unique"):
        decide(("a", (), "failed"), ("a", (), "pending"))


def test_dispatch_and_replay_both_consume_the_single_readiness_owner(
    prepared, native_runner, monkeypatch
):
    """Fails if either call site re-derives readiness inline instead of using the owner.

    The spy patches `readiness.next_dispatch`, so it requires both call sites to call
    it as a module attribute (`readiness.next_dispatch`), not a from-imported name.
    """
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


# --- Skip semantics (B1-PR4): pure readiness and replay over recorded decisions. ---

SKIP = "route_not_selected"


def route(selected_case, selected, skipped, branch="r"):
    """A recorded decision; `case_results` ends at the first match (or covers every case)."""
    results = (False,) * (selected_case or 0) + (True,) if selected_case is not None else (False,)
    return RouteEvaluationOutput(
        branch_id=branch,
        selected_case=selected_case,
        selected_targets=selected,
        skipped_targets=skipped,
        case_results=results,
    )


def node(node_id, preds=(), state="pending", reason=None, route_id=None, merges=()):
    return NodeReadiness(
        node_id=node_id,
        predecessors=tuple(preds),
        state=state,
        reason=reason,
        routing=NodeRouting(route=route_id, merges=merges),
    )


def merge_ab(branch="r"):
    return MergeReadiness(
        branch=branch,
        candidates=(
            MergeCandidate(node="a", entry=("a",)),
            MergeCandidate(node="b", entry=("b",)),
        ),
    )


def step(*nodes, decisions=(), aborted=False):
    output = next_dispatch(ReadinessInput(nodes=nodes, aborted=aborted, decisions=decisions))
    return output.next, output.terminal


ROUTE_B = (route(None, ("b",), ("a",)),)  # no case matched: default arm `b` runs


@pytest.mark.parametrize(
    ("nodes", "expected"),
    [
        # A target the decision did not select closes as skipped, without dispatch.
        (
            (node("src", state="succeeded"), node("a", ("src",), route_id="r")),
            (None, (("a", "skipped", SKIP),)),
        ),
        # The selected target runs.
        (
            (node("src", state="succeeded"), node("b", ("src",), route_id="r")),
            ("b", ()),
        ),
        # Skipped never satisfies a required input: its consumer inherits the skip.
        (
            (
                node("src", state="succeeded"),
                node("a", ("src",), "skipped", SKIP, route_id="r"),
                node("use", ("a", "src")),
            ),
            (None, (("use", "skipped", SKIP),)),
        ),
        # Blocked beats skipped: one rejected and one skipped source block the consumer.
        (
            (
                node("src", state="succeeded"),
                node("a", ("src",), "skipped", SKIP, route_id="r"),
                node("other", state="rejected", reason="validation_rejected"),
                node("use", ("a", "other")),
            ),
            (None, (("use", "blocked", BLOCKED),)),
        ),
        # A rejected route source blocks its targets before any decision is consulted.
        (
            (
                node("src", state="rejected", reason="validation_rejected"),
                node("a", ("src",), route_id="r"),
            ),
            (None, (("a", "blocked", BLOCKED),)),
        ),
        # Merge picks the selected arm even though the other candidate was skipped.
        (
            (
                node("a", state="skipped", reason=SKIP),
                node("b", state="succeeded"),
                node("join", merges=(merge_ab(),)),
            ),
            ("join", ()),
        ),
        # A non-selected candidate's blocked state does not reach the merge consumer.
        (
            (
                node("a", state="blocked", reason=BLOCKED),
                node("b", state="succeeded"),
                node("join", merges=(merge_ab(),)),
            ),
            ("join", ()),
        ),
        # The selected candidate's rejection blocks the merge consumer.
        (
            (
                node("a", state="skipped", reason=SKIP),
                node("b", state="rejected", reason="validation_rejected"),
                node("join", merges=(merge_ab(),)),
            ),
            (None, (("join", "blocked", BLOCKED),)),
        ),
    ],
)
def test_route_decisions_skip_propagate_and_merge(nodes, expected):
    assert step(*nodes, decisions=ROUTE_B) == expected


def test_merge_waits_for_every_candidate_before_resolving():
    # Fails if the merge consumer dispatches before the non-selected arm is closed.
    nodes = (
        node("a", state="pending"),
        node("b", state="succeeded"),
        node("join", merges=(merge_ab(),)),
    )
    assert step(*nodes, decisions=ROUTE_B) == ("a", ())


def test_route_target_without_a_recorded_decision_refuses_instead_of_running():
    # Fails if readiness treats a missing decision as "selected" and dispatches the arm.
    with pytest.raises(ValueError, match="no recorded decision"):
        step(node("src", state="succeeded"), node("a", ("src",), route_id="r"))


def test_merge_over_skipped_source_without_decision_inherits_the_skip():
    # A nested branch whose source was itself skipped records no decision.
    nodes = (
        node("a", state="skipped", reason=SKIP),
        node("b", state="skipped", reason=SKIP),
        node("join", merges=(merge_ab(),)),
    )
    assert step(*nodes) == (None, (("join", "skipped", SKIP),))


def test_skipped_and_blocked_are_neutral_in_body_status():
    states = ("succeeded", "skipped", "skipped")
    assert readiness.body_status(states, tuning=False) == "accepted"
    assert readiness.body_status(states, tuning=True) == "completed"
    assert readiness.body_status((*states, "rejected"), tuning=False) == "rejected"
    assert readiness.body_status(("rejected", "failed", "skipped"), tuning=True) == "failed"


def evidence(node_id, preds, state, reason=None):
    dispatched = state in ("succeeded", "rejected")
    return GraphNodeEvidence(
        node_id=node_id,
        capability="validation",
        predecessors=tuple(preds),
        storage=f"/w/{node_id}",
        state=state,
        record_path=f"/w/{node_id}.json" if dispatched else None,
        record_sha256="0" * 64 if dispatched else None,
        reason=reason,
    )


ROUTED = {"a": NodeRouting(route="r"), "b": NodeRouting(route="r")}

MERGED = {**ROUTED, "join": NodeRouting(merges=(merge_ab(),))}


def test_merge_consumer_with_declared_candidate_predecessors_runs_the_selected_arm():
    """Fails if a merge candidate stays in the AND set: the skipped arm would skip `join`.

    `dependency_graph` lists every merge candidate as a predecessor of the consumer,
    so the slot carries ("a", "b") exactly as declared.
    """
    trace = (
        evidence("src", (), "succeeded"),
        evidence("a", ("src",), "skipped", SKIP),
        evidence("b", ("src",), "succeeded"),
        evidence("join", ("a", "b"), "succeeded"),
    )
    done = {item.node_id: item for item in trace[:3]}
    step = next_dispatch(
        readiness.readiness_input(trace, done, aborted=False, decisions=ROUTE_B, routing=MERGED)
    )
    assert (step.next, step.terminal) == ("join", ())
    replay_readiness(trace, decisions=ROUTE_B, routing=MERGED)
    wrong = (*trace[:3], evidence("join", ("a", "b"), "skipped", SKIP))
    with pytest.raises(ValueError, match="serial readiness"):
        replay_readiness(wrong, decisions=ROUTE_B, routing=MERGED)


def test_merge_candidate_cannot_also_be_a_required_predecessor():
    # Fails if a direct NodeReadiness could AND over a candidate the merge may not select.
    with pytest.raises(ValueError, match="merge candidate"):
        node("join", ("a",), merges=(merge_ab(),))


@pytest.mark.parametrize(
    ("a", "b"),
    [
        # A node dispatched inside the non-selected arm.
        (("succeeded", None), ("succeeded", None)),
        # A skip readiness would not produce: the selected target recorded as skipped.
        (("skipped", SKIP), ("skipped", SKIP)),
        # The terminal state differs from readiness, not only blocked-vs-any-terminal.
        (("blocked", BLOCKED), ("succeeded", None)),
    ],
)
def test_replay_refuses_a_trace_that_disagrees_with_the_route_decision(a, b):
    trace = (
        evidence("src", (), "succeeded"),
        evidence("a", ("src",), *a),
        evidence("b", ("src",), *b),
    )
    with pytest.raises(ValueError, match="serial readiness"):
        replay_readiness(trace, decisions=ROUTE_B, routing=ROUTED)


def test_replay_accepts_the_skip_readiness_produces():
    trace = (
        evidence("src", (), "succeeded"),
        evidence("a", ("src",), "skipped", SKIP),
        evidence("b", ("src",), "succeeded"),
        evidence("use", ("a",), "skipped", SKIP),
    )
    replay_readiness(trace, decisions=ROUTE_B, routing=ROUTED)
    # Without the decision the same skips are unexplained and refused.
    with pytest.raises(ValueError, match="no recorded decision"):
        replay_readiness(trace, routing=ROUTED)


@pytest.mark.parametrize("outcome", sorted(UNROUTED_TRACE_SHA256))
def test_unrouted_graph_trace_bytes_are_unchanged(prepared, native_runner, monkeypatch, outcome):
    """Fails if skip semantics alter serialization or outcome of an existing graph run."""
    from tools.candidate_worker import phases

    from .test_native import Provider

    monkeypatch.setattr(Provider, "reject", outcome == "rejected")
    if outcome == "failed":

        def failed(*args, **kwargs):
            raise RuntimeError("uncertain native failure")

        monkeypatch.setattr(phases, "run_implementation", failed)
    request = fanout_request(prepared)
    receipt = launch_candidate(request)
    payload = trace_projection(receipt)
    assert hashlib.sha256(payload.encode()).hexdigest() == UNROUTED_TRACE_SHA256[outcome], payload
    verify_graph_trace(
        request, initial(request).model_copy(update={"run_id": receipt.run_id}), receipt
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        # B6-D8: a rejected or skipped source is merely inadmissible to an adaptor.
        (("rejected", None), ("pick", ())),
        (("skipped", SKIP), ("pick", ())),
        (("succeeded", None), ("pick", ())),
        # A blocked source has no outcome to weigh: the adaptor is closed, not run.
        (("blocked", BLOCKED), (None, (("pick", "blocked", BLOCKED),))),
    ],
)
def test_an_adaptor_is_ready_once_every_source_is_terminal(source, expected):
    """Fails if adaptors reuse the capability rule (rejected would block) or ignore blocked."""
    state, reason = source
    nodes = (
        NodeReadiness(node_id="a", predecessors=(), state="succeeded"),
        NodeReadiness(node_id="b", predecessors=(), state=state, reason=reason),
        NodeReadiness(node_id="pick", predecessors=("a", "b"), state="pending", kind="adaptor"),
        NodeReadiness(node_id="tune", predecessors=("pick",), state="pending"),
    )
    output = next_dispatch(ReadinessInput(nodes=nodes, aborted=False))
    assert (output.next, output.terminal) == expected


def test_an_adaptor_waits_for_every_source_and_its_rejection_blocks_consumers():
    pending = (
        NodeReadiness(node_id="a", predecessors=(), state="rejected"),
        NodeReadiness(node_id="b", predecessors=(), state="running"),
        NodeReadiness(node_id="pick", predecessors=("a", "b"), state="pending", kind="adaptor"),
    )
    assert next_dispatch(ReadinessInput(nodes=pending, aborted=False)).next is None
    closed = (
        NodeReadiness(
            node_id="pick", predecessors=(), state="rejected", reason="no_admissible_input"
        ),
        NodeReadiness(node_id="tune", predecessors=("pick",), state="pending"),
    )
    output = next_dispatch(ReadinessInput(nodes=closed, aborted=False))
    assert output.terminal == (("tune", "blocked", BLOCKED),)
