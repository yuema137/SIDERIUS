"""Replay committed native body records; never execute task plugins or providers."""

from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

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
    JudgeBoundaryVerdict,
    LoopInputRequest,
    StopReason,
    captured_metric,
    evaluate_stop,
    input_request,
    needs_stop_judge,
    project_body_score,
    stop_input,
)
from .models import CandidateRunReceipt, CandidateRunRequest

if TYPE_CHECKING:
    from .loop_resume import AdviceSchedule, Checkpoint


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


class LoopDerivation(NamedTuple):
    """Everything the stateless evaluator re-derives over a verified completed prefix."""

    stop_reason: StopReason | None  # the met ``stop`` condition at the last boundary
    verdicts: tuple[JudgeBoundaryVerdict, ...]  # every judged boundary, in order
    input_requests: tuple[LoopInputRequest, ...]  # every ``request_input`` boundary
    input_anchor: int  # the last ``request_input`` boundary (0 = none)


class VerifiedLoop(NamedTuple):
    bodies: tuple[CandidateRunReceipt, ...]
    input_anchor: int


def verify_loop(
    request: CandidateRunRequest, initial: CandidateRunReceipt, receipt: CandidateRunReceipt
) -> tuple[CandidateRunReceipt, ...]:
    """Verify the loop terminal; return its accepted body receipts in iteration order."""
    return verified_loop(request, initial, receipt).bodies


def verified_loop(
    request: CandidateRunRequest, initial: CandidateRunReceipt, receipt: CandidateRunReceipt
) -> VerifiedLoop:
    """``verify_loop`` plus the re-derived input anchor a continuation resumes from."""
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
            receipt.status not in ("failed", "timed_out", "interrupted", "cancelled")
            or receipt.validation_passed is not None
        ):
            raise ValueError("loop terminal lacks completed-body index")
        return VerifiedLoop((), 0)
    if trace.attempted_iterations > loop.final_iteration:
        raise ValueError("loop exceeds declared finite limit")
    from .loop_resume import has_successor, verify_segment

    # A segment may pause only after dispatching its own body, never at its resume point.
    resumed_at, checkpoints = verify_segment(initial, receipt)
    successor = has_successor(initial, receipt)
    if trace.attempted_iterations < loop.final_iteration and not successor:
        require_unused_next(request, initial, trace.attempted_iterations)
    from .loop_resume import segment_advice

    _, bodies, scores = replay_completed(
        request,
        initial,
        trace.attempted_iterations,
        advice=segment_advice(initial, trace.segment_id),
    )
    last = bodies[-1] if bodies else None
    derivation = derive_stop(request, initial, bodies, scores)
    derived, verdicts = derivation.stop_reason, derivation.verdicts
    if trace.stop_reason != derived:
        raise ValueError("loop stop reason disagrees with re-derived stop conditions")
    asked = _verify_input_pauses(
        derivation.input_requests,
        checkpoints,
        own=trace.attempted_iterations if trace.attempted_iterations > resumed_at else None,
    )
    if trace.input_request != asked:
        raise ValueError("loop input request disagrees with re-derived stop conditions")
    if trace.judge_verdicts != verdicts:
        raise ValueError("loop judge verdicts disagree with the recorded judge evidence")
    from .loop_judge import require_accounted_judge_evidence, require_judge_cap

    require_judge_cap(initial.workspace, loop, len(verdicts))
    require_accounted_judge_evidence(
        Path(initial.workspace), verdicts, trace.attempted_iterations, successor=successor
    )
    expected = (
        last.status
        if last is not None and last.status != "completed"
        else "completed"
        if trace.attempted_iterations == loop.final_iteration or derived is not None
        else "paused"
        if asked is not None
        or (receipt.status == "paused" and trace.attempted_iterations > resumed_at)
        else "stopped"
    )
    if (
        receipt.status != expected
        or receipt.validation_passed != (None if last is None else last.validation_passed)
        or (expected == "stopped" and not stop_requested(initial))
        or (
            expected == "paused"
            and asked is None
            and not pause_requested(initial, trace.segment_id)
        )
    ):
        raise ValueError("loop terminal disagrees with completed bodies or Stop/Pause evidence")
    return VerifiedLoop(bodies, derivation.input_anchor)


