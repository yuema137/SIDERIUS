"""Real detached reusable preparation → B3 selection → sandboxed candidate transport.

Only the candidate provider is replaced by the existing offline fixture. No API/GPU.
"""

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from tests.integration.tools.test_candidate_operations import wait_for
from tests.integration.tools.test_candidate_operations_native import cli, native_submitter
from tests.unit.tools.candidate_console.conftest import console_config
from tests.unit.tools.candidate_prepare.conftest import selection
from tests.unit.tools.candidate_prepare.test_reusable_preparation import reusable
from tools.candidate_console.reusable_candidate import ReusableCandidate
from tools.candidate_console.reusable_models import ReusableCaptureChoice
from tools.candidate_console.service import CandidateConsole
from tools.candidate_operations import (
    ReusablePrepareOperation,
    build_reusable_operation,
    read_operation,
)
from tools.candidate_operations.process import environment
from tools.candidate_operations.read import releasable
from tools.candidate_operations.store import load_record
from tools.workflow_authoring.models import Project

pytestmark = pytest.mark.skipif(
    os.environ.get("SIDERIUS_TEST_WORKSPACE_SANDBOX") != "1",
    reason="requires explicit bubblewrap-capable host opt-in",
)


def test_detached_capture_is_consumable_by_b3_and_candidate(reusable, console_config, tmp_path):
    """Actual detached child publishes native capture; B3 independently reviews before launch."""
    reusable = reusable.model_copy(
        update={"candidate_environment_names": ("EXPLICIT_TEST_KEY", "OPENAI_API_KEY")}
    )
    store = console_config.operation_store.model_copy(
        update={
            "preparation_roots": (
                *console_config.operation_store.preparation_roots,
                reusable.runs_root,
            ),
            "candidate_roots": (
                *console_config.operation_store.candidate_roots,
                reusable.runs_root,
            ),
        }
    )
    store_path = tmp_path / "store.json"
    store_path.write_text(store.model_dump_json())
    submission = ReusablePrepareOperation(request_id=uuid4(), request=reusable)
    request_path = tmp_path / "prepare.json"
    request_path.write_text(submission.model_dump_json())
    original = Path(reusable.source_path).read_bytes()
    assert (
        json.loads(cli(store_path, "submit", "--request", str(request_path)).stdout)["observation"]
        == "starting"
    )
    wait_for(lambda: releasable(store, submission.request_id), timeout=45)
    snapshot = read_operation(store, submission.request_id)
    assert snapshot.state == "completed" and snapshot.receipt.status == "prepared", snapshot
    assert snapshot.receipt.preparation_id == load_record(store, submission.request_id).native_id
    assert snapshot.receipt.run_id == reusable.run_id
    envelope = Path(snapshot.receipt.envelope)
    assert (envelope / "workflow.py.snapshot").read_bytes() == original
    assert not (envelope / "workspace").exists()

    recovery = tmp_path / "recovery"
    recovery.mkdir(mode=0o700)
    project = Project(
        project_id="detached",
        project_root=Path(reusable.project_root),
        source_file=Path(reusable.source_path),
        recovery_directory=recovery,
    )
    task = console_config.tasks[0].model_copy(
        update={
            "reusable_runs_root": reusable.runs_root,
            "allowed_output_types": None,
            "candidate_environment_names": reusable.candidate_environment_names,
        }
    )
    adapter = ReusableCandidate(
        CandidateConsole(
            console_config.model_copy(
                update={
                    "operation_store": store,
                    "tasks": (task,),
                    "editor_projects": (project,),
                    "runnable_editor_projects": (project.project_id,),
                }
            )
        )
    )
    selected = adapter.select(
        project.project_id, ReusableCaptureChoice(task_id=task.task_id, run_id=reusable.run_id)
    )
    review = adapter.review(project.project_id, selected)
    assert review.source_sha256 == reusable.expected_source_sha256
    assert review.workspace == str(envelope / "workspace")
    candidate = build_reusable_operation(store, selected.preparation, uuid4())
    submitter = native_submitter(tmp_path, envelope / "inputs")
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(candidate.model_dump_json())
    source_env = {
        **environment((), {}),
        "EXPLICIT_TEST_KEY": "bound-value",
        "OPENAI_API_KEY": "offline-test-key",
        "UNRELATED_SENTINEL": "never-pass",
    }
    cli(store_path, "submit", "--request", str(candidate_path), harness=submitter, env=source_env)
    wait_for(lambda: releasable(store, candidate.request_id), timeout=60)
    result = read_operation(store, candidate.request_id)
    assert result.state == "completed" and result.receipt.status == "accepted", result
    assert result.receipt.node_ids == ("hypothesis", "build", "check")
    validation = json.loads(Path(result.receipt.native_output_paths[-1]).read_bytes())
    assert (
        validation["tests_passed"]
        and validation["instantiation_passed"]
        and validation["gradient_check_passed"]
    )
    assert Path(reusable.source_path).read_bytes() == original
    assert (
        json.loads(cli(store_path, "submit", "--request", str(request_path)).stdout)["observation"]
        == "existing"
    )


def test_detached_reusable_native_timeout(reusable, console_config, tmp_path):
    """Real native timeout publishes failed preparation evidence and releases after exit."""
    reusable = reusable.model_copy(update={"preparation_timeout_seconds": 0.001})
    store = console_config.operation_store.model_copy(
        update={
            "preparation_roots": (reusable.runs_root,),
            "candidate_roots": (reusable.runs_root,),
        }
    )
    store_path, request_path = tmp_path / "store.json", tmp_path / "request.json"
    store_path.write_text(store.model_dump_json())
    submission = ReusablePrepareOperation(request_id=uuid4(), request=reusable)
    request_path.write_text(submission.model_dump_json())
    cli(store_path, "submit", "--request", str(request_path))
    wait_for(lambda: releasable(store, submission.request_id), timeout=15)
    result = read_operation(store, submission.request_id)
    assert result.state == "completed" and result.receipt.status == "timed_out", result
    assert result.receipt.candidate_request_path is None
