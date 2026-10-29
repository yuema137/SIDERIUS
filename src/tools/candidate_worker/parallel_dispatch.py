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
- every finished unit is collected before readiness is asked for the next node,
  so a failure that already exited stops new dispatch;
- on SIGTERM, or any exception leaving the loop, every running unit's process
  group is terminated (TERM, grace, KILL) before the error propagates
  (`unit_processes`, which also starts units through the code-package guard).

Contract: candidate-worker-contract.md, "Parallel dispatch".
"""

import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.control_json import encode_control
from core.durable_io import publish_bytes_write_once
from core.runtime_control.scheduling import HostBudget, Placement, ResourceRequest, plan_dispatch

from . import unit_runner
from .graph import GraphBody
from .graph_models import GraphNodeEvidence
from .layout import candidate_control_dir
from .parallel_envelope import declared_units
from .parallel_models import UnitExit, UnitReceipt
from .unit_models import NodeInvocation, unit_paths
from .unit_processes import (
    POLL_SECONDS,
    TermGate,
    UnitProcess,
    UnitTerminated,
    start_unit,
    terminate,
)

#: Concurrent validators must not share one `.pytest_cache`; serial runs keep
#: the exact pytest command (decision 4, 2026-10-28).
PYTEST_ADDOPTS_ENV = "PYTEST_ADDOPTS"
PYTEST_NO_CACHE = "-p no:cacheprovider"
#: The run's scheduling budget, published once per body beside the unit records.
BUDGET_FILE = "parallel_budget.json"


__all__ = ["ParallelRefused", "UnitTerminated", "dispatch_parallel", "start_unit"]


class ParallelRefused(ValueError):
    """A declared unit can never fit the admitted budget: the body runs nothing."""


@dataclass
class RunningUnit:
    node_id: str
    item: GraphNodeEvidence
    invocation: NodeInvocation
    result_path: Path
    process: UnitProcess
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
            _require_tuning_device(node_id, declared, body)
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


def _require_tuning_device(node_id: str, declared, body: GraphBody) -> None:
    """A GPU run's tuning unit must be declared on a GPU covering its VRAM budget.

    A CPU-only placement hides every GPU (``CUDA_VISIBLE_DEVICES=""``), so a
    ``gpu: false`` tuning declaration on a run with an active VRAM budget or a GPU
    hardware context would silently train on CPU.
    """
    assert body.admitted is not None
    bindings = body.admitted.bindings
    active = bindings.active_vram_budget_gb
    hardware = bindings.hardware_context
    gpu_run = active is not None or (hardware is not None and hardware.device_available)
    if not declared.gpu:
        if gpu_run:
            raise ParallelRefused(
                f"resource_refused: tuning node {node_id!r} is declared gpu=false, but the run "
                f"trains on a GPU (active VRAM budget {active}, hardware "
                f"{None if hardware is None else hardware.device_name}); declare tuning with "
                "gpu=true and vram_gib covering the VRAM budget"
            )
        return
    if active is None or (declared.vram_gib or 0.0) < active:
        raise ParallelRefused(
            f"resource_refused: tuning node {node_id!r} declares "
            f"{declared.vram_gib} GiB; the run's active VRAM budget is {active}"
        )


def unit_environment(placement: Placement) -> dict[str, str]:
    env = unit_runner.unit_env(cuda_visible_devices=placement.cuda_visible_devices)
    prior = env.get(PYTEST_ADDOPTS_ENV)
    env[PYTEST_ADDOPTS_ENV] = PYTEST_NO_CACHE if not prior else f"{prior} {PYTEST_NO_CACHE}"
    return env


def dispatch_parallel(body: GraphBody, budget: HostBudget) -> None:
    requests = unit_requests(body, budget)
    control = candidate_control_dir(Path(body.initial.workspace), iteration=body.iteration)
    control.mkdir(parents=True, exist_ok=True)
    publish_bytes_write_once(str(control / BUDGET_FILE), encode_control(budget))
    clock = _Clock()
    running: dict[str, RunningUnit] = {}
    queued: dict[str, int] = {}
    adaptors = {adaptor.id for adaptor in body.definition.adaptors}
    gate = TermGate()
    with gate.installed(), _terminating(body, running, clock, gate):
        while not body.done():
            # A failure that already exited must stop dispatch before readiness runs.
            _collect_finished(body, running, clock)
            if body.done():  # the units just collected may have closed the body
                break
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
                # The last event before this unit queued; consumes no event of its own.
                queued.setdefault(node_id, clock.events)
                if not running:
                    raise RuntimeError(f"unit {node_id!r} queued with nothing running")
                _collect(body, running, _wait_any(running), clock)
                continue
            _start(body, node_id, placement, running, clock, gate, queued.pop(node_id, None))


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
    gate: TermGate,
    queued_event: int | None,
) -> None:
    item = body.running_item(node_id)
    started, started_at = clock.tick(), clock.now()
    try:
        invocation = body.invocation(node_id).model_copy(update={"parallel": True})
        path, result_path = unit_runner.publish_invocation(invocation)
        env = unit_environment(placement)
    except Exception as error:
        body.fail(node_id, item, error)
        _publish(body, node_id, placement, queued_event, started, started_at, clock, "raised")
        body.decide_routes(node_id)
        return
    # A SIGTERM landing between the spawn and the registration would orphan it.
    with gate.held():
        process = start_unit(path, env)
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


def _collect_finished(body: GraphBody, running: dict[str, RunningUnit], clock: _Clock) -> None:
    """Collect every unit that has already exited, in dispatch order."""
    for unit in sorted(running.values(), key=lambda item: item.placement.dispatch_ordinal):
        if unit.process.poll() is not None:
            _collect(body, running, unit.node_id, clock)


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
        unit.process.check()  # the code-package refusal, before any other outcome
        code = unit.process.returncode
        assert code is not None  # collected only after the unit exited
        if code != 0:
            exit_kind = "process_failed"
            raise subprocess.CalledProcessError(code, unit.process.args)
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
def _terminating(
    body: GraphBody, running: dict[str, RunningUnit], clock: _Clock, gate: TermGate
) -> Iterator[None]:
    """Any exit with units still running kills every one of their process groups.

    SIGTERM is held during the cleanup, so a second signal cannot abort it. Each
    terminated unit publishes a ``terminated`` receipt (best effort: the body
    has no trace to verify it against).
    """
    try:
        yield
    finally:
        with gate.held():
            for unit in list(running.values()):
                terminate(unit.process)
                with suppress(Exception):
                    _publish(
                        body,
                        unit.node_id,
                        unit.placement,
                        unit.queued_event,
                        unit.started_event,
                        unit.started_at,
                        clock,
                        "terminated",
                    )
            running.clear()
