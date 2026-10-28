"""Console recovery ordering, host policy and HTTP reachability for native chains."""

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from tests.unit.tools.candidate_console.test_http import client
from tests.unit.tools.candidate_operations.test_native_chain import chain
from tools.candidate_console import CandidateConsole
from tools.candidate_console.native_chain import NativeChainConsole, check_editor_separation
from tools.candidate_console.native_chain_models import (
    NativeChainChoice,
    NativeChainChoiceSelection,
    NativeChainLaunchSelection,
)
from tools.candidate_operations import operation_request_digest
from tools.candidate_operations.models import OperationFailure
from tools.workflow_authoring.models import Project
from tools.workflow_preview.models import FileObservation


def native_config(config, record, *, choices=True):
    return config.model_copy(
        update={
            "operation_store": record.config,
            "tasks": (),
            "native_chain_choices": (
                NativeChainChoice(
                    choice_id="chain",
                    label="Native run",
                    request=record.submission.request,
                ),
            )
            if choices
            else (),
        }
    )


def forbidden(*args, **kwargs):
    pytest.fail("mutable fresh-input reader or dispatch reached during recovery")


def test_recovery_after_removed_choice_inputs_and_credentials(chain, console_config, monkeypatch):
    """A real durable record must recover before any mutable choice/capture/secret reader."""
    record, _ = chain
    secret = Path(console_config.auth_token_file).with_name("credentials")
    secret.write_text('{"OPENAI_API_KEY":"private-value"}')
    secret.chmod(0o600)
    config = native_config(console_config, record, choices=False).model_copy(
        update={"credential_file": str(secret)}
    )
    service = NativeChainConsole(CandidateConsole(config))
    api = client(config)
    secret.unlink()
    Path(record.submission.request.capture_path).unlink()
    for target in (
        "tools.candidate_console.native_chain.NativeChainConsole._choice",
        "tools.candidate_console.native_chain.review_native_chain_operation",
        "tools.candidate_console.native_chain.credentials",
        "tools.candidate_operations.submit.review_native_chain_operation",
        "tools.candidate_operations.submit.spawn",
    ):
        monkeypatch.setattr(target, forbidden)
    selection = NativeChainLaunchSelection(
        choice_id="removed-or-renamed",
        operation_id=record.submission.request_id,
        expected_request_digest=record.request_digest,
    )
    assert service.launch(selection).observation == "existing"
    response = api.post("/api/native-chain/launch", json=selection.model_dump(mode="json"))
    assert response.status_code == 202 and response.json()["observation"] == "existing"
    conflict = selection.model_copy(update={"expected_request_digest": "0" * 64})
    assert (
        api.post("/api/native-chain/launch", json=conflict.model_dump(mode="json")).status_code
        == 409
    )
    # A monitor-only restart deliberately omits the now unavailable credential file.
    monitor = client(config.model_copy(update={"credential_file": None}))
    assert monitor.get("/api/choices").json() == []
    assert monitor.get("/api/native-chain/choices").json() == []
    status = monitor.get(f"/api/operations/{selection.operation_id}").json()
    assert status["kind"] == "native_chain" and status["receipt_available"] is False
    assert status["native_status"] is None and status["native_id"] is None
    assert status["native_chain"]["evidence"]["availability"] == "unavailable"
    tokens = monitor.get(f"/api/operations/{selection.operation_id}/tokens")
    assert tokens.status_code == 200
    assert tokens.json()["availability"] == "unavailable"
    assert tokens.json()["groups"] == []
    assert tokens.json()["scope"] == "chain_cumulative"


