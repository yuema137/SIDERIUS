"""Parallel graph dispatch inside an admitted budget (B3-4b).

Most cases drive the production loop (`parallel_dispatch`) with `start_unit`
replaced by an in-process starter. It runs each unit's real `unit_child` entry
synchronously when the unit starts, then reports the unit as finished only
after a seeded number of polls. So the units' work does not actually overlap:
what varies is the order in which the scheduler observes completions, which is
what aggregation and drain depend on. Every native phase is the shared offline
fake. Real child processes are covered separately: two units running to
completion through the real `start_unit` and `collect_result`, and SIGTERM
cleanup of real process groups.
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
        self.process = self
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

    def check(self):
        """No code package is bound in these fakes, as for an unguarded child."""


class _Starter:
    """Runs the real unit child entry in-process; records env and concurrency."""

    def __init__(
        self, seed: int, failing: frozenset[str] = frozenset(), hold: dict[str, int] | None = None
    ):
        self.rng = random.Random(seed)
        self.failing = failing
        self.hold = hold or {}
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
            # Exits after the next unit has started, so the failure meets a running sibling.
            return _FakeUnit(path, self.hold.get(node, 2), 1, self.active)
        run_invocation_file(path)
        polls = self.hold.get(node, self.rng.randint(0, 4))
        return _FakeUnit(path, polls, 0, self.active)


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

    # build0 outlives build1's start, so the overlap is certain; the rest is seeded.
    starter = _Starter(seed, hold={"build0": 3})
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
    """Two 3 GiB checks may not share a 4 GiB slot: the second waits for the first.

    Each check runs long enough that both would overlap if the second were
    started instead of queued.
    """
    starter = _Starter(7, hold={"check0": 40, "check1": 40})
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
    starter = _Starter(3, failing=frozenset({"build0"}), hold={"build1": 8})
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
    # Swap build1's start with build0's end: still one event permutation, but
    # build1 now starts after the failure ended.
    early = control / "build0" / "placement.json"
    os.chmod(late, 0o600)
    os.chmod(early, 0o600)
    late.write_text(
        record.model_copy(update={"started_event": failed.ended_event}).model_dump_json()
    )
    early.write_text(
        failed.model_copy(update={"ended_event": record.started_event}).model_dump_json()
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


def test_parallel_units_start_under_the_code_package_guard(tmp_path, monkeypatch):
    """A raw spawn would skip the integrity guard serial units get from ``prepare_child``.

    The helper changes after capture; the guarded child must refuse and the
    parent must surface it as the code-package refusal, not an exit status.
    """
    from core.local_code import LocalCodeError, bind_code_package
    from core.subprocess_env import subprocess_env
    from tests.unit.core.test_local_code_failure import package_and_env
    from tools.candidate_worker import unit_runner
    from tools.candidate_worker.unit_processes import start_unit

    package = package_and_env(tmp_path, monkeypatch)
    target = tmp_path / "target.py"
    target.write_text("raise SystemExit(78)\n")
    monkeypatch.setattr(unit_runner, "unit_command", lambda path: [sys.executable, str(target)])
    with bind_code_package(package):
        (tmp_path / "helper.py").write_text("VALUE = 4\n")
        unit = start_unit(tmp_path / "invocation.json", subprocess_env())
        unit.wait()
        with pytest.raises(LocalCodeError, match="digest mismatch"):
            unit.check()


def test_a_gpu_run_refuses_a_cpu_tuning_declaration():
    """A ``gpu: false`` tuning unit is placed with every GPU hidden: it would train on CPU."""
    from types import SimpleNamespace

    from tools.candidate_worker.parallel_dispatch import ParallelRefused, _require_tuning_device

    cpu = CapabilityResources(gpu=False, host_memory_gib=1.0, cpu_slots=1)
    gpu = CapabilityResources(gpu=True, vram_gib=4.0, host_memory_gib=1.0, cpu_slots=1)

    def body(active, available):
        hardware = SimpleNamespace(device_available=available, device_name="NVIDIA H100")
        bindings = SimpleNamespace(active_vram_budget_gb=active, hardware_context=hardware)
        return SimpleNamespace(admitted=SimpleNamespace(bindings=bindings))

    for active, available in ((4.0, False), (None, True)):
        with pytest.raises(ParallelRefused, match="gpu=false"):
            _require_tuning_device("train", cpu, body(active, available))
    _require_tuning_device("train", cpu, body(None, False))  # a CPU-only run may
    _require_tuning_device("train", gpu, body(4.0, True))
    with pytest.raises(ParallelRefused, match="active VRAM budget"):
        _require_tuning_device("train", gpu, body(8.0, True))


def _drain_run(prepared, monkeypatch):
    starter = _Starter(3, failing=frozenset({"build0"}), hold={"build1": 8})
    monkeypatch.setattr(parallel_dispatch, "start_unit", starter)
    request = _parallel(prepared, _budget(units=2))
    receipt = launch_candidate(request)
    assert receipt.status == "failed", receipt.error
    launched = CandidateRunReceipt.model_validate_json(
        (Path(receipt.workspace) / "candidate_run" / "launch.json").read_bytes()
    )
    return request, launched, receipt


def _rewrite(path: Path, model) -> None:
    os.chmod(path, 0o600)
    path.write_text(model.model_dump_json())


def _forge(kind, request, receipt):
    """Apply one forgery class; return the request the verifier is given."""
    units = Path(receipt.workspace) / "candidate_run" / "units"

    def load(node):
        return UnitReceipt.model_validate_json((units / node / "placement.json").read_bytes())

    if kind == "events":  # (a) a reused event number
        build1 = load("build1")
        _rewrite(
            units / "build1" / "placement.json",
            build1.model_copy(update={"ended_event": build1.started_event}),
        )
    elif kind == "placement":  # (b) a declared unit without its placement
        _rewrite(
            units / "build1" / "placement.json",
            load("build1").model_copy(update={"placement": None}),
        )
    elif kind == "alone":  # (b) an undeclared unit overlapped another unit
        propose, build0 = load("propose"), load("build0")
        _rewrite(
            units / "propose" / "placement.json",
            propose.model_copy(update={"placement": None, "ended_event": build0.started_event}),
        )
        _rewrite(
            units / "build0" / "placement.json",
            build0.model_copy(update={"started_event": propose.ended_event}),
        )
        table = {
            key: value for key, value in request.parallel.capabilities.items() if key != "proposal"
        }
        return request.model_copy(
            update={"parallel": request.parallel.model_copy(update={"capabilities": table})}
        )
    elif kind == "exit":  # (c) a succeeded unit whose receipt says it raised
        _rewrite(
            units / "build1" / "placement.json",
            load("build1").model_copy(update={"exit": "raised"}),
        )
    elif kind == "dispatched":  # (d) a receipt for a node readiness blocked
        (units / "check0").mkdir(exist_ok=True)
        (units / "check0" / "placement.json").write_text(
            load("build1").model_copy(update={"node_id": "check0"}).model_dump_json()
        )
    elif kind == "budget":  # (e) a body budget other than the admitted one
        path = Path(receipt.workspace) / "candidate_run" / parallel_dispatch.BUDGET_FILE
        _rewrite(path, _budget(units=3))
    elif kind == "fit":  # (f) a placement that could not fit beside its peer
        build1 = load("build1")
        assert build1.placement is not None
        huge = build1.placement.model_copy(
            update={"reserved": build1.placement.reserved.model_copy(update={"cpu_slots": 16})}
        )
        _rewrite(units / "build1" / "placement.json", build1.model_copy(update={"placement": huge}))
    return request


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("events", "one body-wide sequence"),
        ("placement", "placement contradicts its capability"),
        ("alone", "did not run alone"),
        ("exit", "exit contradicts its state"),
        ("dispatched", "receipt contradicts its state"),
        ("budget", "differs from the run's admitted budget"),
        ("fit", "exceeds the budget beside its peers"),
    ],
)
def test_the_trace_v2_verifier_refuses_each_forged_receipt_class(
    prepared, native_runner, monkeypatch, kind, message
):
    """Each class is one way receipts could vouch for a schedule that never happened."""
    request, launched, receipt = _drain_run(prepared, monkeypatch)
    verify_graph_trace(request, launched, receipt)  # the real receipts verify
    forged = _forge(kind, request, receipt)
    with pytest.raises(ValueError, match=message):
        verify_graph_trace(forged, launched, receipt)


REAL_UNIT = """import json, os, sys
from pathlib import Path
sys.path.insert(0, {src!r})
LOG = Path({log!r})
def log(**row):
    with LOG.open("a") as stream:
        stream.write(json.dumps(row) + "\\n")
