"""Actual CLI and authenticated HTTP status consume the same large-history policy."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.runtime_control.process_group import GroupCleanup, GroupObservation
from tests.unit.tools.candidate_console.test_http import client
from tests.unit.tools.candidate_console.test_native_chain import native_config
from tests.unit.tools.candidate_operations.test_native_chain import chain
from tests.unit.tools.native_chain.test_observation_read_budget import large_history
from tools.candidate_operations import read_operation
from tools.candidate_operations.files import publish
from tools.candidate_operations.native_chain import publish_chain_terminal
from tools.workspace_sandbox.runner import ExecutionResult, ObservedExecutionResult


@pytest.mark.parametrize("chain", [None, 16777216], indirect=True)
def test_large_history_public_status_policy(chain, console_config, tmp_path):
    record, path = chain
    large_history(Path(record.native_chain_admission.workspace))
    supervision = ObservedExecutionResult(
        execution=ExecutionResult(status="completed", returncode=0, elapsed_seconds=1),
        direct_child_reaped=True,
        cleanup=GroupCleanup(required=True, final=GroupObservation(status="absent")),
    )
    completion = publish_chain_terminal(record, path, supervision)
    publish(path / "completion.json", completion)
    terminal_bytes = (path / "native-chain-terminal.json").read_bytes()
    if record.submission.request.max_evidence_read_bytes is None:
        assert b"max_evidence_read_bytes" not in (path / "request.json").read_bytes()
    expected = (
        "available" if record.submission.request.max_evidence_read_bytes else "limit_exceeded"
    )
    snapshot = read_operation(record.config, record.submission.request_id)
    assert snapshot.state == "completed"
    assert snapshot.native_chain.evidence.availability == expected
    assert snapshot.native_chain.terminal.observation_policy == (
        3 if expected == "available" else 2
    )
    store = tmp_path / "store.json"
    store.write_text(record.config.model_dump_json())
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.candidate_operations",
            "status",
            "--store-config",
            str(store),
            "--operation-id",
            str(record.submission.request_id),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    cli = json.loads(result.stdout)
    response = client(native_config(console_config, record)).get(
        f"/api/operations/{record.submission.request_id}"
    )
    assert response.status_code == 200, response.text
    assert (
        cli["native_chain"]
        == response.json()["native_chain"]
        == snapshot.model_dump(mode="json")["native_chain"]
    )
    assert (path / "native-chain-terminal.json").read_bytes() == terminal_bytes
