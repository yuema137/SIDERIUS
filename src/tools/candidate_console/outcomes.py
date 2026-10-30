"""Read-only outcome facts from verified receipts, shared by status and list."""

from tools.candidate_operations import OperationSnapshot, OperationStoreConfig, loop_root_operation
from tools.candidate_worker.graph_models import GraphCapability
from tools.candidate_worker.models import CandidateRunReceipt

from .graph_results import verified_bodies
from .models import OutcomeEvidence


def outcome_evidence(
    store: OperationStoreConfig, snapshot: OperationSnapshot
) -> OutcomeEvidence | None:
    """Do not infer failure from a false validation flag or from log text.

    Loop aggregates have no graph trace; replay through the worker verifier to
    find the failed iteration and count only receipts with status completed.
    """
    receipt = snapshot.receipt
    if not isinstance(receipt, CandidateRunReceipt):
        return None
    bodies = (receipt,)
    completed = None
    if receipt.loop_trace is not None:
        root = loop_root_operation(store, snapshot.operation_id)
        if root is None:
            return None
        bodies = verified_bodies(root, receipt)
        completed = sum(body.status == "completed" for body in bodies)
    phases: dict[GraphCapability, None] = {
        node.capability: None
        for body in bodies
        if body.graph_trace is not None
        for node in (*body.graph_trace.nodes, *body.graph_trace.adaptors)
        if node.state == "failed"
    }
    return OutcomeEvidence(
        validation_passed=receipt.validation_passed,
        failed_phases=tuple(phases),
        completed_iterations=completed,
    )
