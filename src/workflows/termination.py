"""Terminal evidence shared by workflow execution and its callers."""

from collections.abc import Sequence

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from execute_tools.metric_order import MetricOrder


def infrastructure_abort_reason(
    results: Sequence[HyperparamTuningOutput] | None,
) -> str | None:
    """Return the failed status when runtime evidence cannot be trusted.

    Candidate rejection and gate exhaustion are not infrastructure aborts.
    Callers must stop their campaign on this signal, even if earlier results
    contain valid scores. Retain the outputs for diagnosis before stopping.
    """
    for output in results or ():
        if getattr(output, "termination_reason", None) == "infrastructure_abort":
            return getattr(output, "status", None) or "infrastructure_abort"
    return None


def target_reached(
    incumbent: float | None, target: float | None, order: MetricOrder | None
) -> bool:
    """Compare the owner's valid incumbent, never unfiltered progress."""
    return (
        incumbent is not None
        and target is not None
        and order is not None
        and order.is_at_least(incumbent, target)
    )


def workflow_stop_reason(
    results: Sequence[HyperparamTuningOutput],
    incumbent: float | None,
    target: float | None,
    order: MetricOrder | None,
) -> str:
    """Infrastructure failure takes precedence over scientific success."""
    if infrastructure_abort_reason(results) is not None:
        return "infrastructure_abort"
    if target_reached(incumbent, target, order):
        return "target_reached"
    return "iterations_exhausted"