log(kind="env", node=Path(sys.argv[1]).parent.name,
    cuda=os.environ.get("CUDA_VISIBLE_DEVICES"), pytest=os.environ.get("PYTEST_ADDOPTS"),
    session=os.getsid(0) == os.getpid())
import agent.token_unit as token_unit
real_bind = token_unit.bind_token_unit
def bind(unit_id):
    log(kind="token_unit", unit=unit_id)
    return real_bind(unit_id)
token_unit.bind_token_unit = bind
import runpy
runpy.run_path({harness!r}, run_name="__main__")
"""


def test_two_real_units_run_concurrently_to_completion(
    prepared, native_runner, monkeypatch, tmp_path
):
    """Real children through `start_unit` → `collect_result`, with the real placement env.

    Fails if a placed unit does not get its own session, the CPU-unit device
    selector, the parallel pytest-cache option, or its token-unit binding.
    """
    import json

    from tools.candidate_worker import unit_runner

    from .conftest import REPO
    from .test_unit_process import HARNESS, PROBE, Provider

    log = tmp_path / "real_units.jsonl"
    config = tmp_path / "harness.json"
    config.write_text(json.dumps({"fail": "none", "log": str(log), "tuner": False}))
    harness = tmp_path / "harness.py"
    harness.write_text(
        HARNESS.format(
            src=str(REPO / "src"),
            repo=str(REPO),
            provider=__import__("inspect").getsource(Provider),
            config=str(config),
            probe=PROBE,
        )
    )
    wrapper = tmp_path / "real_unit.py"
    wrapper.write_text(REAL_UNIT.format(src=str(REPO / "src"), log=str(log), harness=str(harness)))
    monkeypatch.setattr(
        unit_runner, "unit_command", lambda path: [sys.executable, str(wrapper), path]
    )
    receipt = launch_candidate(_parallel(prepared, _budget(units=2)))
    assert receipt.status == "accepted", receipt.error
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    envs = {row["node"]: row for row in rows if row["kind"] == "env"}
    assert set(envs) == {"propose", "build0", "build1", "check0", "check1"}
    for row in envs.values():
        assert row["cuda"] == "" and "-p no:cacheprovider" in row["pytest"] and row["session"]
    assert {row["unit"] for row in rows if row["kind"] == "token_unit"} == set(envs)
