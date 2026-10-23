"""Operation token projection: active nonce/request and terminal integrity before ledger."""

import json
from pathlib import Path
from uuid import uuid4

import pytest

from tests.unit.tools.candidate_worker.conftest import prepared
from tests.unit.tools.candidate_worker.test_tokens import native_fixture, row
from tools.candidate_operations import (
    CandidateOperation,
    OperationStoreConfig,
    read_operation_tokens,
    submit_operation,
)
from tools.candidate_operations.files import publish
from tools.candidate_operations.models import Completion, OperationFailure
from tools.candidate_operations.store import load_record, operation_path
from tools.candidate_worker import read_candidate_tokens


@pytest.fixture
def candidate(prepared, tmp_path, monkeypatch):
    config = OperationStoreConfig(
        state_root=str(tmp_path / "state"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", lambda *args: None)
    submission = CandidateOperation(request_id=uuid4(), request=prepared)
    submit_operation(config, submission, launch_environment={})
    record = load_record(config, submission.request_id)
    query, initial, control, ledger = native_fixture(prepared, tmp_path)
    initial = initial.model_copy(update={"run_id": record.native_id.hex})
    (control / "launch.json").write_text(initial.model_dump_json())
    ledger.write_bytes(row(run_id=initial.run_id))
    query = query.model_copy(update={"expected_run_id": initial.run_id})
    return config, record, query, initial, control, ledger


def test_code_submitted_active_candidate_uses_same_native_projection(candidate):
    """Unknown process is not an integrity failure and must preserve otherwise valid usage."""
    config, record, query, _, _, _ = candidate
    direct = read_candidate_tokens(query)
    adapted = read_operation_tokens(config, record.submission.request_id)
    assert adapted.model_dump(exclude={"observed_at"}) == direct.model_dump(exclude={"observed_at"})
    assert adapted.run_id == record.native_id.hex and adapted.groups[0].response_rows == 1


@pytest.mark.parametrize(
    "change",
    [
        "active_nonce",
        "active_request",
        "completion_digest",
        "marker_identity",
        "predispatch_contradiction",
    ],
)
def test_integrity_refuses_before_ledger_access(candidate, monkeypatch, change):
    """Removing active nonce binding or completion-verdict reuse admits a foreign normal table."""
    config, record, _, initial, control, _ = candidate
    if change == "active_nonce":
        (control / "launch.json").write_text(
            initial.model_copy(update={"run_id": "foreign"}).model_dump_json()
        )
    elif change == "active_request":
        saved = json.loads((control / "request.json").read_text())
        saved["implementation_advice"] = "changed after admission"
        (control / "request.json").write_text(json.dumps(saved))
    else:
        if change != "marker_identity":
            (control / "receipt.json").write_text(
                initial.model_copy(update={"status": "rejected"}).model_dump_json()
            )
        publish(
            operation_path(config, record.submission.request_id) / "completion.json",
            Completion(
                operation_id=uuid4()
                if change == "marker_identity"
                else record.submission.request_id,
                request_digest=record.request_digest,
                outcome="pre_dispatch_failure"
                if change == "predispatch_contradiction"
                else "native",
                receipt_digest="wrong-digest",
                reason="fixture",
            ),
        )
    monkeypatch.setattr(
        "tools.candidate_worker.tokens.ledger_prefix",
        lambda *args: pytest.fail("ledger accessed before operation integrity"),
    )
    with pytest.raises(OperationFailure, match="verified"):
        read_operation_tokens(config, record.submission.request_id)


def test_pending_launch_can_recover_without_zero(candidate):
    config, record, _, initial, control, _ = candidate
    (control / "launch.json").unlink()
    pending = read_operation_tokens(config, record.submission.request_id)
    assert pending.availability == "unavailable" and not pending.groups
    (control / "launch.json").write_text(initial.model_dump_json())
    assert read_operation_tokens(config, record.submission.request_id).groups[0].response_rows == 1


def test_prepare_not_applicable_does_not_read_usage(admitted, monkeypatch):
    from tools.candidate_operations.store import claim, locked_store

    config, submission, record = admitted
    with locked_store(config) as root:
        claim(root, record)
    monkeypatch.setattr(
        "tools.candidate_worker.tokens.ledger_prefix",
        lambda *args: pytest.fail("prepare ledger access"),
    )
    result = read_operation_tokens(config, submission.request_id)
    assert (
        result.availability == "not_applicable"
        and result.reason == "preparation_not_applicable"
        and not result.groups
    )
