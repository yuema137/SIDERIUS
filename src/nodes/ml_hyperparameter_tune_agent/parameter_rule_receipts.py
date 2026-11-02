"""Transport attempt receipts from effective plans to persisted history.

Two receipts ride ``record_params`` (never executor arguments) and are promoted
to top-level ``ExperimentRecord`` fields at the shared ``_emit_record`` seam, so
every success, refusal and failure builder carries them without its own branch
and the persisted ``params`` stay a pure configuration (the reflector's
best-configuration context reads them):

* ``inactive_parameter_rules`` — rules inactive for the selected loss route.
* ``resolution_events`` — final ``ExecutionProvenance.events`` (issue #1322), so
  planner history can label a superseded proposal after condensation.

Both are written only when nonempty, preserving unaffected record bytes.
"""

from typing import Any

from agent.schemas.execution_provenance import ExecutionProvenance
from agent.schemas.hyperparam_tuning import ExperimentPlan

#: Receipt keys promoted out of ``params``, in promotion (and record key) order.
_PROMOTED_RECEIPT_KEYS = ("inactive_parameter_rules", "resolution_events")


def inactive_parameter_rule_record(plan: ExperimentPlan) -> dict[str, Any]:
    """Keep unaffected records unchanged; never pass receipts to the executor."""
    if not plan.inactive_parameter_rules:
        return {}
    return {
        "inactive_parameter_rules": [
            r.model_dump(mode="json") for r in plan.inactive_parameter_rules
        ]
    }


def resolution_event_record(provenance: ExecutionProvenance) -> dict[str, Any]:
    """Final resolution events only; the plan-only comparison is not execution truth."""
    if not provenance.diverged:
        return {}
    return {"resolution_events": [e.model_dump(mode="json") for e in provenance.events]}


def attach_attempt_receipts(record: dict[str, Any]) -> None:
    """Promote attempt receipts at the shared validated persistence boundary."""
    params = record.get("params", {})
    present = [key for key in _PROMOTED_RECEIPT_KEYS if key in params]
    if not present:
        return
    record["params"] = dict(params)
    for key in present:
        record[key] = record["params"].pop(key)
