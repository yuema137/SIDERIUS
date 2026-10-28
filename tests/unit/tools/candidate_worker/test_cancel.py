"""Loop cancellation: only supervision records ``cancelled``; the receipt verifies and cannot resume."""

import importlib
from pathlib import Path

import pytest

from core.runtime_control.process_group import GroupCleanup, GroupObservation
from tools.candidate_worker import launch_candidate
from tools.candidate_worker.loop_resume import require_clean
from tools.candidate_worker.models import CandidateRunReceipt
from tools.candidate_worker.records import verify_candidate_records
from tools.workspace_sandbox import runner
from tools.workspace_sandbox.runner import ExecutionResult, ObservedExecutionResult

from .test_finite_loop import loop_request

launch_module = importlib.import_module("tools.candidate_worker.launch")


def test_supervised_cancel_yields_verifiable_unresumable_loop_receipt(prepared, monkeypatch):
    """Fails if a cancelled loop terminal is rejected by the shared record verifier (the
    operation reader would then report it unknown), or if its supervision could pass
    the clean-checkpoint check that authorizes Resume."""
    request = loop_request(prepared)
    monkeypatch.setattr(
        runner, "build_command", lambda profile, argv: (["/bin/sh", "-c", "sleep 600"], {})
    )
    receipt = launch_candidate(request, cancel_requested=lambda: True)
    assert receipt.status == "cancelled" and receipt.loop_trace is None
    control = Path(receipt.workspace) / "candidate_run"
    initial = CandidateRunReceipt.model_validate_json((control / "launch.json").read_bytes())
    verify_candidate_records(
        request,
        initial,
        expected_request=request,
        expected_run_id=receipt.run_id,
        workspace=Path(receipt.workspace),
        receipt=receipt,
    )
    with pytest.raises(ValueError, match="clean supervision"):
        require_clean(control)


def test_child_cannot_claim_cancellation(prepared, monkeypatch):
    """Fails if a sandboxed child that exits normally can label its own receipt
    ``cancelled`` (the loop verifier accepts a trace-less cancelled terminal)."""
    request = loop_request(prepared)

    def run_observed(profile, argv, **_):
        control = profile.workspace / "candidate_run"
        initial = CandidateRunReceipt.model_validate_json((control / "launch.json").read_bytes())
        (control / "child.json").write_text(
            initial.model_copy(update={"status": "cancelled"}).model_dump_json()
        )
        return ObservedExecutionResult(
            execution=ExecutionResult(status="completed", returncode=0, elapsed_seconds=0.1),
            cleanup=GroupCleanup(required=False, final=GroupObservation(status="absent")),
            direct_child_reaped=True,
        )

    monkeypatch.setattr(launch_module, "run_observed", run_observed)
    receipt = launch_candidate(request)
    assert receipt.status == "failed"
