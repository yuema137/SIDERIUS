"""Read verified authored-graph tuning records through the native run report.

This module is a read-only projection. It never ranks, reduces or rescores
results across bodies: each verified body is passed separately through the
existing ``execute_tools.run_report`` owner, in the body order accepted by the
receipt verifiers. Any evidence that cannot be re-verified becomes a typed
``OperationFailure("integrity", ...)`` whose HTTP message carries no path.
"""

import hashlib
import json
from pathlib import Path
from uuid import UUID

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from core.file_identity import open_identity_file, regular_file_snapshot
from execute_tools.run_report import project_run
from tools.candidate_operations import loop_root_operation, read_operation
from tools.candidate_operations.files import read_model
from tools.candidate_operations.models import (
    CandidateLoopResumeOperation,
    CandidateOperation,
    OperationFailure,
)
from tools.candidate_operations.read import lookup_operation_request
from tools.candidate_operations.store import native_directory
from tools.candidate_worker.graph_models import GraphNodeEvidence
from tools.candidate_worker.loop_evidence import verify_loop
from tools.candidate_worker.models import CandidateRunReceipt
from workflows.definition.fanout import execution_families

from .models import (
    ConsoleConfig,
    GraphBodyResult,
    GraphResultsView,
    GraphRunSummary,
    GraphSkippedNode,
)


def _summary(output: HyperparamTuningOutput, output_path: Path) -> GraphRunSummary:
    """Project one tuning record to graph summary; output is pre-validated."""
    view = project_run(output, source_path=output_path)
    return GraphRunSummary(
        run_name=view.run_name,
        model_type=view.model_type,
        status=view.status,
        termination_reason=view.termination_reason,
        started_at=view.started_at,
        finished_at=view.finished_at,
        completed_rounds=view.completed_rounds,
        total_attempts=view.total_attempts,
        metric=view.metric,
        metric_source=view.metric_source,
        ranking_refusal=view.ranking_refusal,
        secondary_metrics=tuple(view.secondary_metrics),
        headline=view.headline,
        status_counts=view.status_counts,
    )


def _verified_bodies(
    submission: CandidateOperation, receipt: CandidateRunReceipt
) -> tuple[CandidateRunReceipt, ...]:
    """Return body receipts in verified order; a loop re-uses ``verify_loop`` only."""
    if receipt.loop_trace is None:
        return (receipt,)
    try:
        initial = read_model(
            native_directory(submission) / "launch.json", CandidateRunReceipt, private_file=True
        )
        return verify_loop(submission.request, initial, receipt)
    except OperationFailure:
        raise
    except (OSError, ValueError) as error:
        raise OperationFailure("integrity", "verified loop bodies are unavailable") from error


def _body_result(iteration: int, tuning: GraphNodeEvidence) -> GraphBodyResult:
    """Project one body's tuning record; a non-succeeded stage carries no score."""
    if tuning.state != "succeeded":
        return GraphBodyResult(iteration=iteration, tuning_state=tuning.state, result=None)
    if tuning.record_path is None or tuning.record_sha256 is None:
        raise OperationFailure("integrity", "verified tuning output identity is missing")
    try:
        output = _verified_record(tuning.record_path, tuning.record_sha256)
        result = _summary(output, Path(tuning.record_path))
    except OperationFailure:
        raise
    except (OSError, ValueError) as error:
        # ValueError covers JSON syntax and pydantic ValidationError.
        raise OperationFailure("integrity", "verified tuning output is unavailable") from error
    return GraphBodyResult(
        iteration=iteration,
        tuning_state=tuning.state,
        result=result,
        outcome=tuner_outcome(result),
    )


def tuner_outcome(summary: GraphRunSummary) -> str:
    """One plain sentence of what the tuner achieved, from its own record.

    The graph node state only says the node executed; a tuner that completed no
    round (every attempt refused or failed) must never read as a success.
    """
    rounds = summary.completed_rounds
    counted = (
        f"{rounds} completed round{'s' if rounds != 1 else ''} in "
        f"{summary.total_attempts} attempt{'s' if summary.total_attempts != 1 else ''}"
    )
    ending = summary.termination_reason.replace("_", " ")
    if rounds == 0:
        return f"No training round completed: {counted} (tuner status {summary.status}; ended by {ending})."
    if summary.status == "completed":
        return f"Completed: {counted} (ended by {ending})."
    return f"Not completed (tuner status {summary.status}): {counted} (ended by {ending})."


def _verified_record(path: str, expected_sha256: str) -> HyperparamTuningOutput:
    """Read the record once (no-follow), check its digest and parse those same bytes.

    Parsing mirrors ``load_run_output`` (``json.loads`` then ``model_validate``)
    so a valid record projects exactly as before.
    """
    with open_identity_file(path, require_no_follow=True) as handle:
        before = regular_file_snapshot(handle)
        data = handle.read()
        if regular_file_snapshot(handle) != before:
            raise ValueError("native record changed while reading")
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise OperationFailure("integrity", "verified tuning output changed")
    return HyperparamTuningOutput.model_validate(json.loads(data))


def read_graph_results(config: ConsoleConfig, operation_id: UUID) -> GraphResultsView:
    """Show each verified authored body independently; never aggregate loop scores.

    ``available`` is false unless the operation is a completed candidate or
    authored-loop resume segment whose native receipt carries graph or loop
    evidence. A paused or resumed segment lists every body verified up to its own
    receipt, resolved through the operations owner's root, never by directory. A
    loop that verified no body is available with zero bodies, so the monitor
    states that nothing was recorded instead of hiding the result section.
    """
    snapshot = read_operation(config.operation_store, operation_id)
    unavailable = GraphResultsView(operation_id=operation_id, available=False)
    receipt = snapshot.receipt
    if snapshot.state != "completed" or not isinstance(receipt, CandidateRunReceipt):
        return unavailable
    if receipt.graph_trace is None and receipt.loop_trace is None:
        return unavailable
    submission = lookup_operation_request(config.operation_store, operation_id)
    if isinstance(submission, CandidateLoopResumeOperation):
        # read_operation already verified this segment's receipt against its root;
        # verify_loop replays every body from the root request and launch receipt.
        submission = loop_root_operation(config.operation_store, operation_id)
    if not isinstance(submission, CandidateOperation):
        return unavailable

    bodies = _verified_bodies(submission, receipt)
    preview = submission.request.preview
    tuning_id = execution_families(preview.document.definition, preview.execution_profile).tuning
    if tuning_id is None:
        raise OperationFailure("integrity", "verified graph has no declared tuning node")

    results: list[GraphBodyResult] = []
    for iteration, body in enumerate(bodies, start=1):
        nodes = () if body.graph_trace is None else body.graph_trace.nodes
        tuning = next((item for item in nodes if item.node_id == tuning_id), None)
        if tuning is None:
            raise OperationFailure("integrity", "verified graph is missing its tuning node")
        skipped = tuple(
            GraphSkippedNode(node_id=item.node_id, reason=item.reason)
            for item in nodes
            if item.state == "skipped" and item.reason is not None
        )
        results.append(_body_result(iteration, tuning).model_copy(update={"skipped": skipped}))
    return GraphResultsView(operation_id=operation_id, available=True, bodies=tuple(results))
