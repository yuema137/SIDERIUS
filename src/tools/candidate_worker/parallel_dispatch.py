"""Concurrent dispatch of independent graph units inside an admitted budget (B3-4b).

The scheduler loop reuses the serial owners: readiness (`GraphBody.next_node`,
which wraps B1 `next_dispatch`), placement (`plan_dispatch(..., on_refusal="halt")`)
and the per-unit process runner (`unit_runner`). It adds only bounded
concurrency over them:

- each placed unit runs in its own session (process group) with the placement's
  ``CUDA_VISIBLE_DEVICES``; a unit of an undeclared capability runs alone, with
  the serial runner and environment;
- strict FIFO: when the first ready unit cannot be placed, the loop waits for a
  completion (no backfill, decision B3-Q4);
- drain (decision B3-Q2): after a failure readiness closes every undispatched
  node; running units finish with their real outcome;
- every dispatched entry publishes a write-once `UnitReceipt`;
- on SIGTERM, or any exception leaving the loop, every running unit's process
  group is terminated (TERM, grace, KILL) before the error propagates.

Contract: candidate-worker-contract.md, "Parallel dispatch".
"""

import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.control_json import encode_control
from core.durable_io import publish_bytes_write_once
from core.runtime_control.process_group import terminate_observed_group
from core.runtime_control.scheduling import HostBudget, Placement, ResourceRequest, plan_dispatch

from . import unit_runner
from .graph import GraphBody
from .graph_models import GraphNodeEvidence
from .layout import candidate_control_dir
from .parallel_envelope import declared_units
from .parallel_models import UnitExit, UnitReceipt
from .unit_models import NodeInvocation, unit_paths

#: Seconds between polls of running units.
POLL_SECONDS = 0.05
#: TERM-to-KILL grace when terminating a unit's process group.
TERMINATE_GRACE_SECONDS = 1.0
#: Concurrent validators must not share one `.pytest_cache`; serial runs keep
#: the exact pytest command (decision 4, 2026-10-28).
PYTEST_ADDOPTS_ENV = "PYTEST_ADDOPTS"
PYTEST_NO_CACHE = "-p no:cacheprovider"
#: The run's scheduling budget, published once per body beside the unit records.
BUDGET_FILE = "parallel_budget.json"


class ParallelRefused(ValueError):
    """A declared unit can never fit the admitted budget: the body runs nothing."""


class UnitTerminated(BaseException):
    """SIGTERM reached the worker during parallel dispatch."""


@dataclass
class RunningUnit:
    node_id: str
    item: GraphNodeEvidence
    invocation: NodeInvocation
    result_path: Path
    process: subprocess.Popen
    placement: Placement
    queued_event: int | None
    started_event: int
    started_at: str


class _Clock:
    """One body-wide event sequence (drain ordering) plus wall time for humans."""

    def __init__(self) -> None:
        self.events = 0

    def tick(self) -> int:
        self.events += 1
        return self.events

    @staticmethod
    def now() -> str:
        return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def unit_requests(body: GraphBody, budget: HostBudget) -> dict[str, ResourceRequest]:
    """One request per declared unit, refused before any dispatch if it can never fit.

    A tuning unit's declared VRAM must cover the run's active VRAM budget, and it
    is time-budgeted exactly when the trial or formal time budget is set.
    """
    requests: dict[str, ResourceRequest] = {}
    for ordinal, (node_id, declared) in enumerate(declared_units(body.request).items()):
        timed = False
        if node_id == body.shape.tuning:
            assert body.admitted is not None
            launch = body.admitted.settings.launch
            timed = (
                launch.trial_time_budget_minutes is not None
                or launch.formal_time_budget_minutes is not None
            )
            active = body.admitted.bindings.active_vram_budget_gb
            if declared.gpu and (active is None or (declared.vram_gib or 0.0) < active):
                raise ParallelRefused(
                    f"resource_refused: tuning node {node_id!r} declares "
                    f"{declared.vram_gib} GiB; the run's active VRAM budget is {active}"
                )
        request = ResourceRequest(
            unit_id=node_id,
            dispatch_ordinal=ordinal,
            gpu_count=1 if declared.gpu else 0,
            vram_gib=declared.vram_gib,
            vram_source="configured_cap" if declared.gpu else None,
            host_memory_gib=declared.host_memory_gib,
            cpu_slots=declared.cpu_slots,
            wall_seconds=body.request.timeout_seconds,
            time_budgeted=timed,
        )
        refused = plan_dispatch((request,), (), budget, on_refusal="halt").refused
        if refused:
            raise ParallelRefused(f"resource_refused: {node_id}: " + "; ".join(refused[0].reasons))
        requests[node_id] = request
    return requests


