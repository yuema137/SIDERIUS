"""Authored loop segment bindings, clean checkpoints and internal continuation launch."""

import hashlib
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from core.control_json import encode_control
from core.durable_io import publish_bytes_write_once
from tools.workspace_sandbox.profile import SandboxProfile
from tools.workspace_sandbox.runner import ObservedExecutionResult, run_observed

from .graph_evidence import read_graph_control
from .loop_models import LoopContinuation
from .models import CandidateRunReceipt, CandidateRunRequest

if TYPE_CHECKING:
    from core.chain_state import ChainState

    from .loop_stop import BodyScore


def segment_control(initial: CandidateRunReceipt, segment_id: UUID | None) -> Path:
    root = Path(initial.workspace) / "candidate_run"
    return root if segment_id is None else root / "continuations" / str(segment_id)


def read_continuation(initial: CandidateRunReceipt, segment_id: UUID) -> LoopContinuation:
    value = LoopContinuation.model_validate_json(
        read_graph_control(segment_control(initial, segment_id) / "continuation.json")
    )
    if (value.run_id, value.declaration_digest, value.operation_id) != (
        initial.run_id,
        initial.declaration_digest,
        segment_id,
    ):
        raise ValueError("continuation identity mismatch")
    linked = LoopContinuation.model_validate_json(
        read_graph_control(segment_control(initial, value.predecessor_segment) / "successor.json")
    )
    if linked != value:
        raise ValueError("continuation does not match reserved successor")
    return value


def require_clean(control: Path) -> ObservedExecutionResult:
    observed = ObservedExecutionResult.model_validate_json(
        read_graph_control(control / "supervision.json")
    )
    if (
        observed.execution.status != "completed"
        or observed.execution.returncode != 0
        or not observed.direct_child_reaped
        or observed.cleanup.final.status != "absent"
    ):
        raise ValueError("loop segment lacks proven clean supervision")
    return observed


def predecessor(initial: CandidateRunReceipt, binding: LoopContinuation) -> CandidateRunReceipt:
    control = segment_control(initial, binding.predecessor_segment)
    payload = read_graph_control(control / "receipt.json")
    receipt = CandidateRunReceipt.model_validate_json(payload)
    trace = receipt.loop_trace
    if (
        hashlib.sha256(payload).hexdigest() != binding.predecessor_receipt_digest
        or receipt.status != "paused"
        or trace is None
        or trace.segment_id != binding.predecessor_segment
        or trace.attempted_iterations != binding.completed_iterations
        or receipt.run_id != initial.run_id
        or receipt.declaration_digest != initial.declaration_digest
        or receipt.workspace != initial.workspace
    ):
        raise ValueError("continuation predecessor is not the reviewed paused checkpoint")
    require_clean(control)
    return receipt


def verify_segment(initial: CandidateRunReceipt, receipt: CandidateRunReceipt) -> int:
    """Validate immutable ancestry without recursion or an arbitrary segment limit.

    Returns the completed-body count at which the receipt's own segment resumed (0 at root).
    """
    from .loop import pause_requested

    assert receipt.loop_trace is not None
    segment_id = receipt.loop_trace.segment_id
    seen = set()
    upper = receipt.loop_trace.attempted_iterations
    first = 0
    while segment_id is not None:
        if segment_id in seen:
            raise ValueError("loop continuation cycle")
        seen.add(segment_id)
        binding = read_continuation(initial, segment_id)
        if binding.completed_iterations > upper:
            raise ValueError("continuation checkpoint moved backwards")
        if len(seen) == 1:
            first = binding.completed_iterations
        prior = predecessor(initial, binding)
        if not pause_requested(initial, binding.predecessor_segment):
            raise ValueError("predecessor lacks Pause request")
        upper = binding.completed_iterations
        assert prior.loop_trace is not None
        segment_id = prior.loop_trace.segment_id
    return first


def has_successor(initial: CandidateRunReceipt, receipt: CandidateRunReceipt) -> bool:
    assert receipt.loop_trace is not None
    control = segment_control(initial, receipt.loop_trace.segment_id)
    try:
        binding = LoopContinuation.model_validate_json(
            read_graph_control(control / "successor.json")
        )
    except FileNotFoundError:
        return False
    if read_continuation(initial, binding.operation_id) != binding:
        raise ValueError("successor binding changed")
    if predecessor(initial, binding) != receipt:
        raise ValueError("successor does not bind selected checkpoint")
    return True


