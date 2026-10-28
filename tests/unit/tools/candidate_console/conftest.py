"""Synthetic configured resources and real native offline preparation artifacts."""

import importlib
import secrets
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from tests.unit.tools.candidate_prepare.conftest import selection
from tools.candidate_console import CandidateConsole, ConsoleConfig, PrepareSelection, TaskChoice
from tools.candidate_operations import OperationStoreConfig
from tools.candidate_operations.store import load_record
from tools.candidate_prepare import prepare_candidate
from tools.workspace_sandbox.runner import ExecutionResult


@pytest.fixture
def console_config(selection, tmp_path):
    prep, candidate = tmp_path / "preparations", tmp_path / "candidates"
    prep.mkdir()
    candidate.mkdir()
    token = tmp_path / "token"
    token.write_text(secrets.token_urlsafe(32))
    token.chmod(0o600)
    fields = selection.model_dump(
        exclude={
            "output_dir",
            "candidate_workspace",
            "run_name",
            "proposal_advice",
            "implementation_advice",
            "validation_advice",
        }
    )
    task = TaskChoice(
        **fields,
        task_id="synthetic",
        label="Synthetic task",
        preparation_root=str(prep),
        candidate_root=str(candidate),
    )
    return ConsoleConfig(
        operation_store=OperationStoreConfig(
            state_root=str(tmp_path / "state"),
            preparation_roots=(str(prep),),
            candidate_roots=(str(candidate),),
        ),
        tasks=(task,),
        port=8740,
        browser_origin="http://127.0.0.1:8740",
        auth_token_file=str(token),
    )


@pytest.fixture
def prepared(console_config, monkeypatch):
    service = CandidateConsole(console_config)
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", lambda *args: None)
    selection = PrepareSelection(
        operation_id=uuid4(),
        task_id="synthetic",
        run_name="example",
        proposal_advice="Keep the declared features.",
        implementation_advice="Small model.",
    )
    service.prepare(selection)
    record = load_record(console_config.operation_store, selection.operation_id)

    def offline(profile, argv):
        result = subprocess.run(argv, capture_output=True, text=True, timeout=45)
        assert result.returncode == 0, result.stderr
        return ExecutionResult(status="completed", returncode=0, elapsed_seconds=0.0)

    monkeypatch.setattr(importlib.import_module("tools.candidate_prepare.launch"), "run", offline)
    # As the operation child does: the admitted nonce and run seed.
    receipt = prepare_candidate(
        record.submission.request, invocation_id=record.native_id, run_seed=record.run_seed
    )
    assert receipt.status == "prepared", receipt.error
    return service, selection, receipt