def unit_environment(placement: Placement) -> dict[str, str]:
    env = unit_runner.unit_env(cuda_visible_devices=placement.cuda_visible_devices)
    prior = env.get(PYTEST_ADDOPTS_ENV)
    env[PYTEST_ADDOPTS_ENV] = PYTEST_NO_CACHE if not prior else f"{prior} {PYTEST_NO_CACHE}"
    return env


def start_unit(invocation_path: Path, env: dict[str, str]) -> subprocess.Popen:
    """Spawn the unit child in its own session, sharing the worker log."""
    sys.stdout.flush()
    sys.stderr.flush()
    return subprocess.Popen(
        unit_runner.unit_command(str(invocation_path)), env=env, start_new_session=True
    )


def dispatch_parallel(body: GraphBody, budget: HostBudget) -> None:
    requests = unit_requests(body, budget)
    control = candidate_control_dir(Path(body.initial.workspace), iteration=body.iteration)
    control.mkdir(parents=True, exist_ok=True)
    publish_bytes_write_once(str(control / BUDGET_FILE), encode_control(budget))
    clock = _Clock()
    running: dict[str, RunningUnit] = {}
    queued: dict[str, int] = {}
    adaptors = {adaptor.id for adaptor in body.definition.adaptors}
    with _sigterm_raises(), _terminating(running):
        while not body.done():
            node_id = body.next_node(frozenset(running))
            if node_id is None:
                if running:
                    _collect(body, running, _wait_any(running), clock)
                continue
            if node_id in adaptors:
                _run_adaptor(body, node_id, clock)  # a pure parent step; needs no placement
                continue
            if node_id not in requests:
                if running:  # an undeclared unit waits until it is alone
                    _collect(body, running, _wait_any(running), clock)
                    continue
                _run_alone(body, node_id, clock)
                continue
            decision = plan_dispatch(
                (requests[node_id],),
                tuple(unit.placement for unit in running.values()),
                budget,
                on_refusal="halt",
            )
            if decision.refused:
                raise RuntimeError(f"admitted unit {node_id!r} was refused")
            placement = decision.placements[0]
            if placement.decision == "queued":
                queued.setdefault(node_id, clock.tick())
                if not running:
                    raise RuntimeError(f"unit {node_id!r} queued with nothing running")
                _collect(body, running, _wait_any(running), clock)
                continue
            _start(body, node_id, placement, running, clock, queued.pop(node_id, None))


def _run_adaptor(body: GraphBody, node_id: str, clock: _Clock) -> None:
    started, started_at = clock.tick(), clock.now()
    body.run_adaptor(node_id)
    exit_kind: UnitExit = "raised" if body.evidence[node_id].state == "failed" else "returned"
    _publish(body, node_id, None, None, started, started_at, clock, exit_kind)


def _run_alone(body: GraphBody, node_id: str, clock: _Clock) -> None:
    """An undeclared unit: exactly the serial step and environment, with a receipt."""
    started, started_at = clock.tick(), clock.now()
    item = body.running_item(node_id)
    exit_kind: UnitExit = "returned"
    try:
        output, path = unit_runner.unit_output(body.invocation(node_id))
        body.finish(node_id, item, output, path)
    except Exception as error:
        exit_kind = "raised"
        body.fail(node_id, item, error)
    finally:
        _publish(body, node_id, None, None, started, started_at, clock, exit_kind)
    body.decide_routes(node_id)


