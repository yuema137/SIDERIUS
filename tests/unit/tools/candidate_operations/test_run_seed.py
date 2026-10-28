"""Issue #983 S4: operation admission binds, hands off and reads back one run seed."""

import importlib
import json
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from core.seeding import RunSeedBinding
from tests.unit.tools.candidate_operations.test_reusable import prepared_operation
from tests.unit.tools.candidate_prepare.test_reusable_preparation import direct_child, reusable
from tests.unit.tools.candidate_worker.conftest import prepared
from tools.candidate_operations import (
    CandidateLoopResumeOperation,
    CandidateLoopResumeRequest,
    CandidateOperation,
    OperationStoreConfig,
    ReusablePrepareOperation,
    read_operation,
    submit_operation,
)
from tools.candidate_operations.models import OperationFailure, OperationRecord
from tools.candidate_operations.store import claim, digest, load_record, locked_store
from tools.candidate_prepare.reusable_models import ReusableCandidatePreparationRequest

__all__ = ["direct_child", "prepared", "prepared_operation", "reusable"]
ENV = {"OPENAI_API_KEY": "offline-test-key"}


def store(tmp_path: Path) -> OperationStoreConfig:
    return OperationStoreConfig(
        state_root=str(tmp_path / "state"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )


@pytest.mark.parametrize("explicit", [None, 1234])
def test_admission_records_the_seed_before_spawn_and_never_remints(
    prepared, tmp_path, monkeypatch, explicit
):
    """T5: fails if the seed is generated after claim/spawn, mislabelled, or re-minted on retry."""
    config = store(tmp_path)
    seen = []

    def spawn(path, env):
        # The durable record the child will read already carries the seed.
        seen.append(load_record(config, UUID(path.name)).run_seed)
        raise OSError("no child in this test")

    monkeypatch.setattr("tools.candidate_operations.submit.spawn", spawn)
    request = prepared.model_copy(update={"run_seed": explicit})
    submission = CandidateOperation(request_id=uuid4(), request=request)
    submit_operation(config, submission, launch_environment=ENV)
    record = load_record(config, submission.request_id)
    assert record.run_seed is not None and seen == [record.run_seed]
    if explicit is None:
        assert record.run_seed.source == "generated"
    else:
        assert (record.run_seed.value, record.run_seed.source) == (explicit, "operator")
    payload = (Path(config.state_root) / "operations" / str(submission.request_id)).joinpath(
        "request.json"
    )
    before = payload.read_bytes()
    retried = submit_operation(config, submission, launch_environment=ENV)
    assert retried.observation == "existing" and payload.read_bytes() == before
    assert read_operation(config, submission.request_id).run_seed == record.run_seed


def test_record_refuses_a_binding_that_contradicts_the_request(prepared, tmp_path):
    """Fails if a record could execute a seed other than the operator's explicit one."""
    from tools.candidate_operations.process import runtime_identity
    from tools.candidate_operations.store import now

    submission = CandidateOperation(
        request_id=uuid4(), request=prepared.model_copy(update={"run_seed": 5})
    )
    fields = {
        "native_id": uuid4(),
        "submission": submission,
        "request_digest": digest(submission),
        "config": store(tmp_path),
        "runtime": runtime_identity(),
        "inputs": submission.request.files,
        "admitted_at": now(),
    }
    for wrong in (
        RunSeedBinding(value=6, source="operator"),
        RunSeedBinding(value=5, source="generated"),
    ):
        with pytest.raises(ValueError, match="disagrees with the request"):
            OperationRecord(**fields, run_seed=wrong)


def test_child_without_an_admitted_seed_never_dispatches(admitted, monkeypatch):
    """Fails if the operation child, not admission, could mint a second seed."""
    from tools.candidate_operations.child import execute
    from tools.candidate_operations.process import runtime_identity

    config, _, record = admitted
    record = record.model_copy(update={"runtime": runtime_identity(), "run_seed": None})
    with locked_store(config) as root:
        path = claim(root, record)
    child = importlib.import_module("tools.candidate_operations.child")
    dispatched = Mock()
    monkeypatch.setattr(child, "prepare_candidate", dispatched)
    assert execute(path) == 1
    assert json.loads((path / "completion.json").read_bytes())["outcome"] == (
        "pre_dispatch_failure"
    )
    dispatched.assert_not_called()


def claim_record(config, submission, **fields):
    """Claim a hand-built record, as an earlier build would have admitted it."""
    from tools.candidate_operations.process import runtime_identity
    from tools.candidate_operations.store import now

    record = OperationRecord(
        native_id=uuid4(),
        submission=submission,
        request_digest=digest(submission),
        config=config,
        runtime=runtime_identity(),
        inputs=submission.request.files,
        admitted_at=now(),
        **fields,
    )
    with locked_store(config) as root:
        claim(root, record)
    return record


def test_s3b_era_loop_root_is_refused_at_review_and_resume(prepared, tmp_path, monkeypatch):
    """S4 obligation: a loop root admitted without a seed is never offered or admitted a Resume.

    Fails if Review (or Resume admission) proceeds to native reads, so a Resume
    could adopt the lock's seed or mint a second one.
    """
    from tests.unit.tools.candidate_worker.test_finite_loop import loop_request
    from tools.candidate_operations import review_loop_resume

    config = store(tmp_path)
    root = CandidateOperation(request_id=uuid4(), request=loop_request(prepared))
    record = claim_record(config, root)  # S3b-era shape: no run_seed on the record
    # Release the store's single active slot so Resume admission reaches its review.
    from tools.candidate_operations.files import publish
    from tools.candidate_operations.models import SpawnFailure

    publish(
        Path(config.state_root) / "operations" / str(root.request_id) / "spawn_failure.json",
        SpawnFailure(operation_id=root.request_id, request_digest=record.request_digest),
    )
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", Mock())
    resume = CandidateLoopResumeOperation(
        request_id=uuid4(),
        request=CandidateLoopResumeRequest(
            predecessor_operation_id=root.request_id, expected_receipt_digest="0" * 64
        ),
    )
    for attempt in (
        lambda: review_loop_resume(config, root.request_id),
        lambda: submit_operation(config, resume, launch_environment=ENV),
    ):
        with pytest.raises(OperationFailure, match="predates recorded run seeds") as refused:
            attempt()
        # The operator learns why and what to do.
        assert refused.value.detail.code == "loop_resume"
        message = str(refused.value)
        assert "no run_seed" in message and "Start a fresh candidate run" in message
    assert not (Path(config.state_root) / "operations" / str(resume.request_id)).exists()


def test_seedless_reusable_prepare_digest_is_unchanged():
    """T8: pinned on base 7093d23f; fails if the new field leaks into seedless digests."""
    request = ReusableCandidatePreparationRequest(
        source_path="/legacy/workflow.py",
        project_root="/legacy",
        expected_source_sha256="0" * 64,
        runs_root="/legacy/runs",
        run_id=UUID(int=3),
        run_name="legacy",
        llm_config_file="/legacy/llm.json",
        preparation_timeout_seconds=30.0,
        candidate_timeout_seconds=60.0,
        task_read_only=(),
        candidate_network=False,
        candidate_devices=(),
        candidate_environment_names=(),
    )
    assert (
        digest(ReusablePrepareOperation(request_id=UUID(int=1), request=request))
        == "719a5fb40a2337499d33b47fe54ac7f9989d78287e7523f5906485e9fe3c6cbb"
    )


def test_pre_seed_record_reads_back_without_a_seed(admitted):
    """T8: fails if a record written before S4 stops validating or gains a seed on readback."""
    config, submission, record = admitted
    record = record.model_copy(update={"run_seed": None})
    with locked_store(config) as root:
        path = claim(root, record)
    assert "run_seed" not in json.loads((path / "request.json").read_bytes())
    snapshot = read_operation(config, submission.request_id)
    assert snapshot.run_seed is None and "run_seed" not in snapshot.model_dump()


def test_reusable_candidate_keeps_its_own_seed_and_records_preparation_provenance(
    prepared_operation, monkeypatch
):
    """Fails if an explicit candidate seed is refused as drift, or the preparation seed is reused."""
    config, reviewed, _ = prepared_operation
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", lambda *args: None)
    submission = reviewed.model_copy(
        update={"request": reviewed.request.model_copy(update={"run_seed": 99})}
    )
    submit_operation(config, submission, launch_environment={"OPENAI_API_KEY": "offline"})
    record = load_record(config, submission.request_id)
    from tools.candidate_prepare import verify_reusable_preparation

    assert reviewed.reusable_preparation is not None
    preparation = verify_reusable_preparation(reviewed.reusable_preparation).receipt
    assert preparation.run_seed is not None and preparation.run_seed_source == "generated"
    assert record.run_seed == RunSeedBinding(value=99, source="operator")
    assert record.preparation_run_seed == preparation.run_seed


def test_cli_run_seed_sets_the_request_and_refuses_conflicts(prepared):
    """`submit --run-seed`: fails if a conflicting file seed or a non-seeded kind is accepted."""
    from tools.candidate_operations.__main__ import with_run_seed

    submission = CandidateOperation(request_id=uuid4(), request=prepared)
    assert with_run_seed(submission, 7).request.run_seed == 7
    assert with_run_seed(submission, None) == submission
    pinned = CandidateOperation(
        request_id=uuid4(), request=prepared.model_copy(update={"run_seed": 8})
    )
    assert with_run_seed(pinned, 8).request.run_seed == 8
    with pytest.raises(OperationFailure, match="disagrees"):
        with_run_seed(pinned, 7)
    resume = CandidateLoopResumeOperation(
        request_id=uuid4(),
        request=CandidateLoopResumeRequest(
            predecessor_operation_id=uuid4(), expected_receipt_digest="0" * 64
        ),
    )
    with pytest.raises(OperationFailure, match="does not apply"):
        with_run_seed(resume, 7)


def test_forged_preparation_receipt_seed_is_an_integrity_failure(admitted):
    """(a) Fails if a preparation receipt may claim a seed its operation never admitted."""
    from tests.unit.tools.candidate_operations.test_reader import native_fixture
    from tools.candidate_operations.read import native_receipt

    config, submission, _, _, control, receipt = native_fixture(admitted)
    assert native_receipt(load_record(config, submission.request_id)) is not None
    assert receipt.run_seed is not None
    (control / "receipt.json").write_text(
        receipt.model_copy(update={"run_seed": receipt.run_seed + 1}).model_dump_json()
    )
    with pytest.raises(OperationFailure, match="run seed disagrees") as refused:
        native_receipt(load_record(config, submission.request_id))
    assert refused.value.detail.code == "integrity"
    snapshot = read_operation(config, submission.request_id)
    assert (snapshot.state, snapshot.reason) == ("unknown", "integrity_failure")


def launched_candidate(prepared, config, *, launch_seed: int):
    """An admitted candidate (generated seed) and its hand-published launch receipt."""
    from tools.candidate_worker.launch import publish as native_publish
    from tools.candidate_worker.models import CandidateRunReceipt

    submission = CandidateOperation(request_id=uuid4(), request=prepared)
    record = claim_record(config, submission, run_seed=RunSeedBinding(value=5, source="generated"))
    workspace = Path(prepared.preview.document.definition.task.workspace)
    control = workspace / "candidate_run"
    control.mkdir(parents=True)
    initial = CandidateRunReceipt(
        run_id=record.native_id.hex,
        run_name=prepared.run_name,
        workspace=str(workspace),
        declaration_digest=prepared.declaration_digest,
        status="launched",
        node_ids=tuple(node.id for node in prepared.preview.document.definition.nodes),
        selected_constructor_routes=prepared.selected_constructor_routes,
        ledger_path=str(workspace / "token_usage.jsonl"),
        log_path=str(control / "worker.log"),
        run_seed=launch_seed,
        run_seed_source="generated",
    )
    native_publish(control / "request.json", prepared)
    native_publish(control / "launch.json", initial)
    return submission, control, initial


@pytest.mark.parametrize("forged", ["launch", "terminal"])
def test_forged_candidate_receipt_seed_is_an_integrity_failure(prepared, tmp_path, forged):
    """(a)/(c) Fails if a launch receipt may disagree with the record, or a terminal receipt
    with its launch receipt (`RECEIPT_IDENTITY_FIELDS` in `verify_candidate_records`)."""
    from tools.candidate_worker.launch import publish as native_publish

    config = store(tmp_path)
    submission, control, initial = launched_candidate(
        prepared, config, launch_seed=6 if forged == "launch" else 5
    )
    terminal = initial.model_copy(update={"status": "rejected", "validation_passed": False})
    if forged == "terminal":
        terminal = terminal.model_copy(update={"run_seed": 6})
    native_publish(control / "receipt.json", terminal)
    snapshot = read_operation(config, submission.request_id)
    assert (snapshot.state, snapshot.reason) == ("unknown", "integrity_failure")
    if forged == "terminal":
        honest = terminal.model_copy(update={"run_seed": 5})
        (control / "receipt.json").write_text(honest.model_dump_json(indent=2) + "\n")
        assert read_operation(config, submission.request_id).state == "completed"


def test_worker_reconcile_refuses_a_child_receipt_that_changes_the_seed(prepared, tmp_path):
    """(c) Fails if the sandboxed child may report a seed other than the launch receipt's."""
    from tools.candidate_worker.launch import reconcile
    from tools.candidate_worker.models import CandidateRunReceipt
    from tools.workspace_sandbox.runner import ExecutionResult

    initial = CandidateRunReceipt(
        run_id="a" * 32,
        run_name=prepared.run_name,
        workspace=str(tmp_path / "workspace"),
        declaration_digest=prepared.declaration_digest,
        status="launched",
        node_ids=(),
        selected_constructor_routes=(),
        ledger_path=str(tmp_path / "workspace/token_usage.jsonl"),
        log_path=str(tmp_path / "workspace/candidate_run/worker.log"),
        run_seed=5,
        run_seed_source="generated",
    )
    child = tmp_path / "child.json"
    child.write_text(
        initial.model_copy(update={"status": "accepted", "run_seed": 6}).model_dump_json()
    )
    result = ExecutionResult(status="completed", returncode=0, elapsed_seconds=0.0)
    terminal = reconcile(initial, result, child)
    assert (terminal.status, terminal.error) == ("failed", "child receipt changed run_seed")


def test_operation_listing_carries_the_admitted_seed(prepared, tmp_path, monkeypatch):
    """Fails if the operations listing (`OperationListEntry.snapshot`) drops the record's seed."""
    from tools.candidate_operations import list_operations

    config = store(tmp_path)
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", Mock(side_effect=OSError))
    submission = CandidateOperation(request_id=uuid4(), request=prepared)
    submit_operation(config, submission, launch_environment=ENV)
    record = load_record(config, submission.request_id)
    (entry,) = list_operations(config, 10).entries
    assert record.run_seed is not None and entry.snapshot.run_seed == record.run_seed
