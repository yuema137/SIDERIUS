"""Namespace-local PIDs cannot prove exit or release capacity in another namespace."""

from pathlib import Path

import pytest

from tools.candidate_operations import process, read_operation
from tools.candidate_operations.files import publish
from tools.candidate_operations.host_liveness import session_evidence
from tools.candidate_operations.models import OperationFailure, ProcessIdentity
from tools.candidate_operations.read import releasable
from tools.candidate_operations.store import claim, locked_store, require_available


def test_capture_records_observers_pid_namespace(admitted):
    """Capture must persist the observer namespace, not just a numeric PID."""
    identity = process.current_identity(admitted[2])
    assert identity.pid_namespace_inode == Path("/proc/self/ns/pid").stat().st_ino


@pytest.mark.parametrize(
    "namespace", ["same", "different", "missing", "unreadable", "capture_unreadable"]
)
def test_namespace_gates_process_and_session_evidence(admitted, monkeypatch, namespace):
    """Release needs matching namespaces, except for the legacy same-namespace assumption."""
    config, submission, record = admitted
    if namespace == "capture_unreadable":
        original_stat = Path.stat

        def namespace_denied(path, *args, **kwargs):
            if path == Path("/proc/self/ns/pid"):
                raise PermissionError()
            return original_stat(path, *args, **kwargs)

        with monkeypatch.context() as capture:
            capture.setattr(Path, "stat", namespace_denied)
            identity = process.current_identity(record)
        assert identity.pid_namespace_inode == 0
    else:
        identity = process.current_identity(record)
    encoded = identity.model_dump()
    if namespace == "missing":
        del encoded["pid_namespace_inode"]
    elif namespace == "different":
        encoded["pid_namespace_inode"] = Path("/proc/self/ns/pid").stat().st_ino + 1
    identity = ProcessIdentity.model_validate(encoded)

    def absent(_):
        raise FileNotFoundError()

    def unreadable():
        raise PermissionError()

    monkeypatch.setattr(process, "_stat", absent)
    if namespace == "unreadable":
        monkeypatch.setattr(process, "_pid_namespace_inode", unreadable)
    scans = []
    monkeypatch.setattr(
        "tools.candidate_operations.host_liveness.session_members",
        lambda pid: scans.append(pid) or 0,
    )
    with locked_store(config) as root:
        path = claim(root, record)
    publish(path / "process.json", identity)
    permits_exit = namespace in {"same", "missing"}
    evidence = session_evidence(identity)
    assert evidence.ended == permits_exit
    assert evidence.unobservable == (not permits_exit)
    assert bool(scans) == permits_exit
    assert releasable(config, submission.request_id) == permits_exit
    assert read_operation(config, submission.request_id).state == (
        "operation_failed" if permits_exit else "unknown"
    )
    with locked_store(config) as root:
        if permits_exit:
            require_available(root, lambda op: releasable(config, op))
            assert not (root / "active.json").exists()
        else:
            with pytest.raises(OperationFailure) as refused:
                require_available(root, lambda op: releasable(config, op))
            assert refused.value.detail.code == "busy"
            assert (root / "active.json").exists()

    # A reboot ends the old process regardless of missing/mismatching namespace evidence.
    monkeypatch.setattr(process, "_boot_id", lambda: "another-boot")
    assert session_evidence(identity).ended
