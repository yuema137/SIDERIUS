"""Inert identity verification shared by native and operation read projections."""

from pathlib import Path

from .models import CandidateRunReceipt, CandidateRunRequest


def verify_candidate_records(
    saved: CandidateRunRequest,
    initial: CandidateRunReceipt,
    *,
    expected_request: CandidateRunRequest,
    expected_run_id: str,
    workspace: Path,
    receipt: CandidateRunReceipt | None = None,
) -> None:
    """Verify fixed record identity; interpret no process or acceptance status."""
    control = workspace / "candidate_run"
    request = expected_request
    if (
        saved != request
        or initial.run_id != expected_run_id
        or initial.status != "launched"
        or (receipt is not None and receipt.status == "launched")
        or initial.workspace != str(workspace)
        or initial.run_name != request.run_name
        or initial.declaration_digest != request.declaration_digest
        or initial.node_ids != tuple(node.id for node in request.preview.document.definition.nodes)
        or initial.selected_constructor_routes != request.selected_constructor_routes
        or initial.log_path != str(control / "worker.log")
        or initial.ledger_path != str(workspace / "token_usage.jsonl")
    ):
        raise ValueError("native candidate launch mismatch")
    if receipt is not None:
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
            if getattr(receipt, name) != getattr(initial, name):
                raise ValueError("native candidate receipt identity mismatch")
