"""Parallel graph dispatch inside an admitted budget (B3-4b).

Units run through the production loop (`parallel_dispatch`) with `start_unit`
replaced by an in-process starter: each unit's real `unit_child` entry runs at
start and its process reports completion after a seeded number of polls, so
completion order varies while every native phase is the shared offline fake.
The cancellation case starts real child processes in their own sessions.
"""

import os
import random
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from core.runtime_control.pair_admission import ResolvedGpuCeiling
from core.runtime_control.process_group import observe_group
from core.runtime_control.scheduling import GpuHardwareClass, GpuSlot, HostBudget
from tests.helpers.candidate_fanout import UNROUTED_TRACE_SHA256, fanout_request, trace_projection
from tools.candidate_worker import launch_candidate, parallel_dispatch
from tools.candidate_worker.graph_evidence import verify_graph_trace
from tools.candidate_worker.models import CandidateRunReceipt
from tools.candidate_worker.parallel_models import (
    CapabilityResources,
    ParallelDispatch,
    UnitReceipt,
)

from .test_native import native_runner

__all__ = ["native_runner"]

SLOT = "GPU-aaaa"


def _budget(*, units: int, vram_ceiling: float | None = None) -> HostBudget:
    gpus = ()
    if vram_ceiling is not None:
        hardware = GpuHardwareClass(
            device_name="NVIDIA H100", total_memory_bytes=80 * 1024**3, compute_capability=(9, 0)
        )
        ceiling = ResolvedGpuCeiling(
            operator_ceiling_gib=vram_ceiling,
            operator_source="caller",
            host_quota_gib=None,
            measured_capacity_gib=80.0,
        )
        gpus = (GpuSlot(uuid=SLOT, hardware_class=hardware, ceiling=ceiling),)
    return HostBudget(
        gpus=gpus, host_memory_gib=64.0, cpu_slots=16, max_concurrent_units=units, source="caller"
    )


def _parallel(prepared, budget: HostBudget, *, validation_vram: float | None = None):
    cpu = CapabilityResources(gpu=False, host_memory_gib=1.0, cpu_slots=1)
    validation = (
        cpu
        if validation_vram is None
        else CapabilityResources(
            gpu=True, vram_gib=validation_vram, host_memory_gib=1.0, cpu_slots=1
        )
    )
    table = {"proposal": cpu, "implementation": cpu, "validation": validation}
    request = fanout_request(prepared)
    return request.model_copy(
        update={"parallel": ParallelDispatch(capabilities=table, budget=budget)}
    )


def _reaped_pid() -> int:
    process = subprocess.Popen(["true"])
    process.wait()
    return process.pid


_REAPED_PID = _reaped_pid()


class _FakeUnit:
    """A finished unit child that reports exit only after ``polls`` polls."""

    def __init__(self, path: Path, polls: int, returncode: int, active: list[str]):
        self.args = ["unit", str(path)]
        self.pid = _REAPED_PID  # never this process's group, even on a cleanup path
        self.polls = polls
        self.returncode: int | None = None
        self._code = returncode
        self._active = active
        self.node_id = path.parent.name

    def poll(self):
        if self.returncode is None:
            if self.polls <= 0:
                self.returncode = self._code
                self._active.remove(self.node_id)
            self.polls -= 1
        return self.returncode

    def wait(self):
        return self.poll()


class _Starter:
    """Runs the real unit child entry in-process; records env and concurrency."""

    def __init__(self, seed: int, failing: frozenset[str] = frozenset()):
        self.rng = random.Random(seed)
        self.failing = failing
        self.envs: dict[str, dict[str, str]] = {}
        self.active: list[str] = []
        self.overlaps: list[tuple[str, ...]] = []

    def __call__(self, path: Path, env: dict[str, str]):
        from tools.candidate_worker.unit_child import run_invocation_file

        node = path.parent.name
        self.envs[node] = env
        self.active.append(node)
        self.overlaps.append(tuple(sorted(self.active)))
        if node in self.failing:
            return _FakeUnit(path, 0, 1, self.active)
        run_invocation_file(path)
        return _FakeUnit(path, self.rng.randint(0, 4), 0, self.active)


