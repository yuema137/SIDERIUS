"""Console authorization and native bundle binding, not duplicate schema tests."""

import json
from pathlib import Path
from uuid import uuid4

import pytest

from tools.candidate_console import CandidateConsole, LaunchSelection, PreparedSelection
from tools.candidate_operations import LogReadRequest, read_prepared_candidate
from tools.candidate_operations.models import OperationFailure
from tools.workflow_preview import preview_workflow


def test_review_after_workspace_created_preserves_native_request(prepared):
    service, selection, _ = prepared
    saved = read_prepared_candidate(service.config.operation_store, selection.operation_id)
    workspace = Path(saved.preparation_request.candidate_workspace)
    workspace.mkdir()
    (workspace / "running.txt").write_text("native process already launched")
    review = service.review(PreparedSelection(prepare_operation_id=selection.operation_id))
    assert review.run_name == "example" and review.stages == ("propose", "implement", "validate")
    assert review.prepared_digest == saved.request_sha256
    assert read_prepared_candidate(service.config.operation_store, selection.operation_id) == saved
    with pytest.raises(ValueError, match="absent or an empty"):
        preview_workflow(saved.request.preview)


@pytest.mark.parametrize("mutation", ["advice", "declaration", "foreign_path", "symlink"])
def test_prepared_accessor_refuses_changed_bundle(prepared, mutation, tmp_path):
    service, selection, receipt = prepared
    path = Path(receipt.candidate_request_path)
    raw = json.loads(path.read_text())
    if mutation == "advice":
        raw["implementation_advice"] = "different"
    elif mutation == "declaration":
        raw["preview"]["document"]["definition"]["task"]["workspace"] = str(tmp_path / "foreign")
    elif mutation == "foreign_path":
        raw["preview"]["project_root"] = str(tmp_path)
    else:
        other = tmp_path / "copy.json"
        other.write_text(path.read_text())
        path.unlink()
        path.symlink_to(other)
    if mutation != "symlink":
        path.write_text(json.dumps(raw))
    with pytest.raises(OperationFailure, match="binding failed"):
        service.review(PreparedSelection(prepare_operation_id=selection.operation_id))


@pytest.mark.parametrize("policy", ["environment", "mount", "ambiguous"])
def test_foreign_policy_refuses_before_credentials_but_monitor_still_reads(
    prepared, monkeypatch, policy
):
    service, selection, _ = prepared
    task = service.config.tasks[0]
    updates = (
        {"candidate_environment_names": ("DIFFERENT_KEY",)}
        if policy == "environment"
        else {"task_read_only": (task.data_root,)}
    )
    tasks = (
        (task.model_copy(update=updates),)
        if policy != "ambiguous"
        else (task, task.model_copy(update={"task_id": "duplicate"}))
    )
    other = CandidateConsole(service.config.model_copy(update={"tasks": tasks}))

    def forbidden(*args, **kwargs):
        raise AssertionError("authorization must precede credential access/submission")

    monkeypatch.setattr("tools.candidate_console.service.credentials", forbidden)
    monkeypatch.setattr("tools.candidate_console.service.submit_operation", forbidden)
    with pytest.raises(OperationFailure, match="exactly one"):
        other.launch(
            LaunchSelection(
                candidate_operation_id=uuid4(),
                prepare_operation_id=selection.operation_id,
                expected_prepared_digest="0" * 64,
            )
        )
    assert other.status(selection.operation_id).native_status == "prepared"
    assert (
        other.log(LogReadRequest(operation_id=selection.operation_id, kind="native")).operation_id
        == selection.operation_id
    )


def test_stale_review_precedes_credentials_and_launch(prepared, monkeypatch):
    service, selection, _ = prepared
    monkeypatch.setattr(
        "tools.candidate_console.service.credentials", lambda *args: pytest.fail("credential read")
    )
    with pytest.raises(OperationFailure, match="changed"):
        service.launch(
            LaunchSelection(
                candidate_operation_id=uuid4(),
                prepare_operation_id=selection.operation_id,
                expected_prepared_digest="0" * 64,
            )
        )


def test_credentials_are_selected_fresh_and_not_in_projection(prepared, monkeypatch, tmp_path):
    from tools.candidate_console.files import credentials

    path = tmp_path / "credentials.json"
    path.write_text('{"A":"secret-first", "B":"unrelated"}')
    path.chmod(0o600)
    assert credentials(str(path), ("A",)) == {"A": "secret-first"}
    path.write_text('{"A":"secret-second"}')
    assert credentials(str(path), ("A",)) == {"A": "secret-second"}
    path.chmod(0o644)
    with pytest.raises(OperationFailure, match="unavailable"):
        credentials(str(path), ("A",))


def test_accessor_refuses_resource_alias_after_prepare(prepared, tmp_path):
    service, selection, _ = prepared
    data = Path(service.config.tasks[0].data_root)
    other = tmp_path / "replacement-data"
    data.rename(other)
    data.symlink_to(other, target_is_directory=True)
    with pytest.raises(OperationFailure):
        service.review(PreparedSelection(prepare_operation_id=selection.operation_id))


def test_known_code_candidate_tokens_ignore_task_choices_and_credentials(prepared, monkeypatch):
    """Known code-submitted UUID monitoring needs no currently matching task policy."""
    from tests.unit.tools.candidate_worker.test_tokens import row
    from tools.candidate_operations import CandidateOperation, submit_operation
    from tools.candidate_operations.store import load_record
    from tools.candidate_worker.models import CandidateRunReceipt

    service, preparation, _ = prepared
    assert service.tokens(preparation.operation_id).availability == "not_applicable"
    saved = read_prepared_candidate(service.config.operation_store, preparation.operation_id)
    # The prepared wrapper is deliberately unobserved; a separate state store admits this code UUID.
    config = service.config.operation_store.model_copy(
        update={"state_root": service.config.operation_store.state_root + "-code"}
    )
    submission = CandidateOperation(request_id=uuid4(), request=saved.request)
    submit_operation(config, submission, launch_environment={})
    record = load_record(config, submission.request_id)
    workspace = Path(saved.preparation_request.candidate_workspace)
    control = workspace / "candidate_run"
    control.mkdir(parents=True)
    initial = CandidateRunReceipt(
        run_id=record.native_id.hex,
        run_name=saved.request.run_name,
        workspace=str(workspace),
        declaration_digest=saved.request.declaration_digest,
        status="launched",
        node_ids=tuple(n.id for n in saved.request.preview.document.definition.nodes),
        selected_constructor_routes=saved.request.selected_constructor_routes,
        ledger_path=str(workspace / "token_usage.jsonl"),
        log_path=str(control / "worker.log"),
    )
    (control / "request.json").write_text(saved.request.model_dump_json())
    (control / "launch.json").write_text(initial.model_dump_json())
    (workspace / "token_usage.jsonl").write_bytes(
        row(run_id=initial.run_id, run_name=initial.run_name)
    )
    other = CandidateConsole(
        service.config.model_copy(
            update={
                "operation_store": config,
                "tasks": (
                    service.config.tasks[0].model_copy(
                        update={"candidate_environment_names": ("DIFFERENT_KEY",)}
                    ),
                ),
            }
        )
    )

    def forbidden(*args, **kwargs):
        pytest.fail("monitor cannot dispatch or read credentials")

    monkeypatch.setattr("tools.candidate_console.service.credentials", forbidden)
    monkeypatch.setattr("tools.candidate_console.service.submit_operation", forbidden)
    assert other.tokens(submission.request_id).groups[0].response_rows == 1
