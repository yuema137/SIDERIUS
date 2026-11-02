"""Cross-operation host ledger (B3-5a): separate stores share one declared budget.

Operation children and sandboxes are replaced by real session-leader processes
(``start_new_session``, i.e. setsid) in the production layout: the sandbox is a
separate session from the operation child. bwrap itself is not run here.
"""

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from core.runtime_control.pair_admission import ResolvedGpuCeiling
from core.runtime_control.scheduling import GpuHardwareClass, GpuSlot, HostBudget
from tests.unit.tools.candidate_worker.conftest import prepared
from tools.candidate_operations import CandidateOperation, OperationStoreConfig, submit_operation
from tools.candidate_operations.child import sandbox_observer
from tools.candidate_operations.files import publish
from tools.candidate_operations.host_ledger import (
    HostScheduling,
    locked_ledger,
    read_state,
    release_reservation,
    sweep,
)
from tools.candidate_operations.models import OperationFailure, OperationResources
from tools.candidate_operations.process import identity_of, session_members
from tools.candidate_operations.store import load_record

SLOT = "GPU-aaaa"
KEY = {"OPENAI_API_KEY": "offline-test-key"}
GPU_NAMES = ("CUDA_VISIBLE_DEVICES",)


def _budget(*, acknowledge: bool = False, memory: float = 64.0) -> HostBudget:
    hardware = GpuHardwareClass(
        device_name="NVIDIA H100", total_memory_bytes=80 * 1024**3, compute_capability=(9, 0)
    )
    ceiling = ResolvedGpuCeiling(
        operator_ceiling_gib=4.0,
        operator_source="caller",
        host_quota_gib=None,
        measured_capacity_gib=80.0,
    )
    return HostBudget(
        gpus=(GpuSlot(uuid=SLOT, hardware_class=hardware, ceiling=ceiling),),
        host_memory_gib=memory,
        cpu_slots=16,
        max_concurrent_units=4,
        max_queued_operations=2,
        source="file",
        acknowledge_shared_gpu_time_budget=acknowledge,
    )


def _ledger(tmp_path: Path, name: str = "ledger", **budget) -> HostScheduling:
    root = tmp_path / name
    root.mkdir(mode=0o700)
    return HostScheduling(ledger_root=str(root), budget=_budget(**budget))


def _store(tmp_path: Path, name: str) -> OperationStoreConfig:
    return OperationStoreConfig(
        state_root=str(tmp_path / name),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )


def _gpu_operation(prepared, vram: float, *, time_budgeted: bool = False, names=None):
    names = (*prepared.environment_names, *GPU_NAMES) if names is None else names
    return CandidateOperation(
        request_id=uuid4(),
        request=prepared.model_copy(update={"environment_names": names}),
        resources=OperationResources(
            gpu_count=1,
            vram_gib=vram,
            vram_source="configured_cap",
            host_memory_gib=4.0,
            cpu_slots=1,
            time_budgeted=time_budgeted,
        ),
    )


def _session_leader() -> subprocess.Popen:
    return subprocess.Popen(["sleep", "60"], start_new_session=True)


def _end(process: subprocess.Popen) -> None:
    os.killpg(process.pid, signal.SIGKILL)
    process.wait()
    deadline = time.monotonic() + 10
    while session_members(process.pid) != 0:
        assert time.monotonic() < deadline, "test session did not end"
        time.sleep(0.05)


class _Children:
    """Fake operation spawns: each a real session leader; records child envs."""

    def __init__(self):
        self.envs: list[dict[str, str]] = []
        self.children: list[subprocess.Popen] = []

    def __call__(self, path, env):
        self.envs.append(env)
        child = _session_leader()
        self.children.append(child)
        return child


@pytest.fixture
def processes():
    started: list[subprocess.Popen] = []
    yield started
    for process in started:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


@pytest.fixture
def children(monkeypatch, processes):
    fake = _Children()
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", fake)
    yield fake
    processes.extend(fake.children)


def _code(call) -> str:
    with pytest.raises(OperationFailure) as failure:
        call()
    return failure.value.detail.code


def _claims(config: OperationStoreConfig) -> list[str]:
    operations = Path(config.state_root) / "operations"
    return sorted(os.listdir(operations)) if operations.exists() else []


def _operation_dir(config: OperationStoreConfig, operation: CandidateOperation) -> Path:
    return Path(config.state_root) / "operations" / str(operation.request_id)


def _reservations(host: HostScheduling):
    with locked_ledger(host.ledger_root) as root:
        return read_state(root).reservations


def _held(host: HostScheduling, operation: CandidateOperation) -> bool:
    """Whether the sweep a submission would run keeps this operation's reservation."""
    with locked_ledger(host.ledger_root) as root:
        return any(r.operation_id == operation.request_id for r in sweep(root).reservations)