def _verify_input_pauses(
    requests: tuple[LoopInputRequest, ...],
    checkpoints: tuple["Checkpoint", ...],
    *,
    own: int | None,
) -> LoopInputRequest | None:
    """Account for every re-derived input request; return the receipt's own, if any.

    ``own`` is the receipt's last attempted boundary when its segment dispatched a body.
    Every other request boundary must be a resumed checkpoint whose predecessor recorded
    an equal request; every checkpoint that is not one must hold an operator Pause
    marker and record no request.
    """
    at = {item.completed_iterations: item for item in checkpoints}
    asked: LoopInputRequest | None = None
    for requested in requests:
        boundary = requested.reason.iteration
        if boundary == own:
            asked = requested
            continue
        checkpoint = at.get(boundary)
        if checkpoint is None:
            raise ValueError("loop continued past a condition input request")
        if checkpoint.input_request != requested:
            raise ValueError("predecessor input request disagrees with re-derived conditions")
    requested_at = {item.reason.iteration for item in requests}
    for checkpoint in checkpoints:
        if checkpoint.completed_iterations not in requested_at and (
            not checkpoint.pause_marker or checkpoint.input_request is not None
        ):
            raise ValueError("predecessor lacks Pause request")
    return asked


def derive_stop(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    bodies: tuple[CandidateRunReceipt, ...],
    scores: tuple[BodyScore, ...],
) -> LoopDerivation:
    """Re-run the stateless evaluator at every completed boundary; trust no recorded value.

    A boundary ``needs_stop_judge`` names must hold judge evidence that replays from the
    re-projected request (``replay_stop_judge``); ``verify_loop`` refuses every judge
    evidence file these verdicts do not account for. A met ``stop`` condition must end
    the loop at its boundary. A met ``request_input`` condition moves the input anchor;
    ``verify_loop`` requires each such boundary to be the receipt's own pause or a
    resumed checkpoint. The trace must record exactly the returned verdicts.
    """
    from .loop_judge import replay_stop_judge

    loop = request.preview.document.definition.loop
    assert loop is not None
    if not loop.stop_conditions:
        return LoopDerivation(None, (), (), 0)
    seed = captured_metric(request, initial)
    completed = tuple(body for body in bodies if body.status == "completed")
    reason = None
    anchor = 0
    verdicts: list[JudgeBoundaryVerdict] = []
    requests: list[LoopInputRequest] = []
    for count in range(1, len(scores) + 1):
        if reason is not None:
            raise ValueError("loop continued past a met stop condition")
        value = stop_input(loop, seed, scores[:count], input_anchor=anchor)
        if needs_stop_judge(value):
            verdict = replay_stop_judge(request, initial, completed[:count], value)
            verdicts.append(verdict)
            value = value.model_copy(update={"judge_verdict": verdict})
        decided = evaluate_stop(value)
        reason = decided.reason if decided.decision == "stop" else None
        asked = input_request(value, decided)
        if asked is not None:
            requests.append(asked)
            anchor = count
    return LoopDerivation(reason, tuple(verdicts), tuple(requests), anchor)


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
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    completed: int,
    *,
    advice: "AdviceSchedule" = (),
) -> tuple[ChainState, tuple[CandidateRunReceipt, ...], tuple[BodyScore, ...]]:
    """Shared verified-prefix fold for readback and continuation history.

    Returns the folded history, the verified body receipts in iteration order and the
    completed bodies' scores, projected from the same records and never from the history.
    ``advice`` (``segment_advice``) gives each body the Resume advice its segment received.
    """
    from .loop_resume import body_advice

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
        verify_graph_trace(
            request,
            initial,
            body,
            iteration=iteration,
            history=state,
            operator_advice=body_advice(advice, iteration),
        )
        bodies.append(body)
        if body.status != "completed" and iteration != completed:
            raise ValueError("loop continued without successful required feedback")
        if body.status == "completed":
            advance_body(request, initial, body, state)
            scores.append(project_body_score(request, body, iteration))
    return state, tuple(bodies), tuple(scores)
