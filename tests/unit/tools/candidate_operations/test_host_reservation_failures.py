"""Admission failures and pre-dispatch confirmation interleavings (#1394)."""

import json
import os
import signal
from pathlib import Path

import pytest

from tests.unit.tools.candidate_operations.test_operation_scheduler import (
    KEY,
    _gpu_operation,
    _ledger,
    _operation_dir,
    _reservations,
    _session_leader,
    _store,
    children,
    processes,
)
from tests.unit.tools.candidate_worker.conftest import prepared
from tools.candidate_operations import child as operation_child
from tools.candidate_operations import submit_operation
from tools.candidate_operations.files import publish
from tools.candidate_operations.host_ledger import locked_ledger, read_state, sweep


def test_confirmation_contention_has_a_distinct_durable_reason(
    prepared, tmp_path, children, monkeypatch
):
    """A real flock timeout must not look like a revoked entry or permit dispatch."""
    host, store = _ledger(tmp_path), _store(tmp_path, "store")
    operation = _gpu_operation(prepared, 1.0)
    submit_operation(store, operation, launch_environment=KEY, host=host)
    launched = []
    monkeypatch.setattr(operation_child, "launch_candidate", lambda *a, **k: launched.append(a))
    monkeypatch.setattr("tools.candidate_operations.host_ledger.LEDGER_LOCK_WAIT_SECONDS", 0.01)
    path = _operation_dir(store, operation)
    with locked_ledger(host.ledger_root):
        assert operation_child.execute(path) == 1
    completion = json.loads((path / "completion.json").read_text())
    assert (completion["outcome"], completion["reason"]) == (
        "pre_dispatch_failure",
        "host_reservation_busy",
    )
    assert not launched
    assert [entry.operation_id for entry in _reservations(host)] == [operation.request_id]


@pytest.mark.parametrize(
    "marker", ["host_reservation.json", "placement.json", "host_grant.json", "queued.json"]
)
@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt])
def test_publication_failure_releases_only_the_unspawned_entry(
    prepared, tmp_path, children, monkeypatch, marker, failure
):
    """Every admission marker can fail after the entry write; a live submitter must
    not hold that capacity or FIFO slot indefinitely. Earlier entries survive."""
    from tests.helpers.candidate_fanout import fanout_request
    from tools.candidate_worker.parallel_models import CapabilityResources, ParallelDispatch

    host, store = _ledger(tmp_path), _store(tmp_path, "store")
    first = _gpu_operation(prepared, 3.0)
    submit_operation(store, first, launch_environment=KEY, host=host)
    store = _store(tmp_path, "other")
    operation = _gpu_operation(prepared, 3.0 if marker == "queued.json" else 1.0)
    if marker == "host_grant.json":
        request = fanout_request(operation.request, 2)
        parallel = ParallelDispatch(
            capabilities={
                "implementation": CapabilityResources(gpu=False, host_memory_gib=1.0, cpu_slots=1)
            }
        )
        operation = operation.model_copy(
            update={"request": request.model_copy(update={"parallel": parallel})}
        )

    def failing_publish(path, value):
        if path.name == marker:
            raise failure("injected publication failure")
        publish(path, value)

    monkeypatch.setattr("tools.candidate_operations.host_admission.publish", failing_publish)
    with pytest.raises(failure):
        submit_operation(store, operation, launch_environment=KEY, host=host)
    with locked_ledger(host.ledger_root) as root:
        state = read_state(root)
    assert [entry.operation_id for entry in state.entries()] == [first.request_id]
    assert state.next_ordinal == 2  # claim and ordinal remain durable, never reused
    assert len(children.children) == 1
    assert (_operation_dir(store, operation) / "request.json").exists()


def test_killed_submitter_swept_before_child_identity_cannot_dispatch(
    prepared, tmp_path, monkeypatch
):
    """Popen returns, submitter dies before bind, sweep wins before process.json.
    The surviving child must refuse the now-released placement (#1108/#1394)."""
    host, store = _ledger(tmp_path), _store(tmp_path, "store")
    operation = _gpu_operation(prepared, 1.0)
    read_fd, write_fd = os.pipe()

    def spawn(path, env):
        child = _session_leader()
        os.write(write_fd, str(child.pid).encode())
        return child

    def killed_before_bind(*args):
        os.kill(os.getpid(), signal.SIGKILL)

    monkeypatch.setattr("tools.candidate_operations.submit.spawn", spawn)
    monkeypatch.setattr(
        "tools.candidate_operations.host_admission.LedgerSlot.spawned", killed_before_bind
    )
    submitter = os.fork()
    if submitter == 0:
        os.close(read_fd)
        try:
            submit_operation(store, operation, launch_environment=KEY, host=host)
        finally:
            os._exit(1)
    os.close(write_fd)
    child_pid = None
    try:
        _, status = os.waitpid(submitter, 0)
        payload = os.read(read_fd, 32)
        child_pid = int(payload) if payload else None
        assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
        assert child_pid is not None
        os.kill(child_pid, 0)  # the operation child survived its submitting process
        path = _operation_dir(store, operation)
        assert not (path / "process.json").exists()
        with locked_ledger(host.ledger_root) as root:
            (entry,) = read_state(root).reservations
            assert entry.process is None
            assert entry.submitter is not None and entry.submitter.pid == submitter
            assert sweep(root).entries() == ()
        launched = []
        monkeypatch.setattr(operation_child, "launch_candidate", lambda *a, **k: launched.append(a))
        assert operation_child.execute(path) == 1
        assert (path / "process.json").exists()
        completion = json.loads((path / "completion.json").read_text())
        assert completion["reason"] == "host_reservation_unconfirmed"
        assert completion["outcome"] == "pre_dispatch_failure"
        assert not launched
    finally:
        os.close(read_fd)
        if child_pid is not None:
            os.killpg(child_pid, signal.SIGKILL)
