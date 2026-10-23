"""Confined logs and native receipt integrity without reproducing native lifecycle."""

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from tools.candidate_operations import LogReadRequest, read_operation, read_operation_log
from tools.candidate_operations.files import publish
from tools.candidate_operations.models import Completion
from tools.candidate_operations.process import current_identity
from tools.candidate_operations.read import releasable
from tools.candidate_operations.store import claim, locked_store
from tools.candidate_operations.submit import capture_inputs
from tools.candidate_prepare.launch import publish as publish_native
from tools.candidate_prepare.models import CandidatePreparationReceipt, PreparationControl


def native_fixture(admitted):
    config, submission, record = admitted
    record = record.model_copy(update={"inputs": capture_inputs(submission)})
    with locked_store(config) as root:
        path = claim(root, record)
    control = Path(submission.request.output_dir) / "preparation"
    control.mkdir(parents=True)
    saved = PreparationControl(
        preparation_id=record.native_id, request=submission.request, sources=record.inputs
    )
    publish_native(control / "request.json", saved)
    receipt = CandidatePreparationReceipt(
        preparation_id=saved.preparation_id,
        status="prepared",
        output_dir=submission.request.output_dir,
        request_path=str(control / "request.json"),
        log_path=str(control / "worker.log"),
        source_observations=saved.sources,
    )
    publish_native(control / "receipt.json", receipt)
    return config, submission, record, path, control, receipt


def test_native_receipt_precedence_and_digest_tampering(admitted):
    config, submission, record, path, control, receipt = native_fixture(admitted)
    publish(path / "process.json", current_identity(record))
    snapshot = read_operation(config, submission.request_id)
    assert snapshot.receipt.status == "prepared" and snapshot.finishing
    assert not releasable(config, submission.request_id)
    payload = (control / "receipt.json").read_bytes()
    publish(
        path / "completion.json",
        Completion(
            operation_id=submission.request_id,
            request_digest=record.request_digest,
            outcome="native",
            receipt_digest=hashlib.sha256(payload).hexdigest(),
            reason="native_terminal",
        ),
    )
    (control / "receipt.json").write_bytes(payload + b" ")
    assert read_operation(config, submission.request_id).state == "unknown"
    (control / "receipt.json").unlink()
    (control / "child.json").write_text(receipt.model_dump_json())
    assert read_operation(config, submission.request_id).state == "unknown"
    (control / "receipt.json").write_text(
        receipt.model_copy(update={"preparation_id": uuid4()}).model_dump_json()
    )
    assert read_operation(config, submission.request_id).state == "unknown"


def test_byte_offsets_truncation_missing_and_symlink_escape(admitted, tmp_path):
    config, submission, _, _, control, _ = native_fixture(admitted)
    query = LogReadRequest(operation_id=submission.request_id, kind="native", max_bytes=2)
    assert read_operation_log(config, query).missing
    log = control / "worker.log"
    log.write_bytes(b"a\xe2\x82\xac\xffz")
    chunk = read_operation_log(config, query)
    assert chunk.text == "a\ufffd" and chunk.next_offset == 2
    chunk = read_operation_log(config, query.model_copy(update={"offset": 2, "max_bytes": 4}))
    assert chunk.next_offset == 6 and chunk.text == "\ufffd\ufffd\ufffdz"
    log.write_bytes(b"new")
    chunk = read_operation_log(config, query.model_copy(update={"offset": 6}))
    assert chunk.truncated and chunk.offset == 0 and chunk.next_offset == 2
    log.unlink()
    log.symlink_to(tmp_path / "secret")
    with pytest.raises(OSError):
        read_operation_log(config, query)
    log.unlink()
    control.rename(control.parent / "moved")
    control.symlink_to(control.parent / "moved", target_is_directory=True)
    with pytest.raises(OSError):
        read_operation_log(config, query)


def test_missing_native_nonce_fails_closed(admitted):
    """Old operation records cannot synthesize a fresh native ownership token at read time."""
    import json

    config, submission, _, path, _, _ = native_fixture(admitted)
    record = json.loads((path / "request.json").read_text())
    del record["native_id"]
    (path / "request.json").write_text(json.dumps(record))
    with pytest.raises(ValueError):
        read_operation(config, submission.request_id)
