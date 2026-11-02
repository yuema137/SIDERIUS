"""Opt-in offline benchmark of the real list owner over 20 three-iteration loops."""

import os
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pytest

from tools.candidate_console import CandidateConsole, ConsoleConfig
from tools.candidate_operations import OperationStoreConfig, submit_operation
from tools.candidate_operations.models import CandidateOperation

from .conftest import _prepare_request
from .test_finite_loop import loop_request
from .test_finite_loop import loop_tuner as loop_tuner
from .test_interpretation import interpretation_provider as interpretation_provider
from .test_loop_resume import process_segments as process_segments
from .test_native import native_runner as native_runner
from .test_training import training_runner as training_runner


@pytest.mark.skipif(
    os.environ.get("SIDERIUS_CONSOLE_OUTCOME_BENCHMARK") != "1",
    reason="explicit offline list-cost benchmark",
)
def test_twenty_completed_loops_list_cost(
    prepared,
    loop_tuner,
    interpretation_provider,
    native_runner,
    process_segments,
    monkeypatch,
    tmp_path,
):
    """No timing assertion: report cold/warm list costs, assert 20 verified 3-iteration rows."""
    store = OperationStoreConfig(
        state_root=str(tmp_path / "operations"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    from agent.schemas.proposal import ProposalInput
    from agent.schemas.proposer_evidence import ProposerInterpretationEvidence
    from workflows.task_composition import build_task_composition_ref, compose_run_task_bindings

    for index in range(20):
        case = tmp_path / f"run-{index:02d}"
        project = case / "project"
        project.mkdir(parents=True)
        (project / "data").mkdir()
        candidate = _prepare_request(
            project,
            case / "workspace",
            compose_run_task_bindings,
            build_task_composition_ref,
            ProposalInput,
            ProposerInterpretationEvidence,
        )
        submission = CandidateOperation(
            request_id=uuid4(), request=loop_request(candidate, final_iteration=3)
        )
        submit_operation(
            store, submission, launch_environment={"OPENAI_API_KEY": "offline-test-key"}
        )
        process_segments()
    token = tmp_path / "console-token"
    token.write_text("offline-benchmark-token-012345678901234567890123456789")
    token.chmod(0o600)
    config = ConsoleConfig(
        operation_store=store,
        auth_token_file=str(token),
        port=8740,
        browser_origin="http://127.0.0.1:8740",
    )
    console = CandidateConsole(config)
    durations = []
    for _ in range(3):
        started = perf_counter()
        listing = console.operations()
        durations.append(perf_counter() - started)
        assert len(listing.operations) == 20
        assert all(
            item.native_status == "completed"
            and item.outcome is not None
            and item.outcome.completed_iterations == 3
            for item in listing.operations
        )
    print(f"LIST_COST_SECONDS cold={durations[0]:.6f} warm={durations[1:]}")
    print(f"LIST_COST_WORKSPACE {tmp_path}")