def test_two_stores_share_one_budget_and_the_child_gets_its_placement(prepared, tmp_path, children):
    """A per-store ledger would place both 3 GiB operations on one 4 GiB slot.

    The second is queued, not placed (B3-5b); the first child sees only its slot,
    replacing whatever device selector the launcher inherited.
    """
    host = _ledger(tmp_path)
    first_store, second_store = _store(tmp_path, "store-a"), _store(tmp_path, "store-b")
    first = _gpu_operation(prepared, 3.0)
    launch = {**KEY, "CUDA_VISIBLE_DEVICES": "0,1"}
    handle = submit_operation(first_store, first, launch_environment=launch, host=host)
    assert handle.observation == "starting"
    assert children.envs[0]["CUDA_VISIBLE_DEVICES"] == SLOT
    placement = json.loads((_operation_dir(first_store, first) / "placement.json").read_text())
    assert (placement["decision"], placement["gpu_uuid"]) == ("placed", SLOT)
    (reservation,) = _reservations(host)
    assert reservation.process is not None
    assert reservation.process.pid == children.children[0].pid

    second = _gpu_operation(prepared, 3.0)
    handle = submit_operation(second_store, second, launch_environment=KEY, host=host)
    assert handle.observation == "queued"
    assert _claims(second_store) == [str(second.request_id)]
    assert "CUDA_VISIBLE_DEVICES" not in children.envs[1]  # no device until placed
    assert not (_operation_dir(second_store, second) / "placement.json").exists()
    assert len(_reservations(host)) == 1


def test_reservation_is_kept_while_the_sandbox_session_outlives_the_child(
    prepared, tmp_path, children, processes
):
    """The sandbox (and training) runs in its own session, invisible to the child's.

    A release on the operation child's session alone would free the GPU while
    training still holds it.
    """
    host = _ledger(tmp_path)
    store = _store(tmp_path, "store-a")
    first = _gpu_operation(prepared, 3.0)
    submit_operation(store, first, launch_environment=KEY, host=host)
    sandbox = _session_leader()
    processes.append(sandbox)
    # The child's production observer publishes the sandbox identity.
    publish_sandbox = sandbox_observer(
        load_record(store, first.request_id), _operation_dir(store, first)
    )["on_sandbox_spawn"]
    publish_sandbox(sandbox.pid)
    _end(children.children[0])

    assert _held(host, first)
    assert _code(lambda: release_reservation(host.ledger_root, first.request_id)) == "session_live"

    _end(sandbox)
    assert not _held(host, first)


def test_a_hidden_sandbox_leader_is_never_a_positive_exit(
    prepared, tmp_path, children, processes, monkeypatch
):
    """Setuid-root bwrap under /proc hidepid reads as absent while it may still run."""
    monkeypatch.setattr(
        "tools.candidate_operations.host_liveness.sandbox_may_be_hidden", lambda: True
    )
    host = _ledger(tmp_path)
    store = _store(tmp_path, "store-a")
    first = _gpu_operation(prepared, 3.0)
    submit_operation(store, first, launch_environment=KEY, host=host)
    sandbox = _session_leader()
    processes.append(sandbox)
    sandbox_observer(load_record(store, first.request_id), _operation_dir(store, first))[
        "on_sandbox_spawn"
    ](sandbox.pid)
    _end(children.children[0])
    _end(sandbox)  # now absent from /proc: indistinguishable from hidden

    assert _held(host, first)
    released = release_reservation(host.ledger_root, first.request_id)  # operator's word
    assert released.evidence.sandbox is not None
    assert released.evidence.sandbox.leader == "unknown"


def test_serial_child_publishes_no_sandbox_identity(admitted, tmp_path):
    """Without a placement the child launches exactly as before (no observer)."""
    _, _, record = admitted
    assert sandbox_observer(record, tmp_path) == {}


def test_runner_reports_the_live_sandbox_before_waiting(tmp_path, monkeypatch):
    """The observer must see the sandbox while it runs, not after it is reaped."""
    from tools.workspace_sandbox import runner
    from tools.workspace_sandbox.profile import SandboxProfile

    monkeypatch.setattr(runner, "build_command", lambda profile, argv: (["sleep", "0.3"], {}))
    seen = []

    def observe(pid):
        seen.append(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[3])

    profile = SandboxProfile(workspace=tmp_path, network=False, timeout_seconds=5.0)
    for execute in (runner.run, runner.run_observed):
        execute(profile, ["unused"], on_spawn=observe)
    assert len(seen) == 2


def _crash(*args):
    raise RuntimeError("submitter crashed between spawn and bind")


def test_crash_between_spawn_and_bind_recovers_only_on_published_evidence(
    prepared, tmp_path, children, monkeypatch
):
    """An unbound reservation is never dropped blindly, and never blocks forever."""
    monkeypatch.setattr("tools.candidate_operations.host_admission.bind", _crash)
    host = _ledger(tmp_path)
    store = _store(tmp_path, "store-a")
    first = _gpu_operation(prepared, 3.0)
    with pytest.raises(RuntimeError):
        submit_operation(store, first, launch_environment=KEY, host=host)
    monkeypatch.undo()
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", children)
    (reservation,) = _reservations(host)
    assert reservation.process is None
    child = children.children[0]
    record = load_record(store, first.request_id)
    path = _operation_dir(store, first)

    forged = identity_of(record, child.pid).model_copy(update={"request_digest": "0" * 64})
    publish(path / "process.json", forged)
    assert _held(host, first)  # mismatched evidence keeps it, without raising
    os.unlink(path / "process.json")
    publish(path / "process.json", identity_of(record, child.pid))  # the child's own record
    assert _held(host, first)  # still alive
    _end(child)
    assert not _held(host, first)


