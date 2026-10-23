"""Operation provenance reachability, immutable dispatch and exact-ID recovery."""

import importlib
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from tests.unit.tools.candidate_prepare.test_reusable_preparation import direct_child, reusable
from tools.candidate_operations import (
    CandidateOperation,
    OperationStoreConfig,
    build_reusable_operation,
    submit_operation,
)
from tools.candidate_operations.models import OperationFailure
from tools.candidate_operations.store import load_record
from tools.candidate_prepare import prepare_reusable_candidate, select_reusable_preparation


@pytest.fixture
def prepared_operation(reusable, direct_child, tmp_path):
    request = reusable.model_copy(update={"candidate_environment_names": ("OPENAI_API_KEY",)})
    receipt = prepare_reusable_candidate(request)
    assert receipt.status == "prepared", receipt.error
    config = OperationStoreConfig(
        state_root=str(tmp_path / "state"),
        preparation_roots=(request.runs_root,),
        candidate_roots=(request.runs_root,),
    )
    selection = select_reusable_preparation(receipt.envelope)
    operation = build_reusable_operation(config, selection, uuid4())
    return config, operation, Path(receipt.envelope)


def test_builder_checks_root_before_reading(prepared_operation, monkeypatch, tmp_path):
    """A convenience review API must not turn configuration into an arbitrary path reader."""
    config, submission, _ = prepared_operation
    other = tmp_path / "other"
    other.mkdir()
    config = config.model_copy(update={"preparation_roots": (str(other),)})
    module = importlib.import_module("tools.candidate_operations.reusable")
    monkeypatch.setattr(
        module, "verify_reusable_preparation", lambda _: pytest.fail("read before root policy")
    )
    with pytest.raises(OperationFailure, match="outside configured"):
        build_reusable_operation(config, submission.reusable_preparation, uuid4())


@pytest.mark.parametrize("tamper", ["receipt", "manual_request"])
def test_admission_checks_provenance_before_claim_credentials_or_spawn(
    prepared_operation, monkeypatch, tamper
):
    """Removing the production admission call would reach the forbidden credential/spawn seam."""
    config, reviewed, envelope = prepared_operation
    if tamper == "receipt":
        (envelope / "receipt.json").write_text("{}")
        submission = reviewed
    else:
        # Manually constructed typed submissions must not bypass builder checks.
        submission = CandidateOperation(
            request_id=uuid4(),
            reusable_preparation=reviewed.reusable_preparation,
            request=reviewed.request.model_copy(update={"implementation_advice": "substituted"}),
        )
    module = importlib.import_module("tools.candidate_operations.submit")
    monkeypatch.setattr(
        module, "require_credentials", lambda *args: pytest.fail("credentials read")
    )
    monkeypatch.setattr(module, "spawn", lambda *args: pytest.fail("spawned"))
    with pytest.raises(OperationFailure) as caught:
        submit_operation(config, submission, launch_environment={})
    assert caught.value.detail.code == "reusable_preparation"
    assert not (Path(config.state_root) / "operations" / str(submission.request_id)).exists()
    assert not (envelope / "workspace").exists()


def test_child_rechecks_before_native_entry_and_reports_proven_failure(
    prepared_operation, monkeypatch
):
    """If dispatch bypasses verification the forbidden native launch fails this witness."""
    config, submission, envelope = prepared_operation
    module = importlib.import_module("tools.candidate_operations.submit")
    monkeypatch.setattr(module, "spawn", lambda *args: None)
    submit_operation(config, submission, launch_environment={"OPENAI_API_KEY": "offline"})
    (envelope / "binding.json").write_bytes(b"drift after admission")
    child = importlib.import_module("tools.candidate_operations.child")
    invoked = []
    monkeypatch.setattr(child, "launch_candidate", lambda *args, **kwargs: invoked.append(args))
    path = Path(config.state_root) / "operations" / str(submission.request_id)
    assert child.execute(path) == 1
    completion = json.loads((path / "completion.json").read_bytes())
    assert completion["outcome"] == "pre_dispatch_failure"
    assert completion["reason"] == "reusable_preparation_failed"
    assert invoked == [] and not (envelope / "workspace").exists()


@pytest.mark.parametrize("removed", ["receipt", "envelope"])
def test_exact_retry_survives_removed_capture_without_credentials(
    prepared_operation, monkeypatch, removed
):
    """Recovery must return durable identity before mutable-file checks or another launch."""
    config, submission, envelope = prepared_operation
    module = importlib.import_module("tools.candidate_operations.submit")
    spawned = []
    monkeypatch.setattr(module, "spawn", lambda *args: spawned.append(args))
    first = submit_operation(config, submission, launch_environment={"OPENAI_API_KEY": "offline"})
    record = load_record(config, submission.request_id)
    if removed == "receipt":
        (envelope / "receipt.json").unlink()
    else:
        shutil.rmtree(envelope)
    monkeypatch.setattr(
        module, "require_credentials", lambda *args: pytest.fail("credentials reread")
    )
    retry = submit_operation(config, submission, launch_environment={})
    assert retry.observation == "existing" and retry.request_digest == first.request_digest
    assert len(spawned) == 1
    assert load_record(config, submission.request_id) == record
    changed = submission.model_copy(
        update={
            "reusable_preparation": submission.reusable_preparation.model_copy(
                update={"expected_receipt_sha256": "0" * 64}
            )
        }
    )
    with pytest.raises(OperationFailure) as caught:
        submit_operation(config, changed, launch_environment={})
    assert caught.value.detail.code == "conflict"


def test_cli_extended_submission_uses_same_admission(
    prepared_operation, monkeypatch, capsys, tmp_path
):
    """The existing CLI discriminated parser carries retained identity into the normal store."""
    config, submission, _ = prepared_operation
    module = importlib.import_module("tools.candidate_operations.submit")
    monkeypatch.setattr(module, "spawn", lambda *args: None)
    config_path = tmp_path / "store.json"
    config_path.write_text(config.model_dump_json())
    request_path = tmp_path / "submission.json"
    request_path.write_text(submission.model_dump_json())
    monkeypatch.setenv("OPENAI_API_KEY", "offline")
    monkeypatch.setattr(
        "sys.argv",
        [
            "operations",
            "submit",
            "--store-config",
            str(config_path),
            "--request",
            str(request_path),
        ],
    )
    assert importlib.import_module("tools.candidate_operations.__main__").main() == 0
    assert json.loads(capsys.readouterr().out)["observation"] == "starting"
    assert load_record(config, submission.request_id).submission == submission