def _without_scheduling(receipt) -> str:
    return trace_projection(receipt).replace(',"scheduling":"parallel-v1"', "")


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_parallel_body_reproduces_the_serial_trace_in_any_completion_order(
    prepared, native_runner, monkeypatch, seed
):
    """Aggregation by completion order, or a unit reading a sibling, would move the trace.

    The serial golden (`UNROUTED_TRACE_SHA256`) must hold byte for byte apart
    from the trace v2 marker, while both builds really overlap.
    """
    import hashlib

    starter = _Starter(seed)
    monkeypatch.setattr(parallel_dispatch, "start_unit", starter)
    receipt = launch_candidate(_parallel(prepared, _budget(units=2)))
    assert receipt.status == "accepted", receipt.error
    assert receipt.graph_trace is not None and receipt.graph_trace.scheduling == "parallel-v1"
    digest = hashlib.sha256(_without_scheduling(receipt).encode()).hexdigest()
    assert digest == UNROUTED_TRACE_SHA256["accepted"]
    assert ("build0", "build1") in starter.overlaps
    for env in starter.envs.values():
        assert env["CUDA_VISIBLE_DEVICES"] == ""  # CPU-only placement hides every GPU
        assert "-p no:cacheprovider" in env["PYTEST_ADDOPTS"]


def test_gpu_units_never_exceed_the_reserved_slot(prepared, native_runner, monkeypatch):
    """Two 3 GiB checks may not share a 4 GiB slot: the second waits for the first."""
    starter = _Starter(7)
    monkeypatch.setattr(parallel_dispatch, "start_unit", starter)
    request = _parallel(prepared, _budget(units=4, vram_ceiling=4.0), validation_vram=3.0)
    receipt = launch_candidate(request)
    assert receipt.status == "accepted", receipt.error
    assert not any({"check0", "check1"} <= set(active) for active in starter.overlaps)
    assert starter.envs["check0"]["CUDA_VISIBLE_DEVICES"] == SLOT


def test_a_failure_drains_running_units_and_dispatches_nothing_new(
    prepared, native_runner, monkeypatch
):
    """Decision B3-Q2: `build1` was running when `build0` failed, so it keeps its outcome.

    The serial reference would block `build1`; trace v2 accepts it from the
    receipts, and refuses a forged receipt that started after the failure.
    """
    starter = _Starter(3, failing=frozenset({"build0"}))
    monkeypatch.setattr(parallel_dispatch, "start_unit", starter)
    request = _parallel(prepared, _budget(units=2))
    receipt = launch_candidate(request)
    assert receipt.status == "failed", receipt.error
    assert receipt.graph_trace is not None
    states = {item.node_id: item.state for item in receipt.graph_trace.nodes}
    assert states == {
        "propose": "succeeded",
        "build0": "failed",
        "build1": "succeeded",
        "check0": "blocked",
        "check1": "blocked",
    }
    assert "check1" not in starter.envs  # nothing dispatched after the failure
    control = Path(receipt.workspace) / "candidate_run" / "units"
    launched = CandidateRunReceipt.model_validate_json(
        (Path(receipt.workspace) / "candidate_run" / "launch.json").read_bytes()
    )
    verify_graph_trace(request, launched, receipt)  # the real receipts verify
    late = control / "build1" / "placement.json"
    record = UnitReceipt.model_validate_json(late.read_bytes())
    failed = UnitReceipt.model_validate_json((control / "build0" / "placement.json").read_bytes())
    assert record.started_event < failed.ended_event
    os.chmod(late, 0o600)
    late.write_text(
        record.model_copy(
            update={"started_event": failed.ended_event + 1, "ended_event": failed.ended_event + 2}
        ).model_dump_json()
    )
    with pytest.raises(ValueError, match="dispatched after a failure"):
        verify_graph_trace(request, launched, receipt)


def test_sigterm_kills_every_running_unit_process_group(prepared, native_runner, monkeypatch):
    """A unit outliving its worker would keep its GPU and budget after the run is gone."""
    started: list[subprocess.Popen] = []
    real_start = parallel_dispatch.start_unit

    def sleepers(path, env):
        process = real_start(path, env)
        started.append(process)
        return process

    monkeypatch.setattr(
        "tools.candidate_worker.unit_runner.unit_command",
        lambda path: [sys.executable, "-c", "import time; time.sleep(60)"],
    )
    monkeypatch.setattr(parallel_dispatch, "start_unit", sleepers)
    request = _parallel(prepared, _budget(units=2))
    # `propose` runs first; let it through the real child by running it in-process.
    from tools.candidate_worker.unit_child import run_invocation_file

    def first_in_process(path, env):
        if path.parent.name == "propose":
            run_invocation_file(path)
            return _FakeUnit(path, 0, 0, [path.parent.name])
        return sleepers(path, env)

    monkeypatch.setattr(parallel_dispatch, "start_unit", first_in_process)

    def terminate_when_both_run():
        deadline = time.monotonic() + 30
        while len(started) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=terminate_when_both_run, daemon=True).start()
    with pytest.raises(parallel_dispatch.UnitTerminated):
        launch_candidate(request)
    assert len(started) == 2
    for process in started:
        assert process.returncode is not None
        assert observe_group(process.pid).status == "absent"