def test_unpublished_crash_needs_the_operator_release(prepared, tmp_path, children, monkeypatch):
    """With no identity anywhere the sweep keeps it; the operator may release it."""
    monkeypatch.setattr("tools.candidate_operations.host_admission.bind", _crash)
    host = _ledger(tmp_path)
    first = _gpu_operation(prepared, 3.0)
    with pytest.raises(RuntimeError):
        submit_operation(_store(tmp_path, "store-a"), first, launch_environment=KEY, host=host)
    _end(children.children[0])
    with locked_ledger(host.ledger_root) as root:
        assert len(sweep(root).reservations) == 1
    released = release_reservation(host.ledger_root, first.request_id)
    assert released.evidence.child is None
    assert _reservations(host) == ()


def test_mixed_host_refusals_leave_no_claim(prepared, tmp_path, children):
    """Every launch that would bypass or misstate the live ledger refuses before claim."""
    host = _ledger(tmp_path)
    submit_operation(
        _store(tmp_path, "store-a"),
        _gpu_operation(prepared, 1.0),
        launch_environment=KEY,
        host=host,
    )
    other = _store(tmp_path, "store-b")
    cases = {
        "budget_mismatch": (
            _gpu_operation(prepared, 1.0),
            HostScheduling(ledger_root=host.ledger_root, budget=_budget(memory=32.0)),
        ),
        "resources_required": (CandidateOperation(request_id=uuid4(), request=prepared), host),
        "placement_unreachable": (
            _gpu_operation(prepared, 1.0, names=prepared.environment_names),
            host,
        ),
        "resource_refused": (_gpu_operation(prepared, 5.0), host),
    }
    for expected, (operation, selection) in cases.items():
        code = _code(
            lambda op=operation, sel=selection: submit_operation(
                other, op, launch_environment=KEY, host=sel
            )
        )
        assert code == expected
    assert _claims(other) == []
    assert len(children.children) == 1


def test_ledger_location_is_refused_before_any_side_effect(prepared, tmp_path, children):
    """A missing ledger is not created; one inside a store or input is refused."""
    store = _store(tmp_path, "store-a")
    operation = _gpu_operation(prepared, 1.0)
    missing = HostScheduling(ledger_root=str(tmp_path / "absent"), budget=_budget())
    code = _code(lambda: submit_operation(store, operation, launch_environment=KEY, host=missing))
    assert code == "path"
    assert not (tmp_path / "absent").exists()
    assert Path(store.state_root).is_dir()  # the store (not the ledger) exists by now
    inside = Path(store.state_root) / "ledger"
    inside.mkdir(mode=0o700)
    nested = HostScheduling(ledger_root=str(inside), budget=_budget())
    code = _code(lambda: submit_operation(store, operation, launch_environment=KEY, host=nested))
    assert code == "path"
    assert not (inside / "ledger.lock").exists()
    assert len(children.children) == 0


def test_a_held_ledger_refuses_after_a_bounded_wait(prepared, tmp_path, children, monkeypatch):
    monkeypatch.setattr("tools.candidate_operations.host_ledger.LEDGER_LOCK_WAIT_SECONDS", 0.1)
    host = _ledger(tmp_path)
    store = _store(tmp_path, "store-a")
    with locked_ledger(host.ledger_root):
        code = _code(
            lambda: submit_operation(
                store, _gpu_operation(prepared, 1.0), launch_environment=KEY, host=host
            )
        )
    assert code == "ledger_busy"
    assert _claims(store) == []


def test_time_budgeted_run_shares_a_gpu_only_when_acknowledged(prepared, tmp_path, children):
    """Decision B3-Q6: contention changes measured-time admission of both runs.

    The rule is a ``plan_dispatch`` placement constraint (#1019): with the only
    slot shared, the run is queued (B3-5b) and its queued reason names the
    time-budget contention; the reservation records the flag.
    """
    for acknowledge, ledger in ((False, "plain"), (True, "acknowledged")):
        host = _ledger(tmp_path, ledger, acknowledge=acknowledge)
        submit_operation(
            _store(tmp_path, f"{ledger}-a"),
            _gpu_operation(prepared, 1.0),
            launch_environment=KEY,
            host=host,
        )
        timed = _gpu_operation(prepared, 1.0, time_budgeted=True)
        launch = lambda op=timed, sel=host, name=ledger: submit_operation(  # noqa: E731
            _store(tmp_path, f"{name}-b"), op, launch_environment=KEY, host=sel
        )
        if acknowledge:
            assert launch().observation == "starting"
            with locked_ledger(host.ledger_root) as root:
                flags = [r.placement.reserved.time_budgeted for r in read_state(root).reservations]
            assert flags == [False, True]
        else:
            assert launch().observation == "queued"
            with locked_ledger(host.ledger_root) as root:
                (waiting,) = read_state(root).queued
            assert "time-budgeted unit would share it" in waiting.placement.reasons[0]


def test_spawn_failure_returns_the_reservation(prepared, tmp_path, monkeypatch):
    """A child that never started must not hold the host budget forever."""

    def refuse(path, env):
        raise OSError("no child started")

    monkeypatch.setattr("tools.candidate_operations.submit.spawn", refuse)
    host = _ledger(tmp_path)
    handle = submit_operation(
        _store(tmp_path, "store-a"),
        _gpu_operation(prepared, 3.0),
        launch_environment=KEY,
        host=host,
    )
    assert handle.observation == "operation_failed"
    with locked_ledger(host.ledger_root) as root:
        state = read_state(root)
    assert state.reservations == () and state.next_ordinal == 1


