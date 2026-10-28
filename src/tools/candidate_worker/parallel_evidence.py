"""Verify a ``parallel-v1`` graph trace against its dispatch receipts (B3-4b, trace v2).

Drain rule (decision B3-Q2): after the body's first failure, no new entry is
dispatched; entries already running finish with their real outcome. The
receipts' body-wide event sequence proves it: every dispatched entry started
before the first failed entry ended. Contract: candidate-worker-contract.md,
"Parallel dispatch".
"""

from pathlib import Path

from core.runtime_control.scheduling import HostBudget

from .graph_evidence import read_graph_control
from .graph_models import GraphTrace
from .layout import candidate_control_dir
from .models import CandidateRunReceipt, CandidateRunRequest
from .parallel_models import UnitReceipt
from .unit_models import unit_paths

_DISPATCHED = frozenset(("succeeded", "rejected", "failed"))
_CLOSED_BY_READINESS = frozenset(("blocked",))


def verify_drain(
    request: CandidateRunRequest,
    initial: CandidateRunReceipt,
    trace: GraphTrace,
    *,
    iteration: int,
) -> frozenset[str]:
    """Return the dispatched entries; refuse a trace whose receipts break the drain rule."""
    if request.parallel is None:
        raise ValueError("a parallel-v1 trace requires a parallel request")
    control = candidate_control_dir(Path(initial.workspace), iteration=iteration)
    from .parallel_dispatch import BUDGET_FILE

    budget = HostBudget.model_validate_json(read_graph_control(control / BUDGET_FILE))
    receipts: dict[str, UnitReceipt] = {}
    for item in (*trace.nodes, *trace.adaptors):
        path = unit_paths(initial, item.node_id, iteration=iteration)[0].with_name("placement.json")
        if not path.exists():
            if item.state in _DISPATCHED:
                raise ValueError(f"parallel trace entry {item.node_id!r} has no receipt")
            continue
        receipt = UnitReceipt.model_validate_json(read_graph_control(path))
        if receipt.node_id != item.node_id or item.state in _CLOSED_BY_READINESS:
            raise ValueError(f"parallel receipt {item.node_id!r} contradicts the trace")
        placement = receipt.placement
        if placement is not None and (
            placement.unit_id != item.node_id or placement.budget_digest != budget.digest
        ):
            raise ValueError(f"parallel receipt {item.node_id!r} names another placement")
        receipts[item.node_id] = receipt
    states = {item.node_id: item.state for item in (*trace.nodes, *trace.adaptors)}
    failures = [r.ended_event for key, r in receipts.items() if states[key] == "failed"]
    if failures:
        first = min(failures)
        late = sorted(key for key, r in receipts.items() if r.started_event > first)
        if late:
            raise ValueError(f"parallel trace dispatched after a failure: {late}")
    return frozenset(receipts)
