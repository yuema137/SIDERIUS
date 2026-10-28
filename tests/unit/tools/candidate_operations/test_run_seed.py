"""Issue #983 S4: operation admission binds, hands off and reads back one run seed."""

import argparse
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
from tools.candidate_operations.seed_admission import require_root_seed
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


def test_s3b_era_loop_root_is_refused_not_adopted(admitted):
    """S4 obligation: a root record without a seed cannot be continued (no second seed)."""
    _, _, record = admitted
    with pytest.raises(OperationFailure, match="predates recorded run seeds") as refused:
        require_root_seed(record.model_copy(update={"run_seed": None}))
    # The operator learns why and what to do.
    assert refused.value.detail.code == "loop_resume"
    assert "no run_seed" in str(refused.value) and "Start a fresh candidate run" in str(
        refused.value
    )


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
    from core.run_seed_lock import run_seed_argument

    with pytest.raises(argparse.ArgumentTypeError):
        run_seed_argument(str(2**53))