def test_serial_default_reads_no_ledger_and_keeps_record_bytes(prepared, tmp_path, children):
    """Without a host selection the child env and request.json are exactly as before B3-5."""
    config = _store(tmp_path, "store-a")
    operation = CandidateOperation(request_id=uuid4(), request=prepared)
    submit_operation(config, operation, launch_environment=KEY)
    assert "CUDA_VISIBLE_DEVICES" not in children.envs[0]
    record = _operation_dir(config, operation)
    assert '"resources"' not in (record / "request.json").read_text()
    assert not (record / "placement.json").exists()


def test_cli_passes_the_budget_and_refuses_either_flag_alone(
    prepared, tmp_path, monkeypatch, capsys
):
    """The flags must reach submit_operation; a ledger without a budget has no rule."""
    from tools.candidate_operations import __main__ as cli

    store = tmp_path / "store.json"
    store.write_text(_store(tmp_path, "state").model_dump_json())
    request = tmp_path / "submission.json"
    request.write_text(_gpu_operation(prepared, 1.0).model_dump_json())
    budget_file = tmp_path / "budget.json"
    budget_file.write_text(_budget().model_dump_json(exclude={"source"}))
    seen = []

    def submit(config, submission, *, launch_environment, host):
        seen.append(host)
        return CandidateOperation(request_id=submission.request_id, request=prepared)

    monkeypatch.setattr(cli, "submit_operation", submit)
    base = ["operation", "submit", "--store-config", str(store), "--request", str(request)]
    ledger = ["--host-ledger", str(tmp_path / "ledger")]
    budget = ["--host-budget", str(budget_file)]
    monkeypatch.setattr("sys.argv", [*base, *ledger, *budget])
    assert cli.main() == 0
    assert seen[0] == HostScheduling(ledger_root=str(tmp_path / "ledger"), budget=_budget())
    for alone in (ledger, budget):
        monkeypatch.setattr("sys.argv", [*base, *alone])
        assert cli.main() == 2
        assert json.loads(capsys.readouterr().err)["code"] == "usage"
    assert len(seen) == 1


# --- B3-5b: queued operations -------------------------------------------------


def _queue(host: HostScheduling):
    with locked_ledger(host.ledger_root) as root:
        return read_state(root).queued


def test_a_waiting_child_is_placed_in_submission_order(prepared, tmp_path, children, monkeypatch):
    """Strict FIFO across stores (decision B3-Q4) and the placed child's device.

    ``late`` (1 GiB) would fit beside ``first`` now; planning it without the
    earlier waiter would let it overtake ``middle``. When capacity returns, the
    first poll places every waiter that fits in order, whichever child polls, so
    ``late`` can never take capacity ``middle`` was given.
    """
    from tools.candidate_operations.host_queue import wait_for_placement

    host = _ledger(tmp_path)
    first, middle, late = (_gpu_operation(prepared, vram) for vram in (3.0, 3.0, 1.0))
    stores = [_store(tmp_path, f"store-{name}") for name in "abc"]
    observed = [
        submit_operation(store, op, launch_environment=KEY, host=host).observation
        for store, op in zip(stores, (first, middle, late), strict=True)
    ]
    assert observed == ["starting", "queued", "queued"]
    assert [q.operation_id for q in _queue(host)] == [middle.request_id, late.request_id]

    _end(children.children[0])
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "inherited")
    placement = wait_for_placement(_operation_dir(stores[2], late), late.request_id, lambda: False)
    assert placement is not None and placement.gpu_uuid == SLOT
    assert os.environ["CUDA_VISIBLE_DEVICES"] == SLOT
    assert [r.operation_id for r in _reservations(host)] == [middle.request_id, late.request_id]
    assert _queue(host) == ()
    published = json.loads((_operation_dir(stores[2], late) / "placement.json").read_text())
    assert published["decision"] == "placed"
    # ``middle``'s own child adopts the reservation it was given at its next poll.
    adopted = wait_for_placement(
        _operation_dir(stores[1], middle), middle.request_id, lambda: False
    )
    assert adopted is not None and adopted.unit_id == str(middle.request_id)


def test_a_dead_waiter_does_not_hold_the_line(prepared, tmp_path, children, monkeypatch):
    """A queued child that died never starts; keeping its entry would block every later one."""
    from tools.candidate_operations.host_queue import wait_for_placement

    host = _ledger(tmp_path)
    first, dead, late = (_gpu_operation(prepared, 3.0) for _ in range(3))
    stores = [_store(tmp_path, f"store-{name}") for name in "abc"]
    for store, op in zip(stores, (first, dead, late), strict=True):
        submit_operation(store, op, launch_environment=KEY, host=host)
    _end(children.children[1])
    _end(children.children[0])
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "inherited")
    placement = wait_for_placement(_operation_dir(stores[2], late), late.request_id, lambda: False)
    assert placement is not None
    assert [r.operation_id for r in _reservations(host)] == [late.request_id]
    assert _queue(host) == ()


