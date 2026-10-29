"""Finite declared-body sequencing; native history owns all scientific transitions."""

from pathlib import Path
from uuid import UUID

from core.control_json import encode_control
from core.durable_io import publish_bytes_write_once
from core.runtime_control.scheduling import HostBudget
from workflows.llm_config import WorkflowLLMConfig
from workflows.task_composition import RunTaskComposition

from .budget import WorkerBudget
from .graph_evidence import read_graph_control
from .layout import candidate_control_dir
from .loop_models import LoopContinuation, LoopPause, LoopStop, LoopTrace, admit_loop
from .loop_stop import (
    BodyScore,
    JudgeBoundaryVerdict,
    LoopInputRequest,
    StopEvaluationOutput,
    admit_stop_conditions,
    captured_metric,
    evaluate_stop,
    input_request,
    needs_stop_judge,
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
    host_budget: HostBudget | None = None,
) -> CandidateRunReceipt:
    from .graph import execute_fanout
    from .graph_evidence import verify_graph_trace
    from .loop_evidence import advance_body, initial_history

    admit_loop(request)
    loop = request.preview.document.definition.loop
    assert loop is not None
    if loop.stop_conditions:
        from .loop_judge import admit_judge_route

        # Before any dispatch: a mismatch found after body 1 would orphan its records.
        admit_stop_conditions(loop, captured_metric(request, initial), composition.metric.spec)
        admit_judge_route(loop, config)
    history = initial_history(request, initial)
    attempted = 0
    segment_id = None
    # Last body of the whole run, so a segment that dispatches none keeps its validation.
    last: CandidateRunReceipt | None = None
    # Immutable verified-score carrier for the stateless stop evaluator (never history),
    # and the completed body receipts a judge request is projected from.
    scores: tuple[BodyScore, ...] = ()
    completed: tuple[CandidateRunReceipt, ...] = ()
    # Whole-run judge verdicts; the predecessor's verified trace supplies earlier ones.
    verdicts: tuple[JudgeBoundaryVerdict, ...] = ()
    # Last boundary where a ``request_input`` condition paused the run (0 = none).
    anchor = 0
    if continuation is not None:
        from .loop_resume import resume_history

        history, completed, scores, verdicts, anchor = resume_history(
            request, initial, continuation
        )
        last = completed[-1]
        attempted = continuation.completed_iterations
        segment_id = continuation.operation_id
    resumed_at = attempted
    status = "completed"
    reason = None
    asked: LoopInputRequest | None = None
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
            host_budget=host_budget,
        )
        verify_graph_trace(request, initial, last, iteration=iteration, history=history)
        publish_bytes_write_once(str(control / "body.json"), encode_control(last))
        attempted = iteration
        if last.status != "completed":
            status = last.status
            break
        advance_body(request, initial, last, history)
        if loop.stop_conditions:
            # A met condition completes (``stop``) or pauses (``request_input``) the loop
            # before any pending Stop/Pause is read.
            scores = (*scores, project_body_score(request, last, iteration))
            completed = (*completed, last)
            decided, asked, verdict = _boundary_decision(
                request, initial, completed, scores, prior_calls=len(verdicts), anchor=anchor
            )
            verdicts = verdicts if verdict is None else (*verdicts, verdict)
            if decided.decision == "stop":
                reason = decided.reason
                break
            if asked is not None:
                status = "paused"
                break
    return initial.model_copy(
        update={
            "status": status,
            "loop_trace": LoopTrace(
                attempted_iterations=attempted,
                segment_id=segment_id,
                stop_reason=reason,
                input_request=asked,
                judge_verdicts=verdicts,
                judge_abstentions=sum(item.decision is None for item in verdicts),
            ),
            "validation_passed": None if last is None else last.validation_passed,
        }
    )


def _boundary_decision(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    completed: tuple[CandidateRunReceipt, ...],
    scores: tuple[BodyScore, ...],
    *,
    prior_calls: int,
    anchor: int,
) -> tuple[StopEvaluationOutput, LoopInputRequest | None, JudgeBoundaryVerdict | None]:
    """Deterministic conditions first; the judge is called only when the boundary needs it.

    A judgeable boundary pre-empted by a deterministic decision records a skip marker.
    """
    from .loop_judge import call_stop_judge, mark_skipped_stop_judge

    loop = request.preview.document.definition.loop
    assert loop is not None
    value = stop_input(loop, captured_metric(request, initial), scores, input_anchor=anchor)
    verdict = None
    if needs_stop_judge(value):
        verdict = call_stop_judge(request, initial, completed, value, prior_calls=prior_calls)
        value = value.model_copy(update={"judge_verdict": verdict})
    else:
        mark_skipped_stop_judge(initial, value)
    decided = evaluate_stop(value)
    return decided, input_request(value, decided), verdict
