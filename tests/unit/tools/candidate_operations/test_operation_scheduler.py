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
from uuid import uuid4

import pytest

from core.runtime_control.pair_admission import ResolvedGpuCeiling, host_quota_gib
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
GPU_NAMES = ("CUDA_VISIBLE_DEVICES", "SIDERIUS_GPU_VRAM_QUOTA_MIB")


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


def test_two_stores_share_one_budget_and_the_child_gets_its_placement(prepared, tmp_path, children):
    """A per-store ledger would place both 3 GiB operations on one 4 GiB slot.

    The second is refused before any claim; the first child sees only its slot and
    a VRAM quota no larger than its reservation, which the run's own ceiling owner
    (``host_quota_gib``) reads, so in-run GPU admission refuses anything bigger.
    """
    host = _ledger(tmp_path)
    first_store, second_store = _store(tmp_path, "store-a"), _store(tmp_path, "store-b")
    first = _gpu_operation(prepared, 3.0)
    launch = {**KEY, "SIDERIUS_GPU_VRAM_QUOTA_MIB": "8192", "CUDA_VISIBLE_DEVICES": "0,1"}
    handle = submit_operation(first_store, first, launch_environment=launch, host=host)
    assert handle.observation == "starting"
    env = children.envs[0]
    assert env["CUDA_VISIBLE_DEVICES"] == SLOT
    assert host_quota_gib(environ=env) == 3.0
    placement = json.loads((_operation_dir(first_store, first) / "placement.json").read_text())
    assert (placement["decision"], placement["gpu_uuid"]) == ("placed", SLOT)
    (reservation,) = _reservations(host)
    assert reservation.process is not None
    assert reservation.process.pid == children.children[0].pid

    second = _gpu_operation(prepared, 3.0)
    smaller_quota = {**KEY, "SIDERIUS_GPU_VRAM_QUOTA_MIB": "2048"}
    assert (
        _code(
            lambda: submit_operation(
                second_store, second, launch_environment=smaller_quota, host=host
            )
        )
        == "host_capacity"
    )
    assert _claims(second_store) == []

    _end(children.children[0])
    submit_operation(second_store, second, launch_environment=smaller_quota, host=host)
    assert host_quota_gib(environ=children.envs[1]) == 2.0  # an inherited tighter quota wins


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

    second = _gpu_operation(prepared, 3.0)
    other = _store(tmp_path, "store-b")
    launch = lambda: submit_operation(other, second, launch_environment=KEY, host=host)  # noqa: E731
    assert _code(launch) == "host_capacity"
    assert _code(lambda: release_reservation(host.ledger_root, first.request_id)) == "session_live"

    _end(sandbox)
    assert launch().observation == "starting"


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
    store, other = _store(tmp_path, "store-a"), _store(tmp_path, "store-b")
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
    second = _gpu_operation(prepared, 3.0)
    launch = lambda: submit_operation(other, second, launch_environment=KEY, host=host)  # noqa: E731

    forged = identity_of(record, child.pid).model_copy(update={"request_digest": "0" * 64})
    publish(path / "process.json", forged)
    assert _code(launch) == "host_capacity"  # mismatched evidence keeps it, without raising
    os.unlink(path / "process.json")
    publish(path / "process.json", identity_of(record, child.pid))  # the child's own record
    assert _code(launch) == "host_capacity"  # still alive
    _end(child)
    assert launch().observation == "starting"


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
            _gpu_operation(
                prepared, 1.0, names=(*prepared.environment_names, "CUDA_VISIBLE_DEVICES")
            ),
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
    """Decision B3-Q6: contention changes measured-time admission of both runs."""
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
        else:
            assert _code(launch) == "shared_gpu_time_budget"


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
