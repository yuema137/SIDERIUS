"""New durable claims require fresh routes and bindings; old admissions remain observable."""

from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from tests.unit.tools.candidate_worker.conftest import prepared
from tools.candidate_operations import CandidateOperation, OperationStoreConfig, submit_operation
from tools.candidate_operations.models import OperationFailure


def config_for(tmp_path):
    return OperationStoreConfig(
        state_root=str(tmp_path / "state"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )


@pytest.mark.parametrize("case", ["omitted", "missing", "empty", "extra", "forged", "stale"])
def test_new_candidate_refusal_precedes_record_and_spawn(prepared, tmp_path, monkeypatch, case):
    """Bypassing fresh preview or credential policy creates a durable record and fails this test."""
    config = config_for(tmp_path)
    source = {"OPENAI_API_KEY": "offline-test-key"}
    if case == "omitted":
        prepared = prepared.model_copy(update={"environment_names": ()})
    elif case == "missing":
        source = {}
    elif case == "empty":
        source = {"OPENAI_API_KEY": ""}
    elif case == "extra":
        prepared = prepared.model_copy(
            update={"environment_names": ("OPENAI_API_KEY", "EXTRA_RUNTIME")}
        )
    elif case == "forged":
        prepared = prepared.model_copy(
            update={"selected_constructor_routes": (), "environment_names": ()}
        )
    else:
        (Path(prepared.preview.project_root) / "seed.json").write_text("{}")
    submission = CandidateOperation(request_id=uuid4(), request=prepared)
    spawn = Mock()
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", spawn)
    with pytest.raises(OperationFailure, match=r"environment|changed") as refused:
        submit_operation(config, submission, launch_environment=source)
    if case in {"forged", "stale"}:
        assert refused.value.detail.code == "candidate_preflight"
        assert refused.value.detail.message == "candidate inputs or routes changed; review again"
    assert not (Path(config.state_root) / "operations" / str(submission.request_id)).exists()
    assert not (Path(config.state_root) / "active.json").exists()
    assert not Path(prepared.preview.document.definition.task.workspace).exists()
    spawn.assert_not_called()


def test_valid_dispatch_filters_secrets_and_existing_retry_skips_preflight(
    prepared, tmp_path, monkeypatch
):
    """A valid binding dispatches once; later missing credentials/stale files do not replay it."""
    config = config_for(tmp_path)
    submission = CandidateOperation(request_id=uuid4(), request=prepared)
    spawn = Mock()
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", spawn)
    handle = submit_operation(
        config,
        submission,
        launch_environment={"OPENAI_API_KEY": "offline-test-key", "UNRELATED_SECRET": "unselected"},
    )
    assert handle.observation == "starting"
    assert spawn.call_args.args[1]["OPENAI_API_KEY"] == "offline-test-key"
    assert "UNRELATED_SECRET" not in spawn.call_args.args[1]
    (Path(prepared.preview.project_root) / "seed.json").unlink()
    workspace = Path(prepared.preview.document.definition.task.workspace)
    workspace.mkdir()
    (workspace / "old-output").touch()
    retry = submit_operation(config, submission, launch_environment={})
    assert retry.observation == "existing"
    assert retry.request_digest == handle.request_digest
    spawn.assert_called_once()


def test_historical_omitted_binding_record_remains_readable_and_retryable(
    prepared, tmp_path, monkeypatch
):
    """Admission policy must not become a validator that invalidates old missing-name records."""
    from tools.candidate_operations import read_operation
    from tools.candidate_operations.models import OperationRecord
    from tools.candidate_operations.process import runtime_identity
    from tools.candidate_operations.store import claim, digest, load_record, locked_store, now

    config = config_for(tmp_path)
    old_request = prepared.model_copy(update={"environment_names": ()})
    submission = CandidateOperation(request_id=uuid4(), request=old_request)
    record = OperationRecord(
        native_id=uuid4(),
        submission=submission,
        request_digest=digest(submission),
        config=config,
        runtime=runtime_identity(),
        inputs=old_request.files,
        admitted_at=now(),
    )
    with locked_store(config) as root:
        claim(root, record)
    (Path(prepared.preview.project_root) / "seed.json").unlink()
    assert load_record(config, submission.request_id).submission == submission
    assert read_operation(config, submission.request_id).state == "unknown"
    monkeypatch.setattr(
        "tools.candidate_operations.submit.fresh_preview",
        lambda *a: pytest.fail("historical freshness"),
    )
    monkeypatch.setattr(
        "tools.candidate_operations.submit.require_credentials",
        lambda *a: pytest.fail("historical credentials"),
    )
    assert submit_operation(config, submission, launch_environment={}).observation == "existing"
