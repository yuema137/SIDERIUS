"""Finite declared-body sequencing; native history owns all scientific transitions."""

from pathlib import Path
from uuid import UUID

from core.control_json import encode_control
from core.durable_io import publish_bytes_write_once
from workflows.llm_config import WorkflowLLMConfig
from workflows.task_composition import RunTaskComposition

from .budget import WorkerBudget
from .graph_evidence import read_graph_control
from .layout import candidate_control_dir
from .loop_models import LoopContinuation, LoopPause, LoopStop, LoopTrace, admit_loop
from .loop_stop import (
    BodyScore,
    admit_stop_conditions,
    captured_metric,
    evaluate_stop,
    project_body_score,
    stop_input,
)
from .models import CandidateRunReceipt, CandidateRunRequest


def stop_requested(initial: CandidateRunReceipt) -> bool:
    path = Path(initial.workspace) / "candidate_run" / "stop.json"
    try:
        stop = LoopStop.model_validate_json(read_graph_control(path))
    except FileNotFoundError:
        return False
    if (stop.run_id, stop.declaration_digest) != (initial.run_id, initial.declaration_digest):
        raise ValueError("loop Stop identity mismatch")
    return True


def pause_requested(initial: CandidateRunReceipt, segment_id: UUID | None = None) -> bool:
    """Pause is segment-scoped: a successor never consumes its predecessor's request."""
    from .loop_resume import segment_control

    try:
        marker = LoopPause.model_validate_json(
            read_graph_control(segment_control(initial, segment_id) / "pause.json")
        )
    except FileNotFoundError:
        return False
    if (marker.run_id, marker.declaration_digest, marker.segment_id) != (
        initial.run_id,
        initial.declaration_digest,
        segment_id,
    ):
        raise ValueError("loop Pause identity mismatch")
    return True


def execute_loop(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    composition: RunTaskComposition,
    config: WorkflowLLMConfig,
    *,
    continuation: LoopContinuation | None = None,
    budget: WorkerBudget | None = None,
) -> CandidateRunReceipt:
    from .graph import execute_fanout
    from .graph_evidence import verify_graph_trace
    from .loop_evidence import advance_body, initial_history

    admit_loop(request)
    loop = request.preview.document.definition.loop
    assert loop is not None
    if loop.stop_conditions:
        # Before any dispatch: a mismatch found after body 1 would orphan its records.
        admit_stop_conditions(loop, captured_metric(request, initial), composition.metric.spec)
    history = initial_history(request, initial)
    attempted = 0
    segment_id = None
    # Last body of the whole run, so a segment that dispatches none keeps its validation.
    last: CandidateRunReceipt | None = None
    # Immutable verified-score carrier for the stateless stop evaluator (never history).
    scores: tuple[BodyScore, ...] = ()
    if continuation is not None:
        from .loop_resume import resume_history

        history, last, scores = resume_history(request, initial, continuation)
        attempted = continuation.completed_iterations
        segment_id = continuation.operation_id
    resumed_at = attempted
    status = "completed"
    reason = None
    for iteration in range(attempted + 1, loop.final_iteration + 1):
        if stop_requested(initial):
            status = "stopped"
            break
        if attempted > resumed_at and pause_requested(initial, segment_id):
            status = "paused"
            break
        control = candidate_control_dir(Path(initial.workspace), iteration=iteration)
        control.mkdir(parents=True, exist_ok=iteration == 1)
        last = execute_fanout(
            request,
            initial,
            composition,
            config,
            iteration=iteration,
            history=history,
            budget=budget,
        )
        verify_graph_trace(request, initial, last, iteration=iteration, history=history)
        publish_bytes_write_once(str(control / "body.json"), encode_control(last))
        attempted = iteration
        if last.status != "completed":
            status = last.status
            break
        advance_body(request, initial, last, history)
        if loop.stop_conditions:
            # A met condition completes the loop before any pending Stop/Pause is read.
            scores = (*scores, project_body_score(request, last, iteration))
            reason = evaluate_stop(
                stop_input(loop, captured_metric(request, initial), scores)
            ).reason
            if reason is not None:
                break
    return initial.model_copy(
        update={
            "status": status,
            "loop_trace": LoopTrace(
                attempted_iterations=attempted, segment_id=segment_id, stop_reason=reason
            ),
            "validation_passed": None if last is None else last.validation_passed,
        }
    )