def _start(
    body: GraphBody,
    node_id: str,
    placement: Placement,
    running: dict[str, RunningUnit],
    clock: _Clock,
    queued_event: int | None,
) -> None:
    item = body.running_item(node_id)
    started, started_at = clock.tick(), clock.now()
    try:
        invocation = body.invocation(node_id).model_copy(update={"parallel": True})
        path, result_path = unit_runner.publish_invocation(invocation)
        process = start_unit(path, unit_environment(placement))
    except Exception as error:
        body.fail(node_id, item, error)
        _publish(body, node_id, placement, queued_event, started, started_at, clock, "raised")
        body.decide_routes(node_id)
        return
    running[node_id] = RunningUnit(
        node_id,
        item,
        invocation,
        result_path,
        process,
        placement,
        queued_event,
        started,
        started_at,
    )


def _wait_any(running: dict[str, RunningUnit]) -> str:
    """The first finished unit in dispatch order (ties never depend on timing)."""
    while True:
        for unit in sorted(running.values(), key=lambda item: item.placement.dispatch_ordinal):
            if unit.process.poll() is not None:
                return unit.node_id
        time.sleep(POLL_SECONDS)


def _collect(body: GraphBody, running: dict[str, RunningUnit], node_id: str, clock: _Clock) -> None:
    unit = running.pop(node_id)
    exit_kind: UnitExit = "returned"
    try:
        if unit.process.returncode != 0:
            exit_kind = "process_failed"
            raise subprocess.CalledProcessError(unit.process.returncode, unit.process.args)
        result = unit_runner.collect_result(unit.invocation, unit.result_path)
        if result.outcome in ("raised", "exited", "interrupted"):
            exit_kind = result.outcome
        output, path = unit_runner.result_output(unit.invocation, result)
        body.finish(node_id, unit.item, output, path)
    except Exception as error:
        exit_kind = "raised" if exit_kind == "returned" else exit_kind
        body.fail(node_id, unit.item, error)
    finally:
        _publish(
            body,
            node_id,
            unit.placement,
            unit.queued_event,
            unit.started_event,
            unit.started_at,
            clock,
            exit_kind,
        )
    body.decide_routes(node_id)


def _publish(
    body: GraphBody,
    node_id: str,
    placement: Placement | None,
    queued_event: int | None,
    started_event: int,
    started_at: str,
    clock: _Clock,
    exit_kind: UnitExit,
) -> None:
    receipt = UnitReceipt(
        node_id=node_id,
        placement=placement,
        queued_event=queued_event,
        started_event=started_event,
        ended_event=clock.tick(),
        started_at=started_at,
        ended_at=clock.now(),
        exit=exit_kind,
    )
    path = receipt_path(body, node_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    publish_bytes_write_once(str(path), encode_control(receipt))


def receipt_path(body: GraphBody, node_id: str) -> Path:
    invocation, _ = unit_paths(body.initial, node_id, iteration=body.iteration)
    return invocation.with_name("placement.json")


@contextmanager
def _terminating(running: dict[str, RunningUnit]) -> Iterator[None]:
    """Any exit with units still running kills every one of their process groups."""
    try:
        yield
    finally:
        for unit in list(running.values()):
            terminate_observed_group(
                unit.process.pid,
                grace_seconds=TERMINATE_GRACE_SECONDS,
                poll_seconds=POLL_SECONDS,
                child=unit.process,
            )
            unit.process.wait()
        running.clear()


@contextmanager
def _sigterm_raises() -> Iterator[None]:
    """Turn SIGTERM into ``UnitTerminated`` so the cleanup above runs."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def raise_terminated(signum: int, frame: object) -> None:
        raise UnitTerminated(f"signal {signum}")

    previous: Callable | int | None = signal.signal(signal.SIGTERM, raise_terminated)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)