def test_cancel_removes_a_queued_operation_without_running_it(
    prepared, tmp_path, children, monkeypatch
):
    """Decision B3-5 D2: Stop on a queued operation never claims its workspace.

    The real operation child runs in this process; the test process stands in
    for the live waiting child, so the snapshot is ``queued`` and cancellable.
    """
    import threading

    from tools.candidate_operations import read_operation, request_cancel
    from tools.candidate_operations.child import execute

    monkeypatch.setattr("tools.candidate_operations.host_queue.QUEUE_POLL_SECONDS", 0.05)
    host = _ledger(tmp_path)
    store_a, store_b = _store(tmp_path, "store-a"), _store(tmp_path, "store-b")
    first, waiting = _gpu_operation(prepared, 3.0), _gpu_operation(prepared, 3.0)
    submit_operation(store_a, first, launch_environment=KEY, host=host)
    assert submit_operation(store_b, waiting, launch_environment=KEY, host=host).observation == (
        "queued"
    )
    path = _operation_dir(store_b, waiting)
    codes: list[int] = []
    # Daemon: a regression that never leaves the queue must not hang the session.
    worker = threading.Thread(target=lambda: codes.append(execute(path)), daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while not (path / "process.json").exists():
            assert time.monotonic() < deadline, "operation child never published itself"
            time.sleep(0.02)
        snapshot = read_operation(store_b, waiting.request_id)
        assert (snapshot.state, snapshot.reason, snapshot.cancellable) == (
            "queued",
            "host_queued",
            True,
        )
        request_cancel(store_b, waiting.request_id)
    finally:
        worker.join(timeout=10)
    assert codes == [1]
    snapshot = read_operation(store_b, waiting.request_id)
    assert (snapshot.state, snapshot.reason, snapshot.cancel_requested) == (
        "operation_failed",
        "cancelled_while_queued",
        True,
    )
    assert _queue(host) == ()
    assert [r.operation_id for r in _reservations(host)] == [first.request_id]
    assert not (path / "placement.json").exists()
    workspace = Path(prepared.preview.document.definition.task.workspace)
    assert not (workspace / "candidate_run").exists()


def test_loop_resume_reserves_with_one_declaration_authority(prepared, tmp_path, monkeypatch):
    """A budgeted Resume reserves the root's declaration, else its own (#1385).

    Before #1385 a root without ``resources`` could never resume under a ledger. A
    supplied declaration beside the root's is refused even when equal (one authority),
    and without a ledger it is refused rather than silently ignored.
    """
    from tools.candidate_operations.host_admission import _declared, host_slot
    from tools.candidate_operations.models import (
        CandidateLoopResumeOperation,
        CandidateLoopResumeRequest,
    )

    config = _store(tmp_path, "store-a")
    root = _gpu_operation(prepared, 2.0)
    undeclared = root.model_copy(update={"resources": None})
    own = OperationResources(gpu_count=0, host_memory_gib=1.0, cpu_slots=2, time_budgeted=False)

    def resume(resources):
        return CandidateLoopResumeOperation(
            request_id=uuid4(),
            request=CandidateLoopResumeRequest(
                predecessor_operation_id=root.request_id,
                expected_receipt_digest="a" * 64,
                resources=resources,
            ),
        )

    monkeypatch.setattr("tools.candidate_operations.host_admission.load_record", lambda c, i: i)
    unplaced = Path(config.state_root) / "operations" / str(root.request_id)
    unplaced.mkdir(mode=0o700, parents=True)
    for part in (unplaced.parent, unplaced.parent.parent):
        part.chmod(0o700)
    monkeypatch.setattr(
        "tools.candidate_operations.loop_resume.loop_chain",
        lambda _: (SimpleNamespace(submission=SimpleNamespace(request_id=root.request_id)),),
    )

    def rooted(operation):
        monkeypatch.setattr(
            "tools.candidate_operations.loop_resume.root_record",
            lambda _: SimpleNamespace(submission=operation),
        )

    rooted(root)
    assert _declared(config, resume(None)) == (root, root.resources)
    assert _code(lambda: _declared(config, resume(own))) == "run_resources_conflict"
    assert _code(lambda: _declared(config, resume(root.resources))) == "run_resources_conflict"
    rooted(undeclared)
    assert _code(lambda: _declared(config, resume(None))) == "resources_required"
    assert _declared(config, resume(own)) == (undeclared, own)

    def serial(resources):
        with host_slot(None, config, resume(resources)):
            pass

    serial(None)  # the serial default, unchanged
    assert _code(lambda: serial(own)) == "host_ledger_missing"


def test_a_resume_without_resources_keeps_its_pre_1385_bytes_and_digest():
    """Records admitted before #1385 must replay and verify unchanged; the literals were
    produced by the pre-change code (master cc0dee852), not by this implementation.
    A supplied declaration is part of the request digest, so a retried request ID
    with other resources is a ``conflict`` rather than a silent replay."""
    from uuid import UUID

    from tools.candidate_operations.models import (
        CandidateLoopResumeOperation,
        CandidateLoopResumeRequest,
    )
    from tools.candidate_operations.store import digest

    def resume(resources=None):
        return CandidateLoopResumeOperation(
            request_id=UUID(int=1),
            request=CandidateLoopResumeRequest(
                predecessor_operation_id=UUID(int=2),
                expected_receipt_digest="a" * 64,
                resources=resources,
            ),
        )

    assert resume().model_dump_json() == (
        '{"kind":"candidate_loop_resume","request_id":"00000000-0000-0000-0000-000000000001",'
        '"request":{"predecessor_operation_id":"00000000-0000-0000-0000-000000000002",'
        '"expected_receipt_digest":"' + "a" * 64 + '"}}'
    )
    assert digest(resume()) == "dd205fdc7b49f09153df1e57ca0211a7a734a7c484110fc451cd96f01095f661"
    own = OperationResources(gpu_count=0, host_memory_gib=1.0, cpu_slots=1, time_budgeted=False)
    other = own.model_copy(update={"cpu_slots": 2})
    assert len({digest(resume()), digest(resume(own)), digest(resume(other))}) == 3


def test_a_supplied_resume_declaration_is_what_the_ledger_places(prepared, tmp_path, monkeypatch):
    """The admitted reservation is the segment's own declaration, not an absent root one."""
    from tools.candidate_operations.host_admission import host_slot
    from tools.candidate_operations.models import (
        CandidateLoopResumeOperation,
        CandidateLoopResumeRequest,
    )

    config, host = _store(tmp_path, "store-a"), _ledger(tmp_path)
    root = CandidateOperation(request_id=uuid4(), request=prepared)
    own = OperationResources(gpu_count=0, host_memory_gib=3.0, cpu_slots=2, time_budgeted=False)
    resume = CandidateLoopResumeOperation(
        request_id=uuid4(),
        request=CandidateLoopResumeRequest(
            predecessor_operation_id=root.request_id,
            expected_receipt_digest="a" * 64,
            resources=own,
        ),
    )
    monkeypatch.setattr("tools.candidate_operations.host_admission.load_record", lambda c, i: i)
    monkeypatch.setattr(
        "tools.candidate_operations.loop_resume.root_record",
        lambda _: SimpleNamespace(submission=root),
    )
    with host_slot(host, config, resume) as slot:
        placement = slot.admitted.placement
    assert placement.decision == "placed" and placement.gpu_uuid is None
    assert placement.unit_id == str(resume.request_id)
    assert (placement.reserved.host_memory_gib, placement.reserved.cpu_slots) == (3.0, 2)


def test_completion_records_the_host_placement_it_ran_under(prepared, tmp_path, children):
    """Host placement is operation provenance: the receipt must name the published one."""
    from tools.candidate_operations import read_operation
    from tools.candidate_operations.child import host_placement_evidence
    from tools.candidate_operations.models import Completion

    host = _ledger(tmp_path)
    store = _store(tmp_path, "store-a")
    operation = _gpu_operation(prepared, 3.0)
    submit_operation(store, operation, launch_environment=KEY, host=host)
    record, path = load_record(store, operation.request_id), _operation_dir(store, operation)
    publish(path / "process.json", identity_of(record, children.children[0].pid))
    evidence = host_placement_evidence(record, path)
    assert evidence is not None and evidence.placement.gpu_uuid == SLOT
    assert evidence.sandbox is None  # no sandbox started

    forged = evidence.placement.model_copy(update={"reasons": ("placed elsewhere",)})
    completion = Completion(
        operation_id=operation.request_id,
        request_digest=record.request_digest,
        outcome="pre_dispatch_failure",
        reason="runtime_binding_failed",
        host_placement=evidence.model_copy(update={"placement": forged}),
    )
    publish(path / "completion.json", completion)
    assert read_operation(store, operation.request_id).reason == "integrity_failure"


def test_a_ledger_from_an_earlier_revision_is_refused_with_one_typed_reason(
    prepared, tmp_path, children
):
    """A B3-5a ledger (reservation-level ``time_budgeted``) surfaced as a raw validation
    error, so admission, the sweep and the operator release all failed untyped and
    nothing told the operator what to do."""
    from tools.candidate_operations.files import publish_encoded
    from tools.candidate_operations.host_ledger import LEDGER_FILE

    host = _ledger(tmp_path)
    first = _gpu_operation(prepared, 1.0)
    submit_operation(_store(tmp_path, "a"), first, launch_environment=KEY, host=host)
    path = Path(host.ledger_root) / LEDGER_FILE
    old = json.loads(path.read_text())
    old["reservations"][0]["time_budgeted"] = False
    publish_encoded(path, json.dumps(old).encode(), replace=True)
    before = path.read_bytes()
    second = _gpu_operation(prepared, 1.0)
    launch = lambda: submit_operation(  # noqa: E731
        _store(tmp_path, "b"), second, launch_environment=KEY, host=host
    )
    with pytest.raises(OperationFailure) as refused:
        launch()
    assert refused.value.detail.code == "ledger_format"
    assert str(path) in str(refused.value) and "move" in str(refused.value)
    assert "unreadable by this SIDERIUS revision" in str(refused.value)
    released = lambda: release_reservation(host.ledger_root, first.request_id)  # noqa: E731
    assert _code(released) == "ledger_format"
    assert path.read_bytes() == before  # never rewritten
    assert _claims(_store(tmp_path, "b")) == []
    # A truncated (corrupt) ledger is refused the same way, never repaired.
    publish_encoded(path, before[: len(before) // 2], replace=True)
    assert _code(launch) == "ledger_format"
    assert _code(released) == "ledger_format"


def test_an_interrupted_spawn_leaves_no_ledger_entry(prepared, tmp_path, monkeypatch):
    """A Ctrl-C (not an OSError) between writing the entry and spawning used to keep it."""

    def interrupted(path, env):
        raise KeyboardInterrupt

    monkeypatch.setattr("tools.candidate_operations.submit.spawn", interrupted)
    host = _ledger(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        submit_operation(
            _store(tmp_path, "a"), _gpu_operation(prepared, 3.0), launch_environment=KEY, host=host
        )
    with locked_ledger(host.ledger_root) as root:
        state = read_state(root)
    assert state.reservations == () and state.queued == ()


def test_a_queue_entry_whose_submitter_died_does_not_block_the_line(
    prepared, tmp_path, children, monkeypatch
):
    """A submitter SIGKILLed after writing a queue entry, before any child, left an
    unbound entry at the head of the FIFO forever. Its exited submitter now releases it."""
    host = _ledger(tmp_path)
    first = _gpu_operation(prepared, 3.0)
    submit_operation(_store(tmp_path, "a"), first, launch_environment=KEY, host=host)
    abandoned = _gpu_operation(prepared, 3.0)
    pid = os.fork()
    if pid == 0:  # the submitter, killed right after the entry is written
        monkeypatch.setattr("tools.candidate_operations.submit.spawn", lambda *a: os._exit(0))
        try:
            submit_operation(_store(tmp_path, "b"), abandoned, launch_environment=KEY, host=host)
        finally:
            os._exit(1)
    os.waitpid(pid, 0)
    (entry,) = _queue(host)
    assert entry.operation_id == abandoned.request_id and entry.process is None
    assert entry.submitter is not None and entry.submitter.pid == pid
    _end(children.children[0])
    late = _gpu_operation(prepared, 3.0)
    handle = submit_operation(_store(tmp_path, "c"), late, launch_environment=KEY, host=host)
    assert handle.observation == "starting"
    assert _queue(host) == ()


def test_a_serial_resume_of_a_ledger_placed_loop_is_refused(prepared, tmp_path, monkeypatch):
    """Without the ledger the segment would run unaccounted beside placed runs.

    Any placed segment counts: an undeclared root runs serially while its resumes may
    be placed with their own declaration (#1385), so checking only the root missed them.
    """
    from tools.candidate_operations.host_admission import host_slot
    from tools.candidate_operations.models import (
        CandidateLoopResumeOperation,
        CandidateLoopResumeRequest,
    )
    from tools.candidate_operations.store import operation_path

    config = _store(tmp_path, "a")
    root = _gpu_operation(prepared, 2.0)
    segment = uuid4()
    resume = CandidateLoopResumeOperation(
        request_id=uuid4(),
        request=CandidateLoopResumeRequest(
            predecessor_operation_id=segment, expected_receipt_digest="a" * 64
        ),
    )
    chain = (
        SimpleNamespace(submission=SimpleNamespace(request_id=segment)),
        SimpleNamespace(submission=root),
    )
    monkeypatch.setattr("tools.candidate_operations.host_admission.load_record", lambda c, i: i)
    monkeypatch.setattr("tools.candidate_operations.loop_resume.loop_chain", lambda _: chain)
    monkeypatch.setattr(
        "tools.candidate_operations.loop_resume.root_record",
        lambda _: SimpleNamespace(submission=root),
    )
    directory = Path(config.state_root)
    for part in (directory, directory / "operations"):
        part.mkdir(mode=0o700)
    for operation_id in (segment, root.request_id):
        (directory / "operations" / str(operation_id)).mkdir(mode=0o700)
    with host_slot(None, config, resume):
        pass  # an unplaced loop resumes serially as before

    def enter():
        with host_slot(None, config, resume):
            pass

    for placed in (segment, root.request_id):
        marker = operation_path(config, placed) / "placement.json"
        marker.write_text("{}")
        assert _code(enter) == "host_ledger_required"
        marker.unlink()


@pytest.mark.parametrize("limit", [0, 2])
def test_host_queue_cap_refuses_before_claim_or_spawn(prepared, tmp_path, children, limit):
    """The (limit + 1)th waiter must not allocate another unreserved process."""
    host = _ledger(tmp_path)
    host = host.model_copy(
        update={"budget": host.budget.model_copy(update={"max_queued_operations": limit})}
    )
    first = _gpu_operation(prepared, 3.0)
    submit_operation(_store(tmp_path, "running"), first, launch_environment=KEY, host=host)
    for index in range(limit):
        submit_operation(
            _store(tmp_path, f"waiting-{index}"),
            _gpu_operation(prepared, 3.0),
            launch_environment=KEY,
            host=host,
        )
    refused_store = _store(tmp_path, "refused")
    refused = _gpu_operation(prepared, 3.0)
    assert (
        _code(lambda: submit_operation(refused_store, refused, launch_environment=KEY, host=host))
        == "host_queue_full"
    )
    assert _claims(refused_store) == []
    assert len(children.children) == limit + 1
    assert len(_queue(host)) == limit
    # Promotion frees queue space before applying the cap to a fresh submission.
    _end(children.children[0])
    handle = submit_operation(refused_store, refused, launch_environment=KEY, host=host)
    assert handle.observation == ("queued" if limit else "starting")
    assert len(_queue(host)) == limit


@pytest.mark.parametrize("marker", ["process", "sandbox", "submitter"])
@pytest.mark.parametrize("namespace", ["different", "missing", "capture_unknown"])
@pytest.mark.parametrize("release", ["sweep", "operator"])
def test_namespace_controls_sweep_and_operator_release(
    prepared, tmp_path, children, monkeypatch, marker, namespace, release
):
    """Both release paths reject foreign/unknown namespaces and retain legacy behavior."""
    from tools.candidate_operations import process
    from tools.candidate_operations.files import publish_encoded
    from tools.candidate_operations.host_ledger import LEDGER_FILE

    host = _ledger(tmp_path)
    store = _store(tmp_path, "namespace-store")
    operation = _gpu_operation(prepared, 1.0)
    submit_operation(store, operation, launch_environment=KEY, host=host)
    path = Path(host.ledger_root) / LEDGER_FILE
    payload = json.loads(path.read_text())
    entry = payload["reservations"][0]
    identity = dict(entry["submitter" if marker == "submitter" else "process"])
    if namespace == "missing":
        del identity["pid_namespace_inode"]
    elif namespace == "capture_unknown":
        identity["pid_namespace_inode"] = 0
    else:
        identity["pid_namespace_inode"] += 1
    if marker == "sandbox":
        publish_encoded(
            _operation_dir(store, operation) / "sandbox.json", json.dumps(identity).encode()
        )
    else:
        entry[marker] = identity
        if marker == "submitter":
            entry["process"] = None
        publish_encoded(path, json.dumps(payload).encode(), replace=True)

    def absent(_):
        raise FileNotFoundError()

    monkeypatch.setattr(process, "_stat", absent)
    monkeypatch.setattr("tools.candidate_operations.host_liveness.session_members", lambda _: 0)
    if release == "sweep":
        with locked_ledger(host.ledger_root) as root:
            state = sweep(root)
        assert [entry.operation_id for entry in state.reservations] == (
            [] if namespace == "missing" else [operation.request_id]
        )
    elif namespace == "missing":
        release_reservation(host.ledger_root, operation.request_id)
    else:
        with pytest.raises(OperationFailure) as refused:
            release_reservation(host.ledger_root, operation.request_id)
        assert refused.value.detail.code == "liveness_unobservable"


def test_a_placed_child_runs_only_while_admission_keeps_its_reservation(
    prepared, tmp_path, children, processes, monkeypatch
):
    """Ctrl-C inside ``Popen`` after the fork removed the entry while the forked child
    went on to run unaccounted (#1108). The child now confirms its entry first."""
    from tools.candidate_operations import child as operation_child

    launched: list[object] = []
    monkeypatch.setattr(
        operation_child, "launch_candidate", lambda *args, **kwargs: launched.append(args)
    )
    host = _ledger(tmp_path)
    store = _store(tmp_path, "a")
    kept = _gpu_operation(prepared, 1.0)
    submit_operation(store, kept, launch_environment=KEY, host=host)
    assert operation_child.execute(_operation_dir(store, kept)) == 1  # fake native: no receipt
    assert len(launched) == 1  # a held reservation is confirmed and the run proceeds

    def forked_then_interrupted(path, env):
        processes.append(_session_leader())  # the child already exists
        raise KeyboardInterrupt

    monkeypatch.setattr("tools.candidate_operations.submit.spawn", forked_then_interrupted)
    removed, other = _gpu_operation(prepared, 1.0), _store(tmp_path, "b")
    with pytest.raises(KeyboardInterrupt):
        submit_operation(other, removed, launch_environment=KEY, host=host)
    assert [r.operation_id for r in _reservations(host)] == [kept.request_id]
    path = _operation_dir(other, removed)
    assert operation_child.execute(path) == 1
    completion = json.loads((path / "completion.json").read_text())
    assert (completion["outcome"], completion["reason"]) == (
        "pre_dispatch_failure",
        "host_reservation_unconfirmed",
    )
    assert len(launched) == 1  # the unaccounted child never ran


def test_a_parallel_refusal_names_the_run_declaration_not_the_clamped_envelope(
    prepared, tmp_path, children
):
    """After the envelope clamp only the run's own ``resources`` can exceed an idle
    budget; the generic single-unit message sent the operator to the capabilities."""
    from tests.helpers.candidate_fanout import fanout_request
    from tools.candidate_worker.parallel_models import CapabilityResources, ParallelDispatch

    request = fanout_request(prepared, 2)
    parallel = ParallelDispatch(
        capabilities={
            "implementation": CapabilityResources(gpu=False, host_memory_gib=1.0, cpu_slots=1)
        }
    )
    operation = CandidateOperation(
        request_id=uuid4(),
        request=request.model_copy(update={"parallel": parallel}),
        resources=OperationResources(
            gpu_count=0, host_memory_gib=128.0, cpu_slots=1, time_budgeted=False
        ),
    )
    store = _store(tmp_path, "a")
    with pytest.raises(OperationFailure) as refused:
        submit_operation(store, operation, launch_environment=KEY, host=_ledger(tmp_path))
    assert refused.value.detail.code == "resource_refused"
    assert "resources declaration" in str(refused.value) and "128.00 GiB" in str(refused.value)
    assert _claims(store) == []
