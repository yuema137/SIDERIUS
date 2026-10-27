"""Finite declared-body sequencing; native history owns all scientific transitions."""

from pathlib import Path

from core.control_json import encode_control
from core.durable_io import publish_bytes_write_once
from workflows.llm_config import WorkflowLLMConfig
from workflows.task_composition import RunTaskComposition

from .graph_evidence import read_graph_control
from .layout import candidate_control_dir
from .loop_models import LoopStop, LoopTrace, admit_loop
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


def execute_loop(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    composition: RunTaskComposition,
    config: WorkflowLLMConfig,
) -> CandidateRunReceipt:
    from .graph import execute_fanout
    from .graph_evidence import verify_graph_trace
    from .loop_evidence import advance_body, initial_history

    admit_loop(request)
    loop = request.preview.document.definition.loop
    assert loop is not None
    history = initial_history(request, initial)
    attempted = 0
    terminal = None
    status = "completed"
    for iteration in range(1, loop.final_iteration + 1):
        if stop_requested(initial):
            status = "stopped"
            break
        control = candidate_control_dir(Path(initial.workspace), iteration=iteration)
        control.mkdir(parents=True, exist_ok=iteration == 1)
        terminal = execute_fanout(
            request, initial, composition, config, iteration=iteration, history=history
        )
        verify_graph_trace(request, initial, terminal, iteration=iteration, history=history)
        publish_bytes_write_once(str(control / "body.json"), encode_control(terminal))
        attempted = iteration
        if terminal.status != "completed":
            status = terminal.status
            break
        advance_body(request, initial, terminal, history)
    return initial.model_copy(
        update={
            "status": status,
            "loop_trace": LoopTrace(attempted_iterations=attempted),
            "validation_passed": None if terminal is None else terminal.validation_passed,
        }
    )
