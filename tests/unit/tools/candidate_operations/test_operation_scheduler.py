"""Cross-operation host ledger (B3-5a): separate stores share one declared budget.

The operation child is replaced by a real session-leader process so identity
binding and session-end release are exercised against /proc, not mocks.
"""

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import pytest

from core.runtime_control.pair_admission import ResolvedGpuCeiling
from core.runtime_control.scheduling import GpuHardwareClass, GpuSlot, HostBudget
from tests.unit.tools.candidate_worker.conftest import prepared
from tools.candidate_operations import CandidateOperation, OperationStoreConfig, submit_operation
from tools.candidate_operations.host_ledger import (
    HostScheduling,
    locked_ledger,
    read_state,
    release_reservation,
)
from tools.candidate_operations.models import OperationFailure, OperationResources
from tools.candidate_operations.process import session_members

SLOT = "GPU-aaaa"
KEY = {"OPENAI_API_KEY": "offline-test-key"}


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


def _store(tmp_path: Path, name: str) -> OperationStoreConfig:
    return OperationStoreConfig(
        state_root=str(tmp_path / name),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )


def _gpu_operation(prepared, vram: float, *, time_budgeted: bool = False, names=None):
    names = names or (*prepared.environment_names, "CUDA_VISIBLE_DEVICES")
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


class _Children:
    """Fake operation spawns: real session leaders running ``script``; records envs."""

    def __init__(self, script: str = "exec sleep 60"):
        self.script = script
        self.envs: list[dict[str, str]] = []
        self.children: list[subprocess.Popen] = []

    def __call__(self, path, env):
        self.envs.append(env)
        child = subprocess.Popen(["/bin/sh", "-c", self.script], start_new_session=True)
        self.children.append(child)
        return child

    def end(self, child: subprocess.Popen) -> None:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait()
        _wait_for_session_end(child.pid)


def _wait_for_session_end(session: int) -> None:
    deadline = time.monotonic() + 10
    while session_members(session) != 0:
        assert time.monotonic() < deadline, "test session did not end"
        time.sleep(0.05)


@pytest.fixture
def children(monkeypatch):
    fake = _Children()
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", fake)
    yield fake
    for child in fake.children:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()


def _code(call) -> str:
    with pytest.raises(OperationFailure) as failure:
        call()
    return failure.value.detail.code


def _claims(config: OperationStoreConfig) -> list[str]:
    operations = Path(config.state_root) / "operations"
    return sorted(os.listdir(operations)) if operations.exists() else []


def test_two_stores_share_one_budget_until_the_first_session_ends(prepared, tmp_path, children):
    """A per-store ledger would place both 3 GiB operations on one 4 GiB slot.

    The second is refused before any claim, the first child receives exactly the
    reserved device, and the reservation is released only after its session ends.
    """
    host = HostScheduling(ledger_root=str(tmp_path / "ledger"), budget=_budget())
    first_store, second_store = _store(tmp_path, "store-a"), _store(tmp_path, "store-b")
    first = _gpu_operation(prepared, 3.0)
    handle = submit_operation(first_store, first, launch_environment=KEY, host=host)
    assert handle.observation == "starting"
    assert children.envs[0]["CUDA_VISIBLE_DEVICES"] == SLOT
    placement = json.loads(
        (
            Path(first_store.state_root) / "operations" / str(first.request_id) / "placement.json"
        ).read_text()
    )
    assert (placement["decision"], placement["gpu_uuid"]) == ("placed", SLOT)
    with locked_ledger(host.ledger_root) as root:
        (reservation,) = read_state(root).reservations
    assert reservation.process is not None
    assert reservation.process.pid == children.children[0].pid

    second = _gpu_operation(prepared, 3.0)
    assert (
        _code(lambda: submit_operation(second_store, second, launch_environment=KEY, host=host))
        == "host_capacity"
    )
    assert _claims(second_store) == []

    children.end(children.children[0])
    handle = submit_operation(second_store, second, launch_environment=KEY, host=host)
    assert handle.observation == "starting"
    assert children.envs[1]["CUDA_VISIBLE_DEVICES"] == SLOT


def test_reservation_outlives_its_leader_while_a_session_member_survives(
    prepared, tmp_path, children
):
    """A positive leader exit alone is not proof the GPU is free (orphaned training)."""
    children.script = "sleep 60 & exit 0"
    host = HostScheduling(ledger_root=str(tmp_path / "ledger"), budget=_budget())
    first = _gpu_operation(prepared, 3.0)
    submit_operation(_store(tmp_path, "store-a"), first, launch_environment=KEY, host=host)
    leader = children.children[0]
    leader.wait()  # the operation child itself has exited and been reaped
    assert session_members(leader.pid) == 1

    second = _gpu_operation(prepared, 3.0)
    second_store = _store(tmp_path, "store-b")
    assert (
        _code(lambda: submit_operation(second_store, second, launch_environment=KEY, host=host))
        == "host_capacity"
    )
    assert _code(lambda: release_reservation(host.ledger_root, first.request_id)) == "session_live"

    os.killpg(leader.pid, signal.SIGKILL)
    _wait_for_session_end(leader.pid)
    released = release_reservation(host.ledger_root, first.request_id)
    assert released.evidence is not None and released.evidence.ended
    assert _code(lambda: release_reservation(host.ledger_root, first.request_id)) == "not_reserved"
    submit_operation(second_store, second, launch_environment=KEY, host=host)


def test_mixed_host_refusals_leave_no_claim(prepared, tmp_path, children):
    """Every launch that would bypass or misstate the live ledger refuses before claim."""
    ledger = str(tmp_path / "ledger")
    host = HostScheduling(ledger_root=ledger, budget=_budget())
    submit_operation(
        _store(tmp_path, "store-a"),
        _gpu_operation(prepared, 1.0),
        launch_environment=KEY,
        host=host,
    )
    other = _store(tmp_path, "store-b")
    cases = {
        "host_reserved": (
            _gpu_operation(prepared, 1.0),
            HostScheduling(ledger_root=ledger),
        ),
        "budget_mismatch": (
            _gpu_operation(prepared, 1.0),
            HostScheduling(ledger_root=ledger, budget=_budget(memory=32.0)),
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


def test_time_budgeted_run_shares_a_gpu_only_when_acknowledged(prepared, tmp_path, children):
    """Decision B3-Q6: contention changes measured-time admission of both runs."""
    for acknowledge, ledger in ((False, "plain"), (True, "acknowledged")):
        host = HostScheduling(
            ledger_root=str(tmp_path / ledger), budget=_budget(acknowledge=acknowledge)
        )
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
    host = HostScheduling(ledger_root=str(tmp_path / "ledger"), budget=_budget())
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
    record = Path(config.state_root) / "operations" / str(operation.request_id)
    assert '"resources"' not in (record / "request.json").read_text()
    assert not (record / "placement.json").exists()


def test_cli_passes_the_declared_budget_file_and_refuses_a_budget_without_ledger(
    prepared, tmp_path, monkeypatch, capsys
):
    """The flags must reach submit_operation; a budget without a ledger has no owner."""
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
    monkeypatch.setattr("sys.argv", [*base, *budget])
    assert cli.main() == 2
    assert json.loads(capsys.readouterr().err)["code"] == "usage"
    assert len(seen) == 1
