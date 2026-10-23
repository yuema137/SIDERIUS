"""Detached reusable admission, durable retry identity and native outcome projection."""

import importlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from tests.unit.tools.candidate_prepare.test_reusable_preparation import reusable
from tools.candidate_operations import (
    LogReadRequest,
    OperationStoreConfig,
    ReusablePreparationExpectation,
    ReusablePrepareOperation,
    operation_request_digest,
    read_operation,
    read_operation_log,
    read_operation_tokens,
    recover_reusable_preparation,
    submit_operation,
)
from tools.candidate_operations.models import OperationFailure
from tools.candidate_operations.store import load_record
from tools.candidate_prepare import preflight_reusable_candidate
from tools.candidate_prepare.reusable_models import ReusablePreparationObservations
from tools.workspace_sandbox.runner import ExecutionResult


@pytest.fixture
def intent(reusable, tmp_path):
    config = OperationStoreConfig(
        state_root=str(tmp_path / "state"),
        preparation_roots=(reusable.runs_root,),
        candidate_roots=(reusable.runs_root,),
    )
    submission = ReusablePrepareOperation(request_id=uuid4(), request=reusable)
    expected = ReusablePreparationExpectation(
        request_digest=operation_request_digest(submission),
        observations=ReusablePreparationObservations.from_binding(
            preflight_reusable_candidate(reusable).binding
        ),
    )
    return config, submission, expected


def test_known_identity_recovery_ignores_missing_inputs_and_never_respawns(intent, monkeypatch):
    """Lost responses recover durable observations, whereas changed reviewed observations conflict."""
    config, submission, expected = intent
    owner = importlib.import_module("tools.candidate_operations.submit")
    calls = []
    monkeypatch.setattr(owner, "spawn", lambda path, env: calls.append((path, env)))
    first = submit_operation(
        config,
        submission,
        expected_reusable_inputs=expected,
        launch_environment={"OPENAI_API_KEY": "not-forwarded"},
    )
    record = load_record(config, submission.request_id)
    assert record.inputs == expected.observations.as_inputs()
    assert "OPENAI_API_KEY" not in calls[0][1]
    Path(submission.request.source_path).unlink()
    Path(submission.request.llm_config_file).unlink()
    monkeypatch.setattr(
        owner, "preflight_reusable_candidate", lambda *_: pytest.fail("known ID reobserved")
    )
    assert recover_reusable_preparation(config, submission.request_id, expected) == submission
    retry = submit_operation(
        config, submission, expected_reusable_inputs=expected, launch_environment={}
    )
    assert retry.observation == "existing" and retry.request_digest == first.request_digest
    assert len(calls) == 1
    changed = expected.model_copy(
        update={
            "observations": expected.observations.model_copy(
                update={
                    "config": expected.observations.config.model_copy(update={"sha256": "0" * 64})
                }
            )
        }
    )
    with pytest.raises(OperationFailure, match="reviewed intent"):
        recover_reusable_preparation(config, submission.request_id, changed)
    with pytest.raises(OperationFailure, match="reviewed intent"):
        submit_operation(
            config, submission, expected_reusable_inputs=changed, launch_environment={}
        )


def test_stale_review_conflicts_before_claim(intent, monkeypatch):
    """Digest alone cannot authenticate mutable configuration bytes at fresh admission."""
    config, submission, expected = intent
    Path(submission.request.llm_config_file).write_text("{}\n")
    owner = importlib.import_module("tools.candidate_operations.submit")
    monkeypatch.setattr(owner, "spawn", lambda *a: pytest.fail("stale review spawned"))
    with pytest.raises(OperationFailure, match="reviewed intent"):
        submit_operation(
            config, submission, expected_reusable_inputs=expected, launch_environment={}
        )
    assert not (Path(config.state_root) / "operations" / str(submission.request_id)).exists()
    assert list(Path(submission.request.runs_root).iterdir()) == []


