"""Replay committed native body records; never execute task plugins or providers."""

from pathlib import Path

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from agent.schemas.interpretation import InterpretationInput, InterpretationOutput
from agent.schemas.proposal import ProposalOutput
from core.chain_state import ChainState
from core.resume import commit_time_gate_ids
from workflows.definition.fanout import execution_families
from workflows.research_history import advance_completed_history, history_metric, seed_history

from .fanout_inputs import captured_contents
from .graph_evidence import expected_nodes, read_graph_control, verify_graph_trace
from .layout import candidate_control_dir
from .loop_stop import (
    BodyScore,
    StopReason,
    captured_metric,
    evaluate_stop,
    project_body_score,
    stop_input,
)
from .models import CandidateRunReceipt, CandidateRunRequest


def initial_history(request: CandidateRunRequest, initial: CandidateRunReceipt) -> ChainState:
    edge = execution_families(
        request.preview.document.definition, request.preview.execution_profile
    ).interpretation
    assert edge is not None
    contents = captured_contents(request, Path(initial.workspace), iteration=1)
    value = InterpretationInput.model_validate_json(contents[f"external.{edge.input_binding}"])
    return seed_history(value)


def advance_body(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    body: CandidateRunReceipt,
    state: ChainState,
) -> None:
    """Fold only successful, verified producer records with native commit-time policy."""
    assert body.graph_trace is not None and body.status == "completed"
    shape = execution_families(
        request.preview.document.definition, request.preview.execution_profile
    )
    assert shape.interpretation is not None and shape.tuning is not None
    nodes = {item.node_id: item for item in body.graph_trace.nodes}

    def payload(node_id: str) -> bytes:
        path = nodes[node_id].record_path
        assert path is not None
        return Path(path).read_bytes()

    interpretation = InterpretationOutput.model_validate_json(
        payload(shape.interpretation.interpretation)
    )
    proposal = ProposalOutput.model_validate_json(payload(shape.interpretation.proposal))
    tuning = HyperparamTuningOutput.model_validate_json(payload(shape.tuning))
    edge = shape.interpretation
    contents = captured_contents(request, Path(initial.workspace), iteration=1)
    seed = InterpretationInput.model_validate_json(contents[f"external.{edge.input_binding}"])
    bound_metric = history_metric(state, seed.metric_spec)
    state.iteration_results.append(tuning)
    state.current_collapse_fingerprint_history = dict(interpretation.collapse_fingerprint_history)
    tuning_path = nodes[shape.tuning].record_path
    assert tuning_path is not None
    advance_completed_history(
        state,
        interpretation,
        proposal,
        tuning,
        required_gate_ids=commit_time_gate_ids(tuning, tuning_path, initial.workspace),
        run_metric_spec=seed.metric_spec or tuning.metric_spec or bound_metric,
        bound_metric_spec=bound_metric,
    )