def test_fresh_review_and_launch_share_digest_then_dispatch_once(
    chain, console_config, monkeypatch
):
    """Removing the HTTP→service→owner hop or UUID recovery causes these assertions to fail."""
    record, _ = chain
    config = native_config(console_config, record)
    config = config.model_copy(
        update={
            "operation_store": record.config.model_copy(
                update={"state_root": str(Path(record.config.state_root).with_name("fresh-state"))}
            )
        }
    )
    choice = config.native_chain_choices[0]
    choice = choice.model_copy(
        update={"request": choice.request.model_copy(update={"environment_names": ()})}
    )
    config = config.model_copy(update={"native_chain_choices": (choice,)})
    reviewed = []

    def review(store, submission, **kwargs):
        reviewed.append(submission)
        return record.native_chain_admission.model_copy(
            update={
                "request_digest": operation_request_digest(submission),
                "required_environment_names": (),
            }
        )

    monkeypatch.setattr(
        "tools.candidate_console.native_chain.review_native_chain_operation", review
    )
    monkeypatch.setattr("tools.candidate_operations.submit.review_native_chain_operation", review)
    spawned = []
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", lambda *a: spawned.append(a))
    api = client(config)
    assert api.get("/api/native-chain/choices").json() == [
        {"choice_id": "chain", "label": "Native run"}
    ]
    assert not reviewed
    result = api.post("/api/native-chain/review", json={"choice_id": "chain"}).json()
    assert result["credential_readiness"]["ready"] is True
    payload = dict(
        choice_id="chain",
        operation_id=str(uuid4()),
        expected_request_digest=result["request_digest"],
    )
    assert api.post("/api/native-chain/launch", json=payload).json()["observation"] == "starting"
    assert api.post("/api/native-chain/launch", json=payload).json()["observation"] == "existing"
    assert len(spawned) == 1
    assert all(s.request == choice.request for s in reviewed)
    stale = {**payload, "operation_id": str(uuid4()), "expected_request_digest": "0" * 64}
    count = len(reviewed)
    assert api.post("/api/native-chain/launch", json=stale).status_code == 409
    assert len(reviewed) == count


def test_corrupt_existing_record_never_becomes_fresh(chain, console_config, monkeypatch):
    record, path = chain
    service = NativeChainConsole(CandidateConsole(native_config(console_config, record)))
    (path / "request.json").write_text("corrupt")
    monkeypatch.setattr(service, "_choice", forbidden)
    with pytest.raises(ValidationError):
        service.launch(
            NativeChainLaunchSelection(
                choice_id="chain",
                operation_id=record.submission.request_id,
                expected_request_digest=record.request_digest,
            )
        )


@pytest.mark.parametrize(
    "target", ["source", "lock", "versions", "recovery", "output", "unrelated"]
)
def test_editor_separation_matches_actual_write_authority(chain, console_config, target):
    """Blanket project-root blocking rejects unrelated; missing lock/recovery checks admit collisions."""
    record, _ = chain
    console = CandidateConsole(native_config(console_config, record))
    root = Path(record.config.state_root).parent
    source = root / "editable.json"
    recovery = root / "recovery"
    project = Project(
        project_id="editor", project_root=root, source_file=source, recovery_directory=recovery
    )
    # Policy receives already validated configured projects; no authoring I/O needed here.
    console.config = console.config.model_copy(update={"editor_projects": (project,)})
    paths = {
        "source": source,
        "lock": root / ".editable.json.authoring.lock",
        "versions": root / "editable.json.versions.json",
        "recovery": recovery / "saved.json",
        "unrelated": root / "other.json",
        "output": root / "other.json",
    }
    admission = record.native_chain_admission.model_copy(
        update={
            "input_files": (
                FileObservation(
                    reference="pin", path=str(paths[target]), sha256="a" * 64, size_bytes=1
                ),
            )
        }
    )
    choice = console.config.native_chain_choices[0]
    if target == "output":
        choice = choice.model_copy(
            update={
                "request": choice.request.model_copy(update={"envelope": str(recovery / "run")})
            }
        )
    if target == "unrelated":
        check_editor_separation(console, choice, admission)
    else:
        with pytest.raises(OperationFailure, match="overlaps"):
            check_editor_separation(console, choice, admission)


