"""Verify a ``parallel-v1`` graph trace against its dispatch receipts (B3-4b, trace v2).

``drained_entries`` is the one parallel-v1 check ``verify_graph_trace`` calls.
For a serial trace it only confirms the request is serial. For a parallel trace
it re-derives, from the write-once receipts and the published body budget:

- (e) the body budget is the run's admitted budget (``parallel.budget`` or the
  host grant of the segment that ran this iteration);
- (d) receipts exist exactly for dispatched entries;
- (b) a placement exists exactly for declared units; an undeclared unit
  overlapped no other unit;
- (c) each receipt's exit agrees with its trace state;
- (a) start and end events form one permutation of the body's events;
- (f) every placement fits the budget beside the placements running when it
  started, on the slot it recorded (``plan_dispatch`` re-run);
- causality: every entry starts after all its sources have settled;
- drain (decision B3-Q2): nothing started after the first failure ended.

It returns the receipts' timing (``DrainWindow``), with which ``replay_readiness``
replays the trace under the drain instead of the serial failure stop. Contract:
candidate-worker-contract.md, "Concurrent dispatch (B3-4b)".
"""

from collections.abc import Mapping
from pathlib import Path

from core.runtime_control.scheduling import HostBudget, plan_dispatch

from .graph_evidence import DrainWindow, read_graph_control, settled_sources_end
from .graph_models import DISPATCHED_STATES, GraphNodeEvidence, GraphTrace
from .layout import candidate_control_dir
from .loop_models import LoopContinuation
from .models import CandidateRunReceipt, CandidateRunRequest
from .parallel_envelope import declared_units
from .parallel_models import GRANT_CONTROL_FILE, HostGrant, UnitExit, UnitReceipt
from .unit_models import unit_paths

_RECEIPT_FILE = "placement.json"


def drained_entries(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    trace: GraphTrace,
    *,
    iteration: int,
) -> DrainWindow | None:
    """The receipt timing of a parallel trace's dispatched entries; None for a serial one."""
    if (trace.scheduling == "parallel-v1") != (request.parallel is not None):
        raise ValueError("graph trace scheduling disagrees with the request")
    if trace.scheduling == "serial":
        return None
    from .parallel_dispatch import BUDGET_FILE

    control = candidate_control_dir(Path(initial.workspace), iteration=iteration)
    budget = HostBudget.model_validate_json(read_graph_control(control / BUDGET_FILE))
    if budget.digest != admitted_budget(request, initial, iteration).digest:
        raise ValueError("parallel body budget differs from the run's admitted budget")
    entries = {item.node_id: item for item in (*trace.nodes, *trace.adaptors)}
    adaptors = frozenset(item.node_id for item in trace.adaptors)
    receipts = _receipts(initial, entries, iteration)
    declared = frozenset(declared_units(request))
    for node_id, receipt in receipts.items():
        _check_receipt(entries[node_id], receipt, node_id in declared, node_id in adaptors, budget)
    _check_events(receipts)
    _check_alone(receipts, declared, adaptors)
    _check_fit(receipts, budget)
    failure_end = _check_drain(receipts, entries)
    ended = {node_id: receipt.ended_event for node_id, receipt in receipts.items()}
    window = DrainWindow(ended=ended, failure_end=failure_end)
    _check_causality(receipts, entries, window)
    return window


def admitted_budget(
    request: CandidateRunRequest, initial: CandidateRunReceipt, iteration: int
) -> HostBudget:
    """The run's own ``parallel.budget``, else the grant of the segment running ``iteration``."""
    assert request.parallel is not None
    if request.parallel.budget is not None:
        return request.parallel.budget
    root = Path(initial.workspace) / "candidate_run"
    control, completed = root, 0
    for binding_path in sorted((root / "continuations").glob("*/continuation.json")):
        binding = LoopContinuation.model_validate_json(read_graph_control(binding_path))
        if completed < binding.completed_iterations < iteration:
            control, completed = binding_path.parent, binding.completed_iterations
    grant = HostGrant.model_validate_json(read_graph_control(control / GRANT_CONTROL_FILE))
    return grant.run_budget()


def _dispatched(item: GraphNodeEvidence) -> bool:
    """An entry, unit or adaptor, is dispatched iff it has an outcome (``DISPATCHED_STATES``).

    One definition with the readiness replay (#1454): an executed adaptor closes
    with its ``AdaptorOutcome.status`` (succeeded, rejected or failed) or fails on
    an exception, and readiness closes an undispatched adaptor only as
    ``blocked``. So no valid trace holds a ``skipped`` adaptor; one that does is
    refused here if it has a receipt, else by the replay.
    """
    return item.state in DISPATCHED_STATES


