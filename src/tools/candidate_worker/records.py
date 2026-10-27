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
        or initial.graph_trace is not None
        or initial.loop_trace is not None
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

        if saved.preview.execution_profile is not None:
            from .graph_evidence import verify_graph_trace

            if saved.preview.document.definition.loop is not None:
                from .loop_evidence import verify_loop

                verify_loop(saved, initial, receipt)
            else:
                verify_graph_trace(saved, initial, receipt)
            return
        if receipt.graph_trace is not None or receipt.loop_trace is not None:
            raise ValueError("fixed candidate receipt cannot contain graph evidence")
        if any(node.capability == "tuning" for node in saved.preview.document.definition.nodes):
            if (
                receipt.status == "completed"
                or receipt.training_output is not None
                or (receipt.status == "failed" and receipt.native_output_paths)
            ):
                from .training_evidence import verify_training_evidence

                verify_training_evidence(receipt)
            elif receipt.status == "accepted":
                raise ValueError("four-stage native receipt cannot end at accepted")
        elif receipt.status == "completed" or receipt.training_output is not None:
            raise ValueError("three-stage receipt cannot claim native training")