def test_new_routes_keep_request_boundary_and_safe_errors(chain, console_config, monkeypatch):
    record, _ = chain
    api = client(native_config(console_config, record))
    monkeypatch.setattr(
        "tools.candidate_console.native_chain.review_native_chain_operation", forbidden
    )
    for suffix in ("review", "launch"):
        url = "/api/native-chain/" + suffix
        for headers, expected in (
            ({"Authorization": ""}, 401),
            ({"Host": "evil.invalid"}, 403),
            ({"Origin": "null"}, 403),
            ({"Content-Type": "text/plain"}, 415),
        ):
            assert api.post(url, content="DO-NOT-ECHO", headers=headers).status_code == expected
        response = api.post(url, json={"secret": "DO-NOT-ECHO"})
        assert response.status_code == 422 and "DO-NOT-ECHO" not in response.text
        assert response.headers["cache-control"] == "no-store"
        assert (
            api.post(
                url, content="x" * (256 * 1024 + 1), headers={"Content-Type": "application/json"}
            ).status_code
            == 413
        )
    assert api.get("/api/native-chain/choices", headers={"Authorization": ""}).status_code == 401


def test_missing_credentials_are_name_only_review_blocker(chain, console_config, monkeypatch):
    record, _ = chain
    service = NativeChainConsole(CandidateConsole(native_config(console_config, record)))
    monkeypatch.setattr(
        "tools.candidate_console.native_chain.review_native_chain_operation",
        lambda *a: record.native_chain_admission,
    )
    view = service.review(NativeChainChoiceSelection(choice_id="chain"))
    assert view.credential_readiness.missing_names == ("OPENAI_API_KEY",)
    assert not view.credential_readiness.ready
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", forbidden)
    with pytest.raises(OperationFailure, match="missing credentials"):
        service.launch(
            NativeChainLaunchSelection(
                choice_id="chain",
                operation_id=uuid4(),
                expected_request_digest=record.request_digest,
            )
        )


def test_new_review_and_launch_reach_editor_guard(chain, console_config, monkeypatch):
    """Bypassing the editor-write check at either public service entry makes this red."""
    record, _ = chain
    console = CandidateConsole(native_config(console_config, record))
    source = Path(record.submission.request.capture_path)
    project = Project(
        project_id="overlap",
        project_root=source.parent,
        source_file=source,
        recovery_directory=source.parent / "recovery",
    )
    console.config = console.config.model_copy(update={"editor_projects": (project,)})
    service = NativeChainConsole(console)
    monkeypatch.setattr(
        "tools.candidate_console.native_chain.review_native_chain_operation",
        lambda *a: record.native_chain_admission,
    )
    monkeypatch.setattr("tools.candidate_console.native_chain.credentials", forbidden)
    monkeypatch.setattr(
        "tools.candidate_console.native_chain.named_credential_readiness", forbidden
    )
    monkeypatch.setattr("tools.candidate_console.service.submit_operation", forbidden)
    with pytest.raises(OperationFailure, match="overlaps"):
        service.review(NativeChainChoiceSelection(choice_id="chain"))
    with pytest.raises(OperationFailure, match="overlaps"):
        service.launch(
            NativeChainLaunchSelection(
                choice_id="chain",
                operation_id=uuid4(),
                expected_request_digest=record.request_digest,
            )
        )


def test_existing_other_kind_refuses_even_matching_owner_digest(chain, console_config, monkeypatch):
    """Digest equality alone must never turn a saved candidate preparation into a chain."""
    from tools.candidate_console.models import PrepareSelection
    from tools.candidate_console.service import preparation_request
    from tools.candidate_operations import PrepareOperation

    record, _ = chain
    operation = PrepareOperation(
        request_id=uuid4(),
        request=preparation_request(
            console_config.tasks[0],
            PrepareSelection(operation_id=uuid4(), task_id="synthetic", run_name="other"),
        ),
    )
    monkeypatch.setattr(
        "tools.candidate_console.native_chain.lookup_operation_request", lambda *a: operation
    )
    monkeypatch.setattr("tools.candidate_console.service.submit_operation", forbidden)
    service = NativeChainConsole(CandidateConsole(native_config(console_config, record)))
    with pytest.raises(OperationFailure, match="identity differs"):
        service.launch(
            NativeChainLaunchSelection(
                choice_id="chain",
                operation_id=operation.request_id,
                expected_request_digest=operation_request_digest(operation),
            )
        )