def _receipts(
    initial: CandidateRunReceipt,
    entries: Mapping[str, GraphNodeEvidence],
    iteration: int,
) -> dict[str, UnitReceipt]:
    """(d) a receipt exists exactly for every dispatched entry, and names it."""
    receipts: dict[str, UnitReceipt] = {}
    for node_id, item in entries.items():
        path = unit_paths(initial, node_id, iteration=iteration)[0].with_name(_RECEIPT_FILE)
        dispatched = _dispatched(item)
        if path.exists() != dispatched:
            raise ValueError(f"parallel trace entry {node_id!r} receipt contradicts its state")
        if dispatched:
            receipt = UnitReceipt.model_validate_json(read_graph_control(path))
            if receipt.node_id != node_id:
                raise ValueError(f"parallel receipt {node_id!r} names another entry")
            receipts[node_id] = receipt
    return receipts


def _expected_exits(item: GraphNodeEvidence, adaptor: bool) -> frozenset[UnitExit]:
    if adaptor:
        return frozenset(("raised",) if item.state == "failed" else ("returned",))
    if item.state == "failed" and item.record_path is None:
        return frozenset(("raised", "process_failed"))
    return frozenset(("returned",))


def _check_receipt(
    item: GraphNodeEvidence,
    receipt: UnitReceipt,
    declared: bool,
    adaptor: bool,
    budget: HostBudget,
) -> None:
    """(b) placement iff declared, naming this unit and budget; (c) exit agrees with state."""
    placement = receipt.placement
    if (placement is not None) != (declared and not adaptor):
        raise ValueError(f"parallel receipt {item.node_id!r} placement contradicts its capability")
    if placement is not None and (
        placement.unit_id != item.node_id or placement.budget_digest != budget.digest
    ):
        raise ValueError(f"parallel receipt {item.node_id!r} names another placement")
    if placement is None and receipt.queued_event is not None:
        raise ValueError(f"parallel receipt {item.node_id!r} queued without a placement")
    if receipt.exit not in _expected_exits(item, adaptor):
        raise ValueError(f"parallel receipt {item.node_id!r} exit contradicts its state")


def _check_events(receipts: Mapping[str, UnitReceipt]) -> None:
    """(a) start and end events are one permutation; a queue mark precedes its start."""
    events = sorted(
        event
        for receipt in receipts.values()
        for event in (receipt.started_event, receipt.ended_event)
    )
    if events != list(range(1, len(events) + 1)):
        raise ValueError("parallel receipt events are not one body-wide sequence")
    for node_id, receipt in receipts.items():
        if receipt.queued_event is not None and receipt.queued_event >= receipt.started_event:
            raise ValueError(f"parallel receipt {node_id!r} started before it queued")


def _overlap(left: UnitReceipt, right: UnitReceipt) -> bool:
    return left.started_event < right.ended_event and right.started_event < left.ended_event


def _check_alone(
    receipts: Mapping[str, UnitReceipt], declared: frozenset[str], adaptors: frozenset[str]
) -> None:
    """(b) an undeclared unit ran alone: no other unit overlapped it."""
    units = {key: value for key, value in receipts.items() if key not in adaptors}
    for node_id, receipt in units.items():
        if node_id in declared:
            continue
        if any(other != node_id and _overlap(receipt, value) for other, value in units.items()):
            raise ValueError(f"undeclared unit {node_id!r} did not run alone")


def _check_fit(receipts: Mapping[str, UnitReceipt], budget: HostBudget) -> None:
    """(f) each placement fits, on its recorded slot, beside those running when it started."""
    placed = {key: value for key, value in receipts.items() if value.placement is not None}
    for node_id, receipt in placed.items():
        placement = receipt.placement
        assert placement is not None
        running = tuple(
            value.placement
            for other, value in placed.items()
            if other != node_id
            and value.placement is not None
            and value.started_event < receipt.started_event < value.ended_event
        )
        decision = plan_dispatch((placement.reserved,), running, budget, on_refusal="halt")
        replayed = decision.placed[0] if decision.placed else None
        if replayed is None or replayed.gpu_uuid != placement.gpu_uuid:
            raise ValueError(f"parallel placement {node_id!r} exceeds the budget beside its peers")


def _check_drain(
    receipts: Mapping[str, UnitReceipt], entries: Mapping[str, GraphNodeEvidence]
) -> int | None:
    """Decision B3-Q2: nothing starts after the first failed entry ended; returns that end."""
    failures = [r.ended_event for key, r in receipts.items() if entries[key].state == "failed"]
    if not failures:
        return None
    first = min(failures)
    late = sorted(key for key, r in receipts.items() if r.started_event > first)
    if late:
        raise ValueError(f"parallel trace dispatched after a failure: {late}")
    return first


def _check_causality(
    receipts: Mapping[str, UnitReceipt],
    entries: Mapping[str, GraphNodeEvidence],
    window: DrainWindow,
) -> None:
    """Sources, including route control edges and undispatched closures, settle first."""
    for node_id, receipt in receipts.items():
        if receipt.started_event <= settled_sources_end(node_id, entries, window):
            raise ValueError(f"parallel receipt {node_id!r} started before its sources ended")