def resume_history(
    request: CandidateRunRequest, initial: CandidateRunReceipt, binding: LoopContinuation
) -> tuple["ChainState", tuple[CandidateRunReceipt, ...], tuple["BodyScore", ...]]:
    """Run under the native lease: recheck the binding, then rebuild history by replay.

    Returns the history, every completed body receipt (the last one feeds the next
    body) and the stop-score carrier, all from the same whole-run replay, so conditions
    and judge requests span segments. A paused boundary already holds its judge
    evidence; the continuation starts at the next boundary, so none is judged twice.
    """
    from .loop import stop_requested
    from .loop_evidence import replay_completed, require_unused_next, verify_loop

    if read_continuation(initial, binding.operation_id) != binding:
        raise ValueError("resume binding changed")
    prior = predecessor(initial, binding)
    verify_loop(request, initial, prior)
    if stop_requested(initial):
        raise ValueError("stopped loop cannot resume")
    require_unused_next(request, initial, binding.completed_iterations)
    state, bodies, scores = replay_completed(request, initial, binding.completed_iterations)
    last = bodies[-1] if bodies else None
    if last is None or last.status != "completed":
        raise ValueError("resume requires completed required feedback")
    return state, bodies, scores


def launch_continuation(
    request: CandidateRunRequest, initial: CandidateRunReceipt, binding: LoopContinuation
) -> CandidateRunReceipt:
    """Only operation admission publishes the binding; no fresh-workspace bypass."""
    from .launch import bounded_terminal, publish, reconcile

    control = segment_control(initial, binding.operation_id)
    if read_continuation(initial, binding.operation_id) != binding:
        raise ValueError("resume launch binding changed")
    profile = SandboxProfile(
        workspace=Path(initial.workspace),
        read_only=tuple(Path(p) for p in request.read_only),
        network=request.network,
        devices=tuple(Path(p) for p in request.devices),
        environment_names=request.environment_names,
        timeout_seconds=request.timeout_seconds,
    )
    try:
        observed = run_observed(
            profile, [sys.executable, "-m", __name__, str(control / "continuation.json")]
        )
        publish_bytes_write_once(str(control / "supervision.json"), encode_control(observed))
        terminal = reconcile(
            initial, observed.execution, control / "child.json", graph_request=request
        )
        if terminal.status == "paused":
            require_clean(control)
    except KeyboardInterrupt:
        terminal = initial.model_copy(
            update={"status": "interrupted", "error": "worker interrupted"}
        )
    except Exception as error:
        terminal = initial.model_copy(
            update={"status": "failed", "error": f"{type(error).__name__}: {error}"}
        )
    terminal = bounded_terminal(initial, terminal)
    publish(control / "receipt.json", terminal, bounded=True)
    return terminal


def execute_continuation(path: Path) -> CandidateRunReceipt:
    from core.generated_library import bind_generated_library_to_workspace

    from .budget import WorkerBudget
    from .child import verify_inputs
    from .launch import bounded_terminal, publish

    binding = LoopContinuation.model_validate_json(read_graph_control(path))
    root = path.parent.parent.parent
    request = CandidateRunRequest.model_validate_json(read_graph_control(root / "request.json"))
    budget = WorkerBudget.start(request.timeout_seconds)
    initial = CandidateRunReceipt.model_validate_json(read_graph_control(root / "launch.json"))
    if path != segment_control(initial, binding.operation_id) / "continuation.json":
        raise ValueError("continuation path disagrees with root")
    verify_inputs(request, root)
    bind_generated_library_to_workspace(initial.workspace)
    from .native import execute_native

    receipt = bounded_terminal(
        initial, execute_native(request, initial, continuation=binding, budget=budget)
    )
    publish(path.parent / "child.json", receipt, bounded=True)
    return receipt


if __name__ == "__main__":
    selected = Path(sys.argv[1])
    with (selected.parent / "worker.log").open("x") as log:
        os.dup2(log.fileno(), 1)
        os.dup2(log.fileno(), 2)
        execute_continuation(selected)