def verify_loop(
    request: CandidateRunRequest, initial: CandidateRunReceipt, receipt: CandidateRunReceipt
) -> tuple[CandidateRunReceipt, ...]:
    """Verify the loop terminal; return its accepted body receipts in iteration order."""
    from .loop import pause_requested, stop_requested
    from .loop_models import admit_loop

    admit_loop(request)
    loop = request.preview.document.definition.loop
    assert loop is not None
    if (
        receipt.graph_trace is not None
        or receipt.native_output_paths
        or any(
            value is not None
            for value in (
                receipt.candidate_id,
                receipt.composition_fingerprint,
                receipt.proposal_storage,
                receipt.implementation_storage,
                receipt.training_output,
            )
        )
    ):
        raise ValueError("loop aggregate cannot claim one-body scientific fields")
    trace = receipt.loop_trace
    if trace is None:
        if (
            receipt.status not in ("failed", "timed_out", "interrupted")
            or receipt.validation_passed is not None
        ):
            raise ValueError("loop terminal lacks completed-body index")
        return ()
    if trace.attempted_iterations > loop.final_iteration:
        raise ValueError("loop exceeds declared finite limit")
    from .loop_resume import has_successor, verify_segment

    # A segment may pause only after dispatching its own body, never at its resume point.
    resumed_at = verify_segment(initial, receipt)
    if trace.attempted_iterations < loop.final_iteration and not has_successor(initial, receipt):
        require_unused_next(request, initial, trace.attempted_iterations)
    _, bodies, scores = replay_completed(request, initial, trace.attempted_iterations)
    last = bodies[-1] if bodies else None
    derived = derive_stop(request, initial, scores)
    if trace.stop_reason != derived:
        raise ValueError("loop stop reason disagrees with re-derived stop conditions")
    expected = (
        last.status
        if last is not None and last.status != "completed"
        else "completed"
        if trace.attempted_iterations == loop.final_iteration or derived is not None
        else "paused"
        if receipt.status == "paused" and trace.attempted_iterations > resumed_at
        else "stopped"
    )
    if (
        receipt.status != expected
        or receipt.validation_passed != (None if last is None else last.validation_passed)
        or (expected == "stopped" and not stop_requested(initial))
        or (expected == "paused" and not pause_requested(initial, trace.segment_id))
    ):
        raise ValueError("loop terminal disagrees with completed bodies or Stop/Pause evidence")
    return bodies


def derive_stop(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    scores: tuple[BodyScore, ...],
) -> StopReason | None:
    """Re-run the stateless evaluator at every completed boundary; trust no recorded value.

    Returns the reason that must end the loop at its last completed body, if any.
    """
    loop = request.preview.document.definition.loop
    assert loop is not None
    if not loop.stop_conditions:
        return None
    seed = captured_metric(request, initial)
    reason = None
    for count in range(1, len(scores) + 1):
        if reason is not None:
            raise ValueError("loop continued past a met stop condition")
        reason = evaluate_stop(stop_input(loop, seed, scores[:count])).reason
    return reason


def require_unused_next(
    request: CandidateRunRequest, initial: CandidateRunReceipt, completed: int
) -> None:
    next_iteration = completed + 1
    next_control = candidate_control_dir(Path(initial.workspace), iteration=next_iteration)
    if (next_iteration > 1 and next_control.exists()) or any(
        Path(item.storage).exists()
        for item in expected_nodes(request, initial, iteration=next_iteration)
    ):
        raise ValueError("loop terminal omits an already-dispatched body")


def replay_completed(
    request: CandidateRunRequest, initial: CandidateRunReceipt, completed: int
) -> tuple[ChainState, tuple[CandidateRunReceipt, ...], tuple[BodyScore, ...]]:
    """Shared verified-prefix fold for readback and continuation history.

    Returns the folded history, the verified body receipts in iteration order and the
    completed bodies' scores, projected from the same records and never from the history.
    """
    state = initial_history(request, initial)
    bodies: list[CandidateRunReceipt] = []
    scores: list[BodyScore] = []
    for iteration in range(1, completed + 1):
        control = candidate_control_dir(Path(initial.workspace), iteration=iteration)
        body = CandidateRunReceipt.model_validate_json(read_graph_control(control / "body.json"))
        for name in (
            "run_id",
            "run_name",
            "workspace",
            "declaration_digest",
            "node_ids",
            "selected_constructor_routes",
            "ledger_path",
            "log_path",
        ):
            if getattr(body, name) != getattr(initial, name):
                raise ValueError("loop body identity changed")
        verify_graph_trace(request, initial, body, iteration=iteration, history=state)
        bodies.append(body)
        if body.status != "completed" and iteration != completed:
            raise ValueError("loop continued without successful required feedback")
        if body.status == "completed":
            advance_body(request, initial, body, state)
            scores.append(project_body_score(request, body, iteration))
    return state, tuple(bodies), tuple(scores)
