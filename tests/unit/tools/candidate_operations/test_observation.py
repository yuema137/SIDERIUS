"""Deterministic observation policies, integrity and environment injection boundaries."""

import importlib
from pathlib import Path
from uuid import uuid4

import pytest

from tools.candidate_operations import read_operation, submit_operation
from tools.candidate_operations.child import execute
from tools.candidate_operations.files import publish
from tools.candidate_operations.models import Completion, OperationFailure, ProcessIdentity
from tools.candidate_operations.process import (
    current_identity,
    environment,
    observe,
    runtime_identity,
)
from tools.candidate_operations.read import releasable
from tools.candidate_operations.store import claim, locked_store


def test_process_identity_never_trusts_pid_alone(admitted, monkeypatch):
    record = admitted[2]
    identity = current_identity(record)
    module = importlib.import_module("tools.candidate_operations.process")
    assert observe(identity).status == "alive"
    assert (
        observe(identity.model_copy(update={"start_ticks": identity.start_ticks + 1})).status
        == "exited"
    )
    monkeypatch.setattr(module, "_stat", lambda _: ("Z", identity.start_ticks))
    assert observe(identity).reason == "zombie_or_dead"

    def denied(_):
        raise PermissionError()

    monkeypatch.setattr(module, "_stat", denied)
    assert observe(identity).status == "unknown"
    monkeypatch.setattr(module, "_boot_id", lambda: (_ for _ in ()).throw(FileNotFoundError()))
    assert observe(identity).status == "unknown"


def test_native_exception_is_unknown_and_keeps_slot(admitted, monkeypatch):
    """Even an exception after a mock dispatch may mean paid work already occurred."""
    config, submission, record = admitted
    record = record.model_copy(update={"runtime": runtime_identity()})
    with locked_store(config) as root:
        path = claim(root, record)
    calls = []

    def dispatched(_):
        calls.append(1)
        raise OSError("secret must not appear in completion")

    monkeypatch.setattr(
        importlib.import_module("tools.candidate_operations.child"), "prepare_candidate", dispatched
    )
    assert execute(path) == 1
    assert read_operation(config, submission.request_id).state == "unknown"
    assert not releasable(config, submission.request_id)
    assert submit_operation(config, submission, launch_environment={}).observation == "existing"
    assert calls == [1]
    assert "secret" not in (path / "completion.json").read_text()
    with pytest.raises(OperationFailure, match="unresolved"):
        submit_operation(
            config, submission.model_copy(update={"request_id": uuid4()}), launch_environment={}
        )


def test_wrapper_failure_requires_exit_and_integrity(admitted):
    config, submission, record = admitted
    with locked_store(config) as root:
        path = claim(root, record)
    assert execute(path) == 1  # deliberately wrong saved runtime
    assert read_operation(config, submission.request_id).state == "operation_failed"
    assert not releasable(config, submission.request_id)  # current process still alive
    marker = ProcessIdentity.model_validate_json((path / "process.json").read_bytes())
    publish(
        path / "process.json",
        marker.model_copy(update={"start_ticks": marker.start_ticks + 1}),
        replace=True,
    )
    assert releasable(config, submission.request_id)
    publish(
        path / "completion.json",
        Completion(
            operation_id=submission.request_id,
            request_digest="wrong",
            outcome="pre_dispatch_failure",
            reason="runtime_binding_failed",
        ),
        replace=True,
    )
    assert read_operation(config, submission.request_id).state == "unknown"
    assert not releasable(config, submission.request_id)


def test_outer_environment_excludes_ambient_and_rejects_reserved():
    assert set(environment((), {"OPENAI_API_KEY": "sentinel", "HOME": "ignored"})) == {
        "PATH",
        "LANG",
        "LC_ALL",
        "PYTHONNOUSERSITE",
        "PYTHONDONTWRITEBYTECODE",
    }
    assert (
        environment(("EXPLICIT_KEY",), {"EXPLICIT_KEY": "bound", "OTHER": "sentinel"})[
            "EXPLICIT_KEY"
        ]
        == "bound"
    )
    for name in ("PYTHONPATH", "PYTHONHOME", "LD_PRELOAD", "HOME"):
        with pytest.raises(ValueError, match="reserved"):
            environment((name,), {name: "sentinel"})
    with pytest.raises(OperationFailure, match="EXPLICIT_KEY"):
        environment(("EXPLICIT_KEY",), {})


def test_spawn_failure_and_pre_spawn_crash_are_distinct(admitted, monkeypatch):
    config, submission, _ = admitted
    module = importlib.import_module("tools.candidate_operations.submit")

    def failed(*args):
        raise OSError("exec failed")

    monkeypatch.setattr(module, "spawn", failed)
    assert (
        submit_operation(config, submission, launch_environment={}).observation
        == "operation_failed"
    )
    assert releasable(config, submission.request_id)
    next_submission = submission.model_copy(update={"request_id": uuid4()})

    def ambiguous(*args):
        raise RuntimeError("parent lost between claim and spawn")

    monkeypatch.setattr(module, "spawn", ambiguous)
    with pytest.raises(RuntimeError):
        submit_operation(config, next_submission, launch_environment={})
    assert read_operation(config, next_submission.request_id).state == "unknown"
    assert not releasable(config, next_submission.request_id)
    assert (
        submit_operation(config, next_submission, launch_environment={}).observation == "existing"
    )