@pytest.mark.parametrize("outcome", ["failed", "timed_out", "interrupted"])
def test_dispatch_binds_receipts_logs_tokens_and_console(intent, monkeypatch, outcome):
    """The real wrapper invokes B1 with its nonce and projects native failures honestly."""
    config, submission, _ = intent
    owner = importlib.import_module("tools.candidate_operations.submit")
    child = importlib.import_module("tools.candidate_operations.child")
    launch = importlib.import_module("tools.candidate_prepare.reusable_launch")
    monkeypatch.setattr(owner, "spawn", lambda *a: None)
    submit_operation(config, submission, launch_environment={})
    record = load_record(config, submission.request_id)

    def result(*args, **kwargs):
        if outcome == "interrupted":
            raise KeyboardInterrupt
        return ExecutionResult(status=outcome, returncode=-9, elapsed_seconds=1)

    monkeypatch.setattr(launch, "supervise", result)
    assert child.execute(Path(config.state_root) / "operations" / str(submission.request_id)) == 0
    snapshot = read_operation(config, submission.request_id)
    assert snapshot.state == "completed" and snapshot.receipt.status == outcome
    assert snapshot.receipt.preparation_id == record.native_id
    assert read_operation_tokens(config, submission.request_id).availability == "not_applicable"
    logs = read_operation_log(
        config, LogReadRequest(operation_id=submission.request_id, kind="native")
    )
    assert logs.missing
    native = (
        Path(submission.request.runs_root) / str(submission.request.run_id) / "inputs/preparation"
    )
    (native / "worker.log").write_text("native log")
    assert (
        read_operation_log(
            config, LogReadRequest(operation_id=submission.request_id, kind="native")
        ).text
        == "native log"
    )
    # Exercise the service projection without constructing unrelated catalog/credential policy.
    from types import SimpleNamespace

    from tools.candidate_console.service import CandidateConsole

    view = CandidateConsole.status(
        SimpleNamespace(config=SimpleNamespace(operation_store=config)), submission.request_id
    )
    assert view.kind == "prepare_reusable" and view.native_id == str(record.native_id)
    assert view.validation_passed is None
    top = Path(snapshot.receipt.envelope) / "receipt.json"
    value = json.loads(top.read_bytes())
    value["error"] = "tampered after completion"
    top.write_text(json.dumps(value))
    assert read_operation(config, submission.request_id).reason == "integrity_failure"
    with pytest.raises(OperationFailure, match="verified"):
        read_operation_tokens(config, submission.request_id)


def test_native_capture_race_cannot_complete(intent, monkeypatch):
    """Child dispatch passes admitted observations to the actual B1 capture, not a new baseline."""
    config, submission, _ = intent
    owner = importlib.import_module("tools.candidate_operations.submit")
    child = importlib.import_module("tools.candidate_operations.child")
    monkeypatch.setattr(owner, "spawn", lambda *a: None)
    submit_operation(config, submission, launch_environment={})
    Path(submission.request.llm_config_file).write_text("{}\n")
    assert child.execute(Path(config.state_root) / "operations" / str(submission.request_id)) == 1
    assert read_operation(config, submission.request_id).state == "unknown"
    assert list(Path(submission.request.runs_root).iterdir()) == []


def test_data_state_overlap_refuses_before_claim(intent, monkeypatch):
    """Resolved source data policy must include operation-state isolation."""
    config, submission, _ = intent
    config = config.model_copy(
        update={"state_root": str(Path(submission.request.project_root) / "data/state")}
    )
    with pytest.raises(OperationFailure, match="selected inputs"):
        submit_operation(config, submission, launch_environment={})
    assert list((Path(config.state_root) / "operations").iterdir()) == []


def test_json_cli_uses_same_variant(intent, monkeypatch, capsys):
    """The existing JSON CLI dispatches reusable preparation through the same admission owner."""
    config, submission, _ = intent
    cli = importlib.import_module("tools.candidate_operations.__main__")
    owner = importlib.import_module("tools.candidate_operations.submit")
    calls = []
    monkeypatch.setattr(owner, "spawn", lambda *args: calls.append(args))
    base = Path(submission.request.project_root)
    (base / "store.json").write_text(config.model_dump_json())
    (base / "operation.json").write_text(submission.model_dump_json())
    monkeypatch.setattr(
        "sys.argv",
        [
            "operations",
            "submit",
            "--store-config",
            str(base / "store.json"),
            "--request",
            str(base / "operation.json"),
        ],
    )
    assert cli.main() == 0 and len(calls) == 1
    assert json.loads(capsys.readouterr().out)["kind"] == "prepare_reusable"


def test_missing_top_after_exit_is_unknown_and_blocks_admission(intent, monkeypatch):
    """An inner receipt alone never releases a reusable preparation's operation slot."""
    from tools.candidate_operations.models import ProcessObservation

    config, submission, _ = intent
    owner = importlib.import_module("tools.candidate_operations.submit")
    child = importlib.import_module("tools.candidate_operations.child")
    reader = importlib.import_module("tools.candidate_operations.read")
    launch = importlib.import_module("tools.candidate_prepare.reusable_launch")
    monkeypatch.setattr(owner, "spawn", lambda *a: None)
    submit_operation(config, submission, launch_environment={})
    monkeypatch.setattr(
        launch,
        "supervise",
        lambda *a, **k: ExecutionResult(status="failed", returncode=1, elapsed_seconds=0),
    )
    path = Path(config.state_root) / "operations" / str(submission.request_id)
    assert child.execute(path) == 0
    (path / "completion.json").unlink()
    (Path(submission.request.runs_root) / str(submission.request.run_id) / "receipt.json").unlink()
    monkeypatch.setattr(
        reader, "observe", lambda _: ProcessObservation(status="exited", reason="test-exited")
    )
    assert read_operation(config, submission.request_id).state == "unknown"
    next_request = submission.model_copy(
        update={
            "request_id": uuid4(),
            "request": submission.request.model_copy(update={"run_id": uuid4()}),
        }
    )
    with pytest.raises(OperationFailure, match="unresolved"):
        submit_operation(config, next_request, launch_environment={})
